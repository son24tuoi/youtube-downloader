@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv (
  python -m venv .venv || (echo Can Python 3.10+ ^(https://www.python.org^) & pause & exit /b 1)
  .venv\Scripts\python -m pip install -r requirements.txt
)
start "" .venv\Scripts\pythonw.exe src\app.py
