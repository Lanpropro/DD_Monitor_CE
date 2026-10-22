"""Windows-only, isolated real Setup/update/uninstall check using synthetic data."""
import argparse
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dev.build_setup import APP_ID, payload_files
from ddm import update_install
from ddm.version import DISPLAY_NAME, VERSION

PROBE = '''from pathlib import Path
import json
from ddm.plugins import Plugin
class Probe(Plugin):
    def on_load(self, context):
        from PySide6.QtCore import qVersion
        from ddm import room_input
        class Response:
            status_code = 302
            headers = {'Location': 'https://live.bilibili.com/47867?from=123'}
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def raise_for_status(self): pass
        original = room_input.requests.get
        room_input.requests.get = lambda *a, **kw: Response()
        try:
            share = '【直播就是生活就是直播-哔哩哔哩直播】 https://b23.tv/DDsx7iz'
            assert room_input.resolve_bili_share(room_input.extract_room_input(share)) == '47867'
        finally:
            room_input.requests.get = original
        Path(__file__).with_name('passed.json').write_text(json.dumps({'mobile_share': True, 'qt': qVersion()}))
plugin = Probe()
'''


def registered():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                rf'Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_ID}_is1',
                0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY):
            return True
    except FileNotFoundError:
        return False


def run_installer(executable, arguments, log):
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    return subprocess.run([str(executable), '/VERYSILENT', '/SUPPRESSMSGBOXES',
        '/NORESTART', '/SP-', '/LOG=' + str(log), *arguments],
        startupinfo=startup, timeout=300).returncode


