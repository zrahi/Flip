; Flip's installer (built with Inno Setup by the GitHub build).
; Installs to %LOCALAPPDATA%\Programs\Flip (no admin needed). Flip's data (brain, chats) lives in
; %LOCALAPPDATA%\Flip; the uninstaller asks whether to delete that too.

#define AppVersion GetEnv("FLIP_VERSION")

[Setup]
AppId={{B6A1C3E2-5F4D-4C7A-9E1B-F1A9C0DE1234}
AppName=Flip
AppVersion={#AppVersion}
AppPublisher=zrahi
DefaultDirName={localappdata}\Programs\Flip
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
PrivilegesRequired=lowest
OutputDir=dist
OutputBaseFilename=FlipSetup
SetupIconFile=flip.ico
UninstallDisplayIcon={app}\Flip.exe
UninstallDisplayName=Flip
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=force

[Tasks]
Name: "desktopicon"; Description: "Put Flip on my desktop"; Flags: checkedonce

[Files]
Source: "dist\Flip\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; files from the previous version that aren't in this one
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{userprograms}\Flip"; Filename: "{app}\Flip.exe"
Name: "{userdesktop}\Flip"; Filename: "{app}\Flip.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Flip.exe"; Description: "Open Flip"; Flags: nowait postinstall; Check: ShouldLaunch

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
function ShouldLaunch: Boolean;
var
  i: Integer;
begin
  Result := True;
  for i := 1 to ParamCount do
    if CompareText(ParamStr(i), '/NOLAUNCH') = 0 then
      Result := False;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    if UninstallSilent or (MsgBox('Also delete Flip''s brain, voice, chats and memory? This frees several GB.',
                                  mbConfirmation, MB_YESNO) = IDYES) then
      DelTree(ExpandConstant('{localappdata}\Flip'), True, True, True);
end;
