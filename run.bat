@echo off
setlocal
cd /d "%~dp0server"
if not exist ".venv\Scripts\python.exe" (
  echo Backend is not set up yet. First run:  python build.py
  exit /b 1
)
echo Serving on http://127.0.0.1:8000  (Ctrl+C to stop)
".venv\Scripts\python.exe" -m uvicorn app:app --host 127.0.0.1 --port 8000
