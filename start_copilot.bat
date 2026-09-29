@echo off
rem Launcher for the application copilot desktop app.
rem ASCII-only to avoid codepage issues in cmd.exe.

rem Graphics fallback: if pages render but will not respond to clicks,
rem it is almost always GPU compositing failing on this machine.
rem Keep this line ON to force software rendering.
rem If everything works fine, you may REM this line to try hardware acceleration.
set QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu --disable-software-rasterizer
rem If still broken, uncomment the next line to force ANGLE->SwiftShader (software GL)
rem 2026-09-13: GPU mode crashed (segfault in gpu_channel_manager) on this machine,
rem so software GL is now the default. Remove these two lines to try hardware acceleration.
set QT_OPENGL=angle
set QT_ANGLE_PLATFORM=swiftshader

cd /d "%~dp0"

set PYEXE=C:\Users\you\.workbuddy\binaries\python\envs\default\Scripts\python.exe

if not exist "%PYEXE%" (
  echo [ERROR] Python not found at:
  echo   %PYEXE%
  echo.
  pause
  exit /b 1
)

if not exist "app_desktop_qt.py" (
  echo [ERROR] app_desktop_qt.py not found in:
  echo   %CD%
  echo.
  pause
  exit /b 1
)

echo Starting copilot desktop app (Qt embedded browser)...
echo Keep this window open. Closing it will close the app.
echo.

"%PYEXE%" app_desktop_qt.py

if errorlevel 1 (
  echo.
  echo [ERROR] App exited with code %errorlevel%. See message above.
  pause
)
