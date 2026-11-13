"""Public plugin contracts, platform values and per-plugin context."""
import sys
from dataclasses import dataclass, field
from .plugin_credentials import CredentialSnapshot


class LoginRequiredError(RuntimeError):
    """The platform explicitly rejected the account's login credentials."""


class StreamCodecUnavailable(RuntimeError):
    """The platform did not offer a stream with the requested video codec."""


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
    """一个站的接入实现。流模式需要 ``matches`` / ``room_info`` / ``play_url``。

    ``room_info``、``rooms_status``、``play_url`` 在本体工作线程调用，
    请求必须设置超时。``room_url`` 仅提供额外的官方网页菜单入口。

    ``kind`` 是给界面看的短名（例如 ``douyin``）：房间号前面会带上它，
    这样同一个「12345」在 B 站和别的站不会撞车。
    """

    kind = ""
    label = ""
    room_input_hint = ""  # 可选：添加直播间窗口显示的输入支持说明，由插件提供。
    playback_mode = "stream"
    follow_login_url = ""
    follow_cookie_domain = ""
    account_login_url = ""  # 可选：独立官方登录页面，未提供时使用关注页面。
    account_cookie_domain = ""  # 仅登录的平台可独立声明 Cookie 域，不代表支持关注导入。
    account_info = None  # 可选：account_info(session, cancelled) 返回 uid/uname/face。
    account_login_notice = ""  # 可选：尚未接入登录的平台展示说明，不创建登录浏览器。
    oauth_provider = ""  # 可选：twitch/youtube 使用本体的系统浏览器 OAuth 授权窗口。
    follow_browser_url = ""  # 可选：需要官网浏览器签名的 GET 接口（字符串或元组），包括账号确认。
    follow_browser_script = ""  # 可选：官网请求函数 (url) => Promise<JSON>，只返回接口响应。
    follow_accounts = None  # 可选：完整关注账号列表；待识别账号 room_id 为空，anchor_uid 非空。
    resolve_follow_account = None  # 可选：补充账号的固定房间；返回完整账号字典，不使用登录 Cookie。
    follow_browser_init_script = ""  # 可选：页面创建时安装官网列表响应监听，读取时保持页面可见。

    def follow_rooms(self, session, cancelled) -> list[dict]:
        """可选：后台用授权会话读取关注；每页检查 cancelled，失败抛异常。"""
        raise NotImplementedError

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

    def play_url_for_codec(self, room_id: str, quality: int = 250,
                           *, codec: str = "avc") -> tuple:
        """Strict selection: (url, quality, channel, headers, actual_codec).

        Implementations must identify the requested codec from source metadata;
        missing formats raise StreamCodecUnavailable, other errors propagate.
        The legacy adapter leaves actual_codec empty because it is unverified.
        """
        if codec != "avc":
            raise StreamCodecUnavailable("旧版平台插件不支持选择 HEVC 直播源")
        result = self.play_url(room_id, quality)
        return (*result[:3], dict(result[3]) if len(result) > 3 else {}, "")

    def room_quality_options(self, room_id: str) -> list[dict]:
        """本平台档位 ``{qn, desc, label?}``；qn 是保存标识，label 是按钮短名称。"""
        return []

    def preview_url(self, room_id: str) -> tuple:
        """预览取流；平台可独立选择低码率，避免与手选画质编号混淆。"""
        return self.play_url(room_id, 80)

    def room_url(self, room_id: str) -> str:
        """可选：返回直播间网页地址；空串表示不提供浏览器入口。"""
        return ""

    def danmaku_client(self, room_id: str, parent=None):
        """可选：返回未启动的 QThread（message(dict)/status(str) 信号、stop()）；None 为不支持。"""
        return None


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
        self._active = not manager._unloaded
        self._recording = None
        manager._contexts.add(self)

    # ---- 注册 ----
    def register_platform(self, platform: Platform) -> None:
        self._manager.register_platform(self.name, platform)

    def register_danmaku_sender(self, sender: DanmakuSender) -> None:
        self._manager.register_danmaku_sender(self.name, sender)

    def register_tile_control(self, control_id, factory, *, priority=0) -> None:
        self._manager.register_tile_control(self.name, control_id, factory, priority=priority)

    def register_workspace_control(self, control_id, widget, *, priority=0) -> bool:
        """Place a QToolButton in the host workspace group; False for headless hosts."""
        if not self._active:
            raise RuntimeError('Plugin context is inactive')
        controls = getattr(getattr(self.window, 'sidebar', None), 'workspace_controls', None)
        if controls is None:
            return False
        controls.add(self.name, control_id, widget, priority)
        return True

    def unregister_workspace_control(self, control_id) -> None:
        controls = getattr(getattr(self.window, 'sidebar', None), 'workspace_controls', None)
        if controls is not None:
            controls.remove(self.name, control_id)

    def _clear_workspace_controls(self):
        if self._manager._workspace_pages is not None:
            self._manager._workspace_pages.close_owner(self.name)
        controls = getattr(getattr(self.window, 'sidebar', None), 'workspace_controls', None)
        if controls is not None:
            controls.remove_owner(self.name)

    def show_workspace(self, widget, *, manages_content=False) -> bool:
        """Replace the central content with one embedded page; close the previous page."""
        if not self._active:
            raise RuntimeError('Plugin context is inactive')
        container = getattr(self.window, '_content', None)
        if container is None:
            return False
        if self._manager._workspace_pages is None:
            from .workspace_pages import WorkspacePages
            self._manager._workspace_pages = WorkspacePages(container)
            controls = getattr(getattr(self.window, 'sidebar', None), 'workspace_controls', None)
            if controls is not None:
                controls.bind_pages(self._manager._workspace_pages)
        return self._manager._workspace_pages.show_page(self.name, widget, manages_content=manages_content)

    def credentials(self, platform) -> CredentialSnapshot | None:
        return self._manager.credentials(platform)

    def update_credentials(self, platform, changes, *, expected_generation) -> bool:
        return self._manager.update_credentials(platform, changes, expected_generation=expected_generation)

    def notify(self, message, *, rooms=(), kind='info', on_click=None) -> bool:
        """Queue a main-window notice; False means this owner/window is unavailable."""
        bridge = self._manager._notices
        return bridge.notify(self, message, rooms=rooms, kind=kind, on_click=on_click) if bridge else False

    def request_login(self, platform, *, reauthenticate=False) -> bool:
        """Open the host login flow on the GUI thread after the current callback."""
        bridge = self._manager._notices
        return bridge.request_login(self, platform, reauthenticate=reauthenticate) if bridge else False

    # ---- 取用 ----
    @property
    def recording(self):
        """Recording service v1; operations require an active GUI-thread context."""
        if self._recording is None:
            from .recording_service import RecordingService
            self._recording = RecordingService(self)
        return self._recording

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
    skin = None  # Optional declarative skin v1/v2; see docs/skins.md.

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
