"""插件接口：把「不属于本体」的功能放到外面去。

设计取舍：宁可少而稳，不要多而虚。现在开放五件事，每一件都有明确的
使用场景（录像、接抖音/YouTube/Twitch、发弹幕、给格子加菜单项）：

1. **事件**（``Plugin.on_event``）—— 本体在关键时刻把状态播出去，插件只读。
   例：``stream.resolved`` 给出这一路的真实流地址和请求头，插件拿去喂 ffmpeg
   就能录像，既不用二次取流、也不用碰本体的播放器。

2. **平台**（``Plugin.register_platform``）—— 让本体认识 B 站以外的站。
   平台负责「房间信息」和「取流地址」，取流之后照旧交给 VLC 播放，
   所以「支持抖音/Twitch」这种扩展不需要改播放器和界面。

3. **格子菜单**（``Plugin.tile_actions``）—— 往画面格右键菜单里加一项，
   例如「开始录制 / 停止录制」。

4. **弹幕发送**（``Plugin.send_danmaku``）—— 由插件实现怎么发，
   本体只在需要时调用。各家平台差异太大，塞进本体不划算。

5. **皮肤美化**（``Plugin.skin`` / 清单 ``skin``）—— 背景、分区样式及按钮图标；
   v2 支持个人覆盖，v1 保留背景接管行为，详见 docs/skins.md。

运行时插件放 ``plugins_user/<插件ID>/plugin.py``，里面必须有一个名为 ``plugin`` 的
``Plugin`` 实例；开发模板见 ``plugins_user/_template_platform/plugin.py``，源码与安装副本边界见
``docs/plugins.md``。插件是**受信任的代码**，
它在主进程里跑，能拿到窗口对象，能力和本体代码等价——只装自己看过源码的插件。

插件里的异常不会拖垮本体：事件回调、平台回调、菜单回调都被包住并打印到 stderr，
让一个坏插件只坏它自己。
"""
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
import traceback
import zipfile
import weakref
from dataclasses import dataclass, field
from typing import Any, Callable

from . import config as config_module
from .plugin_worker import worker_command
from .file_ops import replace_directory
from .plugin_controls import TileControl, TileControlContext, TileControls
from .plugin_credentials import (CredentialSnapshot, CredentialStore,
                                 EVENT_ACCOUNT_CHANGED, EVENT_CREDENTIALS_UPDATED)

#: User-installed plugins follow the data folder, separate from bundled resources.
REPO = config_module.data_root()
DEFAULT_PLUGINS_DIR = os.path.join(REPO, "plugins_user")
from .plugin_manifest import (PLUGIN_ID, PLUGIN_INVENTORY, RETIRED_BUNDLED_PLUGINS, RENAMED_PLUGINS, read_manifest)
# 旧发布包的记录插件已由本体接管；覆盖升级保留文件，但不再执行或展示。


# ---- 事件名（字符串常量，插件里直接用字面量也行） ----
EVENT_STARTED = "app.started"
EVENT_CLOSING = "app.closing"
EVENT_STREAM_RESOLVED = "stream.resolved"
EVENT_STREAM_FAILED = "stream.failed"
EVENT_TILE_PLAYING = "tile.playing"
EVENT_TILE_STOPPED = "tile.stopped"
EVENT_TILE_ADDED = "tile.added"
EVENT_TILE_REMOVED = "tile.removed"
EVENT_DANMAKU = "danmaku.message"
EVENT_DANMAKU_STATUS = "danmaku.status"
EVENT_ROOM_LIVE = "room.live"
EVENT_ROOM_OFFLINE = "room.offline"
EVENT_SETTINGS = "settings.changed"

ALL_EVENTS = (
    EVENT_STARTED, EVENT_CLOSING, EVENT_STREAM_RESOLVED, EVENT_STREAM_FAILED,
    EVENT_TILE_PLAYING, EVENT_TILE_STOPPED, EVENT_TILE_ADDED, EVENT_TILE_REMOVED,
    EVENT_DANMAKU, EVENT_DANMAKU_STATUS, EVENT_ROOM_LIVE, EVENT_ROOM_OFFLINE,
    EVENT_SETTINGS,
    EVENT_ACCOUNT_CHANGED, EVENT_CREDENTIALS_UPDATED,
)


