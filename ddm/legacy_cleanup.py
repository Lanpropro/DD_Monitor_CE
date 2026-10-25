"""Quarantine hash-verified obsolete release files, including manifest-less installs."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import threading

from .update_install import destination, relative_path
from .version import VERSION

INVENTORY = 'ddm-program-inventory.json'
CATALOG = Path(__file__).with_name('assets') / 'update' / 'legacy-program-files.json'


def _inside(root, path):
    if not path.resolve().is_relative_to(root):
        raise ValueError('清理路径超出程序目录')
    for part in (path, *path.parents):
        if part.is_symlink() or part.is_junction():
            raise ValueError('程序路径不能包含目录链接')
        if part == root:
            break
    return path


def safe_path(root, name):
    return _inside(root, destination(root, name))


def cleanup_legacy(root, catalog_path=CATALOG, expected_version=VERSION):
    root = Path(root).absolute()
    if root == Path(root.anchor) or root.is_symlink() or root.is_junction():
        raise ValueError('程序目录无效')
    root = root.resolve()
    build = json.loads(safe_path(root, 'ddm-build.json').read_text(encoding='utf-8-sig'))
    inventory = json.loads(safe_path(root, INVENTORY).read_text(encoding='utf-8'))
    catalog = json.loads(Path(catalog_path).read_text(encoding='utf-8'))
    if (build.get('version') != expected_version or build.get('update_protocol') != 1
            or build.get('platform') != 'windows-x64' or inventory.get('schema') != 1
            or inventory.get('version') != expected_version or catalog.get('schema') != 1):
        raise ValueError('程序清单版本不匹配')
    current = inventory['files']
    if not isinstance(current, list) or not {'DD监控室CE.exe', 'ddm-build.json', INVENTORY} <= set(current):
        raise ValueError('当前程序清单不完整')
    for name in current:
        relative_path(name)
    current = {name.casefold() for name in current}
    historical = catalog['files']
    for name, variants in historical.items():
        relative_path(name)
        if not variants:
            raise ValueError('历史文件校验信息缺失')
        for item in variants:
            digest = item['sha256']
            if (not isinstance(item['size'], int) or item['size'] < 0 or len(digest) != 64
                    or any(char not in '0123456789abcdef' for char in digest)):
                raise ValueError('历史文件校验信息无效')
    moved, skipped = [], []
    backup = None
    for name, variants in historical.items():
        if name.casefold() in current:
            continue
        saved = None
        try:
            target = safe_path(root, name)
            if not target.is_file():
                continue
            before = target.stat()
            if before.st_size not in {item['size'] for item in variants}:
                continue
            with target.open('rb') as source:
                digest = hashlib.file_digest(source, 'sha256').hexdigest()
            if not any(item['size'] == before.st_size and item['sha256'] == digest for item in variants):
                continue
            after = safe_path(root, name).stat()
            if ((after.st_ino, after.st_size, after.st_mtime_ns)
                    != (before.st_ino, before.st_size, before.st_mtime_ns)):
                skipped.append(name)
                continue
            if backup is None:
                # The updater already protects work/. Never purge these recovery copies automatically.
                work = root / 'work'
                if work.is_symlink() or work.is_junction():
                    raise ValueError('备份目录不能包含链接')
                work.mkdir(exist_ok=True)
                backup = Path(tempfile.mkdtemp(prefix='legacy-program-backup-', dir=work))
            _inside(root, backup)
            saved = safe_path(backup / 'files', name)
            saved.parent.mkdir(parents=True, exist_ok=True)
            target.rename(saved)
            # If another process changed the file during inspection, restore it rather than clean it.
            with saved.open('rb') as source:
                unchanged = hashlib.file_digest(source, 'sha256').hexdigest() == digest
            if not unchanged:
                if not target.exists():
                    saved.rename(target)
                skipped.append(name)
                continue
            moved.append(name)
        except (OSError, ValueError):
            if saved is not None and saved.is_file() and not target.exists():
                try:
                    _inside(root, saved).rename(safe_path(root, name))
                except (OSError, ValueError):
                    pass  # The relative-path recovery copy remains available if restoration is locked.
            skipped.append(name)  # Locked files and unsafe paths remain for a later start.
    report = {'version': expected_version, 'moved': moved, 'skipped': skipped,
              'backup': str(backup) if backup else None}
    if backup is not None:
        (backup / 'cleanup-report.json').write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


def start_legacy_cleanup(root):
    if not getattr(sys, 'frozen', False) or Path(sys.executable).resolve().parent != Path(root).resolve():
        return None

    def run():
        try:
            report = cleanup_legacy(root)
            print(f"[旧程序清理] 已备份移出 {len(report['moved'])} 个，"
                  f"暂缓 {len(report['skipped'])} 个；备份：{report['backup'] or '无'}",
                  file=sys.stderr, flush=True)
        except (OSError, ValueError, KeyError, TypeError) as error:
            print(f'[旧程序清理] 保留现有文件：{error}', file=sys.stderr, flush=True)

    worker = threading.Thread(target=run, name='legacy-program-cleanup')
    worker.start()
    return worker
