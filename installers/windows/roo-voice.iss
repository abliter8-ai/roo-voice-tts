; Roo Voice — Windows installer (Inno Setup 6).
; Bundles a standalone Python + the app; first launch installs deps + downloads
; the model, then serves the UI. No admin required (installs to LocalAppData).
; Unsigned — SmartScreen: "More info" -> "Run anyway".
; Build: run build.ps1 (stages python + app), then this compiles to dist\Roo-Voice-Setup.exe

#define AppName "Roo Voice"
#define AppVer "1.0.0"

[Setup]
AppId={{A1B2C3D4-ROO0-VOICE-ABLI-TER8AI000001}
AppName={#AppName}
AppVersion={#AppVer}
AppPublisher=abliter8
AppPublisherURL=https://github.com/abliter8-ai/roo-voice-tts
DefaultDirName={localappdata}\Roo Voice
DefaultGroupName=Roo Voice
DisableProgramGroupPage=yes
OutputDir=dist
OutputBaseFilename=Roo-Voice-Setup
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
SetupIconFile=roo-voice.ico
UninstallDisplayIcon={app}\roo-voice.ico
WizardStyle=modern
DisableWelcomePage=no

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional icons:"

[Files]
Source: "staging\python\*"; DestDir: "{app}\python"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "staging\app\*"; DestDir: "{app}\app"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "roo-voice.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Roo Voice"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\app\installers\common\bootstrap.py"""; WorkingDir: "{app}\app"; IconFilename: "{app}\roo-voice.ico"
Name: "{userdesktop}\Roo Voice"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\app\installers\common\bootstrap.py"""; WorkingDir: "{app}\app"; IconFilename: "{app}\roo-voice.ico"; Tasks: desktopicon
Name: "{group}\Uninstall Roo Voice"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\app\installers\common\bootstrap.py"""; WorkingDir: "{app}\app"; Description: "Launch Roo Voice now"; Flags: postinstall nowait skipifsilent

[UninstallDelete]
; Remove the per-user env + model cache created on first run.
Type: filesandordirs; Name: "{localappdata}\Roo Voice\env"
Type: filesandordirs; Name: "{localappdata}\Roo Voice\hf-cache"
