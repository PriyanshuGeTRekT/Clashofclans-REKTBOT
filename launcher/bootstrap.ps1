# Clash Rekt Bot launcher for Windows.
#
# First run: downloads uv (Astral's portable Python manager), Python 3.12 and the libraries in
# requirements.txt into .crb\ next to this app, plus Google's adb if the app has none. Nothing is
# installed system-wide and no admin rights are needed. Later runs start the app right away; the
# setup re-runs by itself when requirements.txt changes or the folder was moved.
#
#   Start Clash Rekt Bot.bat [-AutoStart] [-Classic] [-Repair]
param([switch]$AutoStart, [switch]$Classic, [switch]$Repair, [switch]$NoLaunch, [switch]$NoShortcut)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'          # Invoke-WebRequest is ~10x faster without the bar
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Root  = Split-Path -Parent $PSScriptRoot
$Crb   = Join-Path $Root '.crb'
$Venv  = Join-Path $Crb 'venv'
$Py    = Join-Path $Venv 'Scripts\python.exe'
$PyW   = Join-Path $Venv 'Scripts\pythonw.exe'
$Req   = Join-Path $Root 'requirements.txt'
$Stamp = Join-Path $Crb 'setup.stamp'
$Tools = Join-Path $Root 'runtime\Tools'

function Say($msg, $color = 'Gray') { Write-Host "  $msg" -ForegroundColor $color }

try {
    Write-Host ''
    Write-Host '  CLASH ' -ForegroundColor White -NoNewline
    Write-Host 'REKT ' -ForegroundColor Red -NoNewline
    Write-Host 'BOT' -ForegroundColor Yellow
    Write-Host ''

    # ------------------------------------------------------------------ Python + libraries
    # A developer checkout with its own working .venv uses that instead of downloading another one.
    $devPyW = Join-Path $Root '.venv\Scripts\pythonw.exe'
    if (-not $Repair -and (Test-Path $devPyW)) {
        & (Join-Path $Root '.venv\Scripts\python.exe') -c "import PySide6.QtWidgets, cv2, uiautomator2" 2>$null
        if ($LASTEXITCODE -eq 0) { $Py = Join-Path $Root '.venv\Scripts\python.exe'; $PyW = $devPyW }
    }
    $hash = (Get-FileHash $Req -Algorithm SHA256).Hash + '|' + $Root
    $need = $Repair -or -not (Test-Path $PyW)
    $devEnv = $PyW -eq $devPyW
    if (-not $need -and -not $devEnv -and ((Get-Content $Stamp -ErrorAction SilentlyContinue) -ne $hash)) { $need = $true }
    if (-not $need) {
        & $Py -c "import PySide6.QtWidgets, cv2, uiautomator2" 2>$null
        if ($LASTEXITCODE -ne 0) { $need = $true }
    }
    if ($need) {
        Say 'First-time setup: downloading Python and the bot libraries (one time, a few minutes)...' 'Cyan'
        New-Item -ItemType Directory -Force $Crb | Out-Null
        $uv = Join-Path $Crb 'uv\uv.exe'
        if (-not (Test-Path $uv)) {
            $arch = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { 'aarch64' } else { 'x86_64' }
            $zip = Join-Path $Crb 'uv.zip'
            Say "Downloading uv ($arch)..."
            Invoke-WebRequest "https://github.com/astral-sh/uv/releases/latest/download/uv-$arch-pc-windows-msvc.zip" -OutFile $zip -UseBasicParsing
            Expand-Archive $zip -DestinationPath (Join-Path $Crb 'uv') -Force
            Remove-Item $zip
        }
        $env:UV_PYTHON_INSTALL_DIR = Join-Path $Crb 'python'
        $env:UV_CACHE_DIR = Join-Path $Crb 'cache'
        if (Test-Path $Venv) { Remove-Item -Recurse -Force $Venv }
        Say 'Installing Python 3.12...'
        & $uv venv $Venv --python 3.12 --python-preference only-managed --quiet
        if ($LASTEXITCODE -ne 0) { throw 'Could not set up Python 3.12.' }
        Say 'Installing the bot libraries...'
        & $uv pip install --python $Py -r $Req --quiet
        if ($LASTEXITCODE -ne 0) { throw 'Could not install the libraries (check the internet connection).' }
        Set-Content $Stamp $hash
        & $uv cache clean --quiet 2>$null      # downloads are not needed any more (and have very long paths)
        Say 'Python ready.' 'Green'
    }

    # ------------------------------------------------------------------ adb
    $haveAdb = (Test-Path (Join-Path $Tools 'adb\adb.exe')) -or (Test-Path (Join-Path $Tools 'platform-tools\adb.exe'))
    if (-not $haveAdb) {
        Say "Downloading Google's Android platform-tools (adb)..."
        $zip = Join-Path $Crb 'platform-tools.zip'
        Invoke-WebRequest 'https://dl.google.com/android/repository/platform-tools-latest-windows.zip' -OutFile $zip -UseBasicParsing
        Expand-Archive $zip -DestinationPath $Tools -Force
        Remove-Item $zip
        Say 'adb ready.' 'Green'
    }

    # ------------------------------------------------------------------ desktop shortcut (kept up to date)
    if (-not $NoShortcut) { try {
        $desk = [Environment]::GetFolderPath('Desktop')
        $sh = New-Object -ComObject WScript.Shell
        $lnk = $sh.CreateShortcut((Join-Path $desk 'Clash Rekt Bot.lnk'))
        $lnk.TargetPath = $PyW
        $lnk.Arguments = '"runtime\run_bot.py"'
        $lnk.WorkingDirectory = $Root
        $ico = Join-Path $Root 'runtime\assets\crb_icon.ico'
        if (Test-Path $ico) { $lnk.IconLocation = "$ico,0" }
        $lnk.Description = 'Clash Rekt Bot'
        $lnk.Save()
    } catch { } }

    if ($NoLaunch) { Say 'Setup complete.' 'Green'; exit 0 }

    # ------------------------------------------------------------------ start
    $launchArgs = @('"runtime\run_bot.py"')
    if ($AutoStart) { $launchArgs += '--autostart' }
    if ($Classic) { $launchArgs += '--classic' }
    Start-Process -FilePath $PyW -ArgumentList $launchArgs -WorkingDirectory $Root
    Say 'Starting Clash Rekt Bot...' 'Green'
    Start-Sleep -Seconds 2
}
catch {
    Write-Host ''
    Say "Setup failed: $($_.Exception.Message)" 'Red'
    Say 'Check your internet connection and run "Start Clash Rekt Bot" again.' 'Yellow'
    Say 'If it keeps failing, run it with -Repair, or see Troubleshooting in README.md.' 'Yellow'
    Write-Host ''
    Read-Host '  Press Enter to close'
    exit 1
}
