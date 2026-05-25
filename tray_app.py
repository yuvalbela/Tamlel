"""
Tamlel - אפליקציית רקע עם tray icon ו-hotkey גלובלי.

הפעלה:
    python tray_app.py
    או דרך Tamlel.bat (ללא חלון CMD)

הגדרות נשמרות ב-settings.json:
    - hotkey: למשל "ctrl+shift+space", "alt+r", "f9", "ctrl+alt+t"
    - mode:
        "toggle" - לחיצה ראשונה מתחילה הקלטה, לחיצה שנייה עוצרת ומעבדת
        "hold"   - להחזיק את הקיצור לוחץ = להקליט; ברגע ששוחררים = עיבוד והדבקה

ניתן לשנות את ה-mode דרך right-click על אייקון ה-tray.
לשינוי ה-hotkey: עורכים את settings.json ומפעילים מחדש.
"""

import os
import sys
import time
import threading
import json

# ייבוא הלוגיקה מ-transcribe.py (אותה ליבה כמו ב-CLI)
from transcribe import (
    record_until_event,
    transcribe_audio,
    save_output,
    append_to_history,
    count_today_usage,
    DAILY_LIMIT,
)

# ---------- הגדרות ----------
SETTINGS_FILE = "settings.json"
DEFAULT_SETTINGS = {
    "hotkey": "ctrl+shift+space",
    "mode": "toggle",  # "toggle" או "hold"
}
PASTE_DELAY_SEC = 0.5
MIN_RECORDING_SEC = 0.3  # הקלטה קצרה מזה תיחשב כקליק בטעות
HOLD_POLL_INTERVAL = 0.03  # תדירות בדיקה אם ה-hotkey עוד לחוץ ב-hold mode

# ---------- ספריות חיצוניות ----------
try:
    import keyboard
    import pyperclip
    from pystray import Icon, Menu, MenuItem
    from PIL import Image, ImageDraw
except ImportError as e:
    print(f"ERROR: missing library: {e}")
    print("Run: pip install -r requirements.txt")
    sys.exit(1)


# ---------- ניהול settings.json ----------
def load_settings():
    if not os.path.isfile(SETTINGS_FILE):
        return dict(DEFAULT_SETTINGS)
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        merged = dict(DEFAULT_SETTINGS)
        merged.update(data)
        return merged
    except (json.JSONDecodeError, OSError) as e:
        print(f"WARNING: bad settings.json ({e}), using defaults.")
        return dict(DEFAULT_SETTINGS)


def save_settings_to_disk(settings):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
    except OSError as e:
        print(f"WARNING: could not save settings: {e}")


SETTINGS = load_settings()


# ---------- ציור האייקון: אות t חלקלקה עם hook למטה ----------
def make_t_image(size, color):
    """
    מצייר אות t במבנה chunky:
    גזע אנכי + crossbar אופקי + hook (חצי-אליפסה) בתחתית הגזע.
    """
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    s = size

    # יחסים על קנבס נורמלי (0..1) — לפי תמונת הרפרנס
    stem_x1 = int(s * 0.31)
    stem_x2 = int(s * 0.52)
    stem_y_top = int(s * 0.15)
    stem_y_curve = int(s * 0.62)  # איפה הגזע מתחיל להתעקל

    cb_x1 = stem_x2
    cb_x2 = int(s * 0.74)
    cb_y1 = int(s * 0.38)
    cb_y2 = int(s * 0.57)

    hook_right = int(s * 0.62)
    hook_bottom = int(s * 0.85)

    # גזע (חלק רגיל בלי עיקול)
    draw.rectangle([stem_x1, stem_y_top, stem_x2, stem_y_curve], fill=color)
    # crossbar
    draw.rectangle([cb_x1, cb_y1, cb_x2, cb_y2], fill=color)

    # hook = החצי התחתון של אליפסה
    # האליפסה משתרעת אופקית מ-stem_x1 עד hook_right, אנכית סביב stem_y_curve
    hook_h = hook_bottom - stem_y_curve
    ellipse_box = [stem_x1, stem_y_curve - hook_h, hook_right, stem_y_curve + hook_h]
    draw.pieslice(ellipse_box, 0, 180, fill=color)
    return img


def load_or_draw_icon(filename, color):
    """אם יש קובץ PNG בתיקייה (לדוגמה icon_idle.png) - טוען אותו; אחרת מצייר."""
    if os.path.isfile(filename):
        try:
            return Image.open(filename).convert("RGBA")
        except Exception as e:
            print(f"WARNING: failed to load {filename}: {e}")
    return make_t_image(64, color)


ICON_IDLE = load_or_draw_icon("icon_idle.png", "#1ea84a")        # ירוק
ICON_RECORDING = load_or_draw_icon("icon_recording.png", "#d03030")  # אדום
ICON_PROCESSING = load_or_draw_icon("icon_processing.png", "#e0a020")  # צהוב


# ---------- מצב גלובלי ----------
class AppState:
    def __init__(self):
        self.is_recording = False
        self.stop_event = None
        self.icon = None
        self.lock = threading.Lock()


state = AppState()


