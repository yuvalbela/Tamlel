# Tamlel — כלי תמלול ושכתוב בעברית

<p align="center">
  <img src="media/demo.gif" alt="Tamlel overlay animation" width="320">
</p>

כלי לתמלול דיבור בעברית ועיבוד המלל עלל ידי AI: לוחצים על קיצור מקלדת גלובלי, מדברים,
משחררים — והטקסט מודבק אוטומטית במקום שבו הסמן נמצא. הטקסט מנוקה ממילות מילוי
("אהה", "כאילו"), מקבל פיסוק נכון, ונשמר ביומן.

> **In English (brief):** Hebrew speech-to-text desktop tool. Press a global
> hotkey, speak, release, and the cleaned-up text is auto-pasted wherever your
> cursor is. Uses Gemini for both transcription and cleanup in a single call.

## למה זה קיים

נבדק והוחלט אחרי בדיקות נרחבות שמודלים מקומיים (Whisper + DictaLM) על חומרה
ישנה (i5 ללא GPU) הם איטיים מדי או לא אמינים. Gemini 2.5 Flash מסוגל לקבל קובץ
אודיו ולהחזיר תמלול נקי ומדויק בקריאה אחת — בערך 17 שניות לדקת אודיו, כולל
העלאה.

**מגבלות free tier (2026)**: המכסות החינמיות של Gemini מוגבלות מאוד —
רוב מודלי "flash" האיכותיים מאפשרים רק 20 בקשות ליום (RPD=20) כל אחד.
הדרך לעקוף את זה היא **fallback chain של 5 מודלים** — כל אחד עם מונה quota
נפרד — שמגיעה ל-~580 בקשות יומיות בסה"כ.

## דרישות

- Windows
- Python 3.10+
- מיקרופון
- מפתח Gemini API חינמי

## התקנה

```bash
# 1. שכפול הריפו
git clone https://github.com/<your-username>/Tamlel.git
cd Tamlel

# 2. התקנת הספריות
pip install -r requirements.txt

# 3. יצירת קובץ ההגדרות עם מפתח ה-API
# העתק את config.example.py ל-config.py
copy config.example.py config.py
# פתח את config.py וערוך:
# GEMINI_API_KEY = "המפתח-שלך-כאן"
```

**להשגת מפתח חינמי**: https://aistudio.google.com/apikey

## שימוש

### מצב CLI (פשוט)

```bash
python transcribe.py
```

לחץ Enter להתחלת הקלטה, Enter שוב לעצירה. הטקסט יישמר ב-`output.txt`,
ייווסף ל-`history.txt`, ויועתק ל-clipboard.

או — אם יש לך קובץ אודיו מוכן:

```bash
python transcribe.py recording.m4a
```

### מצב Tray (מומלץ)

```bash
python tray_app.py
```

או לחיצה כפולה על `Tamlel.bat` (פותח את התוכנה בלי חלון CMD).

לאחר ההפעלה:
- האייקון "t" מופיע ליד השעון
- לוחצים `Ctrl+Shift+Space` להפעלה
- לחיצה ימנית על האייקון — תפריט עם:
  - שימוש יומי (מתעדכן בכל פתיחה)
  - הקיצור הנוכחי
  - מעבר בין מצב Toggle ל-Hold
  - יציאה

**שני מצבי הפעלה**:
- **Toggle** (ברירת מחדל): לחיצה ראשונה מתחילה הקלטה, שנייה עוצרת.
- **Hold**: להחזיק את הקיצור = להקליט. ברגע ששוחררים = עיבוד והדבקה.

המצב מתחלף דרך התפריט (right-click → "Mode: ... (click to switch)").

### הרשאות מנהל

ספריית `keyboard` דורשת לפעמים הרשאות אדמין כדי לתפוס קיצור מקלדת גלובלי. אם
הקיצור לא תופס: סגור את התוכנה, פתח CMD/PowerShell **כ-Run as administrator**,
והרץ שוב.

לקיצור אוטומטי כאדמין על שולחן העבודה: לחץ ימני על Tamlel.bat → Properties →
Advanced → Run as administrator.

