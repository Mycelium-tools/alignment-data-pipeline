@echo off
REM Double-click this file to launch the Prompt Studio GUI (Windows).
REM It only needs Python 3 - no install step.
cd /d "%~dp0"
echo Starting Prompt Studio...
echo.
where py >nul 2>nul
if %errorlevel%==0 (
  py gui\app.py
  goto end
)
where python >nul 2>nul
if %errorlevel%==0 (
  python gui\app.py
  goto end
)
echo Python 3 doesn't seem to be installed. Two easy options:
echo.
echo   1) Ask Claude Code:   "launch the prompt GUI"
echo   2) Install Python 3 from https://www.python.org/downloads/
echo      then double-click this file again.
echo.
pause
:end
