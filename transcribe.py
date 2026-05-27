"""
כלי תמלול ושכתוב - גרסה 2

שימוש:
    python transcribe.py              -> מקליט מהמיקרופון (Enter להתחיל, Enter לעצור)
    python transcribe.py audio.mp3    -> משתמש בקובץ קיים
    python transcribe.py "C:\\path\\to\\recording.m4a"
"""

import sys
import os
import time
import tempfile
from datetime import datetime

# ---------- הגדרות ----------
try:
    from config import GEMINI_API_KEY
except ImportError:
    print("ERROR: config.py not found.")
    print("Create a file named config.py in this folder with one line:")
    print('GEMINI_API_KEY = "your-key-here"')
    sys.exit(1)

# רשימת ברירת מחדל ל-fallback chain.
# מגבלות free tier (2026): מודלי "flash" איכותיים מוגבלים ל-20 RPD כל אחד.
# הסדר: מהחדש ביותר (סטטיסטית - איכותי יותר) ליציב המוכר, ואז ל-lite לכמויות.
# סה"כ 60 בקשות איכותיות + 500 lite = 560 ביום.
DEFAULT_MODELS = [
    "gemini-3.5-flash",        # 20 RPD, הכי חדש ויציב
    "gemini-3-flash-preview",  # 20 RPD, preview של דור 3 (יבחן בשימוש)
    "gemini-2.5-flash",        # 20 RPD, יציב ומוכח
    "gemini-2.0-flash",        # 20 RPD, יציב, דור קודם
    "gemini-3.1-flash-lite",   # 500 RPD, workhorse לכמויות
]
# המודל הראשון בשרשרת - נקודת התחלה כברירת מחדל ל-transcribe_audio()
MODEL = DEFAULT_MODELS[0]

OUTPUT_FILE = "output.txt"
HISTORY_FILE = "history.txt"
SAMPLE_RATE = 16000  # 16kHz - מספיק לדיבור, קובץ קטן

PROMPT = """תמלל את קובץ האודיו המצורף לעברית. האודיו הוא דיבור חופשי בעברית.

לאחר התמלול, נקה את הטקסט:
- הסר מילות מילוי וגמגום: "אהה", "אמ", "כאילו", "יעני", "אתה יודע", חזרות מיותרות ותחילות משפט שננטשו.
- תקן שגיאות והוסף פיסוק נכון.
- חלק לפסקאות אם צריך.

חשוב: שמור בדיוק על המשמעות והתוכן של הדובר. אל תוסיף מידע, רעיונות או דעות שלא נאמרו, ואל תהפוך משמעות של אף משפט. תקן ניסוח - אל תמציא תוכן.

החזר רק את הטקסט הסופי הנקי, בלי הקדמות והערות.

חוקים נוקשים שאסור להפר:
- אם האודיו שקט, ריק, לא ברור, או קצר מדי לתמלול — החזר מחרוזת ריקה לחלוטין (בלי שום תו).
- לעולם אל תכתוב התנצלויות כמו "אני מצטער", "I'm sorry", "לא צורף קובץ", "no audio file", או כל הסבר על מגבלות.
- לעולם אל תכתוב תשובת מטא או הסבר על מה שעשית/לא עשית - רק התמלול הסופי או מחרוזת ריקה."""

MIME_TYPES = {
    ".mp3": "audio/mp3",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
    ".aiff": "audio/aiff",
}

# טקסטים אופייניים ל-hallucination של Gemini כשהוא מקבל אודיו קצר/שקט
# ומתפלא ועונה כאילו לא קיבל קובץ. אנחנו מזהים את אלה ומתייחסים אליהם כשגיאה.
HALLUCINATION_PATTERNS = [
    # עברית
    "אני מצטער",
    "לא צורף",
    "לא קיבלתי",
    "לא נשלח",
    "אין באפשרותי",
    "לא יכול לתמלל",
    "לא נמצא קובץ",
    "לא ניתן לעבד",
    # אנגלית
    "i'm sorry",
    "i am sorry",
    "no audio",
    "no file was",
    "no audio file",
    "didn't receive",
    "did not receive",
    "couldn't process",
    "could not process",
    "i cannot transcribe",
    "i can't transcribe",
]


