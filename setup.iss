#define MyAppName "Scan To Excel Host"
#ifndef MyAppVersion
#define MyAppVersion "0.1"
#endif
#define MyAppExeName "ScanToExcelApp.exe"

[Setup]
AppId={{C50614C6-A1B8-4FD1-AAC8-9A16560F03B2}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=Scan To Excel
DefaultDirName={localappdata}\Programs\ScanToExcelHost
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
OutputDir=installer-output
OutputBaseFilename=ScanToExcelHost-Setup-{#MyAppVersion}
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
WizardStyle=modern

[Files]
Source: "dist\ScanToExcelApp\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\Start-ScanToExcelHost.cmd"; WorkingDir: "{app}"
Name: "{group}\Cau hinh {#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--configure"; WorkingDir: "{app}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\Start-ScanToExcelHost.cmd"; WorkingDir: "{app}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Tao bieu tuong tren Desktop"; GroupDescription: "Bieu tuong bo sung:"; Flags: unchecked

[Run]
Filename: "{app}\Start-ScanToExcelHost.cmd"; Description: "Khoi chay {#MyAppName}"; Flags: shellexec nowait postinstall skipifsilent

[UninstallDelete]
; Deliberately keep %LOCALAPPDATA%\ScanToExcelHost. It contains host.env and
; business data and must survive upgrades or application uninstall/reinstall.