from .plugin_types import (LoginRequiredError, StreamCodecUnavailable, StreamSource, RoomInfo, Platform, DanmakuSender, PluginContext, Plugin)
from .plugin_packages import PluginPackages


class PluginManager:
    """装载插件、转发事件、维护平台与菜单项。"""

    def __init__(self, window=None, plugins_dir: str | None = None,
                 enabled: list | None = None):
        self.package_control = PluginPackages(self)
        self.window = window
        self.plugins_dir = plugins_dir or DEFAULT_PLUGINS_DIR
        self.enabled = None if enabled is None else {str(name) for name in enabled}
        self.plugins: list = []
        self.skipped: list = []                  # [(目录名, 原因)]
        self.platforms: dict = {}                # kind -> Platform
        self._platform_owner: dict = {}          # kind -> 插件名
        self._sender: DanmakuSender | None = None
        self._sender_owner = ""
        self._removed: set[str] = set()
        self.plugin_settings: dict = {}
        self._save_settings: Callable | None = None
        self._tiles = weakref.WeakSet()
        self._tile_providers = {}
        self._loading_owner = None
        self._provider_order = 0
        self._credentials = CredentialStore(self.emit)
        self._contexts = weakref.WeakSet()
        self._workspace_pages = None
        self._unloaded = False
        self._notices = None
        if window is not None:
            from PySide6.QtCore import QObject
            if isinstance(window, QObject):
                from .plugin_notices import PluginNotices
                self._notices = PluginNotices(window)

    def register_credentials(self, platform, read, **options):
        self._credentials.register(platform, read, **options)

    def notify_credentials(self, platform):
        self._credentials.notify(platform)

    def credentials(self, platform):
        return self._credentials.snapshot(platform)

    def update_credentials(self, platform, changes, *, expected_generation):
        return self._credentials.update(platform, changes, expected_generation=expected_generation)

    # ---- 装载 ----
    def load(self) -> None:
        if not os.path.isdir(self.plugins_dir):
            return
        from .plugin_updates import apply_pending
        apply_pending(self)
        for old, new in RENAMED_PLUGINS.items():
            if not os.path.isfile(os.path.join(self.plugins_dir, new, "plugin.py")):
                continue
            if self.enabled is not None and old in self.enabled:
                self.enabled.discard(old)
                self.enabled.add(new)
            if old in self.plugin_settings:
                previous = self.plugin_settings.pop(old)
                self.plugin_settings[new] = {**previous, **self.plugin_settings.get(new, {})}
        for entry in sorted(os.listdir(self.plugins_dir)):
            if entry.startswith((".", "_")) or entry in RETIRED_BUNDLED_PLUGINS:
                continue
            if entry in RENAMED_PLUGINS and os.path.isfile(os.path.join(
                    self.plugins_dir, RENAMED_PLUGINS[entry], "plugin.py")):
                continue                  # 新旧目录共存时只装载新插件
            folder = os.path.join(self.plugins_dir, entry)
            module_path = os.path.join(folder, "plugin.py")
            if not os.path.isfile(module_path):
                continue
            if self.enabled is not None and entry not in self.enabled:
                self.skipped.append((entry, "配置里没有启用"))
                continue
            try:
                manifest = read_manifest(folder, entry)
                plugin = self._load_module(entry, module_path)
            except Exception as error:           # noqa: BLE001
                self.skipped.append((entry, f"装载失败：{error}"))
                traceback.print_exc()
                continue
            if plugin is None:
                self.skipped.append((entry, "没有找到名为 plugin 的 Plugin 实例"))
                continue
            if manifest:
                plugin.name = manifest["name"]
                plugin.description = manifest["description"]
                plugin.version = manifest["version"]
                plugin.skin = manifest.get("skin", plugin.skin)
            context = PluginContext(self, entry)
            plugin.context = context
            try:
                self._loading_owner = entry
                plugin.on_load(context)
                if plugin.skin is not None:
                    from .skins import plugin_skin
                    plugin_skin(plugin, folder)
            except Exception as error:           # noqa: BLE001
                context._active = False
                self._remove_tile_owner(entry)
                context._clear_workspace_controls()
                try:
                    plugin.on_unload()
                except Exception:
                    traceback.print_exc()
                if context._recording is not None:
                    context._recording.close()
                self.skipped.append((entry, f"on_load 出错：{error}"))
                traceback.print_exc()
                continue
            finally:
                self._loading_owner = None
            if not plugin.name:
                plugin.name = entry
            self.plugins.append(plugin)
            for tile in tuple(self._tiles):
                self.attach_tile(tile)
            print(f"[插件] 已装载 {plugin.name}"
                  f"{' v' + plugin.version if plugin.version else ''}",
                  file=sys.stderr, flush=True)

    def _load_module(self, name: str, path: str) -> Plugin | None:
        spec = importlib.util.spec_from_file_location(f"ddm_plugin_{name}", path)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        plugin = getattr(module, "plugin", None)
        return plugin if isinstance(plugin, Plugin) else None

    def unload(self) -> None:
        self._unloaded = True
        for context in tuple(self._contexts):
            context._active = False
        for tile in tuple(self._tiles):
            self.detach_tile(tile)
        self._tile_providers.clear()
        for plugin in self.plugins:
            try:
                plugin.on_unload()
            except Exception:                    # noqa: BLE001
                traceback.print_exc()
        for context in tuple(self._contexts):
            context._clear_workspace_controls()
            if context._recording is not None:
                context._recording.close()

    def register_tile_control(self, owner, control_id, factory, *, priority=0):
        key = (owner, str(control_id))
        if not control_id or key in self._tile_providers or not callable(factory):
            raise ValueError('tile control needs a unique ID and callable factory')
        self._provider_order += 1
        self._tile_providers[key] = (factory, int(priority), self._provider_order)
        if self._loading_owner != owner:
            for tile in tuple(self._tiles):
                self.attach_tile(tile)

    def attach_tile(self, tile):
        self._tiles.add(tile)
        controls = getattr(tile, '_plugin_controls', None)
        if controls is None or controls._disposed:
            controls = tile._plugin_controls = TileControls(tile, on_shutdown=self._tiles.discard)
            tile.destroyed.connect(controls.shutdown)
        for (owner, key), (factory, priority, order) in self._tile_providers.items():
            if self._loading_owner != owner:
                controls.add(owner, key, factory, priority, order)

    def detach_tile(self, tile):
        self._tiles.discard(tile)
        controls = getattr(tile, '_plugin_controls', None)
        if controls is not None:
            controls.shutdown()

    def _remove_tile_owner(self, owner):
        for key in tuple(self._tile_providers):
            if key[0] == owner:
                del self._tile_providers[key]
        for tile in tuple(self._tiles):
            tile._plugin_controls.remove_owner(owner)

    def active_skin(self):
        from .skins import plugin_skin
        for plugin in reversed(self.plugins):
            owner = plugin.context.name
            if (owner not in self._removed and plugin.skin is not None
                    and (self.enabled is None or owner in self.enabled)):
                try:
                    return plugin_skin(plugin, os.path.join(self.plugins_dir, owner))
                except (OSError, ValueError) as error:
                    print(f"[插件 {owner}] 皮肤无效：{error}", file=sys.stderr, flush=True)
        return None

    def save_plugin_settings(self) -> None:
        """插件改了自己的配置项；交给本体去落盘（没接回调就只留在内存里）。"""
        if self._save_settings is not None:
            try:
                self._save_settings()
            except Exception:                    # noqa: BLE001
                traceback.print_exc()

    def install_zip(self, archive: str) -> str:
        """安装单插件 ZIP；本次进程不执行新插件代码。"""
        return self.package_control.install_zip(archive, manifest_reader=read_manifest, directory_replace=replace_directory)

    def remove_plugin(self, plugin_id: str) -> None:
        """删除插件目录；已装载的实例在本次进程结束前仍然运行。"""
        return self.package_control.remove_plugin(plugin_id)

    def catalog(self) -> list[dict]:
        """设置页使用的插件目录、元数据和本次启动状态。"""
        return self.package_control.catalog(manifest_reader=read_manifest)

    # ---- 事件 ----
    def emit(self, event: str, **payload) -> None:
        for plugin in self.plugins:
            try:
                plugin.on_event(event, payload)
            except Exception as error:           # noqa: BLE001
                print(f"[插件 {plugin.name}] 处理 {event} 出错：{error}",
                      file=sys.stderr, flush=True)
                traceback.print_exc()

    # ---- 注册 ----
    def register_platform(self, owner: str, platform: Platform) -> None:
        kind = str(getattr(platform, "kind", "") or "").strip()
        if not kind:
            raise ValueError("平台必须有 kind")
        if kind in self.platforms:
            # 注册冲突是配置错误，直接报出来，别悄悄覆盖
            raise ValueError(
                f"平台 {kind} 已被 {self._platform_owner.get(kind)} 注册，"
                f"{owner} 又注册了一次")
        self.platforms[kind] = platform
        self._platform_owner[kind] = owner
        print(f"[插件] {owner} 注册平台 {kind}"
              f"{'（' + platform.label + '）' if platform.label else ''}",
              file=sys.stderr, flush=True)

    def register_danmaku_sender(self, owner: str, sender: DanmakuSender) -> None:
        if self._sender is not None:
            raise ValueError(f"发弹幕的能力已被 {self._sender_owner} 注册")
        self._sender = sender
        self._sender_owner = owner

    # ---- 给本体用的查询 ----
    def platform_for(self, room_id: str) -> Platform | None:
        """按房间号找平台；B 站自己那套不在插件里，返回 None 表示走本体。"""
        for platform in self.platforms.values():
            try:
                if platform.matches(room_id):
                    return platform
            except Exception:                    # noqa: BLE001
                traceback.print_exc()
        return None

    @property
    def danmaku_sender(self) -> DanmakuSender | None:
        return self._sender

    def tile_actions(self, tile) -> list:
        """收集所有插件的格子菜单项，形如 ``[('文字', 回调, 插件名)]``。"""
        actions = []
        for plugin in self.plugins:
            try:
                for item in plugin.tile_actions(tile) or []:
                    label, callback = item[0], item[1]
                    actions.append((str(label), callback, plugin.name))
            except Exception as error:           # noqa: BLE001
                print(f"[插件 {plugin.name}] 生成菜单项出错：{error}",
                      file=sys.stderr, flush=True)
        return actions

    def run_action(self, callback) -> None:
        """执行插件菜单回调，异常不许冒到界面线程。"""
        try:
            callback()
        except Exception as error:               # noqa: BLE001
            print(f"[插件] 菜单动作出错：{error}", file=sys.stderr, flush=True)
            traceback.print_exc()

    @property
    def summary(self) -> str:
        """给日志/设置页用的一行摘要。"""
        parts = [f"{len(self.plugins)} 个插件"]
        if self.platforms:
            parts.append("平台：" + "、".join(sorted(self.platforms)))
        if self._sender is not None:
            parts.append(f"发弹幕：{self._sender_owner}")
        if self.skipped:
            parts.append(f"跳过 {len(self.skipped)} 个")
        return "，".join(parts)


_MANAGER: PluginManager | None = None


def manager() -> PluginManager | None:
    """全局管理器；没装载过就是 None（插件相关代码要容忍这个）。"""
    return _MANAGER


def set_manager(value: PluginManager | None) -> None:
    global _MANAGER
    _MANAGER = value


def emit(event: str, **payload) -> None:
    """本体播报事件。没装插件时是空操作。"""
    if _MANAGER is not None:
        _MANAGER.emit(event, **payload)
