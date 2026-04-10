@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo ERROR: virtual environment not found
    echo Expected file: .venv\Scripts\python.exe
    pause
    exit /b 1
)

title Altaifootball Bot
".venv\Scripts\python.exe" -m app.main

if errorlevel 1 (
    echo.
    echo Bot stopped with error.
    pause
)