def _looks_like_hallucination(text):
    """בודק אם תשובת המודל נראית כמו מטא-תגובה ולא כמו תמלול אמיתי."""
    if not text:
        return False
    head = text.lower().strip()[:200]
    return any(p in head for p in HALLUCINATION_PATTERNS)


def record_until_event(stop_event, on_status=print, on_chunk_rms=None):
    """
    הליבה של ההקלטה: מקליט עד ש-stop_event.set() נקרא.
    משמש גם ל-CLI (כש-Enter קובע) וגם ל-tray (כש-hotkey קובע).

    on_chunk_rms: callback אופציונלי שמקבל float עם ה-RMS של כל chunk אודיו
    תוך כדי הקלטה. שימושי לויזואליזציה בזמן אמת (overlay).

    מחזיר dict: {"path": <wav>, "duration": float, "rms": float} או None אם אין אודיו.
    """
    try:
        import sounddevice as sd
        import numpy as np
        from scipy.io.wavfile import write as wav_write
    except ImportError as e:
        on_status(f"ERROR: missing recording library: {e}")
        on_status("Run: pip install sounddevice scipy numpy")
        return None

    frames = []

    def callback(indata, frame_count, time_info, status):
        if status:
            on_status(f"  (audio status: {status})")
        frames.append(indata.copy())
        if on_chunk_rms is not None:
            try:
                chunk_rms = float(np.sqrt(np.mean(indata.astype(np.float32) ** 2)))
                on_chunk_rms(chunk_rms)
            except Exception:
                pass  # ויזואליזציה לא צריכה להפיל הקלטה

    start = time.time()
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16",
                        callback=callback):
        stop_event.wait()  # חוסם עד ש-set() נקרא

    duration = time.time() - start

    if not frames:
        return None

    audio = np.concatenate(frames, axis=0)
    rms = float(np.sqrt(np.mean(audio.astype(np.float32) ** 2)))

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    wav_write(tmp.name, SAMPLE_RATE, audio)
    return {"path": tmp.name, "duration": duration, "rms": rms}


def record_audio():
    """
    גרסת CLI: Enter להתחיל, Enter לעצור.
    """
    import threading

    print("Press Enter to START recording...")
    input()
    print("Recording... Press Enter to STOP.")

    stop_event = threading.Event()

    def wait_for_enter():
        input()
        stop_event.set()

    waiter = threading.Thread(target=wait_for_enter, daemon=True)
    waiter.start()

    result = record_until_event(stop_event)

    if result is None:
        print("ERROR: no audio captured.")
        sys.exit(1)

    print(f"Stopped. Recorded {result['duration']:.1f} seconds.")
    print(f"Audio level (RMS): {result['rms']:.0f}  (silent < ~50, normal speech ~500-3000)")
    if result["rms"] < 50:
        print("WARNING: audio seems very quiet or silent.")
        print("  Check that the right microphone is selected in Windows sound settings.")

    return result["path"]


# ---------- היררכיית שגיאות תמלול ----------
class TranscriptionError(Exception):
    """שגיאת בסיס לכל שגיאה בתהליך התמלול."""


class TranscriptionServerError(TranscriptionError):
    """5xx מהשרת - שווה לנסות שוב עם backoff (לא נספר בשימוש)."""


class TranscriptionRateLimitError(TranscriptionError):
    """429 rate-limit לדקה - להמתין ולנסות שוב."""


class TranscriptionQuotaError(TranscriptionError):
    """429 quota יומי - לעבור למודל הבא בשרשרת ה-fallback."""


class TranscriptionAuthError(TranscriptionError):
    """401/403 - מפתח שגוי או חסר הרשאות (לא retry)."""


class TranscriptionEmptyResponseError(TranscriptionError):
    """Gemini החזיר תשובה ריקה (אודיו שקט, נחסם, וכד')."""


class TranscriptionModelNotFoundError(TranscriptionError):
    """404 - שם המודל לא קיים/לא נתמך. fallback למודל הבא בשרשרת."""


class TranscriptionFatalError(TranscriptionError):
    """שגיאה אחרת שלא תיפתר מעצמה (לא retry)."""


