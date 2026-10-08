"""插件升级先暂存，下一次启动在加载插件之前替换，并保留原目录数据。"""
import os
from pathlib import Path
import shutil
import tempfile

from .online import version_key
from .file_ops import replace_directory
from .version import VERSION


def check_compatibility(manifest):
    minimum = manifest.get('min_app_version', '0.3')
    if version_key(VERSION) < version_key(minimum):
        raise ValueError(f'此插件需要本体 {minimum} 或更高版本')


def stage(manager, archive, plugin_id, expected_version):
    from .plugins import PluginManager, read_manifest
    target = Path(manager.plugins_dir) / plugin_id
    if not target.is_dir() or target.is_symlink():
        raise ValueError('待升级插件不存在或目录无效')
    old = next(entry for entry in manager.catalog() if entry['id'] == plugin_id)
    if version_key(expected_version) <= version_key(old['version']):
        raise ValueError('新版必须高于当前插件版本')
    pending = Path(manager.plugins_dir) / '.updates'
    pending.mkdir(exist_ok=True)
    destination = pending / plugin_id
    if destination.exists():
        raise ValueError('已有待重启的更新，请先重启软件')
    with tempfile.TemporaryDirectory(prefix='.download-', dir=pending) as temporary:
        installer = PluginManager(plugins_dir=temporary)
        installed = installer.install_zip(archive)
        if installed != plugin_id:
            raise ValueError('下载插件的 ID 与商店记录不一致')
        manifest = read_manifest(str(Path(temporary) / installed), installed)
        check_compatibility(manifest)
        if manifest['version'] != expected_version:
            raise ValueError('插件版本与商店记录不一致')
        replace_directory(Path(temporary) / installed, destination)
    return plugin_id


def pending_versions(manager):
    from .plugins import PLUGIN_ID, read_manifest
    root = Path(manager.plugins_dir) / '.updates'
    result = {}
    if root.is_dir() and not root.is_symlink():
        for folder in root.iterdir():
            if folder.is_dir() and not folder.is_symlink() and PLUGIN_ID.fullmatch(folder.name):
                try:
                    manifest = read_manifest(str(folder), folder.name)
                    if manifest:
                        result[folder.name] = manifest['version']
                except (OSError, ValueError):
                    pass
    return result


def apply_pending(manager):
    from .plugins import read_manifest
    root = Path(manager.plugins_dir)
    for plugin_id in pending_versions(manager):
        package = root / '.updates' / plugin_id
        target = root / plugin_id
        backup = root / '.updates' / (plugin_id + '.backup')
        moved = False
        try:
            if not target.is_dir() or target.is_symlink() or backup.is_symlink():
                raise ValueError('插件目录无效')
            check_compatibility(read_manifest(str(package), plugin_id))
            with tempfile.TemporaryDirectory(prefix='.merge-', dir=root) as temporary:
                merged = Path(temporary) / plugin_id
                # 在启动时复制最终数据，避免丢失下载之后、退出之前的写入。
                shutil.copytree(target, merged)
                shutil.copytree(package, merged, dirs_exist_ok=True)
                read_manifest(str(merged), plugin_id)
                if backup.exists():
                    shutil.rmtree(backup)
                replace_directory(target, backup)
                moved = True
                replace_directory(merged, target)
            shutil.rmtree(package)
        except (OSError, ValueError) as error:
            if moved and not target.exists():
                replace_directory(backup, target)
            manager.skipped.append((plugin_id + ':update', f'更新失败，保留旧插件：{error}'))


def install(manager, archive, offer):
    from .plugins import PluginManager, read_manifest
    existing = {entry['id']: entry for entry in manager.catalog()}
    if offer['id'] in existing:
        return stage(manager, archive, offer['id'], offer['version'])
    # 先验证 ID、版本和兼容性，确认后再安装到实际目录。
    with tempfile.TemporaryDirectory(prefix='ddm-plugin-check-') as temporary:
        installer = PluginManager(plugins_dir=temporary)
        plugin_id = installer.install_zip(archive)
        manifest = read_manifest(str(Path(temporary) / plugin_id), plugin_id)
        if plugin_id != offer['id'] or manifest['version'] != offer['version']:
            raise ValueError('安装包 ID 或版本与商店记录不一致')
        check_compatibility(manifest)
    # 文件安装可在线程内执行，启用选择及其 UI 配置保存由主线程提交。
    return PluginManager(plugins_dir=manager.plugins_dir).install_zip(archive)
