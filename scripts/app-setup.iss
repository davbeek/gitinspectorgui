; Script generated by the Inno Setup Script Wizard.
; SEE THE DOCUMENTATION FOR DETAILS ON CREATING INNO SETUP SCRIPT FILES!

#define MyAppName "GitinspectorGUI"
#define MyAppVersion "0.4.0rc7"
#define MyAppURL "https://gitinspectorgui.readthedocs.io/"
#define MyAppExeName "gitinspectorgui.exe"

[Setup]
; NOTE: The value of AppId uniquely identifies this application. Do not use the same AppId value in installers for other applications.
; (To generate a new GUID, click Tools | Generate GUID inside the IDE.)
AppId={{CF68B05F-9FAD-42D4-8DEE-4112F404DD01}}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
;AppVerName={#MyAppName} {#MyAppVersion}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}
DefaultDirName={autopf}\{#MyAppName}
; "ArchitecturesAllowed=arm64" specifies that Setup cannot run
; on anything but ARM64.
ArchitecturesAllowed=arm64
; "ArchitecturesInstallIn64BitMode=arm64" requests that the
; install be done in "64-bit mode" on ARM64,
; meaning it should use the native ARM64 Program Files directory and
; the ARM64 view of the registry.
ArchitecturesInstallIn64BitMode=arm64
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
DisableDirPage=no
; Remove the following line to run in administrative install mode (install for all users.)
PrivilegesRequired=lowest
OutputDir=C:\Users\dvbeek\1-repos\github\gitinspectorgui\app\pyinstall-setup
OutputBaseFilename=windows-gitinspectorgui-setup
SetupIconFile=C:\Users\dvbeek\1-repos\github\gitinspectorgui\src\gigui\gui\images\icon.ico
Compression=lzma
SolidCompression=yes
WizardStyle=modern

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "C:\Users\dvbeek\1-repos\github\gitinspectorgui\app\bundle\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "C:\Users\dvbeek\minigit\*"; DestDir: "{userappdata}\minigit"; Flags: ignoreversion recursesubdirs createallsubdirs
; NOTE: Don't use "Flags: ignoreversion" on any shared system files

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"

[UninstallDelete]
Type: dirifempty; Name: "{app}"

[Run]
; Add the minigit\cmd folder to the Windows PATH environment variable
Filename: "cmd"; Parameters: "/C setx PATH ""%PATH%;{userappdata}\minigit\cmd"""; Flags: runhidden
; Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