def _classify_429(msg):
    """
    מבחין בין 429 יומי (quota - fallback למודל הבא) ל-429 לדקה (rate - retry).
    Gemini מחזיר את שני הסוגים עם 'Quota exceeded' בהודעה, אז צריך לבדוק את
    metric: per minute / per day.
    """
    if any(s in msg for s in ("per day", "perday", "daily", "rpd", "requests per day")):
        return "quota"
    if any(s in msg for s in ("per minute", "perminute", "rpm", "requests per minute")):
        return "rate"
    # ברירת מחדל כשלא ברור: rate (יותר בטוח - נעשה retry במקום fallback מיותר)
    return "rate"


def _classify_error(exc):
    """מסווג חריגה מ-genai לקטגוריית שגיאה. מחזיר אחת מ:
    'server', 'rate', 'quota', 'auth', 'not_found', 'unknown'."""
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    msg = str(exc).lower()

    # סיווג לפי קוד אם קיים
    if code in (500, 502, 503, 504):
        return "server"
    if code == 429:
        return _classify_429(msg)
    if code in (401, 403):
        return "auth"
    if code == 404:
        return "not_found"

    # סיווג לפי הודעת השגיאה
    if any(c in msg for c in ("503", "500", "502", "504", "unavailable", "internal server")):
        return "server"
    if "429" in msg or "resource_exhausted" in msg:
        return _classify_429(msg)
    if any(s in msg for s in ("401", "403", "unauthorized", "permission denied", "api_key")):
        return "auth"
    if "404" in msg or "not_found" in msg or "is not found" in msg:
        return "not_found"
    return "unknown"


def transcribe_audio(audio_path, model=MODEL):
    """
    שולח קובץ אודיו ל-Gemini ומחזיר את הטקסט המתומלל.
    מעלה אחת מ-TranscriptionError במקרה של כשל.
    """
    ext = os.path.splitext(audio_path)[1].lower()
    mime_type = MIME_TYPES.get(ext)
    if mime_type is None:
        raise TranscriptionFatalError(
            f"unsupported audio format: {ext}. "
            f"Supported: {', '.join(MIME_TYPES.keys())}"
        )

    file_size_mb = os.path.getsize(audio_path) / (1024 * 1024)
    print(f"Audio file: {audio_path} ({file_size_mb:.1f} MB), model: {model}")

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        raise TranscriptionFatalError(
            "google-genai library not installed. Run: pip install google-genai"
        )

    client = genai.Client(api_key=GEMINI_API_KEY)

    print(f"Sending to Gemini ({model})...")
    start = time.time()

    try:
        with open(audio_path, "rb") as f:
            audio_bytes = f.read()

        response = client.models.generate_content(
            model=model,
            contents=[
                PROMPT,
                types.Part.from_bytes(data=audio_bytes, mime_type=mime_type),
            ],
            config=types.GenerateContentConfig(temperature=0.2),
        )
        result_text = response.text

    except Exception as e:
        category = _classify_error(e)
        msg = f"{category}: {e}"
        if category == "server":
            raise TranscriptionServerError(msg) from e
        if category == "rate":
            raise TranscriptionRateLimitError(msg) from e
        if category == "quota":
            raise TranscriptionQuotaError(msg) from e
        if category == "auth":
            raise TranscriptionAuthError(msg) from e
        if category == "not_found":
            raise TranscriptionModelNotFoundError(msg) from e
        raise TranscriptionFatalError(msg) from e

    elapsed = time.time() - start
    print(f"Gemini responded in {elapsed:.1f} seconds.")

    if not result_text or not result_text.strip():
        # מידע דיאגנוסטי כדי להבין למה
        diag = []
        try:
            if response.candidates:
                cand = response.candidates[0]
                diag.append(f"finish_reason={cand.finish_reason}")
                if cand.safety_ratings:
                    diag.append(f"safety_ratings={cand.safety_ratings}")
            if response.prompt_feedback:
                diag.append(f"prompt_feedback={response.prompt_feedback}")
        except Exception:
            pass
        raise TranscriptionEmptyResponseError(
            "Gemini returned an empty response" + (f" ({', '.join(diag)})" if diag else "")
        )

    # זיהוי hallucination - מודל ענה במטא-תגובה במקום בתמלול
    if _looks_like_hallucination(result_text):
        snippet = result_text.strip().replace("\n", " ")[:120]
        raise TranscriptionEmptyResponseError(
            f"Model returned a meta-response instead of a transcription: {snippet}"
        )

    return result_text.strip()


