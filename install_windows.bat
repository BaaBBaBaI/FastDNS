@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_windows.ps1" %*
set "ERR=%ERRORLEVEL%"
echo.
if %ERR% NEQ 0 (
    echo Installation failed with exit code %ERR%.
)
pause
exit /b %ERR%
