"""独立于 Qt/VLC 的本体更新助手：暂存、等待退出、替换和失败回滚。"""
import ctypes
import filecmp
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile

from .data_paths import INSTALL_MARKER
from .update_version import installed_revision, revision, update_key

MANIFEST = '.ddm-program-files.json'
RESULT = '.ddm-update-result.json'
PROTECTED = {'utils', 'cache', 'logs', 'plugins_user', 'recordings', 'results', 'work'}


def relative_path(name):
    path = PurePosixPath(name)
    if (not name or '\\' in name or ':' in name or path.is_absolute()
            or any(part in ('', '.', '..') for part in name.split('/'))
            or path.parts[0].casefold() in PROTECTED or name in (MANIFEST, RESULT, 'update-plan.json')
            or path.parts[0].casefold() == 'backup' or name.casefold() == INSTALL_MARKER):
        raise ValueError('更新包包含用户数据目录或无效路径')
    return path


def destination(root, name):
    path = root.joinpath(*relative_path(name).parts)
    for parent in (path, *path.parents):
        if parent == root:
            break
        if parent.is_symlink():
            raise ValueError('更新目标不能包含链接目录')
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('更新路径超出程序目录')
    return path


def prepare(archive, install_root, current_exe, cancelled=lambda: False, expected_version=None, data_root=None,
            expected_revision=None):
    root = Path(install_root).resolve()
    old_exe = Path(current_exe).resolve()
    if root == Path(root.anchor) or old_exe.parent != root or not old_exe.is_file():
        raise ValueError('只能更新当前程序所在目录')
    stage = Path(tempfile.mkdtemp(prefix='ddm-app-update-'))
    try:
        with zipfile.ZipFile(archive) as package:
            files = [item for item in package.infolist() if not item.is_dir()]
            size = sum(item.file_size for item in files)
            if not files or len(files) > 50000 or size > 2 * 1024 ** 3:
                raise ValueError('更新包为空或超过限制')
            if shutil.disk_usage(root).free < size * 2 or shutil.disk_usage(stage).free < size * 2:
                raise ValueError('磁盘空间不足以暂存更新和备份')
            paths, seen, top = [], set(), None
            for item in files:
                if cancelled():
                    raise InterruptedError('更新准备已取消')
                full = relative_path(item.filename)
                if len(full.parts) < 2 or (item.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError('更新包必须是单一程序目录，不能包含链接')
                top = top or full.parts[0]
                if full.parts[0] != top:
                    raise ValueError('更新包包含多个程序目录')
                name = '/'.join(full.parts[1:])
                relative_path(name)
                if name.casefold() in seen:
                    raise ValueError('更新包包含重复文件')
                seen.add(name.casefold())
                destination(root, name)
                target = destination(stage, name)
                target.parent.mkdir(parents=True, exist_ok=True)
                with package.open(item) as source, target.open('wb') as output:
                    shutil.copyfileobj(source, output)
                paths.append(name)
        fixed = 'DD监控室CE.exe'
        executables = ([fixed] if fixed in paths else [name for name in paths if '/' not in name
                       and name.startswith('DD监控室CE-v') and name.endswith('.exe')])
        if len(executables) != 1 or not (stage / '_internal').is_dir():
            raise ValueError('此安装包不是 Windows EXE 便携版')
        build = json.loads((stage / 'ddm-build.json').read_text(encoding='utf-8-sig'))
        if build.get('update_protocol') != 1 or build.get('platform') != 'windows-x64':
            raise ValueError('更新包不支持当前更新协议')
        if expected_version and (build.get('version') != expected_version
                                 or executables[0] not in (fixed, f'DD监控室CE-v{expected_version}.exe')):
            raise ValueError('更新包版本与发布记录不一致')
        if expected_revision is not None and revision(build.get('revision', 0)) != revision(expected_revision):
            raise ValueError('更新包修订号与发布记录不一致')
        plan = {'root': str(root), 'stage': str(stage), 'files': paths,
                'old_exe': old_exe.name, 'new_exe': executables[0], 'parent_pid': os.getpid()}
        from .data_paths import writable
        plan['elevate'] = os.name == 'nt' and not writable(root)
        plan['result_root'] = str(Path(data_root or root).resolve())
        path = stage / 'update-plan.json'
        path.write_text(json.dumps(plan, ensure_ascii=False), encoding='utf-8')
        return str(path)
    except BaseException:
        shutil.rmtree(stage)
        raise


def wait_parent(pid, timeout=120):
    if pid == os.getpid() or pid <= 0:
        raise ValueError('更新助手不能等待自身')
    if os.name == 'nt':
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        handle = kernel.OpenProcess(0x100000, False, pid)
        if not handle:
            if ctypes.get_last_error() == 87:
                return
            raise OSError('无法等待主程序退出')
        try:
            if kernel.WaitForSingleObject(ctypes.c_void_p(handle), int(timeout * 1000)) != 0:
                raise TimeoutError('主程序仍在退出，更新未执行')
        finally:
            kernel.CloseHandle(ctypes.c_void_p(handle))
    else:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.1)
        raise TimeoutError('主程序仍在退出，更新未执行')


