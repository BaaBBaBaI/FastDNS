[Setup]
AppName=FastDNS
AppVersion=1.0.0
AppPublisher=FastDNS
DefaultDirName={autopf}\FastDNS
DefaultGroupName=FastDNS
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=dist
OutputBaseFilename=FastDNS-Setup
Compression=lzma
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\FastDNS.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\FastDNS"; Filename: "{app}\FastDNS.exe"
Name: "{group}\Uninstall FastDNS"; Filename: "{uninstallexe}"
Name: "{autodesktop}\FastDNS"; Filename: "{app}\FastDNS.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\FastDNS.exe"; Description: "{cm:LaunchProgram,FastDNS}"; Flags: nowait postinstall skipifsilent
