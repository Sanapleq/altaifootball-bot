@echo off
cd /d "%~dp0"

title Altaifootball Bot DEBUG

echo =========================
echo Altaifootball Bot DEBUG
echo =========================
echo Project dir: %cd%
echo.

if not exist ".venv\Scripts\python.exe" (
    echo ERROR: virtual environment not found
    echo Expected file: .venv\Scripts\python.exe
    pause
    exit /b 1
)

echo Python:
".venv\Scripts\python.exe" --version
echo.
echo Starting bot...
echo =========================
echo.

".venv\Scripts\python.exe" -m app.main

echo.
echo =========================
echo Bot finished.
echo Exit code: %errorlevel%
pause