def fingerprint(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def check(setup, payload, update_zip):
    if sys.platform != 'win32':
        raise RuntimeError('This check requires Windows')
    if registered():
        raise RuntimeError('An existing DDMonitorCE installation is registered; check refused')
    files = payload_files(payload)
    work = ROOT / 'work'
    work.mkdir(exist_ok=True)
    logs = work / ('setup-check-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
    logs.mkdir()
    with tempfile.TemporaryDirectory(prefix='setup-sandbox-', dir=work) as temporary:
        sandbox = Path(temporary).resolve()
        assert sandbox.is_relative_to(work.resolve())
        install = sandbox / '中文 空格安装目录'
        unrelated = sandbox / '其他目录'
        unrelated.mkdir()
        sentinel = unrelated / 'logo.png'
        sentinel.write_bytes(b'outside directory must survive')
        bad = sandbox / '已有文件夹'
        bad.mkdir()
        (bad / 'personal.txt').write_bytes(b'not owned by setup')
        result = run_installer(setup, ['/NOICONS', '/DIR=' + str(bad)], logs / 'reject-existing.log')
        assert result != 0 and (bad / 'personal.txt').read_bytes() == b'not owned by setup'
        assert not (bad / f'{DISPLAY_NAME}.exe').exists() and not registered()
        result = run_installer(setup, ['/NOICONS', '/TASKS=', '/DIR=' + str(install)], logs / 'install.log')
        assert result == 0 and registered(), 'Setup did not install successfully'
        for name in files:
            assert fingerprint(install / name) == fingerprint(payload / name), name
        initial = json.loads((install / update_install.MANIFEST).read_text(encoding='utf-8'))
        assert set(initial) == set(files)

        data = {'utils/config.json': json.dumps({'version': 2, 'rooms': [], 'wall': [],
            'user_notice_accepted': True, 'plugins_enabled': ['setup_probe'],
            'settings': {'auto_update': False}}).encode(),
            'utils/accounts/session.bin': b'synthetic account, not a real credential',
            'plugins_user/custom/data.bin': b'plugin data',
            'recordings/test.mp4': b'synthetic recording', 'cache/custom.bin': b'cache',
            'logs/user-notes.txt': b'notes', 'personal.txt': b'user root file',
            '_internal/user-added.bin': b'user library directory file',
            'assets/user-added.txt': b'user asset directory file',
            'setup-license/user-added.txt': b'user license directory file',
            '.ddm-uninstall/user-added.txt': b'user uninstall directory file',
            'plugins_user/setup_probe/plugin.py': PROBE.encode('utf-8'),
            'plugins_user/setup_probe/plugin.json': json.dumps({'id': 'setup_probe',
                'name': 'Setup check', 'version': '1.0'}).encode()}
        for name, value in data.items():
            path = install / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(value)
        # A repair must preserve all synthetic personal files.
        assert run_installer(setup, ['/NOICONS', '/TASKS=', '/DIR=' + str(install)], logs / 'repair.log') == 0
        assert all((install / name).read_bytes() == value for name, value in data.items())

        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        process = subprocess.Popen([str(install / f'{DISPLAY_NAME}.exe')], cwd=install,
            startupinfo=startup, env=dict(os.environ, DDM_NO_SAVE='1', QT_QPA_PLATFORM='offscreen'))
        try:
            deadline = time.monotonic() + 30
            marker = install / 'plugins_user/setup_probe/passed.json'
            while time.monotonic() < deadline:
                assert process.poll() is None, 'Installed program exited during startup'
                content = '\n'.join(p.read_text(encoding='utf-8', errors='replace')
                    for p in (install / 'logs').glob('ddm-*.log'))
                if marker.is_file() and '[方向]' in content:
                    break
                time.sleep(.2)
            assert marker.is_file() and '[方向]' in content, 'Installed program or mobile-share code failed'
            probe = json.loads(marker.read_text())
        finally:
            if process.poll() is None:
                process.kill()  # Only this isolated probe process.
            process.wait(timeout=10)

        obsolete = install / '_internal/obsolete-setup-test.dll'
        obsolete.write_bytes(b'registered old runtime')
        (install / update_install.MANIFEST).write_text(
            json.dumps(initial + ['_internal/obsolete-setup-test.dll']), encoding='utf-8')
        plan = update_install.prepare(update_zip, install, install / f'{DISPLAY_NAME}.exe', expected_version=VERSION)
        try:
            update_install.apply_plan(plan)
            assert not obsolete.exists(), 'Registered obsolete runtime was retained'
            assert all((install / name).read_bytes() == value for name, value in data.items())
        finally:
            update_install.discard_plan(plan, install)

        uninstaller = install / '.ddm-uninstall/unins000.exe'
        assets, saved_assets = install / 'assets', install / 'assets.saved'
        assert assets.resolve().is_relative_to(sandbox) and saved_assets.resolve().is_relative_to(sandbox)
        assets.rename(saved_assets)
        try:
            environment = dict(os.environ, DDM_TEST_LINK=str(assets), DDM_TEST_TARGET=str(unrelated))
            subprocess.run(['powershell', '-NoProfile', '-Command',
                'New-Item -ItemType Junction -Path $env:DDM_TEST_LINK -Target $env:DDM_TEST_TARGET | Out-Null'],
                env=environment, capture_output=True, check=True)
            run_installer(uninstaller, [], logs / 'reject-link.log')
            assert registered() and (install / f'{DISPLAY_NAME}.exe').is_file()
            assert sentinel.read_bytes() == b'outside directory must survive'
        finally:
            if assets.is_junction():
                os.rmdir(assets)  # Remove only the test link, never its target.
            saved_assets.rename(assets)

        assert run_installer(uninstaller, [], logs / 'uninstall.log') == 0
        deadline = time.monotonic() + 10
        while registered() and time.monotonic() < deadline:
            time.sleep(.1)
        assert not registered(), 'Uninstall registry entry was retained'
        for name in files:
            assert not (install / name).exists(), 'Registered program file retained: ' + name
        assert all((install / name).read_bytes() == value for name, value in data.items())
        assert sentinel.read_bytes() == b'outside directory must survive'
        assert (bad / 'personal.txt').read_bytes() == b'not owned by setup'
        report = {'version': VERSION, 'installed_files': len(files),
            'nonempty_directory_rejected': True, 'repair_preserved_data': True,
            'frozen_startup_and_mobile_share': probe, 'update_cleanup_scope': True,
            'junction_uninstall_rejected': True, 'uninstall_preserved_personal_files': len(data),
            'neighbor_directory_preserved': True, 'uninstall_registration_removed': True}
        (logs / 'summary.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False))
        print('PASS: Setup/update/uninstall boundaries; logs:', logs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--setup', type=Path, required=True)
    parser.add_argument('--payload', type=Path, required=True)
    parser.add_argument('--update-zip', type=Path, required=True)
    args = parser.parse_args()
    check(args.setup.resolve(), args.payload.resolve(), args.update_zip.resolve())


if __name__ == '__main__':
    main()
