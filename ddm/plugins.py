"""插件接口：把「不属于本体」的功能放到外面去。

设计取舍：宁可少而稳，不要多而虚。现在只开放四件事，每一件都有明确的
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

插件放 ``plugins/<插件名>/plugin.py``，里面必须有一个名为 ``plugin`` 的
``Plugin`` 实例（见 ``plugins/example/plugin.py``）。插件是**受信任的代码**，
它在主进程里跑，能拿到窗口对象，能力和本体代码等价——只装自己看过源码的插件。

插件里的异常不会拖垮本体：事件回调、平台回调、菜单回调都被包住并打印到 stderr，
让一个坏插件只坏它自己。
"""
import importlib.util
import os
import sys
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable

from . import config as config_module

#: 插件目录要和 utils / cache / logs 一样落在**程序旁边**：源码运行时是仓库根，
#: 打包成 exe 后是 exe 所在目录。这里用 config.REPO（它已经处理了 frozen），
#: 不能用 __file__ —— 冻结后 __file__ 在 _internal 里面，插件目录会找错地方，
#: 结果就是 exe 版永远是「[插件] 0 个插件」。
REPO = config_module.REPO
DEFAULT_PLUGINS_DIR = os.path.join(REPO, "plugins_user")

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
)


@dataclass
class StreamSource:
    """一路直播流的「取流结果」：录像类插件靠它直接拉流。

    ``headers`` 是拉这个地址必须带的请求头。B 站 app-room 通道的地址
    **不能带 Referer**，web 通道的地址**必须带**，弄反了 CDN 直接 403，
    所以这里把通道对应的头一起交出去，插件不要自己猜。
    """

    room_id: str
    url: str
    quality: int = 0
    channel: str = ""
    headers: dict = field(default_factory=dict)
    platform: str = "bilibili"
    uname: str = ""
    title: str = ""


@dataclass
class RoomInfo:
    """统一之后的房间信息。``platform`` 用来区分是哪个站。"""

    room_id: str
    uname: str = ""
    title: str = ""
    live: bool = False
    viewers: str = ""
    cover_url: str = ""
    face: str = ""
    platform: str = "bilibili"
    extra: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        """本体内沿用普通 dict，转换在这一层做完。"""
        payload = {
            "room_id": self.room_id,
            "uname": self.uname,
            "title": self.title,
            "live": self.live,
            "viewers": self.viewers,
            "cover_url": self.cover_url,
            "face": self.face,
            "platform": self.platform,
        }
        payload.update(self.extra or {})
        return payload


class Platform:
    """一个站的接入实现。子类至少要实现 ``matches`` / ``room_info`` / ``play_url``。

    ``kind`` 是给界面看的短名（例如 ``douyin``）：房间号前面会带上它，
    这样同一个「12345」在 B 站和别的站不会撞车。
    """

    kind = ""
    label = ""

    def matches(self, room_id: str) -> bool:
        """这个房间号是不是本平台的。"""
        return False

    def normalize(self, room_id: str) -> str:
        """把用户输入的房间号/链接整理成平台内部的 id。默认原样返回。"""
        return str(room_id or "")

    def room_info(self, room_id: str) -> RoomInfo | None:
        """拉房间信息；拿不到就返回 None。"""
        return None

    def rooms_status(self, room_ids: list) -> dict:
        """批量查直播状态：``{room_id: {live, title, viewers, cover_url, face}}``。"""
        return {}

    def play_url(self, room_id: str, quality: int = 250) -> tuple:
        """取流，返回 ``(url, 实际画质, 通道名)`` 或 ``(url, 实际画质, 通道名, headers)``。"""
        raise NotImplementedError


class DanmakuSender:
    """发弹幕的能力，由插件实现。"""

    def available(self) -> tuple:
        """返回 ``(能不能发, 不能发的原因)``。界面据此决定输入框是否可用。"""
        return False, "这个插件不支持发弹幕"

    def send(self, room_id: str, text: str) -> tuple:
        """发一条弹幕，返回 ``(成功?, 给用户看的结果说明)``。"""
        return False, "没有实现"


