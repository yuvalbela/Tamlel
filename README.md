# Tamlel — כלי תמלול ושכתוב בעברית

כלי לתמלול דיבור בעברית: לוחצים על קיצור מקלדת גלובלי, מדברים,
משחררים — והטקסט מודבק אוטומטית במקום שבו הסמן נמצא. הטקסט מנוקה ממילות מילוי
("אהה", "כאילו"), מקבל פיסוק נכון, ונשמר ביומן.

> **In English (brief):** Hebrew speech-to-text desktop tool. Press a global
> hotkey, speak, release, and the cleaned-up text is auto-pasted wherever your
> cursor is. Uses Gemini for both transcription and cleanup in a single call.

## למה זה קיים

נבדק והוחלט אחרי בדיקות נרחבות שמודלים מקומיים (Whisper + DictaLM) על חומרה
ישנה (i5 ללא GPU) הם איטיים מדי או לא אמינים. Gemini 2.5 Flash מסוגל לקבל קובץ
אודיו ולהחזיר תמלול נקי ומדויק בקריאה אחת — בערך 17 שניות לדקת אודיו, כולל
העלאה. השכבה החינמית של Gemini מספיקה לשימוש אישי (~250 בקשות ביום).

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

## אייקונים בהתאמה אישית

האפליקציה משתמשת באייקון "t" המצויר. אם תרצה אייקונים משלך, שמור בתיקיית
הפרויקט שלושה קבצים בגודל 64×64 פיקסלים, רקע שקוף:

- `icon_idle.png` — מצב המתנה (ירוק כברירת מחדל)
- `icon_recording.png` — מקליט (אדום)
- `icon_processing.png` — מעבד (צהוב)

לקיצור על שולחן העבודה, ייצר קובץ `.ico` מולטי-רזולוציה:

```bash
python make_app_icon.py
```

ייצור `tamlel.ico` עם 6 רזולוציות. לחבר את הקיצור: לחץ ימני על קיצור Tamlel
בשולחן העבודה → Properties → Change Icon → Browse לקובץ.

## מבנה הקבצים

```
transcribe.py        ליבת התמלול + מצב CLI
tray_app.py          אפליקציית tray + hotkey גלובלי
make_app_icon.py     סקריפט לייצור tamlel.ico
Tamlel.bat           משגר ללא חלון CMD
config.example.py    תבנית למפתח API
requirements.txt     ספריות Python נדרשות
settings.json        הגדרות משתמש (נוצר אוטומטית, לא ב-git)
config.py            המפתח שלך (לא ב-git!)
history.txt          יומן תמלולים (לא ב-git)
output.txt           התמלול האחרון (לא ב-git)
```

## פרטיות

האודיו נשלח לשרתי Google. בשכבה החינמית, Google עשויה להשתמש בקלט/פלט לאימון
מודלים. ראה את [תנאי השימוש של Gemini](https://ai.google.dev/gemini-api/terms).
אל תשתמש בכלי לתוכן רגיש שאינך רוצה שיהיה זמין ל-Google.

## רישיון

MIT
