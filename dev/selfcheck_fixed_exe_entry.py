"""固定进程名入口与旧更新器所需的兼容入口。"""
import json
from pathlib import Path
import runpy
import sys
import tempfile
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ddm import update_install


def main():
    with tempfile.TemporaryDirectory(prefix='ddm-fixed-entry-') as temporary:
        root = Path(temporary)
        fixed = root / 'DD监控室CE.exe'
        fixed.write_bytes(b'test')
        alias = root / 'DD监控室CE-v0.3.1.exe'
        alias.write_bytes(b'test')
        for arguments in ([], ['--apply-update', 'plan.json']):
            with patch.object(sys, 'frozen', True, create=True), \
                    patch.object(sys, 'executable', str(alias)), \
                    patch.object(sys, 'argv', [str(alias), *arguments]), \
                    patch('subprocess.Popen') as launch, patch('subprocess.call', return_value=0) as helper:
                try:
                    runpy.run_path(str(ROOT / 'main.py'), run_name='__main__')
                except SystemExit as result:
                    assert result.code == 0
                if arguments:
                    helper.assert_called_once_with([str(fixed), *arguments], cwd=root)
                    launch.assert_not_called()
                else:
                    launch.assert_called_once_with([str(fixed)], cwd=root)
                    helper.assert_not_called()
        archive = root / 'update.zip'
        with zipfile.ZipFile(archive, 'w') as package:
            for name, data in {'DD监控室CE.exe': b'fixed', alias.name: b'compatibility',
                               '_internal/runtime.dll': b'test', 'ddm-build.json': json.dumps({
                                   'version': '0.3.1', 'update_protocol': 1, 'platform': 'windows-x64'})}.items():
                package.writestr('app/' + name, data)
        plan = update_install.prepare(archive, root, alias, expected_version='0.3.1')
        assert json.loads(Path(plan).read_text(encoding='utf-8'))['new_exe'] == fixed.name
        update_install.discard_plan(plan, root)
    print('PASS: fixed EXE entry, compatibility forwarding and fixed-name update installation')


if __name__ == '__main__':
    main()
