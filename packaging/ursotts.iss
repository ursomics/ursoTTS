; Inno Setup script: turns dist\ursoTTS (from PyInstaller) into one setup .exe.
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
OutputDir=..\dist
OutputBaseFilename=ursoTTS-{#AppVersion}-windows-setup
SetupIconFile=icons\ursoTTS.ico
UninstallDisplayIcon={app}\ursoTTS.exe
Compression=lzma2/ultra64
SolidCompression=yes
DiskSpanning=no
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible

[Files]
Source: "..\dist\ursoTTS\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\ursoTTS"; Filename: "{app}\ursoTTS.exe"
Name: "{autodesktop}\ursoTTS"; Filename: "{app}\ursoTTS.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Run]
Filename: "{app}\ursoTTS.exe"; Description: "Open ursoTTS now"; Flags: nowait postinstall skipifsilent
