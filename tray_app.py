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
import shutil
import ctypes
import traceback
from datetime import datetime


# ---------- לוגינג לקובץ (חיוני כשמפעילים דרך pythonw בלי CMD) ----------
LOG_FILE = "app.log"


class _Tee:
    """כותב לכמה זרמים בו זמנית, עם prefix של חותמת זמן בתחילת שורה."""
    def __init__(self, *streams):
        self.streams = [s for s in streams if s is not None]
        self._at_line_start = True

    def write(self, data):
        if not data:
            return
        try:
            if self._at_line_start and data.strip():
                stamp = datetime.now().strftime("[%H:%M:%S] ")
                data = stamp + data
            self._at_line_start = data.endswith("\n")
            for s in self.streams:
                try:
                    s.write(data)
                    s.flush()
                except Exception:
                    pass
        except Exception:
            pass

    def flush(self):
        for s in self.streams:
            try:
                s.flush()
            except Exception:
                pass


_log_fp = open(LOG_FILE, "a", encoding="utf-8", buffering=1)
sys.stdout = _Tee(sys.stdout, _log_fp)
sys.stderr = _Tee(sys.stderr, _log_fp)

print("\n" + "=" * 60)
print(f"===== Tamlel started at {datetime.now():%Y-%m-%d %H:%M:%S} =====")


def _thread_excepthook(args):
    """לוכד שגיאות שקרו בתוך threads (אחרת הן נבלעות בשקט)."""
    print(f"THREAD EXCEPTION in {args.thread.name}: {args.exc_value!r}")
    traceback.print_exception(args.exc_type, args.exc_value, args.exc_traceback)


threading.excepthook = _thread_excepthook

# ייבוא הלוגיקה מ-transcribe.py (אותה ליבה כמו ב-CLI)
from transcribe import (
    record_until_event,
    transcribe_with_fallback,
    save_output,
    append_to_history,
    count_today_usage,
    read_last_transcription,
    HISTORY_FILE,
    DEFAULT_MODELS,
    TranscriptionError,
    TranscriptionAuthError,
    TranscriptionEmptyResponseError,
)
from overlay import RecordingOverlay

# ---------- הגדרות ----------
SETTINGS_FILE = "settings.json"
DEFAULT_SETTINGS = {
    "hotkey": "ctrl+shift+space",
    "mode": "toggle",  # "toggle" או "hold"
    "models": DEFAULT_MODELS,  # שרשרת fallback
}
PASTE_DELAY_SEC = 0.5
# כמה להמתין אחרי ctrl+v לפני שחזור הקליפבורד המקורי. 200ms מספיקים לכל
# אפליקציה מודרנית לקרוא את הקליפבורד אחרי ctrl+v - המשתמש מרגיש את זה
# כסיום מהיר יותר של ה-flow.
CLIPBOARD_RESTORE_DELAY_SEC = 0.2
MIN_RECORDING_SEC = 0.3  # הקלטה קצרה מזה תיחשב כקליק בטעות
HOLD_POLL_INTERVAL = 0.03  # תדירות בדיקה אם ה-hotkey עוד לחוץ ב-hold mode
ERROR_ICON_FLASH_SEC = 8  # כמה זמן האייקון נשאר כתום אחרי כשל
FAILED_RECORDINGS_DIR = "failed_recordings"
FAILED_RECORDINGS_KEEP_DAYS = 14  # מחיקה אוטומטית של הקלטות נכשלות ישנות

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
# האייקון משנה צבעים לפי מצב: ירוק=המתנה, אדום=מקליט, צהוב=מעבד, כתום=שגיאה.
# (האייקון הוא עזר; הפידבק העיקרי בזמן הקלטה הוא חלון ה-overlay במסך.)
ICON_COLOR_IDLE = "#1ea84a"        # ירוק
ICON_COLOR_RECORDING = "#d03030"   # אדום
ICON_COLOR_PROCESSING = "#e0a020"  # צהוב
ICON_COLOR_ERROR = "#ff6b00"       # כתום


