#define AppName "ANIMA Prompt Studio"
#define AppVersion "2.0.0"
#define AppPublisher "ANIMA Prompt Studio"
#define AppExeName "AnimaPromptStudio.exe"

[Setup]
AppId={{8B8AA7C3-0F83-4A9D-9C7E-200000000001}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\ANIMA Prompt Studio
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\release
OutputBaseFilename=ANIMA-Prompt-Studio-Setup-v{#AppVersion}
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64
WizardStyle=modern
UninstallDisplayIcon={app}\{#AppExeName}
PrivilegesRequired=lowest

[Files]
Source: "..\dist\AnimaPromptStudio\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Run]
Filename: "{app}\{#AppExeName}"; Description: "启动 {#AppName}"; Flags: nowait postinstall skipifsilent
