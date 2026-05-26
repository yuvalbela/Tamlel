"""
חלון overlay צף - "pill" קטן ועגול שמופיע בתחתית המסך הפעיל בזמן הקלטה,
עם ויזואליזציה של עוצמת הקול.

תכונות:
- צורת פיל (capsule) עם פינות מעוגלות במלואן
- frameless, always on top, click-through, לא גונב פוקוס
- מופיע במסך שבו נמצא החלון הפעיל (multi-monitor aware)
- DPI aware (קואורדינטות נכונות גם בסקיילינג שונה למסך)
"""

import tkinter as tk
import ctypes
from collections import deque


# ---------- מבני Win32 ----------
class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", _RECT),
                ("rcWork", _RECT), ("dwFlags", ctypes.c_ulong)]


_MONITOR_DEFAULTTONEAREST = 2


def _set_dpi_aware():
    """מודיע ל-Windows שאנחנו DPI-aware - חיוני לקואורדינטות נכונות במולטי-מסך."""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Per-monitor V2
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def _get_active_monitor_workarea():
    """
    מחזיר (left, top, right, bottom) של ה-work area (לא כולל taskbar) של המסך
    שבו נמצא החלון הפעיל; fallback למסך של הסמן; fallback למסך הראשי.
    """
    user32 = ctypes.windll.user32
    hmon = None

    hwnd = user32.GetForegroundWindow()
    if hwnd:
        rect = _RECT()
        if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            pt = _POINT((rect.left + rect.right) // 2,
                        (rect.top + rect.bottom) // 2)
            hmon = user32.MonitorFromPoint(pt, _MONITOR_DEFAULTTONEAREST)

    if not hmon:
        pt = _POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        hmon = user32.MonitorFromPoint(pt, _MONITOR_DEFAULTTONEAREST)

    mi = _MONITORINFO()
    mi.cbSize = ctypes.sizeof(_MONITORINFO)
    if not user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
        # fallback מוחלט
        sw = user32.GetSystemMetrics(0)
        sh = user32.GetSystemMetrics(1)
        return (0, 0, sw, sh)
    r = mi.rcWork
    return (r.left, r.top, r.right, r.bottom)


# ---------- חלון ה-overlay ----------
class RecordingOverlay:
    NUM_BARS = 13
    BAR_WIDTH = 3
    BAR_GAP = 4
    BAR_MIN_HEIGHT = 2
    BAR_COLOR = "#ffffff"

    PILL_FILL_COLOR = "#1a1a1a"     # מילוי כהה שייראה על כל רקע
    PILL_OUTLINE_COLOR = "#ffffff"
    PILL_OUTLINE_WIDTH = 1
    PILL_HEIGHT = 38

    # alpha של החלון: 1.0 = אטום מלא, 0.0 = שקוף לגמרי. הערך הזה משפיע על כל מה
    # שמצויר בחלון (גם הפיל וגם הברים) - אז הוא צריך לשמור על קונטרסט מספיק.
    WINDOW_ALPHA = 0.82

    # צבע נדיר ש-Windows יחשיב כשקוף לחלוטין + click-through (לאזורים מחוץ לפיל)
    TRANSPARENT_COLOR = "#ff00fe"

    WINDOW_HEIGHT = 46
    PADDING_X = 18
    BOTTOM_OFFSET = 30  # מרחק מתחתית ה-work area (מעל ה-taskbar)

    SMOOTHING = 0.45
    LEVEL_SCALE = 5000.0

    def __init__(self):
        _set_dpi_aware()

        self.root = tk.Tk()
        self.root.title("Tamlel Overlay")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", self.WINDOW_ALPHA)
        # פיקסלים בצבע הזה הופכים שקופים לחלוטין + click-through
        self.root.attributes("-transparentcolor", self.TRANSPARENT_COLOR)
        self.root.config(bg=self.TRANSPARENT_COLOR)

        width = (self.NUM_BARS * (self.BAR_WIDTH + self.BAR_GAP)
                 - self.BAR_GAP + 2 * self.PADDING_X)
        self.width = width
        self.height = self.WINDOW_HEIGHT

        self.canvas = tk.Canvas(
            self.root, width=self.width, height=self.height,
            bg=self.TRANSPARENT_COLOR, highlightthickness=0, bd=0,
        )
        self.canvas.pack()

        self._draw_pill()
        self._create_bars()

        # geometry ראשוני (יעודכן ב-show לפי המסך הפעיל)
        self.root.geometry(f"{self.width}x{self.height}+0+0")

        self.root.update_idletasks()
        try:
            self._apply_win32_styles()
        except Exception as e:
            print(f"WARNING: could not apply overlay window styles: {e}")

        self.root.withdraw()

        self.levels = deque([0.0] * self.NUM_BARS, maxlen=self.NUM_BARS)
        self.current_height = [0.0] * self.NUM_BARS
        self._animating = False

    def _apply_win32_styles(self):
        GWL_EXSTYLE = -20
        WS_EX_LAYERED = 0x00080000
        WS_EX_TRANSPARENT = 0x00000020
        WS_EX_TOOLWINDOW = 0x00000080
        WS_EX_NOACTIVATE = 0x08000000

        user32 = ctypes.windll.user32
        hwnd = user32.GetParent(self.root.winfo_id())
        current = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(
            hwnd, GWL_EXSTYLE,
            current | WS_EX_LAYERED | WS_EX_TRANSPARENT
            | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        )

    def _draw_pill(self):
        """מצייר pill עם מילוי כהה ועם outline דק - מקבל שקיפות חלקית
        ע"י WINDOW_ALPHA על כל החלון."""
        ph = self.PILL_HEIGHT
        margin_y = (self.height - ph) // 2
        left = 2
        right = self.width - 2
        top = margin_y
        bot = margin_y + ph
        r = ph // 2
        fill = self.PILL_FILL_COLOR
        outline = self.PILL_OUTLINE_COLOR
        w = self.PILL_OUTLINE_WIDTH

        # ---------- מילוי ----------
        # חצי-עיגול שמאלי
        self.canvas.create_oval(
            left, top, left + 2 * r, bot,
            fill=fill, outline="",
        )
        # חצי-עיגול ימני
        self.canvas.create_oval(
            right - 2 * r, top, right, bot,
            fill=fill, outline="",
        )
        # מלבן באמצע
        self.canvas.create_rectangle(
            left + r, top, right - r, bot,
            fill=fill, outline="",
        )

        # ---------- outline ----------
        self.canvas.create_arc(
            left, top, left + 2 * r, bot,
            start=90, extent=180,
            style=tk.ARC, outline=outline, width=w,
        )
        self.canvas.create_arc(
            right - 2 * r, top, right, bot,
            start=-90, extent=180,
            style=tk.ARC, outline=outline, width=w,
        )
        self.canvas.create_line(
            left + r, top, right - r, top,
            fill=outline, width=w,
        )
        self.canvas.create_line(
            left + r, bot, right - r, bot,
            fill=outline, width=w,
        )

    def _create_bars(self):
        cy = self.height // 2
        self.bars = []
        for i in range(self.NUM_BARS):
            x0 = self.PADDING_X + i * (self.BAR_WIDTH + self.BAR_GAP)
            x1 = x0 + self.BAR_WIDTH
            bar_id = self.canvas.create_rectangle(
                x0, cy - 1, x1, cy + 1,
                fill=self.BAR_COLOR, outline="",
            )
            self.bars.append((bar_id, x0, x1))

    # ---------- API שמיועד לקריאה מ-threads אחרים ----------
    def show(self):
        self.root.after(0, self._do_show)

    def hide(self):
        self.root.after(0, self._do_hide)

    def push_level(self, rms):
        normalized = min(1.0, max(0.0, rms / self.LEVEL_SCALE))
        self.levels.append(normalized)

    def quit(self):
        try:
            self.root.after(0, self.root.quit)
        except Exception:
            pass

    def run_mainloop(self):
        self.root.mainloop()

    # ---------- מתבצע ב-thread של tkinter ----------
    def _position_on_active_monitor(self):
        try:
            left, top, right, bottom = _get_active_monitor_workarea()
            mon_w = right - left
            x = left + (mon_w - self.width) // 2
            y = bottom - self.height - self.BOTTOM_OFFSET
            self.root.geometry(f"{self.width}x{self.height}+{x}+{y}")
        except Exception as e:
            print(f"WARNING: could not detect active monitor: {e}")

    def _do_show(self):
        self._position_on_active_monitor()
        self.levels = deque([0.0] * self.NUM_BARS, maxlen=self.NUM_BARS)
        self.current_height = [0.0] * self.NUM_BARS
        self.root.deiconify()
        self.root.attributes("-topmost", True)
        if not self._animating:
            self._animating = True
            self._animate()

    def _do_hide(self):
        self._animating = False
        self.root.withdraw()

    def _animate(self):
        if not self._animating:
            return
        max_h = self.PILL_HEIGHT - 4
        min_h = self.BAR_MIN_HEIGHT
        cy = self.height // 2

        targets = list(self.levels)

        for i in range(self.NUM_BARS):
            target_h = min_h + targets[i] * (max_h - min_h)
            self.current_height[i] += (target_h - self.current_height[i]) * self.SMOOTHING
            h = max(min_h, self.current_height[i])

            bar_id, x0, x1 = self.bars[i]
            y0 = cy - h / 2
            y1 = cy + h / 2
            self.canvas.coords(bar_id, x0, y0, x1, y1)

        self.root.after(33, self._animate)
