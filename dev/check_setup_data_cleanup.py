"""Exercise generated personal-data cleanup in a disposable miniature install."""
import argparse
import ctypes
import os
import json
import zipfile
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from dev import build_setup, check_setup_install, selfcheck_setup
from ddm import data_paths
from ddm.plugins import PluginManager, PLUGIN_INVENTORY

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

        for clean, linked, external, broken in ((False, False, False, False), (True, False, False, False),
                (True, True, False, False), (False, False, True, False), (True, False, True, False),
                (True, True, True, False), (True, False, True, True)):
            case = work / ('clean' + str(clean) + '-link' + str(linked) + '-external' + str(external) + '-broken' + str(broken))
            case.mkdir(exist_ok=True)
            with patch.object(build_setup, 'APP_ID', alias):
                script = build_setup.write_script(payload, case / 'build', case)
            source = script.read_text(encoding='utf-8-sig').replace('Compression=lzma2/fast', 'Compression=none')
            source = source.replace('{localappdata}\\DDMonitorCE\\locations\\',
                                    '{app}\\..\\user-home\\locations\\')
            if clean:
                source = source.replace('if UninstallSilent then Exit;',
                    'if UninstallSilent then begin RemovePersonalData := True; Exit; end;')
            script.write_text(source, encoding='utf-8-sig')
            subprocess.run([str(iscc), str(script)],
                stdout=subprocess.DEVNULL, check=True)
            with tempfile.TemporaryDirectory(prefix='data-cleanup-',dir=work) as temporary:
                sandbox = Path(temporary).resolve()
                assert sandbox.is_relative_to(work.resolve())
                install = sandbox / '中文 安装目录'
                data_root = sandbox / '用户 数据目录' if external else install
                runner = check_setup_install.run_installer
                assert runner(case / 'DDMonitorSetup.exe', ['/NOICONS', '/DIR=' + str(install)],case / 'install.log') == 0
                try:
                    if external:
                        location = data_paths.location_file(install, sandbox / 'user-home')
                        location.parent.mkdir(parents=True)
                        data_paths._write_location(location, {'root': str(data_root)})
                        if broken:
                            location.write_text(location.read_text(encoding='utf-8').replace('"}', '\\q"}'), encoding='utf-8')
                        legacy = install / 'utils/config.json'
                        legacy.parent.mkdir()
                        legacy.write_bytes(b'old copied configuration must remain')
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
                        path = data_root / name
                        path.parent.mkdir(parents=True,exist_ok=True)
                        path.write_bytes(content)
                    archive = sandbox / 'plugin.zip'
                    plugin_files = {'plugin.py': b'fixture plugin',
                        'plugin.json': json.dumps({'id': 'registered', 'name': 'fixture',
                            'description': 'test', 'version': '1.0'}).encode(),
                        'assets/按钮.txt': b'packaged asset'}
                    with zipfile.ZipFile(archive, 'w') as package:
                        for name, content in plugin_files.items():
                            package.writestr('registered/' + name, content)
                    plugin_root = data_root / 'plugins_user'
                    PluginManager(plugins_dir=str(plugin_root)).install_zip(str(archive))
                    plugin_folder = plugin_root / 'registered'
                    notes = plugin_folder / 'user-notes.txt'
                    notes.write_bytes(b'unknown user file')
                    recording = plugin_folder / 'recordings/session.mp4'
                    recording.parent.mkdir()
                    recording.write_bytes(b'user recording')
                    legacy_plugin = plugin_root / 'legacy'
                    legacy_plugin.mkdir()
                    (legacy_plugin / 'plugin.py').write_bytes(b'legacy plugin')
                    (legacy_plugin / 'plugin.json').write_bytes(b'legacy manifest')
                    (legacy_plugin / 'unknown.txt').write_bytes(b'unknown legacy asset')
                    pending_root = plugin_root / '.updates'
                    PluginManager(plugins_dir=str(pending_root)).install_zip(str(archive))
                    pending_folder = pending_root / 'registered'
                    backup_folder = pending_root / 'registered.backup'
                    shutil.copytree(pending_folder, backup_folder)
                    unsafe_plugin = plugin_root / 'unsafe_record'
                    unsafe_plugin.mkdir()
                    (unsafe_plugin / 'plugin.py').write_bytes(b'preserve invalid inventory')
                    (unsafe_plugin / PLUGIN_INVENTORY).write_text('../outside.txt\n', encoding='utf-8-sig')
                    outside = plugin_root / 'outside.txt'
                    outside.write_bytes(b'outside must survive')
                    saved = data_root / 'utils-saved'
                    if linked:
                        (data_root / 'utils').rename(saved)
                        env = dict(os.environ, DDM_LINK=str(data_root / 'utils'), DDM_TARGET=str(saved))
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
                        assert (data_root/'utils').is_junction()
                        os.rmdir(data_root/'utils')  # Remove only our own test junction.
                        saved.rename(data_root/'utils')
                    for name, value in data.items():
                        if clean and not linked and not broken: assert not (data_root/name).exists(),name
                        else: assert (data_root/name).read_bytes()==value,name
                    for name,value in extra.items(): assert (data_root/name).read_bytes()==value,name
                    removed = clean and not linked and not broken
                    for folder in (plugin_folder, pending_folder, backup_folder):
                        for name, value in plugin_files.items():
                            if removed: assert not (folder/name).exists(), str(folder/name)
                            else: assert (folder/name).read_bytes() == value
                        assert (folder/PLUGIN_INVENTORY).exists() is not removed
                    assert notes.read_bytes() == b'unknown user file'
                    assert recording.read_bytes() == b'user recording'
                    assert (legacy_plugin/'plugin.py').exists() is not removed
                    assert (legacy_plugin/'plugin.json').exists() is not removed
                    assert (legacy_plugin/'unknown.txt').read_bytes() == b'unknown legacy asset'
                    assert outside.read_bytes() == b'outside must survive'
                    assert (unsafe_plugin/'plugin.py').read_bytes() == b'preserve invalid inventory'
                    if external:
                        assert legacy.read_bytes() == b'old copied configuration must remain'
                    assert not launcher.exists(), 'Native launcher was retained during uninstall'
                    print('PASS', {'clean':clean,'linked':linked,'external':external,'broken':broken,'preserved_extra':len(extra)},flush=True)
                finally:
                    check_setup_install.cleanup_registration(install, case/'cleanup.log')
                    link = data_root / 'utils'
                    if link.is_junction():
                        os.rmdir(link)
                        saved.rename(link)
        print('PASS: default preserve, explicit clean, native launcher, linked data protection')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--iscc', type=Path, required=True)
    args = parser.parse_args()
    check(args.iscc.resolve())
