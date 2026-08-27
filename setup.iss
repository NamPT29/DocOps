#define MyAppName "Scan To Excel Host"
#define MyAppVersion "1.1.0"
#define MyAppExeName "ScanToExcelApp.exe"

[Setup]
AppId={{C50614C6-A1B8-4FD1-AAC8-9A16560F03B2}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={localappdata}\Programs\ScanToExcelHost
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
OutputDir=installer-output
OutputBaseFilename=Setup_ScanToExcelHost_{#MyAppVersion}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
WizardStyle=modern

[Files]
Source: "dist\ScanToExcelApp\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Tao bieu tuong tren Desktop"; GroupDescription: "Bieu tuong bo sung:"; Flags: unchecked

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Khoi chay {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Deliberately keep %LOCALAPPDATA%\ScanToExcelHost. It contains host.env and
; business data and must survive upgrades or application uninstall/reinstall.