def retry_file_operation(operation, timeout=5):
    """Only retry Windows access/sharing errors, with a fixed deadline."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            return operation()
        except OSError as error:
            if getattr(error, 'winerror', None) not in (5, 32, 33) or time.monotonic() >= deadline:
                raise
            time.sleep(.2)


def check_replaceable(path):
    """Open an existing target without changing it; directory probes are insufficient."""
    if os.name != 'nt':
        return
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateFileW.argtypes = [ctypes.c_wchar_p, ctypes.c_ulong, ctypes.c_ulong,
                                  ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_void_p]
    kernel.CreateFileW.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    # GENERIC_WRITE | DELETE, share read/write/delete, OPEN_EXISTING. Never truncate.
    handle = kernel.CreateFileW(str(path), 0x40010000, 7, None, 3, 0x80, None)
    if handle == ctypes.c_void_p(-1).value:
        code = ctypes.get_last_error()
        if code in (2, 3):
            return
        error = ctypes.WinError(code)
        error.filename = str(path)
        raise error
    kernel.CloseHandle(handle)


def apply_plan(plan_path):
    """调用者已等待主进程退出；只更新记录中的程序文件，保留其他文件。"""
    plan = json.loads(Path(plan_path).read_text(encoding='utf-8'))
    root, stage = Path(plan['root']).resolve(), Path(plan['stage']).resolve()
    if (root == Path(root.anchor) or root == stage or root.is_relative_to(stage)
            or Path(plan_path).resolve().parent != stage):
        raise ValueError('更新目录无效')
    files = list(plan['files'])
    for name in files:
        destination(root, name)
        if not destination(stage, name).is_file():
            raise ValueError('暂存程序文件缺失')
    old_exe, new_exe = plan['old_exe'], plan['new_exe']
    if '/' in old_exe or '/' in new_exe or new_exe not in files:
        raise ValueError('程序入口无效')
    previous = []
    manifest = root / MANIFEST
    if manifest.is_file():
        previous = json.loads(manifest.read_text(encoding='utf-8'))
        for name in previous:
            destination(root, name)
    obsolete = set(previous + [old_exe]) - set(files)
    changed = []
    for name in files:
        target = destination(root, name)
        if not target.is_file() or not filecmp.cmp(destination(stage, name), target, shallow=False):
            changed.append(name)
    # This also protects old plans whose parent did not wait for its settings worker.
    for name in changed + sorted(obsolete) + [MANIFEST]:
        target = destination(root, name) if name != MANIFEST else manifest
        retry_file_operation(lambda: check_replaceable(target))
    backup = stage / 'backup'
    backup.mkdir(exist_ok=True)
    replaced, saved = [], set()
    manifest_before = manifest.read_bytes() if manifest.is_file() else None
    try:
        for name in changed + sorted(obsolete):
            target = destination(root, name)
            if target.is_file():
                copy = destination(backup, name)
                copy.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, copy)
                saved.add(name)
            if name in obsolete:
                if target.exists():
                    retry_file_operation(target.unlink)
                    replaced.append(name)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(prefix='.ddm-new-', dir=target.parent)
            os.close(descriptor)
            temporary = Path(temporary_name)
            try:
                shutil.copy2(destination(stage, name), temporary)
                retry_file_operation(lambda: os.replace(temporary, target))
                replaced.append(name)
            finally:
                temporary.unlink(missing_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(prefix='.ddm-manifest-', dir=root)
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            temporary.write_text(json.dumps(files, ensure_ascii=False), encoding='utf-8')
            retry_file_operation(lambda: os.replace(temporary, manifest))
        finally:
            temporary.unlink(missing_ok=True)
    except BaseException:
        for name in reversed(replaced):
            target = destination(root, name)
            if name in saved:
                retry_file_operation(lambda: shutil.copy2(destination(backup, name), target))
            else:
                target.unlink(missing_ok=True)
        if manifest_before is None:
            manifest.unlink(missing_ok=True)
        else:
            manifest.write_bytes(manifest_before)
        raise
    return str(root / new_exe)


def run_helper(plan_path):
    plan = json.loads(Path(plan_path).read_text(encoding='utf-8'))
    root = Path(plan['root']).resolve()
    entry = str(destination(root, plan['old_exe']))
    started_at = time.time()
    phase = 'wait-parent'
    try:
        wait_parent(int(plan['parent_pid']))
        phase = 'replace-program-files'
        if plan.get('elevate'):
            from .windows_elevation import run_elevated
            run_elevated(sys.executable, ['--apply-update-elevated', str(plan_path)], plan['stage'])
            elevated = json.loads((Path(plan['stage']) / 'elevated-result.json').read_text(encoding='utf-8'))
            if not elevated['ok']:
                error = OSError(elevated['message'])
                error.winerror = elevated.get('winerror')
                raise error
            entry = str(destination(root, plan['new_exe']))
        else:
            entry = apply_plan(plan_path)
        result = {'ok': True, 'message': '软件更新完成', 'stage': plan['stage'],
                  'root': str(root), 'helper_pid': os.getpid()}
    except Exception as error:
        hint = '请完全退出软件（包括托盘和设置进程），并检查目标文件的只读属性和访问权限。'
        result = {'ok': False, 'message': f'软件更新未完成：{error}\n{hint}', 'stage': plan['stage'],
                  'phase': phase, 'winerror': getattr(error, 'winerror', None),
                  'root': str(root), 'helper_pid': os.getpid()}
    result.update(started_at=started_at, completed_at=time.time())
    try:
        build = json.loads((Path(plan['stage']) / 'ddm-build.json').read_text(encoding='utf-8-sig'))
        result.update(target_version=build['version'], target_revision=revision(build.get('revision', 0)))
    except (OSError, ValueError, KeyError, TypeError):
        pass
    (Path(plan.get('result_root', root)) / RESULT).write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    if Path(entry).is_file():
        subprocess.Popen([entry], cwd=root)
    return 0 if result['ok'] else 1


def result_message(install_root, result_root, current_version):
    """Keep failure evidence on disk, but do not show a superseded install failure."""
    try:
        result = json.loads((Path(result_root) / RESULT).read_text(encoding='utf-8'))
        if result.get('ok') is False:
            # Legacy failures have no target identity and cannot describe this new build.
            if 'target_version' not in result:
                return ''
            current = update_key(current_version, installed_revision(install_root, current_version))
            target = update_key(result['target_version'], result.get('target_revision', 0))
            if current >= target:
                return ''
        return result['message']
    except (OSError, ValueError, KeyError, TypeError):
        return ''


def run_elevated_helper(plan_path):
    """Only replace program files; the unelevated helper restarts the application."""
    stage = Path(plan_path).resolve().parent
    try:
        apply_plan(plan_path)
        result = {'ok': True, 'message': ''}
    except Exception as error:
        result = {'ok': False, 'message': str(error), 'winerror': getattr(error, 'winerror', None)}
    (stage / 'elevated-result.json').write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    return 0 if result['ok'] else 1


def clean_previous(install_root, result_root=None):
    """启动后清理已完成助手的临时副本；仍占用时保留到下一次启动。"""
    root = Path(install_root).resolve()
    result_path = Path(result_root or root) / RESULT
    if not result_path.is_file():
        return
    try:
        result = json.loads(result_path.read_text(encoding='utf-8'))
        stage = Path(result.get('stage', '')).resolve()
        if (stage.parent != Path(tempfile.gettempdir()).resolve()
                or not stage.name.startswith('ddm-app-update-') or stage.is_symlink()
                or Path(result.get('root', '')).resolve() != root):
            return
        pid = int(result.get('helper_pid', 0))
        if os.name == 'nt' and pid > 0:
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            kernel.OpenProcess.restype = ctypes.c_void_p
            handle = kernel.OpenProcess(0x100000, False, pid)
            if handle:
                try:
                    if kernel.WaitForSingleObject(ctypes.c_void_p(handle), 0) != 0:
                        return
                finally:
                    kernel.CloseHandle(ctypes.c_void_p(handle))
        if stage.is_dir():
            shutil.rmtree(stage)
        result.pop('stage', None)
        result.pop('helper_pid', None)
        result_path.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    except (OSError, ValueError, KeyError):
        pass


def discard_plan(plan_path, install_root):
    """取消安装时只清理本次生成、且归属当前程序的暂存目录。"""
    try:
        path = Path(plan_path).resolve()
        stage = path.parent
        if stage.parent != Path(tempfile.gettempdir()).resolve() or not stage.name.startswith('ddm-app-update-'):
            return
        plan = json.loads(path.read_text(encoding='utf-8'))
        if Path(plan['stage']).resolve() == stage and Path(plan['root']).resolve() == Path(install_root).resolve():
            shutil.rmtree(stage)
    except (OSError, ValueError, KeyError):
        pass
