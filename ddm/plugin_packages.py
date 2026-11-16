"""Plugin package installation, removal and catalog; runtime manager owns loaded instances and settings."""
import json
import os
import shutil
import tempfile
import zipfile
from .plugin_manifest import (PLUGIN_ID, PLUGIN_INVENTORY, RETIRED_BUNDLED_PLUGINS, RENAMED_PLUGINS, read_manifest)


class PluginPackages:
    def __init__(self, host):
        self.host = host

    def install_zip(self, archive: str, *, manifest_reader, directory_replace) -> str:
        """安装单插件 ZIP；本次进程不执行新插件代码。"""
        host = self.host
        read_manifest = manifest_reader
        replace_directory = directory_replace
        with zipfile.ZipFile(archive) as package:
            files = [item for item in package.infolist() if not item.is_dir()]
            if not files or len(files) > 256 or sum(item.file_size for item in files) > 100 * 1024 * 1024:
                raise ValueError("插件包为空或超过大小限制")
            if len({item.filename for item in files}) != len(files):
                raise ValueError("插件包包含重复文件")
            names = [item.filename.split("/") for item in files]
            plugin_id = names[0][0]
            if not PLUGIN_ID.fullmatch(plugin_id):
                raise ValueError("插件目录名须为小写英文字母开头，只能包含字母、数字和下划线")
            if plugin_id in RETIRED_BUNDLED_PLUGINS:
                raise ValueError("此旧版内置插件的功能已由本体提供，无需装载")
            for item, parts in zip(files, names):
                if (len(parts) < 2 or parts[0] != plugin_id or
                        any(part in ("", ".", "..") for part in parts) or
                        "\\" in item.filename or ":" in item.filename or
                        '\n' in item.filename or '\r' in item.filename or
                        (item.external_attr >> 16) & 0o170000 == 0o120000):
                    raise ValueError("插件包包含不安全路径或多个顶层目录")
            if f"{plugin_id}/plugin.py" not in package.namelist() or \
                    f"{plugin_id}/plugin.json" not in package.namelist():
                raise ValueError("插件包必须包含 plugin.py 和 plugin.json")
            os.makedirs(host.plugins_dir, exist_ok=True)
            target = os.path.join(host.plugins_dir, plugin_id)
            if os.path.exists(target):
                raise ValueError(f"插件 {plugin_id} 已存在")
            with tempfile.TemporaryDirectory(prefix="_import_", dir=host.plugins_dir) as staging:
                for item, parts in zip(files, names):
                    destination = os.path.join(staging, *parts)
                    os.makedirs(os.path.dirname(destination), exist_ok=True)
                    with package.open(item) as source, open(destination, "wb") as output:
                        shutil.copyfileobj(source, output)
                read_manifest(os.path.join(staging, plugin_id), plugin_id)
                inventory = os.path.join(staging, plugin_id, PLUGIN_INVENTORY)
                with open(inventory, 'w', encoding='utf-8-sig') as output:
                    output.write('\n'.join(sorted('/'.join(parts[1:]) for parts in names)) + '\n')
                replace_directory(os.path.join(staging, plugin_id), target)
        if host.enabled is not None:
            host.enabled.add(plugin_id)
            host.save_plugin_settings()
        return plugin_id

    def remove_plugin(self, plugin_id: str) -> None:
        """删除插件目录；已装载的实例在本次进程结束前仍然运行。"""
        host = self.host
        if (not isinstance(plugin_id, str) or not plugin_id or
                plugin_id.startswith((".", "_")) or
                any(char in plugin_id for char in ("/", "\\", ":"))):
            raise ValueError("只能删除插件目录中的有效插件")
        root = os.path.realpath(host.plugins_dir)
        target = os.path.join(root, plugin_id)
        if (os.path.commonpath((root, os.path.realpath(target))) != root or
                not os.path.isdir(target) or os.path.islink(target) or
                not os.path.isfile(os.path.join(target, "plugin.py"))):
            raise ValueError("只能删除插件目录中的有效插件")
        shutil.rmtree(target)
        host._removed.add(plugin_id)
        pending = os.path.join(root, ".updates", plugin_id)
        if os.path.isdir(pending) and not os.path.islink(pending) and os.path.commonpath(
                (root, os.path.realpath(pending))) == root:
            shutil.rmtree(pending)
        if host.enabled is not None:
            host.enabled.discard(plugin_id)
        host.plugin_settings.pop(plugin_id, None)
        host.save_plugin_settings()
        refresh = getattr(host.window, 'refresh_skin', None)
        if callable(refresh):
            refresh()

    def catalog(self, *, manifest_reader) -> list[dict]:
        """设置页使用的插件目录、元数据和本次启动状态。"""
        host = self.host
        read_manifest = manifest_reader
        if not os.path.isdir(host.plugins_dir):
            return []
        loaded = {plugin.context.name: plugin for plugin in host.plugins
                  if plugin.context is not None and plugin.context.name not in host._removed}
        skipped = dict(host.skipped)
        entries = []
        for folder in sorted(os.listdir(host.plugins_dir)):
            if folder.startswith((".", "_")) or folder in RETIRED_BUNDLED_PLUGINS or not os.path.isfile(
                    os.path.join(host.plugins_dir, folder, "plugin.py")):
                continue
            if folder in RENAMED_PLUGINS and os.path.isfile(os.path.join(
                    host.plugins_dir, RENAMED_PLUGINS[folder], "plugin.py")):
                continue
            plugin = loaded.get(folder)
            try:
                manifest = read_manifest(os.path.join(host.plugins_dir, folder), folder)
                manifest_error = ""
            except (OSError, ValueError, json.JSONDecodeError) as error:
                manifest = None
                manifest_error = f"plugin.json 无效：{error}"
            reason = skipped.get(folder, manifest_error)
            entries.append({
                "id": folder,
                "name": manifest["name"] if manifest else (str(plugin.name or folder) if plugin else folder),
                "description": manifest["description"] if manifest else (str(plugin.description or "") if plugin else ""),
                "version": manifest["version"] if manifest else (str(plugin.version or "") if plugin else ""),
                "enabled": host.enabled is None or folder in host.enabled,
                "status": "已加载" if plugin else (
                    "已禁用" if reason == "配置里没有启用" else
                    "加载失败" if reason else "待重启"),
                "reason": "" if plugin else reason,
            })
        return entries