# ---------- זרימת תמלול ----------
def do_transcribe_flow(audio_path, duration, rms):
    try:
        state.icon.icon = ICON_PROCESSING
        state.icon.title = "Tamlel - processing..."

        print(f"Recorded {duration:.1f}s, RMS={rms:.0f}")

        if duration < MIN_RECORDING_SEC:
            print(f"WARNING: recording too short ({duration:.2f}s), skipping.")
            return
        if rms < 50:
            print("WARNING: audio very quiet, skipping.")
            return

        text = transcribe_audio(audio_path)
        save_output(text)
        append_to_history(text)

        pyperclip.copy(text)
        # שחרור מפורש של המודיפיירים שלוחצו ב-hotkey, כדי שה-Ctrl+V לא יתפרש
        # כקומבינציה משונה עם המודיפיירים שעוד "פתוחים" במערכת.
        _release_hotkey_modifiers()
        time.sleep(PASTE_DELAY_SEC)
        keyboard.send("ctrl+v")

        used = count_today_usage()
        print(f"Done. Daily usage: {used} / {DAILY_LIMIT}")
        state.icon.title = f"Tamlel - {used}/{DAILY_LIMIT} today"

    except SystemExit:
        print("Transcription aborted.")
    except Exception as e:
        print(f"ERROR in transcribe flow: {e}")
    finally:
        try:
            if os.path.exists(audio_path):
                os.remove(audio_path)
        except OSError:
            pass
        state.icon.icon = ICON_IDLE
        try:
            state.icon.update_menu()
        except Exception:
            pass


def start_recording():
    print("Recording started.")
    state.stop_event = threading.Event()
    state.icon.icon = ICON_RECORDING
    state.icon.title = "Tamlel - recording..."

    def runner():
        result = record_until_event(state.stop_event)
        with state.lock:
            state.is_recording = False
        if result is None:
            print("ERROR: no audio captured.")
            state.icon.icon = ICON_IDLE
            return
        do_transcribe_flow(result["path"], result["duration"], result["rms"])

    threading.Thread(target=runner, daemon=True).start()


def stop_recording():
    # idempotent: לא מדפיסים ולא משדרים סיגנל פעמיים
    if state.stop_event is None or state.stop_event.is_set():
        return
    print("Stopping recording...")
    state.stop_event.set()


# ---------- מטפלי hotkey ----------
MODIFIER_KEYS = {"ctrl", "shift", "alt", "win", "windows", "cmd"}


def _hotkey_parts():
    """מפצל את ה-hotkey למפתחות נפרדים (lowercase)."""
    return [k.strip().lower() for k in SETTINGS["hotkey"].split("+") if k.strip()]


def _release_hotkey_modifiers():
    """משחרר ידנית את המודיפיירים של ה-hotkey הנוכחי, כדי שלא יישארו 'תקועים'."""
    for k in _hotkey_parts():
        if k in MODIFIER_KEYS:
            try:
                keyboard.release(k)
            except Exception:
                pass


def _is_hotkey_still_pressed():
    """בודק אם הקיצור עדיין לחוץ. מנסה קודם את המחרוזת המלאה, אחר כך לפי מקשים."""
    try:
        return keyboard.is_pressed(SETTINGS["hotkey"])
    except Exception:
        pass
    try:
        return all(keyboard.is_pressed(k) for k in _hotkey_parts())
    except Exception:
        return False


def _hold_watcher():
    """רץ ב-thread נפרד ב-hold mode: עוצר את ההקלטה כשהקיצור משוחרר."""
    # המתנה ארוכה יחסית לפני שמתחילים לבדוק: ספריית keyboard עלולה לקרוא
    # ל-callback לפני שהמקשים הספיקו להירשם ב-is_pressed.
    time.sleep(0.25)
    while _is_hotkey_still_pressed():
        time.sleep(HOLD_POLL_INTERVAL)
    stop_recording()


def on_hotkey_press():
    """לחיצה על ה-hotkey. ההתנהגות תלויה ב-mode."""
    if SETTINGS["mode"] == "hold":
        with state.lock:
            if state.is_recording:
                return  # כבר מקליט (key repeat - מתעלמים)
            state.is_recording = True
        start_recording()
        threading.Thread(target=_hold_watcher, daemon=True).start()
    else:
        # toggle
        with state.lock:
            if state.is_recording:
                should_stop = True
            else:
                state.is_recording = True
                should_stop = False
        if should_stop:
            stop_recording()
        else:
            start_recording()


# ---------- תפריט tray ----------
def usage_text(_item):
    return f"Daily usage: {count_today_usage()} / {DAILY_LIMIT}"


def hotkey_text(_item):
    return f"Hotkey: {SETTINGS['hotkey']}"


def mode_text(_item):
    label = "Hold to record" if SETTINGS["mode"] == "hold" else "Press to toggle"
    return f"Mode: {label}  (click to switch)"


def toggle_mode(icon, _item):
    SETTINGS["mode"] = "hold" if SETTINGS["mode"] == "toggle" else "toggle"
    save_settings_to_disk(SETTINGS)
    print(f"Mode changed to: {SETTINGS['mode']}")
    icon.update_menu()


def on_quit(icon, _item):
    print("Quitting...")
    icon.stop()


def build_menu():
    return Menu(
        MenuItem(usage_text, lambda *_: None, enabled=False),
        MenuItem(hotkey_text, lambda *_: None, enabled=False),
        Menu.SEPARATOR,
        MenuItem(mode_text, toggle_mode),
        Menu.SEPARATOR,
        MenuItem("Quit", on_quit),
    )


# ---------- רישום קיצורים ----------
def register_hotkeys():
    try:
        # רישום של handler אחד בלבד - השחרור מטופל ע"י polling ב-hold mode
        keyboard.add_hotkey(SETTINGS["hotkey"], on_hotkey_press)
    except Exception as e:
        print(f"ERROR: could not register hotkey '{SETTINGS['hotkey']}': {e}")
        print("On Windows you may need to run as Administrator.")
        sys.exit(1)


def main():
    register_hotkeys()
    print(f"Tamlel running. Hotkey: {SETTINGS['hotkey']}, mode: {SETTINGS['mode']}")
    print("Right-click the tray icon for menu (mode toggle, daily usage, quit).")

    icon = Icon("Tamlel", ICON_IDLE, "Tamlel - ready", menu=build_menu())
    state.icon = icon
    icon.run()


if __name__ == "__main__":
    main()