def make_t_image(size, color):
    """
    מצייר אות t במבנה chunky: גזע אנכי + crossbar אופקי + hook (חצי-אליפסה).
    יחסים מורחבים - האות תופסת ~90% מהקנבס (יותר גדולה ובולטת ב-tray).
    """
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    s = size

    stem_x1 = int(s * 0.26)
    stem_x2 = int(s * 0.52)
    stem_y_top = int(s * 0.06)
    stem_y_curve = int(s * 0.65)

    cb_x1 = stem_x2
    cb_x2 = int(s * 0.79)
    cb_y1 = int(s * 0.35)
    cb_y2 = int(s * 0.59)

    hook_right = int(s * 0.64)
    hook_bottom = int(s * 0.94)

    draw.rectangle([stem_x1, stem_y_top, stem_x2, stem_y_curve], fill=color)
    draw.rectangle([cb_x1, cb_y1, cb_x2, cb_y2], fill=color)

    hook_h = hook_bottom - stem_y_curve
    ellipse_box = [stem_x1, stem_y_curve - hook_h, hook_right, stem_y_curve + hook_h]
    draw.pieslice(ellipse_box, 0, 180, fill=color)
    return img


ICONS_DIR = "icons"


def load_or_draw_icon(filename, color):
    """טוען PNG אם קיים ב-icons/ או בשורש (לתאימות), אחרת מצייר."""
    for path in (os.path.join(ICONS_DIR, filename), filename):
        if os.path.isfile(path):
            try:
                return Image.open(path).convert("RGBA")
            except Exception as e:
                print(f"WARNING: failed to load {path}: {e}")
    return make_t_image(96, color)


ICON_IDLE = load_or_draw_icon("icon_idle.png", ICON_COLOR_IDLE)
ICON_RECORDING = load_or_draw_icon("icon_recording.png", ICON_COLOR_RECORDING)
ICON_PROCESSING = load_or_draw_icon("icon_processing.png", ICON_COLOR_PROCESSING)
ICON_ERROR = load_or_draw_icon("icon_error.png", ICON_COLOR_ERROR)


# ---------- מצב גלובלי ----------
class AppState:
    def __init__(self):
        self.is_recording = False
        self.is_processing = False  # תמלול/retry באוויר - לא לקבל hotkey חדש
        self.stop_event = None
        self.icon = None
        self.overlay = None  # מוקצה ב-main לפני run_detached
        self.lock = threading.Lock()
        # מעקב אחר המודל הפעיל וההתראות שכבר הצגנו (כדי לא להציג שוב באותה ריצה)
        self.current_model = None
        self.notified_fallbacks = set()  # שמות מודלים שכבר הצגנו עליהם toast


state = AppState()


# ---------- זרימת תמלול ----------
def _notify(title, message):
    """שולח Toast notification של Windows. שקט בכישלון."""
    try:
        state.icon.notify(message, title)
    except Exception as e:
        print(f"  (could not show toast: {e})")


def _flash_error_icon():
    """משאיר את האייקון כתום למשך כמה שניות ואז חוזר לירוק."""
    state.icon.icon = ICON_ERROR

    def revert():
        time.sleep(ERROR_ICON_FLASH_SEC)
        # רק אם לא חזרנו להקלטה/עיבוד בינתיים
        if state.icon.icon is ICON_ERROR:
            state.icon.icon = ICON_IDLE
            state.icon.title = "Tamlel - ready"

    threading.Thread(target=revert, daemon=True).start()


