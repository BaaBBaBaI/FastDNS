param(
    [switch]$System,
    [switch]$Uninstall,
    [switch]$NoDesktopShortcut
)

$ErrorActionPreference = "Stop"

$AppName = "FastDNS"
$SourceDir = Split-Path -Parent $MyInvocation.MyCommand.Path

if ($System) {
    $InstallDir = Join-Path $env:ProgramFiles "FastDNS"
    $StartMenuDir = Join-Path $env:ProgramData "Microsoft\Windows\Start Menu\Programs\FastDNS"
    $DesktopDir = [Environment]::GetFolderPath("CommonDesktopDirectory")
    $RegUninstallPath = "HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\FastDNS"
} else {
    $InstallDir = Join-Path $env:LOCALAPPDATA "Programs\FastDNS"
    $StartMenuDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\FastDNS"
    $DesktopDir = [Environment]::GetFolderPath("Desktop")
    $RegUninstallPath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\FastDNS"
}

function Find-Python {
    foreach ($cmd in @("python", "py")) {
        $found = Get-Command $cmd -ErrorAction SilentlyContinue
        if (-not $found) { continue }
        # Skip Microsoft Store stub
        if ($found.Source -like "*\WindowsApps\*") { continue }
        try {
            if ($cmd -eq "py") {
                $exe = & py -3 -c "import sys; print(sys.executable)" 2>$null
            } else {
                $exe = & python -c "import sys; print(sys.executable)" 2>$null
            }
            if ($LASTEXITCODE -eq 0 -and $exe -and (Test-Path $exe.Trim())) {
                return $exe.Trim()
            }
        } catch {
            continue
        }
    }
    return $null
}

function New-Shortcut {
    param(
        [string]$ShortcutPath,
        [string]$TargetPath,
        [string]$Arguments,
        [string]$WorkingDirectory,
        [string]$Description
    )
    $WshShell = New-Object -ComObject WScript.Shell
    $Shortcut = $WshShell.CreateShortcut($ShortcutPath)
    $Shortcut.TargetPath = $TargetPath
    $Shortcut.Arguments = $Arguments
    $Shortcut.WorkingDirectory = $WorkingDirectory
    $Shortcut.Description = $Description
    $Shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,13"
    $Shortcut.Save()
}

if ($Uninstall) {
    Write-Host "Uninstalling $AppName..."
    if (Test-Path $InstallDir) {
        Remove-Item -Path $InstallDir -Recurse -Force
    }
    if (Test-Path $StartMenuDir) {
        Remove-Item -Path $StartMenuDir -Recurse -Force
    }
    $DesktopLink = Join-Path $DesktopDir "FastDNS.lnk"
    if (Test-Path $DesktopLink) {
        Remove-Item -Path $DesktopLink -Force
    }
    if (Test-Path $RegUninstallPath) {
        Remove-Item -Path $RegUninstallPath -Recurse -Force
    }
    Write-Host "$AppName has been uninstalled."
    exit 0
}

if ($System) {
    $currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    if (-not $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Write-Error "System-wide installation requires Administrator privileges. Run PowerShell as Administrator or omit -System."
        exit 1
    }
}

$PythonExe = Find-Python
if (-not $PythonExe) {
    Write-Host "Python 3 was not found."
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        $reply = Read-Host "Install Python 3.12 via winget now? [Y/n]"
        if ($reply -eq "" -or $reply -match "^[Yy]") {
            winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
            # Refresh PATH for current session
            $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User")
            $PythonExe = Find-Python
        }
    }
}

if (-not $PythonExe) {
    Write-Error "Python 3 is required. Download it from https://www.python.org/downloads/ (enable 'Add Python to PATH' and 'tcl/tk')."
    exit 1
}

$PythonDir = Split-Path -Parent $PythonExe
$PythonwExe = Join-Path $PythonDir "pythonw.exe"
if (-not (Test-Path $PythonwExe)) {
    $PythonwExe = $PythonExe
}

