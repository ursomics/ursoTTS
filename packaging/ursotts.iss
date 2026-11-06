; Inno Setup script: turns dist\ursoTTS (from PyInstaller) into one setup .exe.
; English edition:  ISCC /DAppVersion=1.0.0 ursotts.iss
; Korean edition:   ISCC /DAppVersion=1.0.0 /DKO "/DKOREAN_ISL=C:\path\to\Korean.isl" ursotts.iss
;   (KOREAN_ISL is optional: without it the Korean edition's wizard stays in English)
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{6E2B3C1A-7F4D-4C2B-9E1A-55A0C0D1E7B3}
AppName=ursoTTS
AppVersion={#AppVersion}
AppPublisher=Ursus (@ursomics)
AppPublisherURL=https://github.com/ursomics/ursotts
DefaultDirName={autopf}\ursoTTS
DefaultGroupName=ursoTTS
PrivilegesRequired=lowest
#ifdef KO
OutputBaseFilename=ursoTTS-{#AppVersion}-windows-setup_ko
#else
OutputBaseFilename=ursoTTS-{#AppVersion}-windows-setup
#endif
OutputDir=..\dist
SetupIconFile=icons\ursoTTS.ico
UninstallDisplayIcon={app}\ursoTTS.exe
Compression=lzma2/ultra64
SolidCompression=yes
DiskSpanning=no
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
#if Defined(KO) && Defined(KOREAN_ISL)
; the Korean installer is always Korean (no language picker, no guessing from Windows)
ShowLanguageDialog=no
LanguageDetectionMethod=none
#endif

[Languages]
#if Defined(KO) && Defined(KOREAN_ISL)
Name: "korean"; MessagesFile: "{#KOREAN_ISL}"
#endif
Name: "english"; MessagesFile: "compiler:Default.isl"

[CustomMessages]
english.DesktopShortcut=Create a desktop shortcut
english.LaunchApp=Open ursoTTS now
#if Defined(KO) && Defined(KOREAN_ISL)
korean.DesktopShortcut=바탕 화면에 바로 가기 만들기
korean.LaunchApp=지금 ursoTTS 열기
#endif

[Files]
Source: "..\dist\ursoTTS\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\ursoTTS"; Filename: "{app}\ursoTTS.exe"
Name: "{autodesktop}\ursoTTS"; Filename: "{app}\ursoTTS.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "{cm:DesktopShortcut}"; Flags: unchecked

[Run]
Filename: "{app}\ursoTTS.exe"; Description: "{cm:LaunchApp}"; Flags: nowait postinstall skipifsilent