def _save_failed_recording(audio_path):
    """מעביר WAV שנכשל לתיקיית failed_recordings/ עם חותמת זמן."""
    try:
        os.makedirs(FAILED_RECORDINGS_DIR, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        target = os.path.join(FAILED_RECORDINGS_DIR, f"recording_{stamp}.wav")
        shutil.move(audio_path, target)
        print(f"Saved failed recording to: {target}")
        return target
    except OSError as e:
        print(f"WARNING: could not save failed recording: {e}")
        return None


def _on_retry(event_type, model, attempt, exc, wait_sec):
    """Callback מ-transcribe_with_fallback - לפידבק ויזואלי במהלך retries."""
    if event_type == "retrying":
        state.icon.title = f"Tamlel - retrying ({model}, wait {wait_sec}s)..."
    elif event_type == "fallback":
        # סיבת ה-fallback מהשם של ה-exception (QuotaError / EmptyResponseError / ...)
        reason = type(exc).__name__.replace("Transcription", "").replace("Error", "")
        state.icon.title = f"Tamlel - falling back to {model}..."
        # מציגים toast רק בפעם הראשונה שעוברים למודל הזה בריצה הנוכחית
        if model not in state.notified_fallbacks:
            state.notified_fallbacks.add(model)
            _notify("Tamlel", f"Switching to {model} ({reason} on previous model)")
    # giving_up מטופל במקום אחר


def do_transcribe_flow(audio_path, duration, rms):
    state.is_processing = True
    # מצבים אפשריים: "idle" (חזרה לירוק), "error" (כתום - מנוהל ע"י _flash_error_icon)
    final_state = "idle"
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

        models = SETTINGS.get("models") or DEFAULT_MODELS
        try:
            result = transcribe_with_fallback(audio_path, models=models, on_retry=_on_retry)
        except TranscriptionAuthError as e:
            print(f"AUTH ERROR: {e}")
            _notify("Tamlel — Authentication failed",
                    "Check your GEMINI_API_KEY in config.py")
            _flash_error_icon()
            final_state = "error"
            return
        except TranscriptionEmptyResponseError as e:
            print(f"EMPTY/HALLUCINATED RESPONSE: {e}")
            _notify("Tamlel — Empty response",
                    "Gemini returned no usable transcription. Try speaking longer/clearer.")
            _flash_error_icon()
            final_state = "error"
            return
        except TranscriptionError as e:
            print(f"TRANSCRIPTION FAILED: {type(e).__name__}: {e}")
            saved_to = _save_failed_recording(audio_path)
            audio_path = None  # מסמן שאל תנסה למחוק שוב
            note = (f" Saved to {saved_to}" if saved_to else "")
            _notify("Tamlel — Transcription failed",
                    f"Gemini unavailable after retries.{note}")
            _flash_error_icon()
            final_state = "error"
            return

        text = result["text"]
        print(f"(used model: {result['model_used']})")
        state.current_model = result["model_used"]

        save_output(text)
        append_to_history(text)

        # שומרים את הקליפבורד המקורי (טקסט בלבד; אם הוא לא היה טקסט, pyperclip
        # מחזיר ""), כדי לשחזר אחרי ה-paste בלי לדרוס מה שהמשתמש העתיק.
        try:
            original_clipboard = pyperclip.paste()
        except Exception as e:
            print(f"  Could not read original clipboard: {e}")
            original_clipboard = None

        pyperclip.copy(text)
        # שחרור מפורש של המודיפיירים שלוחצו ב-hotkey, כדי שה-Ctrl+V לא יתפרש
        # כקומבינציה משונה עם המודיפיירים שעוד "פתוחים" במערכת.
        _release_hotkey_modifiers()
        time.sleep(PASTE_DELAY_SEC)
        keyboard.send("ctrl+v")

        # ממתינים שההדבקה תתבצע באפליקציית היעד לפני שמשחזרים את הקליפבורד.
        # אם משחזרים מוקדם מדי - הקליפבורד יתחלף עוד לפני שהיעד קרא אותו והדבקה
        # תיכשל / תדביק את התוכן הישן.
        time.sleep(CLIPBOARD_RESTORE_DELAY_SEC)
        if original_clipboard is not None:
            try:
                pyperclip.copy(original_clipboard)
            except Exception as e:
                print(f"  Could not restore clipboard: {e}")

        used = count_today_usage()
        print(f"Done. Transcriptions today: {used}")
        state.icon.title = f"Tamlel - {used} transcriptions today"

    except Exception as e:
        print(f"ERROR in transcribe flow: {type(e).__name__}: {e}")
        _flash_error_icon()
        final_state = "error"
    finally:
        # כעת אפשר להוריד את הפיל - אחרי שהטקסט הודבק (או אחרי שגיאה)
        if state.overlay is not None:
            state.overlay.hide()

        # ניקוי קובץ זמני (אלא אם נשמר ב-failed_recordings - אז audio_path = None)
        if audio_path:
            try:
                if os.path.exists(audio_path):
                    os.remove(audio_path)
            except OSError:
                pass

        # החזרת אייקון: רק אם לא במצב שגיאה (אז _flash_error_icon מנהל)
        if final_state == "idle":
            state.icon.icon = ICON_IDLE
            state.icon.title = "Tamlel - ready"

        try:
            state.icon.update_menu()
        except Exception:
            pass

        # שחרור הנעילה רק אחרי שהכל סגור - מקבלים hotkey חדש שוב
        state.is_processing = False


def start_recording():
    print("Recording started.")
    state.stop_event = threading.Event()
    state.icon.icon = ICON_RECORDING
    state.icon.title = "Tamlel - recording..."

    # פותחים את ה-overlay במסך - מתחיל להראות מיד
    if state.overlay is not None:
        state.overlay.show()

    def runner():
        on_chunk = state.overlay.push_level if state.overlay is not None else None
        result = record_until_event(state.stop_event, on_chunk_rms=on_chunk)
        with state.lock:
            state.is_recording = False
        if result is None:
            print("ERROR: no audio captured.")
            if state.overlay is not None:
                state.overlay.hide()
            state.icon.icon = ICON_IDLE
            return
        # ההקלטה הסתיימה: עוברים את הפיל למצב ספינר (לא מסתירים עדיין)
        if state.overlay is not None:
            state.overlay.show_processing()
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
    # חסימה אם אנחנו עדיין מעבדים תמלול קודם (כולל retries)
    if state.is_processing:
        print("Ignoring hotkey: still processing previous recording.")
        return
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
def current_model_text(_item):
    if state.current_model is None:
        # לא הריצו עדיין - מציגים את המודל הראשון בשרשרת
        models = SETTINGS.get("models") or DEFAULT_MODELS
        first = models[0] if models else "?"
        return f"Active model: {first} (default)"
    return f"Active model: {state.current_model}"


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


def _confirm_dialog(title, message):
    """דיאלוג Yes/No מודאלי של Windows. מחזיר True אם המשתמש לחץ Yes.

    חשוב: המסך הזה חייב לרוץ ב-thread חדש משלו ולא ב-thread של ה-tray icon.
    pystray מנהל message pump משלו על אותו thread, ו-MessageBox מנהל message
    pump משלו - שני pumps על אותו thread → קפיאה (הכפתורים, ה-X, הכל לא
    מגיב). אז כאן יוצרים thread חדש, מריצים שם את הדיאלוג עם message pump
    שלו, וממתינים לתוצאה בעזרת Event.
    """
    MB_YESNO = 0x4
    MB_ICONWARNING = 0x30
    MB_SETFOREGROUND = 0x10000
    MB_TOPMOST = 0x40000
    IDYES = 6
    flags = MB_YESNO | MB_ICONWARNING | MB_SETFOREGROUND | MB_TOPMOST

    result = {"value": False}
    done = threading.Event()

    def show():
        try:
            r = ctypes.windll.user32.MessageBoxW(0, message, title, flags)
            result["value"] = (r == IDYES)
        except Exception as e:
            print(f"WARNING: could not show confirmation dialog: {e}")
        finally:
            done.set()

    threading.Thread(target=show, daemon=True).start()
    done.wait()
    return result["value"]


def on_clear_data(icon, _item):
    """מוחק את history.txt, app.log, וכל הקלטה ב-failed_recordings/."""
    if not _confirm_dialog(
        "Tamlel — Clear data",
        "Delete history, log, and all saved failed recordings?\n\n"
        "This cannot be undone."
    ):
        print("Clear data: cancelled by user.")
        return

    cleared = []

    # history.txt
    try:
        if os.path.isfile(HISTORY_FILE):
            os.remove(HISTORY_FILE)
            cleared.append("history.txt")
    except OSError as e:
        print(f"WARNING: could not delete {HISTORY_FILE}: {e}")

    # failed_recordings/ - מוחקים את כל הקבצים בתיקייה (משאירים את התיקייה)
    try:
        if os.path.isdir(FAILED_RECORDINGS_DIR):
            count = 0
            for name in os.listdir(FAILED_RECORDINGS_DIR):
                path = os.path.join(FAILED_RECORDINGS_DIR, name)
                try:
                    if os.path.isfile(path):
                        os.remove(path)
                        count += 1
                except OSError as e:
                    print(f"WARNING: could not remove {path}: {e}")
            if count:
                cleared.append(f"{count} failed recording{'s' if count != 1 else ''}")
    except OSError as e:
        print(f"WARNING: could not list {FAILED_RECORDINGS_DIR}: {e}")

    # app.log - חיתוך דרך ה-handle הפתוח (אם נמחק קובץ פתוח, Python יכתוב לקובץ
    # מחוק ולא נוכל לראות לוג חדש). seek+truncate שומר את ה-handle תקין.
    try:
        _log_fp.seek(0)
        _log_fp.truncate()
        cleared.append("app.log")
    except OSError as e:
        print(f"WARNING: could not truncate app.log: {e}")

    summary = ", ".join(cleared) if cleared else "nothing (already empty)"
    print(f"Cleared: {summary}")
    _notify("Tamlel", f"Cleared: {summary}")
    try:
        icon.update_menu()
    except Exception:
        pass


# Cache קצר של תוצאת read_last_transcription. pystray קורא לתוויות (callable
# label, callable enabled) בכל פתיחת תפריט - בלי cache היו 2+ קריאות מהדיסק.
_LAST_TXN_CACHE_TTL_SEC = 0.5
_last_txn_cache = {"text": None, "expires_at": 0.0}


def _cached_last_transcription():
    now = time.monotonic()
    if now < _last_txn_cache["expires_at"]:
        return _last_txn_cache["text"]
    text = read_last_transcription()
    _last_txn_cache["text"] = text
    _last_txn_cache["expires_at"] = now + _LAST_TXN_CACHE_TTL_SEC
    return text


def on_copy_last(icon, _item):
    """מעתיק את התמלול האחרון מ-history.txt לקליפבורד. עובד גם בין סשנים -
    אם סגרת והפעלת את האפליקציה מחדש, התמלול האחרון נטען מהקובץ."""
    text = _cached_last_transcription()
    if not text:
        _notify("Tamlel", "No transcription in history yet")
        return
    try:
        pyperclip.copy(text)
        preview = text[:40].replace("\n", " ")
        if len(text) > 40:
            preview += "..."
        _notify("Tamlel", f"Copied: {preview}")
    except Exception as e:
        print(f"WARNING: could not copy last transcription: {e}")
        _notify("Tamlel", f"Copy failed: {e}")


def copy_last_text(_item):
    """תווית התפריט - מציגה תצוגה מקדימה קצרה מ-history.txt."""
    text = _cached_last_transcription()
    if not text:
        return "Copy last transcription (none yet)"
    snippet = text[:30].replace("\n", " ")
    if len(text) > 30:
        snippet += "..."
    return f'Copy last: "{snippet}"'


def copy_last_enabled(_item):
    return _cached_last_transcription() is not None


def on_quit(icon, _item):
    print("Quitting...")
    icon.stop()
    # סוגרים גם את ה-tkinter mainloop כדי שהתוכנית באמת תיסגר
    if state.overlay is not None:
        state.overlay.quit()


def build_menu():
    return Menu(
        MenuItem(current_model_text, lambda *_: None, enabled=False),
        MenuItem(hotkey_text, lambda *_: None, enabled=False),
        Menu.SEPARATOR,
        MenuItem(copy_last_text, on_copy_last, enabled=copy_last_enabled),
        MenuItem(mode_text, toggle_mode),
        Menu.SEPARATOR,
        MenuItem("Clear history and log", on_clear_data),
        MenuItem("Quit", on_quit),
    )


def _cleanup_old_failed_recordings():
    """מוחק קבצים בתיקיית failed_recordings/ ישנים מ-FAILED_RECORDINGS_KEEP_DAYS
    ימים. רץ פעם אחת בעלייה של האפליקציה - הצטברות של חודשים של הקלטות
    נכשלות עלולה לתפוס דיסק (כל אחת ~0.5 MB)."""
    if not os.path.isdir(FAILED_RECORDINGS_DIR):
        return
    cutoff = time.time() - FAILED_RECORDINGS_KEEP_DAYS * 24 * 3600
    deleted = 0
    for name in os.listdir(FAILED_RECORDINGS_DIR):
        path = os.path.join(FAILED_RECORDINGS_DIR, name)
        try:
            if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                os.remove(path)
                deleted += 1
        except OSError as e:
            print(f"  Could not check/delete {path}: {e}")
    if deleted:
        print(f"Cleanup: removed {deleted} failed recording"
              f"{'s' if deleted != 1 else ''} older than "
              f"{FAILED_RECORDINGS_KEEP_DAYS} days.")


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
    _cleanup_old_failed_recordings()
    register_hotkeys()
    print(f"Tamlel running. Hotkey: {SETTINGS['hotkey']}, mode: {SETTINGS['mode']}")
    print("Right-click the tray icon for menu (current model, mode toggle, quit).")

    # יוצרים את ה-overlay על main thread (tkinter דורש זאת)
    state.overlay = RecordingOverlay()

    # יוצרים את אייקון ה-tray ומריצים אותו ב-thread נפרד
    icon = Icon("Tamlel", ICON_IDLE, "Tamlel - ready", menu=build_menu())
    state.icon = icon
    icon.run_detached()

    # ה-mainloop של tkinter חוסם את ה-thread הראשי עד היציאה
    state.overlay.run_mainloop()


if __name__ == "__main__":
    main()
