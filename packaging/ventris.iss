; Inno Setup script for the Windows installer. packaging/build.py passes the /D values.
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6C0E8D7A-3B2F-4E51-9D8A-7A1E5C9B4F20}
AppName=Ventris
AppVersion={#AppVersion}
AppPublisher=Patrick Hoskins
AppPublisherURL=https://github.com/armchairpolymath/ventris
DefaultDirName={autopf}\Ventris
DefaultGroupName=Ventris
DisableProgramGroupPage=yes
; Install for the current user only, so no administrator prompt is needed.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir={#OutputDir}
OutputBaseFilename={#OutputName}
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\Ventris.exe
LicenseFile=..\LICENSE
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
ChangesAssociations=yes

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "assoc"; Description: "Open .gcode and .bgcode files with Ventris"; GroupDescription: "File types:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Ventris"; Filename: "{app}\Ventris.exe"
Name: "{autodesktop}\Ventris"; Filename: "{app}\Ventris.exe"; Tasks: desktopicon

[Registry]
Root: HKA; Subkey: "Software\Classes\Ventris.GCode"; ValueType: string; ValueData: "G-code file"; Flags: uninsdeletekey; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\Ventris.GCode\DefaultIcon"; ValueType: string; ValueData: "{app}\Ventris.exe,0"; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\Ventris.GCode\shell\open\command"; ValueType: string; ValueData: """{app}\Ventris.exe"" ""%1"""; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\.gcode\OpenWithProgids"; ValueType: string; ValueName: "Ventris.GCode"; ValueData: ""; Flags: uninsdeletevalue; Tasks: assoc
Root: HKA; Subkey: "Software\Classes\.bgcode\OpenWithProgids"; ValueType: string; ValueName: "Ventris.GCode"; ValueData: ""; Flags: uninsdeletevalue; Tasks: assoc

[Run]
Filename: "{app}\Ventris.exe"; Description: "{cm:LaunchProgram,Ventris}"; Flags: nowait postinstall skipifsilent
