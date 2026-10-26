"""Exercise generated personal-data cleanup in a disposable miniature install."""
import argparse
import ctypes
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from dev import build_setup, check_setup_install, selfcheck_setup

alias = 'DDMonitorCE_DataCleanupCheck'


def check(iscc):
    extract = ctypes.windll.shell32.ExtractIconExW
    extract.argtypes = [ctypes.c_wchar_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
    extract.restype = ctypes.c_uint
    assert extract(str(root / 'work/setup-native/DDMonitorInstallerHelper.exe'), -1, None, None, 0) > 0
    print('PASS: native uninstall entry contains an icon resource', flush=True)
    with patch.object(check_setup_install, 'APP_ID', alias):
        assert not check_setup_install.registered()
        work = root / 'work/setup-data-cleanup-check'
        work.mkdir(exist_ok=True)
        payload = work / 'fixture'
        if not payload.exists(): selfcheck_setup.fixture(payload)

        for clean, linked in ((False, False), (True, False), (True, True)):
            case = work / ('clean' + str(clean) + '-link' + str(linked))
            case.mkdir(exist_ok=True)
            with patch.object(build_setup, 'APP_ID', alias):
                script = build_setup.write_script(payload, case / 'build', case)
            source = script.read_text(encoding='utf-8-sig').replace('Compression=lzma2/fast', 'Compression=none')
            if clean:
                source = source.replace('if UninstallSilent then Exit;',
                    'if UninstallSilent then begin RemovePersonalData := True; Exit; end;')
            script.write_text(source, encoding='utf-8-sig')
            subprocess.run([str(iscc), str(script)],
                stdout=subprocess.DEVNULL, check=True)
            with tempfile.TemporaryDirectory(prefix='data-cleanup-',dir=work) as temporary:
                sandbox = Path(temporary).resolve()
                assert sandbox.is_relative_to(work.resolve())
                install = sandbox / 'installed'
                runner = check_setup_install.run_installer
                assert runner(case / 'DDMonitorSetup.exe', ['/NOICONS', '/DIR=' + str(install)],case / 'install.log') == 0
                try:
                    data = {name:b'known data' for name in build_setup.PERSONAL_FILES}
                    extra = {'recordings/test.mp4':b'recording', 'personal.txt':b'extra',
                        'utils/personal.txt':b'keep', 'utils/accounts/personal.bin':b'keep',
                        'utils/skins/own.png':b'keep', 'plugins_user/custom/own.txt':b'keep',
                        'plugins_user/custom/plugin.json':b'unknown manifest',
                        'logs/ddm-2026-10-23.log':b'unknown log source',
                        'cache/avatars/0123456789abcdef0123456789abcdef.png':b'unknown cache source',
                        'utils/skins/0123456789abcdef0123456789abcdef_own.png':b'unknown skin source',
                        '_internal/personal.bin':b'keep', 'assets/personal.txt':b'keep',
                        'setup-license/personal.txt':b'keep', '.ddm-uninstall/personal.txt':b'keep'}
                    for name, content in (data | extra).items():
                        path = install / name
                        path.parent.mkdir(parents=True,exist_ok=True)
                        path.write_bytes(content)
                    saved = install / 'utils-saved'
                    if linked:
                        (install / 'utils').rename(saved)
                        env = dict(os.environ, DDM_LINK=str(install / 'utils'), DDM_TARGET=str(saved))
                        subprocess.run(['powershell','-NoProfile','-Command',
                            'New-Item -ItemType Junction -Path $env:DDM_LINK -Target $env:DDM_TARGET | Out-Null'],
                            env=env,check=True,capture_output=True)
                    launcher = install / 'DDMonitorUninstall.exe'
                    assert runner(launcher, [], case / 'uninstall.log') == 0
                    deadline=time.monotonic()+15
                    while (check_setup_install.registered() or
                           (install/'.ddm-uninstall/unins000.exe').exists()) and time.monotonic()<deadline:
                        time.sleep(.1)
                    assert not check_setup_install.registered()
                    if linked:
                        assert (install/'utils').is_junction()
                        os.rmdir(install/'utils')  # Remove only our own test junction.
                        saved.rename(install/'utils')
                    for name, value in data.items():
                        if clean and not linked: assert not (install/name).exists(),name
                        else: assert (install/name).read_bytes()==value,name
                    for name,value in extra.items(): assert (install/name).read_bytes()==value,name
                    assert not launcher.exists(), 'Native launcher was retained during uninstall'
                    print('PASS', {'clean':clean,'linked':linked,'preserved_extra':len(extra)},flush=True)
                finally:
                    check_setup_install.cleanup_registration(install, case/'cleanup.log')
                    link = install / 'utils'
                    if link.is_junction():
                        os.rmdir(link)
                        saved.rename(link)
        print('PASS: default preserve, explicit clean, native launcher, linked data protection')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iscc', type=Path, required=True)
    args = parser.parse_args()
    check(args.iscc.resolve())
