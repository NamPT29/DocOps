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

; Do not launch the host automatically after setup.  The Start Menu/Desktop
; shortcut is the one supported entry point and owns its single visible console.
; Auto-launching here can overlap with a manual shortcut click and produce two
; host consoles and competing server processes.

[UninstallDelete]
; Deliberately keep %LOCALAPPDATA%\ScanToExcelHost. It contains host.env and
; business data and must survive upgrades or application uninstall/reinstall.

[Code]
const
  ExistingUninstallKey =
    'Software\Microsoft\Windows\CurrentVersion\Uninstall\{C50614C6-A1B8-4FD1-AAC8-9A16560F03B2}_is1';

function TryGetExistingInstall(
  var ExistingVersion: String; var ExistingUninstaller: String): Boolean;
begin
  ExistingVersion := '';
  ExistingUninstaller := '';
  Result := RegQueryStringValue(HKCU, ExistingUninstallKey, 'DisplayVersion', ExistingVersion);
  if Result then
    RegQueryStringValue(HKCU, ExistingUninstallKey, 'UninstallString', ExistingUninstaller);
end;

function ExtractExecutablePath(const CommandLine: String): String;
var
  ClosingQuote: Integer;
  ExecutableEnd: Integer;
  FirstSpace: Integer;
begin
  Result := '';
  if CommandLine = '' then
    exit;

  if CommandLine[1] = '"' then begin
    ClosingQuote := Pos('"', Copy(CommandLine, 2, MaxInt));
    if ClosingQuote > 0 then
      Result := Copy(CommandLine, 2, ClosingQuote - 1);
    exit;
  end;

  ExecutableEnd := Pos('.exe', Lowercase(CommandLine));
  if ExecutableEnd > 0 then begin
    Result := Copy(CommandLine, 1, ExecutableEnd + 3);
    exit;
  end;

  FirstSpace := Pos(' ', CommandLine);
  if FirstSpace = 0 then
    Result := CommandLine
  else
    Result := Copy(CommandLine, 1, FirstSpace - 1);
end;

function RemoveExistingInstall(const ExistingUninstaller: String): Boolean;
var
  UninstallerPath: String;
  ResultCode: Integer;
begin
  Result := False;
  UninstallerPath := ExtractExecutablePath(ExistingUninstaller);
  if (UninstallerPath = '') or (not FileExists(UninstallerPath)) then begin
    MsgBox(
      'Khong tim thay trinh go cai dat cua ban cai hien tai. Khong thay doi nao da duoc thuc hien.',
      mbError,
      MB_OK
    );
    exit;
  end;

  if not Exec(UninstallerPath, '', '', SW_SHOW, ewWaitUntilTerminated, ResultCode) then begin
    MsgBox('Khong the chay trinh go cai dat.', mbError, MB_OK);
    exit;
  end;

  if ResultCode <> 0 then begin
    MsgBox('Go cai dat chua hoan tat. Setup se dung de dam bao an toan.', mbError, MB_OK);
    exit;
  end;
  Result := True;
end;

function InitializeSetup(): Boolean;
var
  ExistingVersion: String;
  ExistingUninstaller: String;
  Response: Integer;
begin
  Result := True;
  if not TryGetExistingInstall(ExistingVersion, ExistingUninstaller) then
    exit;

  if ExistingVersion = '{#MyAppVersion}' then begin
    Response := MsgBox(
      'Da cai Scan To Excel Host phien ban ' + ExistingVersion + '.' + #13#10 + #13#10 +
      'Co (Yes): Sua/cai lai ung dung, giu nguyen PostgreSQL, host.env va du lieu.' + #13#10 +
      'Khong (No): Go ung dung hien tai (du lieu nghiep vu van duoc giu lai).' + #13#10 +
      'Huy (Cancel): Khong thay doi gi.',
      mbConfirmation,
      MB_YESNOCANCEL
    );
    if Response = IDYES then
      exit;
  end else begin
    Response := MsgBox(
      'Da cai Scan To Excel Host phien ban ' + ExistingVersion +
      '. Ban cai nay la phien ban {#MyAppVersion}.' + #13#10 + #13#10 +
      'Co (Yes): Cap nhat tai cho, giu nguyen PostgreSQL, host.env va du lieu.' + #13#10 +
      'Khong (No): Go ung dung hien tai.' + #13#10 +
      'Huy (Cancel): Khong thay doi gi.',
      mbConfirmation,
      MB_YESNOCANCEL
    );
    if Response = IDYES then
      exit;
  end;

  if Response = IDNO then begin
    if RemoveExistingInstall(ExistingUninstaller) then
      MsgBox('Da go ung dung. Hay chay lai file Setup neu muon cai moi.', mbInformation, MB_OK);
  end;
  Result := False;
end;
