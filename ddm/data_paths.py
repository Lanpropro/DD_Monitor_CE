"""Program-independent user data locations and restart-time migration."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

INSTALL_MARKER = '.ddm-install.json'
DATA_DIRS = ('utils', 'plugins_user', 'cache', 'logs')


def user_home():
    return Path(os.environ.get('LOCALAPPDATA') or Path.home() / '.local/share') / 'DDMonitorCE'


def location_file(program_root, home=None):
    identity = hashlib.sha256(str(Path(program_root).resolve()).lower().encode()).hexdigest()[:16]
    return Path(home or user_home()) / 'locations' / (identity + '.json')


def _write_location(path, values):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.location-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(values, stream, ensure_ascii=False)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _read_location(path):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def installed(program_root):
    root = Path(program_root)
    return (root / INSTALL_MARKER).is_file() or (root / '.ddm-uninstall/unins000.dat').is_file()


def writable(directory):
    """Probe actual write access rather than folder names or Windows ACL guesses."""
    try:
        with tempfile.TemporaryDirectory(prefix='.ddm-write-', dir=directory) as temporary:
            (Path(temporary) / 'probe').write_bytes(b'write check')
        return True
    except OSError:
        return False


def validate_target(source, target, program_root):
    source, target, program = map(lambda value: Path(value).absolute(), (source, target, program_root))
    if target == Path(target.anchor):
        raise ValueError('请选择专门用于 DDMonitorCE 数据的文件夹，不要选择磁盘根目录。')
    for part in (target, *target.parents):
        if part.is_symlink() or part.is_junction():
            raise ValueError('数据目录不能包含文件夹链接。')
    source, target, program = source.resolve(), target.resolve(), program.resolve()
    if (source == target or target.is_relative_to(source) or source.is_relative_to(target)
            or target == program or target.is_relative_to(program)):
        raise ValueError('请选择与当前数据目录和程序目录分开的文件夹。')
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise ValueError('目标文件夹必须为空，避免覆盖已有文件。')
    parent = target if target.exists() else target.parent
    if not parent.is_dir() or not writable(parent):
        raise ValueError('目标位置不可写，请选择当前用户有写入权限的文件夹。')
    return target


def copy_data(source, target):
    """Copy only app-owned data categories; preserve the source and unrelated files."""
    source, target = Path(source), Path(target)
    if target.exists() and any(target.iterdir()):
        raise ValueError('目标文件夹已有内容，迁移已停止。')
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.ddm-migrate-', dir=target.parent))
    try:
        for name in DATA_DIRS:
            entry = source / name
            if not entry.exists():
                continue
            for path in (entry, *entry.rglob('*')):
                if path.is_symlink() or path.is_junction():
                    raise ValueError('原数据包含文件夹或文件链接，迁移已停止。')
            shutil.copytree(entry, stage / name)
        if target.exists():
            target.rmdir()  # Refuse if anything appeared while data was copying.
        os.replace(stage, target)
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def schedule_migration(program_root, source, target, home=None):
    target = validate_target(source, target, program_root)
    _write_location(location_file(program_root, home), {
        'root': str(Path(source).resolve()),
        'pending': {'target': str(target), 'pid': os.getpid()}})
    return target


def resolve(program_root, home=None):
    """Resolve/migrate before caches and plugins import their data paths."""
    program = Path(program_root).resolve()
    location = location_file(program, home)
    values = _read_location(location)
    current = Path(values.get('root') or program).resolve()
    pending = values.get('pending')
    if pending:
        try:
            from .update_install import wait_parent
            wait_parent(int(pending['pid']))
            target = validate_target(current, pending['target'], program)
            copy_data(current, target)
            _write_location(location, {'root': str(target)})
            return target, ''
        except (OSError, ValueError, TimeoutError) as error:
            _write_location(location, {'root': str(current)})
            return current, f'数据迁移未完成，仍使用原目录，原文件已保留：{error}'
    if values:
        if not current.is_dir():
            raise OSError(f'数据目录不存在，请恢复该目录后重新启动：{current}')
        return current, ''
    if not installed(program):
        return program, ''
    target = location.parent.parent / 'data' / location.stem
    if not target.exists():
        copy_data(program, target)
    _write_location(location, {'root': str(target)})
    return target, ''
