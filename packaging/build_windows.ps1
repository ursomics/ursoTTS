# Build ursoTTS for Windows and a setup .exe with Inno Setup.
# Run from the project folder in PowerShell:  powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
# Korean edition:                             powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1 -Ko
param([switch]$Ko)
$ErrorActionPreference = "Stop"
$Version = (Select-String -Path ursotts\__init__.py -Pattern '__version__ = "([^"]+)"').Matches[0].Groups[1].Value

# The installed app's default language is the one-word text file ursotts\assets\default_lang.txt
# (bundled by ursotts.spec with the rest of assets\). Write it only for the build, then put things
# back, so an English build after a Korean build is English again.
$LangFile = Join-Path (Get-Location).Path "ursotts\assets\default_lang.txt"
$HadLangFile = Test-Path $LangFile
$LangBackup = if ($HadLangFile) { [IO.File]::ReadAllText($LangFile) } else { $null }
try {
    if ($Ko) { [IO.File]::WriteAllText($LangFile, "ko`n") }
    elseif ($HadLangFile) { Remove-Item $LangFile }
    Write-Host ("Building the " + $(if ($Ko) { "Korean (ko)" } else { "English (en)" }) + " edition")
    python -m pip install --upgrade pip
    python -m pip install ".[chatterbox]" sounddevice pyinstaller
    pyinstaller packaging\ursotts.spec --noconfirm --clean
}
finally {
    if ($HadLangFile) { [IO.File]::WriteAllText($LangFile, $LangBackup) }
    elseif (Test-Path $LangFile) { Remove-Item $LangFile }
}

$Iscc = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
if (-not (Test-Path $Iscc)) { throw "Inno Setup 6 is not installed (https://jrsoftware.org/isinfo.php)" }

# Korean setup wizard: Korean.isl is an *unofficial* translation that may not ship with Inno Setup.
# Use an installed copy if there is one, else try to download it. If that fails, warn and carry on:
# the app is still Korean, only the installer wizard stays in English.
$KoIsl = $null
if ($Ko) {
    $InnoDir = Split-Path $Iscc
    foreach ($candidate in @("$InnoDir\Languages\Korean.isl", "$InnoDir\Languages\Unofficial\Korean.isl")) {
        if (Test-Path $candidate) { $KoIsl = $candidate; break }
    }
    if (-not $KoIsl) {
        $Url = "https://raw.githubusercontent.com/jrsoftware/issrc/main/Files/Languages/Unofficial/Korean.isl"
        $Dest = Join-Path (Get-Location).Path "dist\Korean.isl"
        try {
            New-Item -ItemType Directory -Force -Path (Split-Path $Dest) | Out-Null
            [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
            Invoke-WebRequest -Uri $Url -OutFile $Dest -UseBasicParsing
            if ((Get-Item $Dest).Length -lt 2000) { throw "the downloaded file is too small to be Korean.isl" }
            $KoIsl = $Dest
        }
        catch {
            Write-Warning "Could not get Korean.isl ($($_.Exception.Message)). The installer wizard will be in English; the app itself is still Korean."
            if (Test-Path $Dest) { Remove-Item $Dest -ErrorAction SilentlyContinue }
        }
    }
}

$IsccArgs = @("/DAppVersion=$Version")
if ($Ko) {
    $IsccArgs += "/DKO"
    if ($KoIsl) { $IsccArgs += "/DKOREAN_ISL=$KoIsl" }
}
& $Iscc @IsccArgs packaging\ursotts.iss
if ($LASTEXITCODE -ne 0 -and $KoIsl) {
    Write-Warning "Inno Setup failed with the Korean wizard language; building again with an English wizard."
    $IsccArgs = @("/DAppVersion=$Version", "/DKO")
    & $Iscc @IsccArgs packaging\ursotts.iss
}
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed (exit code $LASTEXITCODE)" }

$Out = if ($Ko) { "dist\ursoTTS-$Version-windows-setup_ko.exe" } else { "dist\ursoTTS-$Version-windows-setup.exe" }
Write-Host "Built $Out"
