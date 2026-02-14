@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo Creating virtual environment...
python -m venv .venv
if errorlevel 1 (
    echo Failed to create venv
    pause
    exit /b 1
)

echo Activating venv and installing dependencies...
call .venv\Scripts\activate.bat
pip install -r requirements.txt
if errorlevel 1 (
    echo Failed to install dependencies
    pause
    exit /b 1
)

echo Initializing Git...
git init
git add .
git commit -m "Initial commit: bot structure and core modules"

echo.
echo Setup complete!
echo.
echo Next steps:
echo 1. Create .env from .env.example and add your keys
echo 2. Create repo on GitHub: https://github.com/new?name=vedic-astrologer-bot
echo 3. git remote add origin https://github.com/YOUR_USERNAME/vedic-astrologer-bot.git
echo 4. git branch -M main
echo 5. git push -u origin main
echo.
echo To run bot: .venv\Scripts\activate && python main.py
pause
