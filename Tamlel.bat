@echo off
REM מפעיל את Tamlel בלי חלון CMD מציק.
REM אם קיצור המקלדת הגלובלי לא תופס - לחץ ימני על הקובץ -> Run as administrator.
cd /d "%~dp0"
start "" pythonw tray_app.py
