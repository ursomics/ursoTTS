# Build ursoTTS for Windows and a setup .exe with Inno Setup.
# Run from the project folder in PowerShell:  powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
$ErrorActionPreference = "Stop"
$Version = (Select-String -Path ursotts\__init__.py -Pattern '__version__ = "([^"]+)"').Matches[0].Groups[1].Value
python -m pip install --upgrade pip
python -m pip install ".[chatterbox]" pyinstaller
pyinstaller packaging\ursotts.spec --noconfirm --clean
$Iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $Iscc)) { throw "Inno Setup 6 is not installed (https://jrsoftware.org/isinfo.php)" }
& $Iscc "/DAppVersion=$Version" packaging\ursotts.iss
Write-Host "Built dist\ursoTTS-$Version-windows-setup.exe"
