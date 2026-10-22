"""Build DDMonitorSetup.exe from an already verified Windows portable directory."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ddm.update_install import MANIFEST, PROTECTED, relative_path
from ddm.version import DISPLAY_NAME, VERSION

APP_ID = 'DDMonitorCE'
PROGRAM_DIRS = {'_internal', 'assets', 'ffmpeg-license', 'mpv-license'}
PROGRAM_FILES = {f'{DISPLAY_NAME}.exe', 'ffmpeg.exe', 'ddm-build.json', 'LICENSE',
                 'NOTICE.md', f'RELEASE-v{VERSION}.md', '运行说明.txt'}


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
        if path.is_file():
            files.append(rel)
    required = {f'{DISPLAY_NAME}.exe', 'ffmpeg.exe', '_internal/libmpv-2.dll'}
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
    entries = []
    directories = {''}
    for name in files:
        parent = Path(name).parent
        suffix = '' if str(parent) == '.' else '\\' + str(parent).replace('/', '\\')
        directories.add(suffix)
        entries.append(f'Source: {quote(payload / name)}; DestDir: "{{app}}{suffix}"; Flags: ignoreversion')
    entries.append(f'Source: {quote(inventory)}; DestDir: "{{app}}"; Flags: ignoreversion')
    entries.append(f'Source: {quote(ROOT / "dev/installer/ChineseSimplified-LICENSE.txt")}; '
                   'DestDir: "{app}\\setup-license"; Flags: ignoreversion')
    directories.add('\\setup-license')
    guards = '\n'.join('  if not SafePath(ExpandConstant(' +
                       "'{app}" + directory.replace("'", "''") + "')) then Exit;"
                       for directory in sorted(directories))
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
WizardStyle=modern
Compression=lzma2/normal
SolidCompression=yes
CloseApplications=no
RestartApplications=no
SetupLogging=yes

[Languages]
Name: "chinesesimp"; MessagesFile: "{ROOT / 'dev/installer/ChineseSimplified.isl'}"

[Messages]
WelcomeLabel1=欢迎安装 {DISPLAY_NAME}
WelcomeLabel2=安装程序将安装 {DISPLAY_NAME} {VERSION}。%n%n卸载只移除安装程序登记的文件和快捷方式；保留账号、配置、插件、录制和其他个人文件。
ConfirmUninstall=确定卸载 %1？%n%n只移除安装程序登记的文件和快捷方式，保留账号、配置、插件、录制和其他个人文件。

[Tasks]
Name: desktopicon; Description: "创建桌面快捷方式"; Flags: unchecked

[Files]
{chr(10).join(entries)}

[Icons]
Name: "{{autoprograms}}\\DDMonitorCE\\{DISPLAY_NAME}"; Filename: "{{app}}\\{DISPLAY_NAME}.exe"; Check: CanCreateShortcut('{{autoprograms}}\\DDMonitorCE\\{DISPLAY_NAME}.lnk')
Name: "{{autodesktop}}\\{DISPLAY_NAME}"; Filename: "{{app}}\\{DISPLAY_NAME}.exe"; Tasks: desktopicon; Check: CanCreateShortcut('{{autodesktop}}\\{DISPLAY_NAME}.lnk')

[Run]
Filename: "{{app}}\\{DISPLAY_NAME}.exe"; Description: "启动 {DISPLAY_NAME}"; Flags: nowait postinstall skipifsilent unchecked

[Code]
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
    script = write_script(args.payload, ROOT / 'work/setup-build', output)
    subprocess.run([str(args.iscc.resolve()), str(script)], check=True)
    print(output / 'DDMonitorSetup.exe')


if __name__ == '__main__':
    main()