## הגדרות

`settings.json` נוצר אוטומטית בריצה הראשונה ומכיל:

```json
{
  "hotkey": "ctrl+shift+space",
  "mode": "toggle"
}
```

- `hotkey` — אפשר לערוך ידנית (לדוגמה: `"alt+r"`, `"f9"`, `"ctrl+alt+t"`). הפעל
  מחדש את התוכנה אחרי שינוי.
- `mode` — ניתן לשנות גם דרך תפריט ה-tray.
- `models` — שרשרת fallback של מודלי Gemini. ברירת מחדל:
  ```json
  ["gemini-3.5-flash", "gemini-3-flash-preview", "gemini-2.5-flash",
   "gemini-2.0-flash", "gemini-3.1-flash-lite"]
  ```
  הסדר: מהחדש (סטטיסטית - איכותי יותר) ליציב המוכר, ואז ל-lite לכמויות.
  ארבעת ה-flash הראשונים: 20 RPD כל אחד (כל אחד עם מונה quota נפרד) =
  80 בקשות איכותיות ביום. כש**כולם** נגמרים → fallback ל-
  `gemini-3.1-flash-lite` שיש לו 500 RPD (איכות סבירה, workhorse לכמויות).
  סה"כ ~580 בקשות ביום.

  `gemini-3-flash-preview` הוא גרסת preview של דור 3 — שווה ניסיון לאיכות
  עדיפה, אבל preview עלול להשתנות או להיעלם. אם זה קורה, ה-chain פשוט
  מדלג עליו ל-2.5.

  שגיאה זמנית של מודל (כמו 503 UNAVAILABLE) — קופצים מיד לבא בתור, בלי
  לבזבז retries (זה גם חוסך RPM). שם מודל לא קיים (404) — אותו דבר,
  fallback מיידי. רק המודל האחרון בשרשרת מקבל retry עם backoff
  (כי אין למי ליפול עליו).

## אייקונים בהתאמה אישית

האפליקציה משתמשת באייקון "t" המצויר. אם תרצה אייקונים משלך, שמור בתיקיית
`icons/` קבצים בגודל 64×64 פיקסלים, רקע שקוף:

- `icons/icon_idle.png` — מצב המתנה (ירוק כברירת מחדל)
- `icons/icon_recording.png` — מקליט (אדום)
- `icons/icon_processing.png` — מעבד (צהוב)
- `icons/icon_error.png` — שגיאה (כתום)

לקיצור על שולחן העבודה, צור קובץ ICO מולטי-רזולוציה משלך (למשל באתר
[icoconvert.com](https://icoconvert.com)) ושמור אותו כ-`icons/icon.ico`.
לחבר את הקיצור: לחץ ימני על קיצור Tamlel בשולחן העבודה → Properties →
Change Icon → Browse לקובץ `icons/icon.ico`.

## מבנה הקבצים

```
transcribe.py            ליבת התמלול + מצב CLI
tray_app.py              אפליקציית tray + hotkey גלובלי
overlay.py               חלון ה-pill הצף עם ויזואליזציית קול
Tamlel.bat               משגר ללא חלון CMD
config.example.py        תבנית למפתח API
requirements.txt         ספריות Python נדרשות
icons/                   אייקונים לאפליקציה (PNG ל-tray, ICO לקיצור)
settings.json            הגדרות משתמש (נוצר אוטומטית, לא ב-git)
config.py                המפתח שלך (לא ב-git!)
history.txt              יומן תמלולים (לא ב-git)
output.txt               התמלול האחרון (לא ב-git)
app.log                  לוג ריצה (לא ב-git)
failed_recordings/       WAV של הקלטות שנכשלו (לא ב-git)
```

## פרטיות

האודיו נשלח לשרתי Google. בשכבה החינמית, Google עשויה להשתמש בקלט/פלט לאימון
מודלים. ראה את [תנאי השימוש של Gemini](https://ai.google.dev/gemini-api/terms).
אל תשתמש בכלי לתוכן רגיש שאינך רוצה שיהיה זמין ל-Google.

## רישיון

MIT