Write-Host "Using Python: $PythonExe"
Write-Host "Installing $AppName to $InstallDir..."

New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null

# Clean old code/profiles copy before copying fresh files
foreach ($sub in @("fastdns", "dns_profiles")) {
    $destSub = Join-Path $InstallDir $sub
    if (Test-Path $destSub) {
        Remove-Item -Path $destSub -Recurse -Force
    }
    Copy-Item -Path (Join-Path $SourceDir $sub) -Destination $destSub -Recurse -Force
}

Get-ChildItem -Path $InstallDir -Directory -Recurse -Filter "__pycache__" | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

Copy-Item -Path (Join-Path $SourceDir "main.py") -Destination (Join-Path $InstallDir "main.py") -Force
Copy-Item -Path (Join-Path $SourceDir "install_windows.ps1") -Destination (Join-Path $InstallDir "install_windows.ps1") -Force

# Create CLI wrapper
$CmdWrapper = @"
@echo off
"$PythonExe" "$InstallDir\main.py" %*
"@
Set-Content -Path (Join-Path $InstallDir "fastdns.cmd") -Value $CmdWrapper -Encoding ASCII

# Create Uninstall script
$UninstallBat = @"
@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_windows.ps1" -Uninstall
pause
"@
if ($System) {
    $UninstallBat = @"
@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_windows.ps1" -System -Uninstall
pause
"@
}
Set-Content -Path (Join-Path $InstallDir "uninstall.bat") -Value $UninstallBat -Encoding ASCII

# Create Start Menu shortcut
New-Item -ItemType Directory -Path $StartMenuDir -Force | Out-Null
New-Shortcut `
    -ShortcutPath (Join-Path $StartMenuDir "FastDNS.lnk") `
    -TargetPath $PythonwExe `
    -Arguments "`"$InstallDir\main.py`"" `
    -WorkingDirectory $InstallDir `
    -Description "FastDNS Conditional DNS Switcher"

New-Shortcut `
    -ShortcutPath (Join-Path $StartMenuDir "Uninstall FastDNS.lnk") `
    -TargetPath (Join-Path $InstallDir "uninstall.bat") `
    -Arguments "" `
    -WorkingDirectory $InstallDir `
    -Description "Uninstall FastDNS"

# Create Desktop shortcut
if (-not $NoDesktopShortcut) {
    New-Shortcut `
        -ShortcutPath (Join-Path $DesktopDir "FastDNS.lnk") `
        -TargetPath $PythonwExe `
        -Arguments "`"$InstallDir\main.py`"" `
        -WorkingDirectory $InstallDir `
        -Description "FastDNS Conditional DNS Switcher"
}

# Register in Windows Installed Apps (Add/Remove Programs)
New-Item -Path $RegUninstallPath -Force | Out-Null
Set-ItemProperty -Path $RegUninstallPath -Name "DisplayName" -Value "FastDNS"
Set-ItemProperty -Path $RegUninstallPath -Name "DisplayVersion" -Value "1.0.0"
Set-ItemProperty -Path $RegUninstallPath -Name "Publisher" -Value "FastDNS"
Set-ItemProperty -Path $RegUninstallPath -Name "InstallLocation" -Value $InstallDir
Set-ItemProperty -Path $RegUninstallPath -Name "UninstallString" -Value "`"$InstallDir\uninstall.bat`""
Set-ItemProperty -Path $RegUninstallPath -Name "NoModify" -Value 1 -Type DWord
Set-ItemProperty -Path $RegUninstallPath -Name "NoRepair" -Value 1 -Type DWord

Write-Host ""
Write-Host "FastDNS installed successfully."
Write-Host "  Install directory : $InstallDir"
Write-Host "  Start Menu        : $StartMenuDir\FastDNS.lnk"
if (-not $NoDesktopShortcut) {
    Write-Host "  Desktop shortcut  : $DesktopDir\FastDNS.lnk"
}
Write-Host "  CLI command       : $InstallDir\fastdns.cmd"
