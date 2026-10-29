"""Check installer write permissions using disposable directories and an isolated AppId."""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dev import build_setup, check_setup_install, selfcheck_setup
from ddm.version import DISPLAY_NAME
from ddm import config, data_paths


def check(iscc):
    if sys.platform != 'win32':
        raise RuntimeError('This check requires Windows')
    work = ROOT / 'work/setup-permissions-check'
    work.mkdir(exist_ok=True)
    invalid_picker = subprocess.run([str(ROOT / 'work/setup-native/DDMonitorInstallerHelper.exe'),
                                     '--pick-folder', 'E:\\'], timeout=5)
    assert invalid_picker.returncode == 2, 'Invalid picker arguments must not launch the uninstaller'
    with patch.object(check_setup_install, 'APP_ID', 'DDMonitorCE_PermissionsCheck'):
        if check_setup_install.registered():
            raise RuntimeError('An existing permissions-check installation is registered')
        with tempfile.TemporaryDirectory(prefix='permissions-', dir=work) as temporary:
            sandbox = Path(temporary).resolve()
            assert sandbox.is_relative_to(work.resolve())
            payload = sandbox / 'payload'
            selfcheck_setup.fixture(payload)
            denied = sandbox / 'restricted'
            denied.mkdir()
            sentinel = denied / 'keep.txt'
            sentinel.write_bytes(b'keep this existing file')
            before = sorted(denied.iterdir())
            # Deny only file/directory creation inside this synthetic directory.
            subprocess.run(['icacls', str(denied), '/deny', '*S-1-1-0:(WD,AD)'],
                           check=True, capture_output=True)
            try:
                for skip_directory_page in (False, True):
                    case = sandbox / str(skip_directory_page)
                    with patch.object(build_setup, 'APP_ID', check_setup_install.APP_ID):
                        script = build_setup.write_script(payload, case / 'build', case)
                    source = script.read_text(encoding='utf-8-sig')
                    source = source.replace('if CurPageID <> wpSelectDir then Exit;',
                                            "if CurPageID <> wpSelectDir then Exit;\n  Log('DDM_DIR_PAGE');")
                    if skip_directory_page:
                        source = source.replace('DisableDirPage=no', 'DisableDirPage=yes')
                    script.write_text(source, encoding='utf-8-sig')
                    subprocess.run([str(iscc), str(script)], check=True, stdout=subprocess.DEVNULL)
                    for destination in (denied, denied / 'missing/安装目录'):
                        log = case / ('missing.log' if destination != denied else 'existing.log')
                        result = check_setup_install.run_installer(case / 'DDMonitorSetup.exe',
                            ['/NOICONS', '/TASKS=', '/DIR=' + str(destination)], log)
                        assert result != 0
                        assert not check_setup_install.registered()
                        assert '无法写入所选安装位置' in log.read_text(encoding='utf-8-sig')
                        assert sorted(denied.iterdir()) == before
                        assert sentinel.read_bytes() == b'keep this existing file'
                    print(f'PASS: unwritable existing/new path rejected; skipped page={skip_directory_page}')
            finally:
                subprocess.run(['icacls', str(denied), '/remove:d', '*S-1-1-0'],
                               check=True, capture_output=True)

            # Names such as Program Files must not be blacklisted if the path is writable.
            parent = sandbox / '可写 Program Files'
            parent.mkdir()
            install = parent / '新目录/DDMonitorCE'
            setup = sandbox / 'False/DDMonitorSetup.exe'
            result = check_setup_install.run_installer(setup,
                ['/NOICONS', '/TASKS=', '/DIR=' + str(install)], sandbox / 'install.log')
            try:
                assert result == 0 and check_setup_install.registered(), (sandbox / 'install.log').read_text(encoding='utf-8-sig')
                assert (install / f'{DISPLAY_NAME}.exe').read_bytes() == b'program'
                assert sorted(path.name for path in parent.iterdir()) == ['新目录']
                assert not list(install.glob('ddm*.tmp'))
                assert (install / data_paths.INSTALL_MARKER).is_file()
                repair_log = sandbox / 'repair.log'
                assert check_setup_install.run_installer(setup,
                    ['/NOICONS', '/TASKS=', '/DIR=' + str(install)], repair_log) == 0
                assert 'DDM_DIR_PAGE' in repair_log.read_text(encoding='utf-8-sig'), 'Repeat install skipped the directory page'
                subprocess.run(['icacls', str(install), '/deny', '*S-1-1-0:(WD,AD)'],
                               check=True, capture_output=True)
                try:
                    with patch.object(config, 'REPO', str(install)), patch.object(config, 'DATA_ROOT', None), patch.object(config, 'CONFIG_PATH', ''), patch.object(config, 'DATA_MIGRATION_ERROR', ''), patch.object(data_paths, 'user_home', return_value=sandbox / 'user-home'), patch.dict('os.environ', {'DDM_NO_SAVE': ''}):
                        config.initialize_paths()
                        config.save({'version': 1, 'settings': {'default_volume': 37}})
                        assert config.load()['settings']['default_volume'] == 37
                        assert Path(config.data_root()).is_relative_to(sandbox / 'user-home')
                        assert not (install / 'utils').exists()
                finally:
                    subprocess.run(['icacls', str(install), '/remove:d', '*S-1-1-0'],
                                   check=True, capture_output=True)
            finally:
                check_setup_install.cleanup_registration(install, sandbox / 'uninstall.log')
                deadline = time.monotonic() + 15
                while (check_setup_install.registered() or
                       (install / '.ddm-uninstall/unins000.exe').exists()) and time.monotonic() < deadline:
                    time.sleep(.1)
                assert not check_setup_install.registered()
            print('PASS: repeat-install directory page, install marker, configuration save with read-only program root, uninstall and no probe leftovers')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iscc', type=Path, required=True)
    check(parser.parse_args().iscc.resolve())
