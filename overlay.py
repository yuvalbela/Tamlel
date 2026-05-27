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
    NUM_BARS = 14
    BAR_WIDTH = 3       # ברוחב 2 כמעט לא רואים את הקצוות העגולים ב-tkinter;
                         # 3 פיקסלים זה המינימום שבו ה-capstyle=ROUND ניכר.
    BAR_GAP = 2          # הוקטן כדי לשמור על אותו רוחב פיל כולל.
    BAR_MIN_HEIGHT = 3   # ≥ BAR_WIDTH כדי שגם במצב הכי שטוח יראו עיגול מלא.
    BAR_COLOR = "#ffffff"

    PILL_FILL_COLOR = "#1a1a1a"     # מילוי כהה שייראה על כל רקע
    PILL_OUTLINE_COLOR = "#ffffff"
    PILL_OUTLINE_WIDTH = 2
    PILL_HEIGHT = 26

    # alpha של החלון: 1.0 = אטום מלא, 0.0 = שקוף לגמרי. הערך הזה משפיע על כל מה
    # שמצויר בחלון (גם הפיל וגם הברים) - אז הוא צריך לשמור על קונטרסט מספיק.
    WINDOW_ALPHA = 0.82

    # צבע נדיר ש-Windows יחשיב כשקוף לחלוטין + click-through (לאזורים מחוץ לפיל)
    TRANSPARENT_COLOR = "#ff00fe"

    WINDOW_HEIGHT = 34
    PADDING_X = 12
    BOTTOM_OFFSET = 30  # מרחק מתחתית ה-work area (מעל ה-taskbar)

    SMOOTHING = 0.45
    LEVEL_SCALE = 5000.0

    # אנימציית פתיחה/סגירה בסגנון Dynamic Island. מחושבת כל פריים מחדש לפי
    # רוחב/גובה החלון, אז משתנה אוטומטית עם שינוי המידות של הפיל.
    ANIM_OPEN_MS = 280
    ANIM_CLOSE_MS = 200
    ANIM_FRAME_MS = 16  # ~60fps

    # אזור פנימי מוסתר מסביב לפיל כדי שה-'overshoot' של ease_out_back (עד ~10%
    # מעל גודל המטרה) יוכל להתפרס בלי שיותר ייחתך בקצוות הקנבס. בלי זה רואים
    # 'מסגרת מלבנית' רגעית - הקווים שעולים על קצה הקנבס נראים כקו ישר חתוך.
    OVERSHOOT_PAD_X = 14
    OVERSHOOT_PAD_Y = 6

    # ספינר עיבוד: מצויר *בתוך* הפיל הקיים (לא מרחיב אותו). הברים מתכווצים
    # שמאלה כדי לפנות לו מקום.
    SPINNER_SIZE = 14           # קוטר הספינר
    SPINNER_MARGIN_RIGHT = 4    # מרחק קצה ספינר מקצה פנימי של הפיל
    SPINNER_GAP_FROM_BARS = 4   # רווח בין הברים המכווצים לספינר
    SPINNER_ARC_EXTENT = 90     # אורך הקשת במעלות
    SPINNER_WIDTH = 2
    SPINNER_COLOR = "#ffffff"
    SPINNER_ROT_PER_FRAME = 18  # מעלות לכל פריים (~30FPS → ~540°/sec)

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

        # גודל המטרה של הפיל (מה שמופיע בסוף האנימציה).
        bars_width_full = (self.NUM_BARS * (self.BAR_WIDTH + self.BAR_GAP)
                           - self.BAR_GAP)
        self._target_pill_w = self.PADDING_X * 2 + bars_width_full
        self._target_pill_h = self.WINDOW_HEIGHT
        # הקנבס/חלון גדול ב-overshoot_pad מסביב לפיל. הפיל ממורכז בתוכו תמיד.
        # האזור החיצוני נשאר ב-TRANSPARENT_COLOR (=שקוף + click-through).
        self.width = self._target_pill_w + self.OVERSHOOT_PAD_X
        self.height = self._target_pill_h + self.OVERSHOOT_PAD_Y
        # הסטה של הפיל בתוך הקנבס בגודלו המלא (הוא מתחיל ב-pad/2 משמאל/מעל)
        self._pill_off_x = self.OVERSHOOT_PAD_X // 2
        self._pill_off_y = self.OVERSHOOT_PAD_Y // 2

        # מיקומי הברים בקואורדינטות הקנבס. הברים עוקבים אחרי מיקום הפיל - לכן
        # מוסטים ב-_pill_off_x.
        self._bar_positions = [
            (self._pill_off_x + self.PADDING_X
             + i * (self.BAR_WIDTH + self.BAR_GAP),
             self._pill_off_x + self.PADDING_X
             + i * (self.BAR_WIDTH + self.BAR_GAP) + self.BAR_WIDTH)
            for i in range(self.NUM_BARS)
        ]
        # מיקום הספינר: בקצה הימני הפנימי של הפיל בגודלו המלא.
        self._spinner_left = (self._pill_off_x + self._target_pill_w
                              - self.PADDING_X - self.SPINNER_MARGIN_RIGHT
                              - self.SPINNER_SIZE)
        # במצב processing מסתירים את הברים שמדרסים על הספינר.
        max_visible_x = self._spinner_left - self.SPINNER_GAP_FROM_BARS
        self._num_bars_visible_processing = sum(
            1 for x0, x1 in self._bar_positions if x1 <= max_visible_x
        )

        self.canvas = tk.Canvas(
            self.root, width=self.width, height=self.height,
            bg=self.TRANSPARENT_COLOR, highlightthickness=0, bd=0,
        )
        self.canvas.pack()

        self._redraw_pill(self._target_pill_w, self._target_pill_h)
        self._create_bars()
        self._create_spinner()
        # אחרי שכל הפריטים נוצרו - מוודאים שהפיל נמצא ב-z-order התחתון, כדי
        # שהברים והספינר יישארו מעליו גם אחרי redraw של הפיל באנימציה.
        self.canvas.tag_lower("pill")

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
        # "recording" = ברים פעילים, ספינר מוסתר.
        # "processing" = הברים הימניים מוסתרים, ספינר מסתובב.
        self._mode = "recording"
        self._spinner_angle = 0
        # מזהה אנימציית geometry: כל אנימציה חדשה מבטלת את הקודמת (open לא ינעל
        # את close אם המשתמש פתח-סגר מהר).
        self._anim_id = 0
        # נקודת עיגון לאנימציה: (center_x, bottom_y) של המיקום הסופי על המסך.
        self._final_anchor = None

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

    def _redraw_pill(self, w, h):
        """מצייר פיל בגודל נתון (w × h) *ממורכז בתוך הקנבס המלא*. החלון עצמו
        לא משנה גודל בזמן אנימציה - השטח החיצוני נשאר ב-TRANSPARENT_COLOR
        ולכן שקוף לחלוטין + click-through. זה מבטל את ה'מסגרת המלבנית' שהופיעה
        קודם כשהחלון עצמו עבר resize (Windows מצייר רגעית מסגרת על layered
        window בזמן שינוי גודל)."""
        self.canvas.delete("pill")
        if w < 4 or h < 4:
            return

        # פיל-גובה ו-inset שמאל/ימין משתנים פרופורציונלית עם h. היחס מבוסס
        # על המידות *של הפיל* (לא של הקנבס) כדי שגם ב-overshoot הפרופורציה
        # נשמרת.
        ph_ratio = self.PILL_HEIGHT / self._target_pill_h
        ph = max(2, int(h * ph_ratio))
        inset_x = max(1, int(round(2 * h / self._target_pill_h)))

        # מרכז הקנבס המלא - כל גדלי הפיל ממורכזים סביב אותה נקודה
        cx = self.width // 2
        cy = self.height // 2

        # רוחב פיל בפועל אחרי הורדת ה-insets
        pill_w_total = w - 2 * inset_x
        if pill_w_total < 4:
            return

        left = cx - pill_w_total // 2
        right = left + pill_w_total
        top = cy - ph // 2
        bot = top + ph
        r = min(ph // 2, pill_w_total // 2)
        if r < 1:
            return

        fill = self.PILL_FILL_COLOR
        outline = self.PILL_OUTLINE_COLOR
        ow = self.PILL_OUTLINE_WIDTH

        # ---------- מילוי ----------
        self.canvas.create_oval(
            left, top, left + 2 * r, bot,
            fill=fill, outline="", tags="pill",
        )
        self.canvas.create_oval(
            right - 2 * r, top, right, bot,
            fill=fill, outline="", tags="pill",
        )
        if right - r > left + r:
            self.canvas.create_rectangle(
                left + r, top, right - r, bot,
                fill=fill, outline="", tags="pill",
            )

        # ---------- outline ----------
        self.canvas.create_arc(
            left, top, left + 2 * r, bot,
            start=90, extent=180,
            style=tk.ARC, outline=outline, width=ow, tags="pill",
        )
        self.canvas.create_arc(
            right - 2 * r, top, right, bot,
            start=-90, extent=180,
            style=tk.ARC, outline=outline, width=ow, tags="pill",
        )
        if right - r > left + r:
            self.canvas.create_line(
                left + r, top, right - r, top,
                fill=outline, width=ow, tags="pill",
            )
            self.canvas.create_line(
                left + r, bot, right - r, bot,
                fill=outline, width=ow, tags="pill",
            )
        # שומר את הפיל מתחת לברים והספינר (נקרא ב-init אחרי יצירת הפריטים, אבל
        # ב-redraw בזמן ריצה הפריטים הקיימים כבר במקום)
        self.canvas.tag_lower("pill")

    def _create_bars(self):
        """כל בר הוא create_line בודד עם capstyle='round' - tkinter מטפל
        בקצוות העגולים native, ואין בעיית יישור בין חצאי-עיגול למלבן.
        כשגובה הבר ≤ רוחבו, הוא נראה כעיגול קטן."""
        cy = self.height // 2
        self.bars = []
        for x0, x1 in self._bar_positions:
            bw = x1 - x0
            cx_pos = (x0 + x1) / 2
            # נקודת התחלה: מינימום (cy) - האנימציה תמתח אותו
            bar_id = self.canvas.create_line(
                cx_pos, cy, cx_pos, cy,
                fill=self.BAR_COLOR, width=bw,
                capstyle=tk.ROUND,
            )
            self.bars.append({
                "id": bar_id, "x0": x0, "x1": x1, "cx": cx_pos, "bw": bw,
            })

    def _apply_bar_layout(self, mode):
        """מחביא/מציג ברים לפי המצב."""
        if mode == "processing":
            visible = self._num_bars_visible_processing
        else:
            visible = self.NUM_BARS
        for i, bar in enumerate(self.bars):
            state = "normal" if i < visible else "hidden"
            self.canvas.itemconfigure(bar["id"], state=state)

    def _create_spinner(self):
        """יוצר את קשת הספינר. מוסתרת בתחילה (מצב recording)."""
        cy = self.height // 2
        r = self.SPINNER_SIZE // 2
        cx = self._spinner_left + r
        self._spinner_bbox = (cx - r, cy - r, cx + r, cy + r)
        self._spinner_id = self.canvas.create_arc(
            *self._spinner_bbox,
            start=0, extent=self.SPINNER_ARC_EXTENT,
            style=tk.ARC, outline=self.SPINNER_COLOR,
            width=self.SPINNER_WIDTH,
            state="hidden",
        )

    # ---------- API שמיועד לקריאה מ-threads אחרים ----------
    def show(self):
        self.root.after(0, self._do_show)

    def show_processing(self):
        """עובר ממצב recording ל-processing: ברים נחים, ספינר מתחיל לסובב."""
        self.root.after(0, self._do_show_processing)

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
    def _compute_anchor(self):
        """מחשב (center_x, bottom_y) של המיקום הסופי במסך הפעיל. נקודת העיגון
        קבועה לכל אורך אנימציית הפתיחה/סגירה: הפיל גדל/מתכווץ סביב המרכז
        האופקי וצמוד לקצה התחתון."""
        try:
            left, _top, right, bottom = _get_active_monitor_workarea()
            mon_w = right - left
            cx = left + mon_w // 2
            by = bottom - self.BOTTOM_OFFSET
            return (cx, by)
        except Exception as e:
            print(f"WARNING: could not detect active monitor: {e}")
            return (640, 700)

    def _position_window(self, anchor):
        """ממקם את החלון בגודלו המלא, כך שתחתית *הפיל* (לא הקנבס) תהיה
        בנקודת העיגון. שטחי ה-overshoot סביב הפיל שקופים. החלון לא יזוז יותר
        לאורך אנימציה - האנימציה משנה רק את ציור הפיל בקנבס. זה מבטל flicker
        של Windows ב-layered window בזמן resize."""
        cx, by = anchor
        x = cx - self.width // 2
        # תחתית הפיל בקואורדינטות הקנבס: canvas_center_y + pill_height/2.
        # אנחנו רוצים שזה ייפול בדיוק על by במסך.
        pill_bot_in_canvas = self.height // 2 + self.PILL_HEIGHT // 2
        y = by - pill_bot_in_canvas
        self.root.geometry(f"{self.width}x{self.height}+{x}+{y}")

    def _open_start_size(self):
        """גודל ההתחלה של אנימציית הפתיחה - 'כדור' קטן באמצע (בסגנון Dynamic
        Island). מבוסס על גובה הפיל המלא כך שמסתגל לכל שינוי גודל."""
        start_h = max(4, self._target_pill_h * 6 // 10)
        start_w = start_h  # עיגול
        return (start_w, start_h)

    @staticmethod
    def _ease_out_back(t):
        """ease-out עם חריגה קלה - נותן את ה-'pop' של Dynamic Island בפתיחה."""
        c1 = 1.70158
        c3 = c1 + 1
        return 1 + c3 * (t - 1) ** 3 + c1 * (t - 1) ** 2

    @staticmethod
    def _ease_in_back(t):
        """ease-in הופכי: מתכווץ חזרה עם קצת 'משיכה' לפני שנעלם."""
        c1 = 1.70158
        c3 = c1 + 1
        return c3 * t ** 3 - c1 * t ** 2

    def _hide_dynamic_items(self):
        """מסתיר ברים + ספינר. שימושי במהלך אנימציית פתיחה/סגירה - רק הפיל
        עצמו רואים אז."""
        for bar in self.bars:
            self.canvas.itemconfigure(bar["id"], state="hidden")
        self.canvas.itemconfigure(self._spinner_id, state="hidden")

    def _animate_geometry(self, start, end, duration_ms, easing, on_done):
        """מריץ אנימציה של ציור הפיל בלולאת after. החלון לא משנה גודל - רק
        הציור של הפיל בתוך הקנבס. מבטל אנימציות קודמות אוטומטית ע"י bump של
        _anim_id."""
        self._anim_id += 1
        aid = self._anim_id
        sw, sh = start
        ew, eh = end
        frame_ms = self.ANIM_FRAME_MS
        steps = max(1, duration_ms // frame_ms)

        def step(i):
            if aid != self._anim_id:
                return  # אנימציה חדשה התחילה - להפסיק את הישנה
            t = min(1.0, max(0.0, i / steps))
            e = easing(t)
            w = max(4, int(round(sw + (ew - sw) * e)))
            h = max(4, int(round(sh + (eh - sh) * e)))
            self._redraw_pill(w, h)
            if i < steps:
                self.root.after(frame_ms, lambda: step(i + 1))
            else:
                # פריים אחרון בגודל המדויק (לא תוצר עיגול ביניים)
                self._redraw_pill(ew, eh)
                if on_done:
                    on_done()

        step(0)

    def _do_show(self):
        self._final_anchor = self._compute_anchor()
        self._position_window(self._final_anchor)
        self.levels = deque([0.0] * self.NUM_BARS, maxlen=self.NUM_BARS)
        self.current_height = [0.0] * self.NUM_BARS
        self._mode = "recording"
        self._hide_dynamic_items()
        sw, sh = self._open_start_size()
        self._redraw_pill(sw, sh)
        self.root.deiconify()
        self.root.attributes("-topmost", True)
        self._animate_geometry(
            start=(sw, sh), end=(self._target_pill_w, self._target_pill_h),
            duration_ms=self.ANIM_OPEN_MS, easing=self._ease_out_back,
            on_done=lambda: self._on_open_done("recording"),
        )

    def _do_show_processing(self):
        """אם הפיל לא גלוי - פותח עם אנימציה לתוך מצב processing.
        אם כבר גלוי - מעבר חלק (החלפת layout + הצגת ספינר) בלי geometry anim."""
        if not self.root.winfo_viewable():
            self._final_anchor = self._compute_anchor()
            self._position_window(self._final_anchor)
            self.levels = deque([0.0] * self.NUM_BARS, maxlen=self.NUM_BARS)
            self.current_height = [0.0] * self.NUM_BARS
            self._mode = "processing"
            self._hide_dynamic_items()
            sw, sh = self._open_start_size()
            self._redraw_pill(sw, sh)
            self.root.deiconify()
            self.root.attributes("-topmost", True)
            self._animate_geometry(
                start=(sw, sh), end=(self._target_pill_w, self._target_pill_h),
                duration_ms=self.ANIM_OPEN_MS, easing=self._ease_out_back,
                on_done=lambda: self._on_open_done("processing"),
            )
            return

        # כבר גלוי במלוא גודלו - רק החלפת מצב
        self._mode = "processing"
        self._apply_bar_layout("processing")
        self.levels = deque([0.0] * self.NUM_BARS, maxlen=self.NUM_BARS)
        self.current_height = [0.0] * self.NUM_BARS
        self.canvas.itemconfigure(self._spinner_id, state="normal")

    def _on_open_done(self, mode):
        """נקרא בסיום אנימציית הפתיחה - חושף את התוכן הדינמי ומתחיל את לולאת
        אנימציית הברים."""
        self._mode = mode
        self._apply_bar_layout(mode)
        self.canvas.itemconfigure(
            self._spinner_id,
            state="normal" if mode == "processing" else "hidden",
        )
        if not self._animating:
            self._animating = True
            self._animate()

    def _do_hide(self):
        self._animating = False
        self._hide_dynamic_items()
        if self._final_anchor is None:
            # תאורטית לא יקרה (hide בלי show), אבל למקרה הצורך
            self.root.withdraw()
            return
        ew, eh = self._open_start_size()
        self._animate_geometry(
            start=(self._target_pill_w, self._target_pill_h), end=(ew, eh),
            duration_ms=self.ANIM_CLOSE_MS, easing=self._ease_in_back,
            on_done=self._on_close_done,
        )

    def _on_close_done(self):
        self._mode = "recording"
        self.root.withdraw()
        # מחזירים את ציור הפיל לגודל המלא לקראת ה-show הבא (כדי שאם משהו ימדוד
        # את הפיל לפני אנימציה, הוא יראה את הגודל הסופי).
        self._redraw_pill(self._target_pill_w, self._target_pill_h)

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

            bar = self.bars[i]
            cx_pos = bar["cx"]
            bw = bar["bw"]
            # capstyle='round' מוסיף חצי-עיגול בקצה הקו - לכן אורך הקו
            # האמיתי הוא h-bw (הקצוות העגולים מוסיפים bw/2 בכל קצה).
            line_len = max(0, h - bw)
            y0 = cy - line_len / 2
            y1 = cy + line_len / 2
            self.canvas.coords(bar["id"], cx_pos, y0, cx_pos, y1)

        # סיבוב הספינר רק במצב processing
        if self._mode == "processing":
            self._spinner_angle = (self._spinner_angle - self.SPINNER_ROT_PER_FRAME) % 360
            self.canvas.itemconfigure(self._spinner_id, start=self._spinner_angle)

        self.root.after(33, self._animate)
