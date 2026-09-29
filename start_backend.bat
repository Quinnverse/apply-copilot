@echo off
rem Backend-only launcher (userscript edition).
rem The PyQt desktop shell is retired; the dashboard now opens in your browser.
rem ASCII-only to avoid codepage issues in cmd.exe.

cd /d "%~dp0"

set PYEXE=C:\Users\you\.workbuddy\binaries\python\envs\default\Scripts\python.exe

if not exist "%PYEXE%" (
  echo [ERROR] Python not found at:
  echo   %PYEXE%
  echo.
  pause
  exit /b 1
)

echo Starting copilot backend on http://127.0.0.1:8787 ...
echo Keep this window open. Closing it stops the backend.
echo Dashboard: http://127.0.0.1:8787
echo.

"%PYEXE%" -m uvicorn server:app --host 127.0.0.1 --port 8787

if errorlevel 1 (
  echo.
  echo [ERROR] Backend exited with code %errorlevel%. See message above.
  pause
)
