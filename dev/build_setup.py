"""Build DDMonitorSetup.exe from an already verified Windows portable directory."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ddm.update_install import MANIFEST, PROTECTED, relative_path
from ddm.legacy_cleanup import INVENTORY
from ddm.version import DISPLAY_NAME, VERSION

APP_ID = 'DDMonitorCE'
PROGRAM_DIRS = {'_internal', 'assets', 'ffmpeg-license', 'mpv-license'}
PROGRAM_FILES = {f'{DISPLAY_NAME}.exe', 'ffmpeg.exe', 'ddm-build.json', 'LICENSE',
                 'NOTICE.md', f'RELEASE-v{VERSION}.md', '运行说明.txt', INVENTORY,
                 'DDMonitorDiagnostics.exe', '诊断工具说明.md'}
PORTABLE_ONLY = {'运行说明.txt'}
# Only files written by config.py / AccountStore for the bundled platforms.
PERSONAL_FILES = ['utils/config.json', 'utils/config.json.bak'] + [
    f'utils/accounts/{kind}.{suffix}'
    for kind in ('bilibili', 'douyin', 'douyu', 'huya', 'youtube', 'twitch',
                 'douyin_follows', 'youtube_oauth_client', 'twitch_oauth_client')
    for suffix in ('bin', 'tmp')]


def quote(value):
    value = str(value)
    if '\n' in value or '\r' in value:
        raise ValueError('Installer paths must not contain newlines')
    return '"' + value.replace('"', '""') + '"'


def payload_files(payload):
    """Allow only release program files, never local data or directory links."""
    payload = Path(payload).resolve()
    build = json.loads((payload / 'ddm-build.json').read_text(encoding='utf-8-sig'))
    if build != {'version': VERSION, 'update_protocol': 1, 'platform': 'windows-x64'}:
        raise ValueError('Portable build does not match this release')
    files = []
    for path in sorted(payload.rglob('*')):
        if path.is_symlink() or path.is_junction():
            raise ValueError(f'Linked payload path: {path.name}')
        rel = path.relative_to(payload).as_posix()
        if rel in PROTECTED and path.is_dir() and not any(path.iterdir()):
            continue
        relative_path(rel)
        if rel.split('/')[0] not in PROGRAM_DIRS and rel not in PROGRAM_FILES:
            raise ValueError(f'Not a release program path: {rel}')
        if path.is_file() and rel not in PORTABLE_ONLY:
            files.append(rel)
    required = {f'{DISPLAY_NAME}.exe', 'ffmpeg.exe', '_internal/libmpv-2.dll',
                'DDMonitorDiagnostics.exe', '诊断工具说明.md'}
    if not required.issubset(files):
        raise ValueError('Portable program or playback runtime is missing')
    return files


def write_script(payload, work, output):
    payload, work, output = map(lambda p: Path(p).resolve(), (payload, work, output))
    files = payload_files(payload)
    work.mkdir(parents=True, exist_ok=True)
    # Only Setup receives this initial inventory; the update ZIP forbids this path.
    inventory = work / MANIFEST
    inventory.write_text(json.dumps(files, ensure_ascii=False), encoding='utf-8')
    helper = ROOT / 'work/setup-native/DDMonitorInstallerHelper.exe'
    # Keep the pre-install tool before the large payload, in its own solid block.
    entries = [f'Source: {quote(helper)}; Flags: dontcopy']
    directories = {''}
    for index, name in enumerate(files):
        parent = Path(name).parent
        suffix = '' if str(parent) == '.' else '\\' + str(parent).replace('/', '\\')
        directories.add(suffix)
        flags = 'ignoreversion solidbreak' if index == 0 else 'ignoreversion'
        entries.append(f'Source: {quote(payload / name)}; DestDir: "{{app}}{suffix}"; Flags: {flags}')
    # Install this early-stored file before the payload to avoid a second seek.
    entries.insert(1, f'Source: {quote(helper)}; DestDir: "{{app}}"; '
                   'DestName: "DDMonitorUninstall.exe"; Flags: ignoreversion')
    entries.append(f'Source: {quote(inventory)}; DestDir: "{{app}}"; Flags: ignoreversion')
    entries.append(f'Source: {quote(ROOT / "dev/installer/ChineseSimplified-LICENSE.txt")}; '
                   'DestDir: "{app}\\setup-license"; Flags: ignoreversion')
    directories.add('\\setup-license')
    guards = '\n'.join('  if not SafePath(ExpandConstant(' +
                       "'{app}" + directory.replace("'", "''") + "')) then Exit;"
                       for directory in sorted(directories))
    cleanup_guards = '\n'.join("  if not SafePath(ExpandConstant('{app}\\" +
                               name.replace('/', '\\') + "')) then Exit;" for name in PERSONAL_FILES)
    cleanup_files = '\n'.join("  RemovePersonalFile('" + name.replace('/', '\\') + "');"
                              for name in PERSONAL_FILES)
    script = f'''[Setup]
AppId={APP_ID}
AppName={DISPLAY_NAME}
AppVersion={VERSION}
AppPublisher=Lanpropro
AppPublisherURL=https://github.com/Lanpropro/DD_Monitor_CE
DefaultDirName={{localappdata}}\\Programs\\DDMonitorCE
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={output}
OutputBaseFilename=DDMonitorSetup
SetupIconFile={ROOT / 'favicon.ico'}
UninstallDisplayIcon={{app}}\\{DISPLAY_NAME}.exe
UninstallFilesDir={{app}}\\.ddm-uninstall
DisableProgramGroupPage=yes
AllowNoIcons=yes
WizardStyle=modern dark includetitlebar hidebevels
WizardBackColor=#202225
WizardImageFile={ROOT / 'dev/installer/wizard.png'}
WizardSmallImageFile={ROOT / 'assets/logo.png'}
WizardImageBackColor=#202225
WizardSmallImageBackColor=#202225
DisableWelcomePage=no
WizardSizePercent=110
Compression=lzma2/fast
SolidCompression=yes
CloseApplications=no
RestartApplications=no
SetupLogging=no

[Languages]
Name: "chinesesimp"; MessagesFile: "{ROOT / 'dev/installer/ChineseSimplified.isl'}"

[Messages]
WelcomeLabel1=欢迎安装 {DISPLAY_NAME}
WelcomeLabel2=安装程序将安装 {DISPLAY_NAME} {VERSION}。%n%n卸载默认保留个人数据，可主动清除可识别的个人信息。录制和未登记来源的文件始终保留。
ConfirmUninstall=确定卸载 %1？%n%n将按所选范围卸载。未勾选清理时保留个人数据；录制和未登记来源的文件始终保留，不会整目录清空。

[Tasks]
Name: desktopicon; Description: "创建桌面快捷方式"; Flags: unchecked

[Files]
{chr(10).join(entries)}

[Icons]
Name: "{{autoprograms}}\\DDMonitorCE\\{DISPLAY_NAME}"; Filename: "{{app}}\\{DISPLAY_NAME}.exe"; Check: CanCreateShortcut('{{autoprograms}}\\DDMonitorCE\\{DISPLAY_NAME}.lnk')
Name: "{{autodesktop}}\\{DISPLAY_NAME}"; Filename: "{{app}}\\{DISPLAY_NAME}.exe"; Tasks: desktopicon; Check: CanCreateShortcut('{{autodesktop}}\\{DISPLAY_NAME}.lnk')
Name: "{{autoprograms}}\\DDMonitorCE\\卸载 {DISPLAY_NAME}"; Filename: "{{uninstallexe}}"; Check: CanCreateShortcut('{{autoprograms}}\\DDMonitorCE\\卸载 {DISPLAY_NAME}.lnk')

[Run]
Filename: "{{app}}\\{DISPLAY_NAME}.exe"; Description: "启动 {DISPLAY_NAME}"; Flags: nowait postinstall skipifsilent unchecked

[Code]
var
  RemovePersonalData, CleanupFailed: Boolean;

procedure BrowseInstallFolder(Sender: TObject);
var
  Selected, Output, Initial: String;
  Lines: TArrayOfString;
  ResultCode: Integer;
begin
  ResultCode := 2;
  Output := ExpandConstant('{{tmp}}\\selected-folder.txt');
  Initial := WizardForm.DirEdit.Text;
  while (not DirExists(Initial)) and (ExtractFileDir(Initial) <> Initial) do
    Initial := ExtractFileDir(Initial);
  if Exec(ExpandConstant('{{tmp}}\\DDMonitorInstallerHelper.exe'),
      '--pick-folder "' + Initial + '" "' + Output + '" ' + IntToStr(WizardForm.Handle),
      '', SW_SHOWNORMAL, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0) then begin
    if LoadStringsFromFile(Output, Lines) and (GetArrayLength(Lines) = 1) then begin
      Selected := Trim(Lines[0]);
      if CompareText(ExtractFileName(RemoveBackslashUnlessRoot(Selected)), 'DDMonitorCE') <> 0 then
        Selected := AddBackslash(Selected) + 'DDMonitorCE';
      WizardForm.DirEdit.Text := Selected;
    end;
  end else if ResultCode <> 1 then
    MsgBox('无法打开系统文件夹选择器，请直接在安装目录输入框填写路径。', mbError, MB_OK);
  DeleteFile(Output);
end;

procedure InitializeWizard;
begin
  ExtractTemporaryFile('DDMonitorInstallerHelper.exe');
  WizardForm.DirBrowseButton.OnClick := @BrowseInstallFolder;
end;

function GetFileAttributes(Name: String): LongWord;
  external 'GetFileAttributesW@kernel32.dll stdcall';

function CanCreateShortcut(Name: String): Boolean;
begin
  Result := not FileExists(ExpandConstant(Name));
end;

function SafePath(Name: String): Boolean;
var
  Attr: LongWord;
  Parent: String;
begin
  Result := False;
  while Name <> '' do begin
    Attr := GetFileAttributes(Name);
    if (Attr <> $FFFFFFFF) and ((Attr and $400) <> 0) then Exit;
    Parent := ExtractFileDir(Name);
    if Parent = Name then Break;
    Name := Parent;
  end;
  Result := True;
end;

function SafeProgramPaths: Boolean;
begin
  Result := False;
{guards}
  if not SafePath(ExpandConstant('{{app}}\\.ddm-uninstall')) then Exit;
  Result := True;
end;

function PersonalPathsSafe: Boolean;
begin
  Result := False;
{cleanup_guards}
  Result := True;
end;

function ChooseUninstallOptions: Boolean;
var
  Form: TSetupForm;
  Choice: TNewCheckBox;
  Description: TNewStaticText;
  ProceedButton, CancelButton: TNewButton;
begin
  RemovePersonalData := False;
  Result := True;
  if UninstallSilent then Exit;
  Form := CreateCustomForm(470, 245, True, True);
  try
    Form.Caption := '卸载 {DISPLAY_NAME}';
    Form.Position := poScreenCenter;
    Form.BorderStyle := bsDialog;
    Choice := TNewCheckBox.Create(Form);
    Choice.Parent := Form;
    Choice.SetBounds(ScaleX(20), ScaleY(18), ScaleX(430), ScaleY(30));
    Choice.Caption := '同时清除可识别的个人信息（账号和设置）';
    Choice.Checked := False;
    Description := TNewStaticText.Create(Form);
    Description.Parent := Form;
    Description.SetBounds(ScaleX(20), ScaleY(62), ScaleX(430), ScaleY(125));
    Description.AutoSize := False;
    Description.WordWrap := True;
    Description.Caption := '默认保留。勾选后清除内置平台的登录凭据、关注房间、布局和设置及其备份。' + #13#10 + #13#10 +
      '录制和未登记来源的文件始终保留。现有插件、皮肤、日志和缓存没有逐文件来源记录，因此保留，安装目录可能仍有内容。清理前请退出软件。';
    ProceedButton := TNewButton.Create(Form);
    ProceedButton.Parent := Form;
    ProceedButton.SetBounds(ScaleX(260), ScaleY(200), ScaleX(90), ScaleY(28));
    ProceedButton.Caption := '继续卸载';
    ProceedButton.ModalResult := mrOk;
    ProceedButton.Default := True;
    CancelButton := TNewButton.Create(Form);
    CancelButton.Parent := Form;
    CancelButton.SetBounds(ScaleX(360), ScaleY(200), ScaleX(90), ScaleY(28));
    CancelButton.Caption := '取消';
    CancelButton.ModalResult := mrCancel;
    CancelButton.Cancel := True;
    Result := Form.ShowModal = mrOk;
    if Result then RemovePersonalData := Choice.Checked;
  finally
    Form.Free;
  end;
end;

procedure RemovePersonalFile(RelativeName: String);
var
  Name: String;
begin
  Name := ExpandConstant('{{app}}\\') + RelativeName;
  if not SafePath(Name) then begin
    CleanupFailed := True;
    Exit;
  end;
  if FileExists(Name) and not DeleteFile(Name) then CleanupFailed := True;
end;

procedure CurUninstallStepChanged(Step: TUninstallStep);
begin
  if (Step = usUninstall) and RemovePersonalData then begin
    if not PersonalPathsSafe then CleanupFailed := True
    else begin
{cleanup_files}
      RemoveDir(ExpandConstant('{{app}}\\utils\\accounts'));
      RemoveDir(ExpandConstant('{{app}}\\utils'));
    end;
  end;
  if (Step = usPostUninstall) and CleanupFailed then
    SuppressibleMsgBox('部分个人信息无法清理，或路径包含链接。为保护其他文件，已保留这些内容。请检查原安装目录。',
      mbError, MB_OK, IDOK);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Found: TFindRec;
  OldDir: String;
  HasFiles, OwnInstall: Boolean;
begin
  Result := '';
  if not SafeProgramPaths then begin
    Result := '安装目录包含链接，请选择普通文件夹。';
    Exit;
  end;
  HasFiles := False;
  if FindFirst(ExpandConstant('{{app}}\\*'), Found) then begin
    try
      repeat
        if (Found.Name <> '.') and (Found.Name <> '..') then HasFiles := True;
      until not FindNext(Found);
    finally
      FindClose(Found);
    end;
  end;
  OwnInstall := RegQueryStringValue(HKCU,
    'Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\{APP_ID}_is1',
    'InstallLocation', OldDir);
  OwnInstall := OwnInstall and
    (CompareText(RemoveBackslashUnlessRoot(OldDir),
      RemoveBackslashUnlessRoot(ExpandConstant('{{app}}'))) = 0) and
    FileExists(ExpandConstant('{{app}}\\.ddm-uninstall\\unins000.dat'));
  if HasFiles and not OwnInstall then
    Result := '此文件夹已有其他内容。请选择新的空文件夹；已安装用户可使用软件内更新。';
end;

function InitializeUninstall: Boolean;
begin
  Result := SafeProgramPaths;
  if not Result then
    SuppressibleMsgBox('程序目录被改成了链接。为保护其他位置的文件，卸载已停止，请先恢复普通目录。',
      mbError, MB_OK, IDOK);
  if Result then Result := ChooseUninstallOptions;
end;
'''
    target = work / 'DDMonitorSetup.iss'
    target.write_text(script, encoding='utf-8-sig')
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--payload', type=Path, required=True)
    parser.add_argument('--out-dir', type=Path, required=True)
    parser.add_argument('--iscc', type=Path, required=True)
    args = parser.parse_args()
    output = args.out_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    native = ROOT / 'work/setup-native'
    native.mkdir(parents=True, exist_ok=True)
    resource = native / 'helper.rc'
    resource.write_text('1 ICON "' + (ROOT / 'favicon.ico').as_posix() + '"\n', encoding='utf-8')
    subprocess.run(['rc', '/nologo', '/fo', str(native / 'helper.res'), str(resource)], check=True)
    subprocess.run(['cl', '/nologo', '/O1', '/MT', '/EHsc', '/utf-8',
                    '/DUNICODE', '/D_UNICODE', str(ROOT / 'dev/installer/helper.cpp'),
                    '/Fe:' + str(native / 'DDMonitorInstallerHelper.exe'),
                    '/Fo:' + str(native / 'helper.obj'), '/link', '/SUBSYSTEM:WINDOWS',
                    str(native / 'helper.res'),
                    'ole32.lib', 'shell32.lib', 'uuid.lib', 'user32.lib'], check=True)
    script = write_script(args.payload, ROOT / 'work/setup-build', output)
    subprocess.run([str(args.iscc.resolve()), str(script)], check=True)
    print(output / 'DDMonitorSetup.exe')


if __name__ == '__main__':
    main()
