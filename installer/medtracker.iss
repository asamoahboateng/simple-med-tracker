; Inno Setup 6 script for MedTracker (Windows).
; Build:  iscc /DMyAppVersion=1.2.0 installer\medtracker.iss
; Needs the PyInstaller folder build in dist\MedTracker first. Output: dist\MedTracker-Setup-<version>.exe
; Installs per user (no administrator rights) and never touches the data in %APPDATA%\MedTracker.

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

[Setup]
; Fixed ID: lets a newer installer recognise and replace an older install. Never change it.
AppId={{8E3B5D1A-4C7F-4B2E-9A61-5D0F2C7A9E34}
AppName=MedTracker
AppVersion={#MyAppVersion}
AppPublisher=MedTracker
DefaultDirName={autopf}\MedTracker
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
; PrivilegesRequiredOverridesAllowed is left at its default (none): no "all users" choice.
OutputDir=..\dist
OutputBaseFilename=MedTracker-Setup-{#MyAppVersion}
SetupIconFile=..\resources\icon.ico
UninstallDisplayIcon={app}\MedTracker.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop icon"; GroupDescription: "Additional icons:"; Flags: unchecked

[Files]
Source: "..\dist\MedTracker\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\MedTracker"; Filename: "{app}\MedTracker.exe"
Name: "{autodesktop}\MedTracker"; Filename: "{app}\MedTracker.exe"; Tasks: desktopicon

[Run]
; Normal install: offer to launch at the end.
Filename: "{app}\MedTracker.exe"; Description: "Launch MedTracker"; Flags: nowait postinstall skipifsilent
; Silent (automatic) update: reopen the app right away.
Filename: "{app}\MedTracker.exe"; Flags: nowait skipifnotsilent

[InstallDelete]
; Clear old program files before copying (only inside the install folder).
Type: filesandordirs; Name: "{app}\_internal"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