def transcribe_with_fallback(audio_path, models=None,
                             max_retries_per_model=3,
                             on_retry=None):
    """
    מנסה לתמלל עם retry על שגיאות זמניות, ו-fallback למודל הבא אם quota נגמר.

    on_retry(event_type, model, attempt, exc, wait_sec) - callback לפידבק ויזואלי:
      event_type ∈ {"retrying", "fallback", "giving_up"}

    מחזיר dict: {"text": <str>, "model_used": <str>}.
    מעלה TranscriptionError אחרון אם כל הניסיונות נכשלו.
    """
    if models is None:
        models = list(DEFAULT_MODELS)

    last_error = None

    for model_index, model in enumerate(models):
        is_last_model = (model_index == len(models) - 1)

        for attempt in range(max_retries_per_model):
            try:
                text = transcribe_audio(audio_path, model=model)
                return {"text": text, "model_used": model}

            except TranscriptionServerError as e:
                last_error = e
                print(f"  Server error on {model}: {e}")
                if not is_last_model:
                    # יש מודל הבא בשרשרת - עוברים אליו מיד במקום לבזבז retries
                    # על flash שעמוס (זה גם הסיבה העיקרית שנחצה RPM).
                    next_model = models[model_index + 1]
                    print(f"  Skipping retries; falling back to: {next_model}")
                    if on_retry:
                        on_retry("fallback", next_model, attempt, e, 0)
                    break
                # מודל אחרון - retry כ-resort אחרון
                wait = 2 ** (attempt + 1)  # 2, 4, 8
                if attempt + 1 < max_retries_per_model:
                    print(f"  Last model in chain. Retrying in {wait}s... "
                          f"(attempt {attempt+2}/{max_retries_per_model})")
                    if on_retry:
                        on_retry("retrying", model, attempt, e, wait)
                    time.sleep(wait)
                    continue

            except TranscriptionRateLimitError as e:
                last_error = e
                wait = 30
                print(f"  Rate limited on {model}: {e}")
                if attempt + 1 < max_retries_per_model:
                    print(f"  Waiting {wait}s before retry...")
                    if on_retry:
                        on_retry("retrying", model, attempt, e, wait)
                    time.sleep(wait)
                    continue

            except TranscriptionQuotaError as e:
                last_error = e
                print(f"  Quota exhausted for {model}: {e}")
                if not is_last_model:
                    next_model = models[model_index + 1]
                    print(f"  Falling back to: {next_model}")
                    if on_retry:
                        on_retry("fallback", next_model, attempt, e, 0)
                break  # exit retry loop, go to next model

            except TranscriptionModelNotFoundError as e:
                # שם המודל לא קיים/לא נתמך - אין טעם ב-retry, עוברים מיד הלאה.
                # זה מגן מטעויות קלות בשם של מודל ב-settings.json.
                last_error = e
                print(f"  Model '{model}' not found/supported: {e}")
                if not is_last_model:
                    next_model = models[model_index + 1]
                    print(f"  Falling back to: {next_model}")
                    if on_retry:
                        on_retry("fallback", next_model, attempt, e, 0)
                break

            except TranscriptionEmptyResponseError as e:
                # תשובה ריקה או hallucination - לא להפעיל retry על אותו מודל,
                # אבל כדאי לנסות מודל הבא בשרשרת (אולי הוא יצליח)
                last_error = e
                print(f"  Empty/hallucinated response from {model}: {e}")
                if not is_last_model:
                    next_model = models[model_index + 1]
                    print(f"  Falling back to: {next_model}")
                    if on_retry:
                        on_retry("fallback", next_model, attempt, e, 0)
                break

            except TranscriptionError as e:
                # שגיאות שלא ניתן לפתור (auth, fatal) - מתפשטות מיד
                if on_retry:
                    on_retry("giving_up", model, attempt, e, 0)
                raise

    if on_retry:
        on_retry("giving_up", models[-1] if models else "?", 0, last_error, 0)
    raise last_error or TranscriptionFatalError("All transcription attempts failed")


