@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    py -3 "%~dp0GHXP.py"
    goto :finish
)
where python >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    python "%~dp0GHXP.py"
    goto :finish
)
echo.
echo Python 3.10 or later was not found on this PC.
echo Download Python from: https://www.python.org/downloads/windows/
echo During setup, select "Add python.exe to PATH".
echo Then double-click START_INSTALLER.bat again.
echo.
pause
exit /b 1
:finish
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo The installer could not start. Ensure Python 3.10+ and tkinter are installed.
    pause
)
endlocal