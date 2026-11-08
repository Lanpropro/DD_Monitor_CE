"""Run real miniature Setup/uninstall/reinstall with retained synthetic data."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dev import build_setup, check_setup_install, selfcheck_setup
from ddm import data_paths

ALIAS = 'DDMonitorCE_RetainedReinstallCheck'


def check(iscc):
    work = ROOT / 'work/setup-reinstall-check'
    work.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='case-', dir=work) as temporary, \
            patch.object(build_setup, 'APP_ID', ALIAS), \
            patch.object(check_setup_install, 'APP_ID', ALIAS):
        assert not check_setup_install.registered()
        sandbox = Path(temporary).resolve()
        payload, output = sandbox / 'payload', sandbox / 'output'
        output.mkdir()
        files = selfcheck_setup.fixture(payload)
        script = build_setup.write_script(payload, sandbox / 'build', output)
        source = script.read_text(encoding='utf-8-sig').replace('Compression=lzma2/fast', 'Compression=none')
        source = source.replace('{localappdata}\\DDMonitorCE\\locations\\',
                                '{app}\\..\\user-home\\locations\\')
        script.write_text(source, encoding='utf-8-sig')
        subprocess.run([str(iscc), str(script)], stdout=subprocess.DEVNULL, check=True)
        setup = output / 'DDMonitorSetup.exe'
        install = sandbox / '中文 原安装目录'
        runner = check_setup_install.run_installer
        try:
            unrelated = sandbox / '其他非空目录'
            unrelated.mkdir()
            note = unrelated / 'personal.txt'
            note.write_bytes(b'not an application directory')
            assert runner(setup, ['/NOICONS', '/TASKS=', '/DIR=' + str(unrelated)], work / 'reject-unrelated.log') != 0
            assert note.read_bytes() == b'not an application directory'
            assert runner(setup, ['/NOICONS', '/TASKS=', '/DIR=' + str(install)], work / 'install.log') == 0
            data = sandbox / '保留的数据'
            data.mkdir()
            location = data_paths.location_file(install, sandbox / 'user-home')
            data_paths._write_location(location, {'root': str(data)})
            preserved = {data / 'config.json': b'synthetic settings',
                         install / 'personal.txt': b'keep user file',
                         install / 'plugins_user/custom/data.bin': b'keep plugin data',
                         install / 'recordings/test.mp4': b'keep recording'}
            for path, value in preserved.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(value)
            uninstaller = install / '.ddm-uninstall/unins000.exe'
            assert runner(uninstaller, [], work / 'uninstall.log') == 0
            deadline = time.monotonic() + 15
            while check_setup_install.registered() and time.monotonic() < deadline:
                time.sleep(.1)
            assert not check_setup_install.registered()
            assert not (install / 'ddm-build.json').exists()
            assert all(path.read_bytes() == value for path, value in preserved.items())
            saved = location.read_bytes()
            location.write_text('{"root":', encoding='utf-8')
            assert runner(setup, ['/NOICONS', '/TASKS=', '/DIR=' + str(install)], work / 'reject-invalid-location.log') != 0
            location.write_bytes(saved)
            collision = install / 'ffmpeg.exe'
            collision.write_bytes(b'unregistered file must survive')
            assert runner(setup, ['/NOICONS', '/TASKS=', '/DIR=' + str(install)], work / 'reject-collision.log') != 0
            assert collision.read_bytes() == b'unregistered file must survive'
            collision.unlink()
            result = runner(setup, ['/NOICONS', '/TASKS=', '/DIR=' + str(install)], work / 'reinstall.log')
            assert result == 0, 'Reinstall after preserving data during uninstall was rejected'
            assert check_setup_install.registered()
            assert all((install / name).read_bytes() == value for name, value in files.items())
            assert all(path.read_bytes() == value for path, value in preserved.items())
            assert location.read_bytes() == saved
            print('PASS: retained-data reinstall, ordinary directory/malformed location/collision rejection, data preservation')
        finally:
            check_setup_install.cleanup_registration(install, work / 'cleanup.log')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--iscc', type=Path, required=True)
    check(parser.parse_args().iscc.resolve())