class PluginContext:
    """交给插件的把手：注册平台 / 菜单项，以及问本体要东西。"""

    def __init__(self, manager: "PluginManager", name: str):
        self._manager = manager
        self.name = name

    # ---- 注册 ----
    def register_platform(self, platform: Platform) -> None:
        self._manager.register_platform(self.name, platform)

    def register_danmaku_sender(self, sender: DanmakuSender) -> None:
        self._manager.register_danmaku_sender(self.name, sender)

    # ---- 取用 ----
    @property
    def window(self):
        """主窗口。插件可以直接用它，但优先用下面这些稳定入口。"""
        return self._manager.window

    @property
    def manager(self) -> "PluginManager":
        return self._manager

    def setting(self, key: str, default=None):
        """读插件自己的配置项（存在 ``utils/config.json`` 的 ``plugins`` 段）。"""
        return ((self._manager.plugin_settings.get(self.name) or {})
                .get(key, default))

    def set_setting(self, key: str, value) -> None:
        """写插件自己的配置项并落盘。"""
        bucket = self._manager.plugin_settings.setdefault(self.name, {})
        bucket[key] = value
        self._manager.save_plugin_settings()

    def platform(self, kind: str) -> Platform | None:
        return self._manager.platforms.get(str(kind))

    def log(self, message: str) -> None:
        print(f"[插件 {self.name}] {message}", file=sys.stderr, flush=True)


class Plugin:
    """插件基类。所有钩子都是可选的，只需要覆盖自己关心的那几个。"""

    #: 显示名，缺省用目录名
    name = ""
    #: 一句话说明，插件列表里展示
    description = ""
    version = ""

    def __init__(self) -> None:
        self.context: PluginContext | None = None

    # ---- 生命周期 ----
    def on_load(self, context: PluginContext) -> None:
        """插件被装载时调用。注册平台/菜单一般放这里。"""

    def on_unload(self) -> None:
        """程序退出时调用。要停线程、关文件就放这里。"""

    def on_event(self, event: str, payload: dict) -> None:
        """本体播报事件。只读，别在这里改 ``payload`` 里的对象。"""

    # ---- 界面 ----
    def tile_actions(self, tile) -> list:
        """往这个格子的右键菜单加项。

        每一项是 ``(显示文字, 回调)``；回调不带参数，被调用时可以从
        ``tile.room`` 读这一路的房间信息。多个插件按装载顺序排列。
        """
        return []


class PluginManager:
    """装载插件、转发事件、维护平台与菜单项。"""

    def __init__(self, window=None, plugins_dir: str | None = None,
                 enabled: list | None = None):
        self.window = window
        self.plugins_dir = plugins_dir or DEFAULT_PLUGINS_DIR
        self.enabled = None if enabled is None else {str(name) for name in enabled}
        self.plugins: list = []
        self.skipped: list = []                  # [(目录名, 原因)]
        self.platforms: dict = {}                # kind -> Platform
        self._platform_owner: dict = {}          # kind -> 插件名
        self._sender: DanmakuSender | None = None
        self._sender_owner = ""
        self.plugin_settings: dict = {}
        self._save_settings: Callable | None = None

    # ---- 装载 ----
    def load(self) -> None:
        if not os.path.isdir(self.plugins_dir):
            return
        for entry in sorted(os.listdir(self.plugins_dir)):
            if entry.startswith((".", "_")):
                continue
            folder = os.path.join(self.plugins_dir, entry)
            module_path = os.path.join(folder, "plugin.py")
            if not os.path.isfile(module_path):
                continue
            if self.enabled is not None and entry not in self.enabled:
                self.skipped.append((entry, "配置里没有启用"))
                continue
            try:
                plugin = self._load_module(entry, module_path)
            except Exception as error:           # noqa: BLE001
                self.skipped.append((entry, f"装载失败：{error}"))
                traceback.print_exc()
                continue
            if plugin is None:
                self.skipped.append((entry, "没有找到名为 plugin 的 Plugin 实例"))
                continue
            context = PluginContext(self, entry)
            plugin.context = context
            try:
                plugin.on_load(context)
            except Exception as error:           # noqa: BLE001
                self.skipped.append((entry, f"on_load 出错：{error}"))
                traceback.print_exc()
                continue
            if not plugin.name:
                plugin.name = entry
            self.plugins.append(plugin)
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
        for plugin in self.plugins:
            try:
                plugin.on_unload()
            except Exception:                    # noqa: BLE001
                traceback.print_exc()

    def save_plugin_settings(self) -> None:
        """插件改了自己的配置项；交给本体去落盘（没接回调就只留在内存里）。"""
        if self._save_settings is not None:
            try:
                self._save_settings()
            except Exception:                    # noqa: BLE001
                traceback.print_exc()

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
