"""本体更新解压、用户数据保护、过期文件清理和失败回滚。"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ddm import update_install as updater


def package(path, version='0.3.1', extra=None):
    prefix = 'DD监控室CE-v' + version + '-exe/'
    files = {'DD监控室CE-v' + version + '.exe': b'new-executable',
             '_internal/runtime.dll': b'new-runtime', 'assets/logo.txt': b'new-logo',
             'ddm-build.json': json.dumps({'version': version, 'update_protocol': 1,
                                          'platform': 'windows-x64'}).encode()}
    files.update(extra or {})
    with zipfile.ZipFile(path, 'w') as archive:
        for name, data in files.items():
            archive.writestr(prefix + name, data)


def main():
    stages = []
    with tempfile.TemporaryDirectory(prefix='ddm-update-test with spaces-') as temporary:
        root = Path(temporary)
        install = root / '软件目录'
        install.mkdir()
        old = install / 'DD监控室CE-v0.3.exe'
        old.write_bytes(b'old-executable')
        (install / '_internal').mkdir()
        (install / '_internal' / 'runtime.dll').write_bytes(b'old-runtime')
        (install / '_internal' / 'obsolete.dll').write_bytes(b'obsolete')
        (install / updater.MANIFEST).write_text(json.dumps([
            old.name, '_internal/runtime.dll', '_internal/obsolete.dll']))
        preserved = {'utils/config.json': b'folders/settings', 'utils/accounts/session.bin': b'login',
                     'plugins_user/custom/plugin.py': b'custom-plugin', 'plugins_user/custom/data.bin': b'plugin-data',
                     'recordings/recording.mp4': b'recording', 'cache/custom.txt': b'cache'}
        for name, data in preserved.items():
            path = install / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        archive = root / 'update.zip'
        package(archive)
        plan_path = updater.prepare(archive, install, old, expected_version='0.3.1')
        stage = Path(plan_path).parent
        stages.append(stage)
        before = {path.relative_to(install).as_posix(): path.read_bytes() for path in install.rglob('*') if path.is_file()}
        replace = os.replace
        def fail_runtime(source, target):
            if str(target).endswith('runtime.dll'):
                raise OSError('simulated file lock')
            return replace(source, target)
        with patch.object(updater.os, 'replace', side_effect=fail_runtime):
            try:
                updater.apply_plan(plan_path)
                raise AssertionError('must fail')
            except OSError:
                pass
        after = {path.relative_to(install).as_posix(): path.read_bytes() for path in install.rglob('*') if path.is_file()}
        assert before == after, 'partial replacement must restore all program and user files'
        entry = updater.apply_plan(plan_path)
        assert Path(entry).read_bytes() == b'new-executable'
        assert not old.exists() and not (install / '_internal' / 'obsolete.dll').exists()
        assert (install / '_internal' / 'runtime.dll').read_bytes() == b'new-runtime'
        for name, data in preserved.items():
            assert (install / name).read_bytes() == data
        cancelled_plan = updater.prepare(archive, install, entry, expected_version='0.3.1')
        updater.discard_plan(cancelled_plan, install)
        assert not Path(cancelled_plan).parent.exists()
        # 第二轮更新从持久化程序清单判断旧文件，不删除第三方或用户文件。
        package(archive, '0.3.2')
        next_plan = updater.prepare(archive, install, entry, expected_version='0.3.2')
        stages.append(Path(next_plan).parent)
        next_entry = updater.apply_plan(next_plan)
        assert Path(next_entry).is_file() and not Path(entry).exists()
        for name, data in preserved.items():
            assert (install / name).read_bytes() == data
        for extra in ({'utils/config.json': b'bad'}, {'../../escaped.txt': b'bad'}, {'plugins_user/custom/plugin.py': b'bad'}):
            package(archive, extra=extra)
            try:
                updater.prepare(archive, install, next_entry)
                raise AssertionError('unsafe update must be refused')
            except ValueError:
                pass
        package(archive)
        try:
            updater.prepare(archive, install, next_entry, expected_version='9.0')
            raise AssertionError('wrong build version must be refused')
        except ValueError:
            pass
        # 助手等待确切的父 PID，实际检查 Windows 进程句柄。
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(0.2)'])
        updater.wait_parent(child.pid, timeout=5)
        child.wait(timeout=5)
        plan = json.loads(Path(next_plan).read_text(encoding='utf-8'))
        plan['parent_pid'] = child.pid
        Path(next_plan).write_text(json.dumps(plan), encoding='utf-8')
        with patch.object(updater.subprocess, 'Popen') as launch:
            assert updater.run_helper(next_plan) == 0
            launch.assert_called_once_with([next_entry], cwd=install.resolve())
        result = json.loads((install / updater.RESULT).read_text(encoding='utf-8'))
        assert result['ok']
        updater.clean_previous(install)
        assert Path(next_plan).parent.exists(), 'running helper must not have its runtime removed'
        result['helper_pid'] = child.pid
        (install / updater.RESULT).write_text(json.dumps(result), encoding='utf-8')
        updater.clean_previous(install)
        assert not Path(next_plan).parent.exists()
        # 实际从 main.py 进入助手，损坏计划也写出结果；不初始化 Qt/VLC。
        bootstrap_stage = root / 'bootstrap'
        bootstrap_stage.mkdir()
        bootstrap = bootstrap_stage / 'update-plan.json'
        bootstrap.write_text(json.dumps({'root': str(install), 'stage': str(bootstrap_stage),
            'parent_pid': child.pid, 'old_exe': 'missing.exe', 'new_exe': 'new.exe', 'files': ['missing.dll']}), encoding='utf-8')
        environment = dict(os.environ, PYTHON_VLC_LIB_PATH='definitely-missing-vlc.dll')
        helper = subprocess.run([sys.executable, 'main.py', '--apply-update', str(bootstrap)],
                                capture_output=True, env=environment, timeout=10)
        assert helper.returncode == 1
        assert not json.loads((install / updater.RESULT).read_text(encoding='utf-8'))['ok']
    for stage in stages:
        if stage.exists():
            shutil.rmtree(stage)
    print('PASS: EXE update staging, build protocol, user data, rollback, managed files, PID wait and helper restart')


if __name__ == '__main__':
    main()
