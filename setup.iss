[Setup]
AppName=Scan To Excel
AppVersion=1.0
DefaultDirName={localappdata}\ScanToExcel
DefaultGroupName=Scan To Excel
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\ScanToExcelApp.exe
Compression=lzma2
SolidCompression=yes
OutputDir=D:\version
OutputBaseFilename=Setup_ScanToExcel_v1.0

[Files]
Source: "dist\ScanToExcelApp\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Scan To Excel"; Filename: "{app}\ScanToExcelApp.exe"
Name: "{autodesktop}\Scan To Excel"; Filename: "{app}\ScanToExcelApp.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Tao bieu tuong tren Desktop"; GroupDescription: "Additional icons:"; Flags: unchecked

[Run]
Filename: "{app}\ScanToExcelApp.exe"; Description: "Khoi chay Scan To Excel ngay"; Flags: nowait postinstall skipifsilent
