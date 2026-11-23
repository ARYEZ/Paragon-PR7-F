; Paragon PR7-F installer (Inno Setup 6).
;   iscc /DAppVersion=0.1.0 installer\pr7f.iss      (after pyinstaller pr7f.spec has made dist\PR7-F)
;
; Per-user (no admin rights) into %LOCALAPPDATA%\Programs\PR7-F, with a Start menu entry.
; The uninstaller leaves your sites (%APPDATA%\Paragon\PR7-F) and saved passwords (Credential Manager) alone,
; as FileZilla's does, so a reinstall finds them again.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
; AppId is permanent: it's how a new version finds and upgrades the installed one. Never change it.
AppId={{34F163CD-E4F2-4415-9865-1175C28F5408}
AppName=Paragon PR7-F
AppVersion={#AppVersion}
AppVerName=Paragon PR7-F {#AppVersion}
AppPublisher=Paragon
VersionInfoVersion={#AppVersion}
PrivilegesRequired=lowest
DefaultDirName={autopf}\PR7-F
DefaultGroupName=Paragon PR7-F
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=PR7-F-Setup-{#AppVersion}
SetupIconFile=..\pr7f\icons\app.ico
UninstallDisplayIcon={app}\PR7-F.exe
UninstallDisplayName=Paragon PR7-F
WizardStyle=modern
WizardImageFile=wizard-large-1x.bmp,wizard-large-2x.bmp
WizardSmallImageFile=wizard-small-1x.bmp,wizard-small-2x.bmp
Compression=lzma2/max
SolidCompression=yes
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\PR7-F\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\Paragon PR7-F"; Filename: "{app}\PR7-F.exe"; Comment: "File transfer (FTP, FTPS, SFTP)"
Name: "{autodesktop}\Paragon PR7-F"; Filename: "{app}\PR7-F.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\PR7-F.exe"; Description: "{cm:LaunchProgram,Paragon PR7-F}"; Flags: nowait postinstall skipifsilent
