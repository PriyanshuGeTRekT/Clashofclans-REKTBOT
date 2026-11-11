; Clash Rekt Bot - Windows installer (Inno Setup 6).
; Build: tools\build_windows_installer.py  (or ISCC installer\ClashRektBot.iss after tools\make_release.py)
; Per-user install (no admin rights): the app writes its settings and logs inside its own folder.

#define AppName "Clash Rekt Bot"
#ifndef AppVersion
  #define AppVersion "2.0.0"
#endif
#define Src "..\dist\ClashRektBot"

[Setup]
AppId={{609983BA-D322-4D3D-965A-25888F80AD99}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=PriyanshuGeTRekT
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=ClashRektBot-Setup-{#AppVersion}
SetupIconFile=..\runtime\assets\crb_icon.ico
UninstallDisplayIcon={app}\runtime\assets\crb_icon.ico
UninstallDisplayName={#AppName}
WizardStyle=modern
WizardImageFile=wizard_100.bmp,wizard_200.bmp
WizardSmallImageFile=wizard_small_100.bmp,wizard_small_200.bmp
Compression=lzma2/ultra64
SolidCompression=yes
ArchitecturesAllowed=x64compatible arm64
ArchitecturesInstallIn64BitMode=x64compatible arm64
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}
VersionInfoDescription={#AppName} installer

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
WelcomeLabel2=This will install [name/ver] on your computer.%n%nThe first start downloads Python and the bot's libraries into the app's own folder (a few minutes, one time only). Nothing else on your PC is changed.

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "{#Src}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\Start Clash Rekt Bot.bat"; WorkingDir: "{app}"; IconFilename: "{app}\runtime\assets\crb_icon.ico"; Comment: "Start Clash Rekt Bot"
Name: "{group}\README"; Filename: "{app}\README.md"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\Start Clash Rekt Bot.bat"; WorkingDir: "{app}"; IconFilename: "{app}\runtime\assets\crb_icon.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\Start Clash Rekt Bot.bat"; WorkingDir: "{app}"; Description: "Set up and start {#AppName} now"; Flags: postinstall nowait shellexec skipifsilent

[UninstallRun]
; .crb holds Python's deep folders (paths can pass Windows' 260-character limit): remove it with an
; extended-length path, which the plain delete below cannot always do.
Filename: "{cmd}"; Parameters: "/c rmdir /s /q ""\\?\{app}\.crb"""; Flags: runhidden; RunOnceId: "RemovePythonEnv"

[UninstallDelete]
; the downloaded Python environment, adb and Python's cache files (settings in runtime\profiles and
; runtime\logs are kept)
Type: filesandordirs; Name: "{app}\.crb"
Type: filesandordirs; Name: "{app}\runtime\Tools\platform-tools"
Type: filesandordirs; Name: "{app}\source"
