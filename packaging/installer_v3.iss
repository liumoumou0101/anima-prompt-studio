#ifndef AppVersion
  #define AppVersion "3.0.0-alpha.1"
#endif
#define AppName "ANIMA Prompt Studio V3"
#define AppPublisher "ANIMA Prompt Studio"
#define AppExeName "AnimaPromptStudioV3.exe"

[Setup]
AppId={{8B8AA7C3-0F83-4A9D-9C7E-300000000001}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\ANIMA Prompt Studio V3
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=..\release
OutputBaseFilename=ANIMA-Prompt-Studio-V3-Setup-v{#AppVersion}
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64
WizardStyle=modern
UninstallDisplayIcon={app}\{#AppExeName}
PrivilegesRequired=lowest
CloseApplications=yes
RestartApplications=no

[Files]
Source: "..\dist\AnimaPromptStudioV3\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加快捷方式："

[Run]
Filename: "{app}\{#AppExeName}"; Description: "启动 {#AppName}"; Flags: nowait postinstall skipifsilent
