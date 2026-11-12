@echo off
setlocal
cd /d "%~dp0"

where python >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo Error: Python 3 is not installed or not in PATH.
    pause
    exit /b 1
)

python -m PyInstaller --version >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo Installing PyInstaller...
    python -m pip install --upgrade pyinstaller
    if %ERRORLEVEL% NEQ 0 (
        echo Failed to install PyInstaller.
        pause
        exit /b 1
    )
)

echo Building FastDNS standalone executable...
python -m PyInstaller --noconfirm --clean fastdns.spec
if %ERRORLEVEL% NEQ 0 (
    echo PyInstaller build failed.
    pause
    exit /b 1
)

echo.
echo Built standalone app: dist\FastDNS\FastDNS.exe

where iscc >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    echo Building Inno Setup installer...
    iscc installer_windows.iss
    if %ERRORLEVEL% EQU 0 (
        echo Built installer: dist\FastDNS-Setup.exe
    )
) else (
    if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" (
        echo Building Inno Setup installer...
        "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" installer_windows.iss
        if %ERRORLEVEL% EQU 0 (
            echo Built installer: dist\FastDNS-Setup.exe
        )
    ) else (
        echo Inno Setup (ISCC.exe) not found; skipping FastDNS-Setup.exe.
        echo You can still use install_windows.bat directly without building an EXE.
    )
)

echo.
echo Done.
pause