def save_output(text):
    """שומר את התמלול האחרון לקובץ output.txt (UTF-8, דורס כל פעם)."""
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    print(f"Result saved to: {OUTPUT_FILE}")


def count_today_usage():
    """
    סופר כמה רשומות עם התאריך של היום קיימות ב-history.txt.
    מחזיר 0 אם הקובץ עוד לא קיים.
    """
    if not os.path.isfile(HISTORY_FILE):
        return 0
    today_prefix = datetime.now().strftime("%Y-%m-%d")
    count = 0
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith(today_prefix):
                    count += 1
    except OSError as e:
        print(f"WARNING: could not read history: {e}")
        return 0
    return count


def append_to_history(text):
    """מוסיף רשומה ל-history.txt עם חותמת זמן ומספר התמלולים המוצלחים היום."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sep_thick = "=" * 64
    sep_thin = "-" * 64
    # סופרים כמה תמלולים מוצלחים היו היום *לפני* הוספת הרשומה הנוכחית, ואז +1
    used_today = count_today_usage() + 1
    usage_line = f"Transcription #{used_today} today"
    entry = f"{sep_thick}\n{timestamp}  |  {usage_line}\n{sep_thin}\n{text}\n"
    try:
        with open(HISTORY_FILE, "a", encoding="utf-8") as f:
            f.write(entry)
        print(f"Appended to: {HISTORY_FILE}")
    except OSError as e:
        print(f"WARNING: could not write history: {e}")


def read_last_transcription():
    """קורא את הטקסט של התמלול האחרון מ-history.txt. מחזיר None אם אין היסטוריה.

    המבנה של כל רשומה:
        ==== thick separator (64 chars) ====
        2026-05-27 12:23:08  |  Transcription #N today
        ---- thin separator (64 chars) ----
        <text - יכול לתפוס מספר שורות>

    הרשומה האחרונה היא הבלוק האחרון אחרי ה-thick separator האחרון."""
    if not os.path.isfile(HISTORY_FILE):
        return None
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError as e:
        print(f"WARNING: could not read history: {e}")
        return None

    sep_thick = "=" * 64
    sep_thin = "-" * 64

    parts = content.split(sep_thick)
    # parts[0] - מה שלפני ה-separator הראשון (בד"כ ריק)
    # parts[-1] - הרשומה האחרונה (אחרי הקו העבה האחרון)
    if len(parts) < 2:
        return None
    last_block = parts[-1]
    # פיצול על הקו הדק כדי לדלג על שורת ה-timestamp
    if sep_thin in last_block:
        _header, _, body = last_block.partition(sep_thin)
        text = body.strip("\n")
    else:
        text = last_block.strip("\n")
    return text or None


def copy_to_clipboard(text):
    """מעתיק טקסט ל-clipboard (CLI בלבד; ה-tray מטפל בהדבקה עצמאית)."""
    try:
        import pyperclip
    except ImportError:
        print("WARNING: pyperclip not installed, skipping clipboard copy.")
        print("  Run: pip install pyperclip")
        return
    try:
        pyperclip.copy(text)
        print("Copied to clipboard. Paste anywhere with Ctrl+V.")
    except Exception as e:
        print(f"WARNING: could not copy to clipboard: {e}")


def main():
    cleanup_path = None

    if len(sys.argv) > 1:
        audio_path = sys.argv[1]
        if not os.path.isfile(audio_path):
            print(f"ERROR: audio file not found: {audio_path}")
            sys.exit(1)
    else:
        audio_path = record_audio()
        cleanup_path = audio_path

    try:
        try:
            result = transcribe_with_fallback(audio_path)
            text = result["text"]
            print(f"(used model: {result['model_used']})")
        except TranscriptionError as e:
            print(f"ERROR: {type(e).__name__}: {e}")
            sys.exit(1)

        save_output(text)
        append_to_history(text)
        copy_to_clipboard(text)

        used = count_today_usage()
        print(f"Transcriptions today: {used}")

    finally:
        if cleanup_path and os.path.exists(cleanup_path):
            try:
                os.remove(cleanup_path)
            except OSError:
                pass


if __name__ == "__main__":
    main()
