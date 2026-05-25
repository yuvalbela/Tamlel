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

MODEL = "gemini-2.5-flash"
OUTPUT_FILE = "output.txt"
HISTORY_FILE = "history.txt"
DAILY_LIMIT = 250  # מכסה משוערת של Gemini 2.5 Flash בשכבה החינמית
SAMPLE_RATE = 16000  # 16kHz - מספיק לדיבור, קובץ קטן

PROMPT = """תמלל את קובץ האודיו המצורף לעברית. האודיו הוא דיבור חופשי בעברית.

לאחר התמלול, נקה את הטקסט:
- הסר מילות מילוי וגמגום: "אהה", "אמ", "כאילו", "יעני", "אתה יודע", חזרות מיותרות ותחילות משפט שננטשו.
- תקן שגיאות והוסף פיסוק נכון.
- חלק לפסקאות אם צריך.

חשוב: שמור בדיוק על המשמעות והתוכן של הדובר. אל תוסיף מידע, רעיונות או דעות שלא נאמרו, ואל תהפוך משמעות של אף משפט. תקן ניסוח - אל תמציא תוכן.

החזר רק את הטקסט הסופי הנקי, בלי הקדמות והערות."""

MIME_TYPES = {
    ".mp3": "audio/mp3",
    ".wav": "audio/wav",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".ogg": "audio/ogg",
    ".flac": "audio/flac",
    ".aiff": "audio/aiff",
}


def record_until_event(stop_event, on_status=print):
    """
    הליבה של ההקלטה: מקליט עד ש-stop_event.set() נקרא.
    משמש גם ל-CLI (כש-Enter קובע) וגם ל-tray (כש-hotkey קובע).

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


def transcribe_audio(audio_path):
    """
    שולח קובץ אודיו ל-Gemini ומחזיר את הטקסט המתומלל.
    """
    ext = os.path.splitext(audio_path)[1].lower()
    mime_type = MIME_TYPES.get(ext)
    if mime_type is None:
        print(f"ERROR: unsupported audio format: {ext}")
        print(f"Supported: {', '.join(MIME_TYPES.keys())}")
        sys.exit(1)

    file_size_mb = os.path.getsize(audio_path) / (1024 * 1024)
    print(f"Audio file: {audio_path} ({file_size_mb:.1f} MB)")

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        print("ERROR: google-genai library not installed.")
        print("Run: pip install google-genai")
        sys.exit(1)

    client = genai.Client(api_key=GEMINI_API_KEY)

    print("Sending to Gemini...")
    start = time.time()

    try:
        with open(audio_path, "rb") as f:
            audio_bytes = f.read()

        response = client.models.generate_content(
            model=MODEL,
            contents=[
                PROMPT,
                types.Part.from_bytes(data=audio_bytes, mime_type=mime_type),
            ],
            config=types.GenerateContentConfig(temperature=0.2),
        )
        result_text = response.text

    except Exception as e:
        print(f"ERROR: request to Gemini failed:")
        print(f"  {e}")
        sys.exit(1)

    elapsed = time.time() - start
    print(f"Gemini responded in {elapsed:.1f} seconds.")

    if not result_text or not result_text.strip():
        print("ERROR: Gemini returned an empty response.")
        # מידע דיאגנוסטי כדי להבין למה
        try:
            if response.candidates:
                cand = response.candidates[0]
                print(f"  finish_reason: {cand.finish_reason}")
                if cand.safety_ratings:
                    print(f"  safety_ratings: {cand.safety_ratings}")
            if response.prompt_feedback:
                print(f"  prompt_feedback: {response.prompt_feedback}")
        except Exception as diag_err:
            print(f"  (could not read diagnostics: {diag_err})")
        sys.exit(1)

    return result_text.strip()


def save_output(text):
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
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sep_thick = "=" * 64
    sep_thin = "-" * 64
    # סופרים כמה בקשות היו היום *לפני* הוספת הרשומה הנוכחית, ואז +1
    used_today = count_today_usage() + 1
    usage_line = f"Request {used_today} / {DAILY_LIMIT} today"
    entry = f"{sep_thick}\n{timestamp}  |  {usage_line}\n{sep_thin}\n{text}\n"
    try:
        with open(HISTORY_FILE, "a", encoding="utf-8") as f:
            f.write(entry)
        print(f"Appended to: {HISTORY_FILE}")
    except OSError as e:
        print(f"WARNING: could not write history: {e}")


def copy_to_clipboard(text):
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
        text = transcribe_audio(audio_path)
        save_output(text)
        append_to_history(text)
        copy_to_clipboard(text)

        used = count_today_usage()
        print(f"Daily usage: {used} / {DAILY_LIMIT} requests today.")

    finally:
        if cleanup_path and os.path.exists(cleanup_path):
            try:
                os.remove(cleanup_path)
            except OSError:
                pass


if __name__ == "__main__":
    main()
