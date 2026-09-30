@echo off
setlocal
rem One-click local backend launcher. It creates only this project's .venv.
cd /d "%~dp0"

set "PYEXE=.venv\Scripts\python.exe"
if not exist "%PYEXE%" (
  echo Creating local Python environment...
  py -3 -m venv .venv 2>nul
  if errorlevel 1 python -m venv .venv
)
if not exist "%PYEXE%" (
  echo [ERROR] Python 3 was not found. Install Python 3.11+ and run this file again.
  pause
  exit /b 1
)

"%PYEXE%" -c "import fastapi,uvicorn,multipart" >nul 2>nul
if errorlevel 1 (
  echo Installing declared backend dependencies...
  "%PYEXE%" -m pip install -r deploy\requirements.txt
  if errorlevel 1 (
    echo [ERROR] Dependency installation failed. Check your network, then run again.
    pause
    exit /b 1
  )
)

echo Starting Apply Copilot at http://127.0.0.1:8787 ...
echo Keep this window open while using the browser extension.
start "" http://127.0.0.1:8787/
"%PYEXE%" server.py --host 127.0.0.1 --port 8787

if errorlevel 1 (
  echo.
  echo [ERROR] Backend exited with code %errorlevel%. See the message above.
  pause
)
