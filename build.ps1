param(
    [switch]$Clean
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$venv = Join-Path $root '.venv'
$activate = Join-Path $venv 'Scripts/Activate.ps1'
if ($Clean) {
    if (Test-Path $venv) { Remove-Item -Recurse -Force $venv }
    if (Test-Path (Join-Path $root 'build')) { Remove-Item -Recurse -Force (Join-Path $root 'build') }
    if (Test-Path (Join-Path $root 'dist')) { Remove-Item -Recurse -Force (Join-Path $root 'dist') }
}
if (-not (Test-Path $venv)) {
    Write-Host 'Creating venv...'
    python -m venv $venv
}
Write-Host 'Activating venv...'
. $activate
Write-Host 'Installing requirements...'
python -m pip install --upgrade pip
pip install -r (Join-Path $root 'requirements.txt')
Write-Host 'Building executable with PyInstaller...'
$entry = Join-Path $root 'src/main.py'
pyinstaller --noconfirm --onefile --windowed --name FoundryLocalChat --add-data "src;src" $entry
Write-Host "Build complete. EXE at: $(Join-Path $root 'dist/FoundryLocalChat.exe')"
