"""应用外壳：左侧房间列表 + 右侧画面墙。

画面墙上的每个格子是一个"播放位"：关掉某一路会留下空格子，等着把侧栏里的
直播间拖进来；播放器按格子持有，和房间号解耦。
"""
import faulthandler
from copy import deepcopy
import os
from pathlib import Path
import sys
import time
import webbrowser
from urllib.parse import urlsplit

from PySide6.QtCore import (QByteArray, QEvent, QLoggingCategory, QProcess,
                           QPoint, Qt, QtMsgType, QTimer, qInstallMessageHandler)
from PySide6.QtGui import QCursor, QIcon, QKeySequence, QShortcut
from PySide6.QtMultimedia import QMediaDevices
from PySide6.QtWidgets import (
    QApplication, QBoxLayout, QDialog, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox,
    QPlainTextEdit, QStackedWidget, QTextEdit,
    QVBoxLayout, QWidget,
)

from . import bili
from . import config as config_module
from . import diagnostics
from . import layouts
from . import room_presets
from . import overlay
from . import plugins as plugin_api
from . import theme
from . import version as version_module
from . import watchdog
from . import window_fullscreen
from .auto_quality import AUTO_QUALITY, OVERSEAS_PLATFORMS
from .fullscreen_cursor import FullscreenCursor
from .danmaku import DanmakuClient
from .super_chat_api import SuperChatSnapshot
from .super_chat_model import SuperChatStore
from .bili import (
    AccountLoader, InfoResolver, StatsPoller, StatusPoller, StreamResolver,
)
from .dialogs import SettingsDialog
from .room_dialogs import AddRoomDialog
from .settings_general import CodecSettingsDialog
from .shortcut_actions import SHORTCUT_ACTIONS
from .images import (AvatarLoader, CachedAvatarLoader, CachedCoverLoader,
                     load_cached_avatar)
from .player import TilePlayer
from .playback_recovery import PlaybackRecovery
from .stream_playback import StreamPlayback
from .codec_control import CodecControl
from .preview import HoverPreview
from .recording import RecordingManager
from .room_placement import RoomPlacement
from .room_preset_control import RoomPresetController
from .app_updates import AppUpdates
from .settings_control import SettingsControl
from .window_layout import WindowLayout
from .room_status import RoomStatus
from .room_images import RoomImages
from .capture_control import CaptureControl
from .danmaku_lifecycle import DanmakuLifecycle
from .sidebar_widgets import Sidebar
from .tile_widgets import Tile
from .wall_widgets import WallGrid
from .playback_controls import VolumeButton
from .watch_history import WatchHistory
from .system_tray import SystemTray
from .single_instance import SingleInstance, restore_main_window

#: 音频巡检间隔（毫秒）：格子记的静音 / 音量和播放器**实际**的值走散了就按格子重下发
AUDIO_AUDIT_MS = 2_000

MAX_TILES = 16
POLL_INTERVAL_MS = 60_000        # 关注列表状态轮询：1 分钟
#: 窗口「宽 / 高」小于这个值就按竖屏处理（含接近方形）
PORTRAIT_MAX_RATIO = 0.9
PORTRAIT_ENTER_RATIO = PORTRAIT_MAX_RATIO
PORTRAIT_EXIT_RATIO = 1.0
RESIZE_SETTLE_MS = 150
from .fullscreen_presentation import FullscreenPresentation
from .app_accounts import AppAccounts
from .app_shortcuts import AppShortcuts
from .fullscreen_control import FullscreenControl
from .app_notices import AppNotices

DEFAULT_SHORTCUTS = {key: default for key, _label, default in SHORTCUT_ACTIONS}


def setup_file_log() -> str:
    """Install Qt capture after the standard-library startup logger is ready."""
    session = diagnostics.start(os.path.join(config_module.data_root(), "logs"))
    # Font fallback logs while holding Qt's font mutex; font getters hold the GIL.
    # Filter this informational path in Qt, before it can re-enter Python logging.
    QLoggingCategory.setFilterRules("qt.text.font.db.info=false")
    # pythonw 没有原生 stderr；Qt 的致命错误必须在终止进程前写进日志。
    def qt_message(kind, context, message):
        print(f"[Qt {kind.name}] {message}", file=sys.stderr, flush=True)
        if kind == QtMsgType.QtFatalMsg:
            faulthandler.dump_traceback(file=session.crash_handle, all_threads=True)

    qInstallMessageHandler(qt_message)
    print(f"日志文件: {session.path}", file=sys.stderr)
    return session.path

EMPTY_HINT = ("还没有直播间\n\n"
              "点左下角「+ 添加直播间」填房间号，\n"
              "或者用「导入关注」从 B 站账号导入")


class MainWindow(QMainWindow):
    def __init__(self, rooms: list[dict], wall_rooms: list[dict] | None = None,
                 layout_id: str = "", state: dict | None = None):
        super().__init__()
        self.notice_control = AppNotices(self)
        self.fullscreen_control = FullscreenControl(self)
        self.shortcut_control = AppShortcuts(self)
        self.account_control = AppAccounts(self)
        self.setWindowTitle(version_module.DISPLAY_NAME)
        self.setFocusPolicy(Qt.StrongFocus)     # 让窗口能接收快捷键
        self.rooms = rooms
        self.state = state or {}
        self._tray_hint_shown = bool((self.state.get("ui") or {}).get("tray_hint_shown", False))
        self.room_presets = room_presets.collection(self.state.get("room_presets"))
        self._active_room_preset_id = (self.state.get("ui") or {}).get("room_preset_id", "")
        self._applying_room_preset = False
        self._room_preset_fullscreen_layout = None
        self._preset_retired_tiles = set()
        self.layout_id = layout_id
        self.players: dict[Tile, TilePlayer] = {}      # 按格子持有播放器
        self.room_placement = RoomPlacement(self)
        self.room_preset_control = RoomPresetController(self)
        self.app_updates = AppUpdates(self)
        self.settings_control = SettingsControl(self)
        self.window_layout = WindowLayout(self)
        self.stream_playback = StreamPlayback(self)
        self.codec_control = CodecControl(self)
        self.room_status = RoomStatus(self)
        self.room_images = RoomImages(self)
        self.capture_control = CaptureControl(self)
        self.danmaku_lifecycle = DanmakuLifecycle(self)
        self._resolvers: dict[object, StreamResolver] = {}
        self._resolvers_running: set[StreamResolver] = set()
        self._platform_info_running: set[InfoResolver] = set()
        self._stream_attempts: dict[object, int] = {}
        #: 正在关窗。取流线程的 resolved 是队列连接，关窗之后还会再投递一次；
        #: 那时候播放器已经 release 了，谁再碰它就是野指针（见 closeEvent）
        self._closing = False
        self._interactive_resize = False
        self._resize_dirty = False
        self._resize_on_show = False
        self._startup_layout_pending = True
        self._settling_resize = False
        self._native_size_state = 0
        self._resize_idle_timer = QTimer(self)
        self._resize_idle_timer.setSingleShot(True)
        self._resize_idle_timer.setInterval(RESIZE_SETTLE_MS)
        self._resize_idle_timer.timeout.connect(self._finish_interactive_resize)
        self._restart_requested = False
        self._update_plan = ""
        self._available_update = None
        self._startup_update_task = None
        self._startup_update_checked = False
        self._startup_plugin_task = None
        self._startup_plugin_checked = False
        self._plugin_update_offers = []
        self._plugin_catalog_offers = []
        self._update_notice = None
        self._replay_suppressed: dict[Tile, str] = {}
        self._avatar_loaders: list = []                 # 头像下载线程，关窗时要等它们
        self._accounts: dict[str, dict] = {}
        self._platform_login_sessions: dict[str, dict] = {}
        self._douyin_follow_cache = None
        self._poller = None
        self._startup_status_complete = False
        self._refresh_queued = False
        self._stats_poller = None
        self._codec_dialogs: dict[Tile, CodecSettingsDialog] = {}
        self._stream_info_dialogs = {}
        self.playback_recovery = PlaybackRecovery(self)
        # Compatibility views; all recovery state is owned by the controller.
        self._retry_count = self.playback_recovery.retry_count
        self._retry_timers = self.playback_recovery.retry_timers
        self._freeze_refreshed = self.playback_recovery.freeze_refreshed
        self._freeze_retry_timers = self.playback_recovery.freeze_retry_timers
        self._fullscreen_tile: Tile | None = None
        self._fullscreen_cursor = FullscreenCursor(self)
        self._fullscreen_presentation = FullscreenPresentation(self)
        self._fullscreen_audio_saved: dict[Tile, bool] = {}
        self._danmaku: DanmakuClient | None = None      # 弹幕格当前连的那一路
        self._danmaku_room = ""
        self._danmaku_clients: dict[str, object] = {}
        self._danmaku_status: dict[str, str] = {}
        self._danmaku_retired: list = []
        self._super_chats: dict[str, SuperChatStore] = {}
        self._super_chat_snapshots: dict[str, SuperChatSnapshot] = {}
        self._super_chat_retired: list = []
        self._super_chat_timer = QTimer(self)
        self._super_chat_timer.setInterval(1000)
        self._super_chat_timer.timeout.connect(self._tick_super_chats)
        self._super_chat_timer.start()
        self.shortcuts = dict(DEFAULT_SHORTCUTS)
        self.settings = dict(config_module.DEFAULT_SETTINGS)
        saved_settings = self.state.get("settings") or {}
        self.settings.update(saved_settings)
        if "video_danmaku_outline" in saved_settings:
            self.settings["video_danmaku_outline_width"] = (
                saved_settings.get("video_danmaku_outline_width", 2)
                if saved_settings["video_danmaku_outline"] else 0)
            self.settings.pop("video_danmaku_outline", None)
        self.settings["appearance_mode"] = theme.normalize_mode(self.settings.get("appearance_mode"))
        if not isinstance(self.settings.get('skin_background'), str):
            self.settings['skin_background'] = ''
        theme.apply(self.settings["appearance_mode"])
        self.settings["freeze_watch"] = True  # 卡死检测固定开启，不再提供全局开关。
        if (saved_settings.get("danmaku_retention_version") != 1
                and self.settings.get("danmaku_max_blocks") == 300):
            self.settings["danmaku_max_blocks"] = 3000
        if "decode_mode" not in saved_settings:
            self.settings["decode_mode"] = ("auto" if saved_settings.get("hw_decode", True)
                                            else "none")
        self.settings.pop("hw_decode", None)
        self.settings.pop("auto_reconnect", None)  # 旧配置的开关不再控制内置重连
        self.settings.pop("recording_backup_dir", None)
        self.settings.pop("recording_ffmpeg", None)
        self.recorder = RecordingManager(self.settings, self, source_resolver=self._refresh_recording_source)
        self.recorder.noticeWithRoom.connect(self._record_notice)
        self.recorder.changed.connect(self._record_state_changed)
        self._capture_quality: dict[object, tuple[str, int]] = {}
        self._pending_capture: dict[object, bool] = {}

        # 布局按方向分别记；老配置只有一个 layout 键，当作横屏的。
        # 这一步必须在建画面墙**之前**做：第一次摆就要按存过的那套布局来，
        # 否则老配置会被当成「没存过布局」而退回默认。
        ui = self.state.setdefault("ui", {})
        if "layout" in ui and "layout_landscape" not in ui:
            ui["layout_landscape"] = ui.pop("layout")

        # 侧栏和画面墙总共只有一份，方向切换时**重新摆放**它们。
        # 注意：不要「构建期就造好两套排布」——Qt 里 addWidget 会把控件从旧布局
        # 里移走，两套都挂同一个控件的结果是它只留在最后那一套里。
        root = QWidget()
        root.setObjectName("Root")
        self._root_layout = QHBoxLayout(root)
        self._root_layout.setContentsMargins(0, 0, 0, 0)
        self._root_layout.setSpacing(0)

        self.sidebar = Sidebar(
            rooms,
            card_mode=bool(self.settings.get("sidebar_card_mode", True)),
            auto_compact=bool(self.settings.get("sidebar_auto_compact", True)),
            compact_threshold=int(self.settings.get("sidebar_compact_threshold", 18)),
            compact_background=bool(self.settings.get("sidebar_compact_background", True)),
        )

        self.empty_hint = QLabel(EMPTY_HINT)
        self.empty_hint.setObjectName("EmptyHint")
        self.empty_hint.setAlignment(Qt.AlignCenter)
        # 没有显式墙面房间时，墙面应从空位开始；关注列表不等于已上墙房间。
        # 否则布局变大时，原本隐藏的关注会被误显示成新格子的主播。
        # 没显式指定布局（正式启动就是这样）时，先按配置里存的那套摆；
        # 新配置也就是第一次启动，用 FIRST_LAYOUT（1 主画面 + 5 小环绕）。
        self.wall = WallGrid(
            wall_rooms if wall_rooms is not None else [],
            layout_id if layout_id and layout_id != "auto"
            else self._saved_layout("landscape"), prepare_room=self._prepare_room,
            corner_ratios=ui.get("corner_ratios"), layout_ratios=ui.get("layout_ratios"),
            pane_layouts=ui.get("pane_layouts"))

        #: 画面墙那一块（画面墙 + 空态提示），横竖两套排布共用它
        self._content = QWidget()
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_layout.addWidget(self.wall, 1)
        content_layout.addWidget(self.empty_hint, 1)
        from .picture_in_picture import PictureInPicture
        self.picture_in_picture = PictureInPicture(self)
        self.sidebar.pictureInPictureRequested.connect(self.picture_in_picture.manage)
        from .wall_removal import WallRemoval
        self.wall_removal = WallRemoval(self)

        self.setCentralWidget(root)
        from .skins import SkinController
        self.skin_controller = SkinController(self)
        self.orientation = ""                  # 由 _apply_orientation 填
        #: 各方向「切走之前在用的布局」：切回来时还原，别被容量折算换掉
        self._layout_by_orientation: dict[str, str] = {}
        self._build_arrangement("landscape")
        #: 构造时显式指定的布局（交给 _apply_orientation 决定用哪个方向的）
        self._pending_layout = ""

        # 信号接线
        self.sidebar.collapseAnimationChanged.connect(self.wall.set_sidebar_animating)
        self.sidebar.roomSelected.connect(self.wall.tileClicked.emit)
        self.sidebar.addRoomClicked.connect(self.open_add_room)
        self.sidebar.importFollowsClicked.connect(self.open_import_follows)
        self.sidebar.addToWallRequested.connect(self.add_to_wall)
        self.sidebar.removeRequested.connect(self.remove_room)
        self.sidebar.openBrowserRequested.connect(self._open_room_browser)
        self.sidebar.deleteRequested.connect(self.remove_rooms)
        self.sidebar.logoutRequested.connect(self.logout)
        self.sidebar.platformLogoutRequested.connect(self.logout)
        self.sidebar.loginRequested.connect(lambda: self.open_login())
        self.sidebar.pinChanged.connect(self._on_pin_changed)
        self.sidebar.sortChanged.connect(self._on_sort_changed)
        self.sidebar.orderChanged.connect(self._on_order_changed)
        self.sidebar.foldersChanged.connect(self._on_order_changed)
        self.sidebar.refreshRequested.connect(self.refresh_follow)
        self.sidebar.settingsRequested.connect(self._open_sidebar_settings)
        self.sidebar.clearWallRequested.connect(self._clear_wall)
        self.sidebar.pluginSettingsRequested.connect(lambda: self.open_settings('plugins'))
        self.sidebar.cardModeChanged.connect(self._sidebar_card_mode_changed)
        self.sidebar.appearanceChanged.connect(self.set_appearance)
        self.sidebar.layoutChosen.connect(self._on_layout_changed)
        self.sidebar.room_presets_host = self
        self.sidebar.layoutResetRequested.connect(self.wall.reset_layout_ratios)
        self.sidebar.set_layout_name(self.wall.layout_id)
        self.wall.paneEditRequested.connect(self.switch_tile_to_danmaku)
        self.wall.paneApplyRequested.connect(self._apply_pane_menu)
        self.wall.danmakuPanelCreated.connect(self._connect_danmaku_panel)
        self.wall.paneConfigurationChanged.connect(self._pane_configuration_changed)
        for panel in self.wall.pane_danmaku.all_panels():
            self._connect_danmaku_panel(panel)
        # 悬停预览：鼠标在关注列表的直播上停 2 秒弹个小画面
        self.hover_preview = HoverPreview(
            self.sidebar, self, platform_resolver=lambda rid: self.plugins.platform_for(rid))
        self.sidebar.previewHovered.connect(self.hover_preview.on_hover)
        self.sidebar.previewUnhovered.connect(self.hover_preview.on_unhover)
        # 拖字号滑块时别每一步都写配置，停手后再存
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(700)
        self._save_timer.timeout.connect(lambda: config_module.save(self.current_state()))
        self.sidebar.workspace_controls.pinsChanged.connect(self._save_timer.start)
        self.sidebar.navigation.orderChanged.connect(self._save_timer.start)
        self.wall.cornerRatiosChanged.connect(self._save_timer.start)
        self.wall.layoutRatiosChanged.connect(self._save_timer.start)
        # 音频巡检：`audio_set_mute` / `audio_set_volume` 是在 aout 上生效的，而 aout
        # 要等真正开始播放才建。补设置靠 play() 后那几次重试 + 看门狗，个别机器上
        # （慢启动、断流重连、切音频输出路径）会错过窗口，于是「静音标志亮着、声音
        # 还在」—— 用户报的「音频连在一起」就是这一类。这里定时比一遍，走散了就按
        # **格子**的值重新下发（格子是权威）。
        self._audio_audit_timer = QTimer(self)
        self._audio_audit_timer.setInterval(AUDIO_AUDIT_MS)
        self._audio_audit_timer.timeout.connect(self._audit_audio)
        self._audio_audit_timer.start()
        self._audio_devices = QMediaDevices(self)
        self._default_audio_output_id = bytes(self._audio_devices.defaultAudioOutput().id())
        self._audio_devices.audioOutputsChanged.connect(self._check_audio_output_device)
        self._audio_device_timer = QTimer(self)
        self._audio_device_timer.setInterval(AUDIO_AUDIT_MS)
        self._audio_device_timer.timeout.connect(self._check_audio_output_device)
        self._audio_device_timer.start()
        #: 各格开始录制的时刻（monotonic），用来刷「● REC 旁边的录制时长」
        self._recording_since: dict = {}
        self._record_clock = QTimer(self)
        self._record_clock.setInterval(1000)
        self._record_clock.timeout.connect(self._tick_record_clock)
        self._watch_history_last_tick = time.monotonic()
        self._watch_history_timer = QTimer(self)
        self._watch_history_timer.setInterval(1000)
        self._watch_history_timer.timeout.connect(self._tick_watch_history)
        self._watch_history_timer.start()
        self._record_clock.start()
        self.wall.tileClicked.connect(self._on_tile_clicked)
        self.wall.roomDropped.connect(self._on_room_dropped)
        self.wall.tileSwapped.connect(self._on_tile_swapped)
        self.wall.tileCreated.connect(self._wire_tile)
        for tile in self.wall.tiles:
            self._wire_tile(tile)

        bili.set_login_cookies(self.state.get("sessdata", ""), self.state.get("bili_jct", ""),
                               self.state.get("buvid3", ""))
        self._restore_ui()
        # 如果构造时显式指定了布局（自检/预览脚本会这么干），别被配置里的覆盖掉。
        # 记到哪个方向名下要看**布局本身**——构造时窗口还没尺寸，is_portrait() 不可靠。
        if layout_id not in ("", "auto"):
            key = ("layout_portrait" if layouts.is_portrait_layout(layout_id)
                   else "layout_landscape")
            self.state.setdefault("ui", {})[key] = layout_id
            self._pending_layout = layout_id
            # 显式指定了就尊重它：调用方可能就是想看看这个布局在各个尺寸下的样子，
            # 不要因为窗口方向不符就换成别的（自检/预览脚本依赖这一点）
            self.orientation = ("portrait" if layouts.is_portrait_layout(layout_id)
                                else "landscape")
        self._apply_orientation()          # 先按窗口方向把排布和布局定下来
        self.apply_danmaku_settings()
        self.apply_preview_settings()
        self._refresh_meta()

        # 插件：在界面都搭好之后再装载，插件里的注册/回调这时能拿到完整的窗口
        self.plugins = plugin_api.PluginManager(
            window=self,
            enabled=self.state.get("plugins_enabled"),
        )
        self.plugins.plugin_settings = self.state.setdefault("plugins", {})
        self.plugins._save_settings = lambda: config_module.save(self.current_state())
        plugin_api.set_manager(self.plugins)
        self.plugins.register_credentials('bilibili', bili._cookies,
            update=self._update_bilibili_credentials,
            identity_keys=('SESSDATA', 'bili_jct'), writable_fields=('buvid3',))
        self.plugins.load()
        for tile in self.wall.tiles:
            self.plugins.attach_tile(tile)
        self.refresh_skin()
        self._restore_platform_accounts()
        self._sync_platform_rooms()
        # 旧版虎牙网页卡片升级为格子播放；保留原关注、排序和置顶。
        for room in self.sidebar.rooms() + [tile.room for tile in self.wall.tiles]:
            platform = self.plugins.platform_for(str(room.get("room_id") or ""))
            if platform is not None:
                room.update(platform=platform.kind, playback_mode=platform.playback_mode)
                if callable(getattr(platform, "restore_follow_rooms", None)):
                    platform.restore_follow_rooms([room])
        self.sidebar.browser_url_resolver = self._room_browser_url
        print(f"[插件] {self.plugins.summary}", file=sys.stderr, flush=True)
        for entry, reason in self.plugins.skipped:
            print(f"[插件] 跳过 {entry}：{reason}", file=sys.stderr, flush=True)
        self._tray = SystemTray(self)
        QTimer.singleShot(0, lambda: self.plugins.emit(plugin_api.EVENT_STARTED))

        QTimer.singleShot(0, self._start_startup_tiles)
        # 封面和头像都先用本地留的那张顶上去（纯读文件、不联网），别让卡片空着
        # 等状态轮询 —— 收起的关注栏整条只剩一个头像，更等不得
        QTimer.singleShot(120, self.load_cached_covers)
        QTimer.singleShot(120, self.load_cached_avatars)
        QTimer.singleShot(800, self.refresh_account)
        QTimer.singleShot(1200, self.load_room_avatars)
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(self.poll_interval_ms())
        self._poll_timer.timeout.connect(self.refresh_status)
        self._poll_timer.start()
        QTimer.singleShot(1500, self.refresh_status)
        # 看过人数（和 B 站页面一致）单独拉，只查画面墙上的房间
        self._stats_timer = QTimer(self)
        self._stats_timer.setInterval(POLL_INTERVAL_MS)
        self._stats_timer.timeout.connect(self.refresh_stats)
        self._stats_timer.start()
        self._stats_refresh_timer = QTimer(self)
        self._stats_refresh_timer.setSingleShot(True)
        self._stats_refresh_timer.setInterval(1500)
        self._stats_refresh_timer.timeout.connect(self.refresh_stats)
        self._startup_update_timer = QTimer(self)
        self._startup_update_timer.setSingleShot(True)
        self._startup_update_timer.setInterval(2500)
        self._startup_update_timer.timeout.connect(self._check_startup_update)
        from . import online
        from pathlib import Path
        cached = online.load_plugin_cache(Path(config_module.data_root()) / 'cache' / 'plugin-catalog.json')
        self._set_plugin_updates(cached.get('offers', []))
        if os.environ.get("DDM_SETTINGS_PROCESS") == "1":
            QTimer.singleShot(1000, self._get_settings_process().warm)
        if self.settings.get("auto_update", False) or self.plugins.catalog():
            self._startup_update_timer.start()

    def _check_startup_update(self) -> None:
        return self.app_updates.check_startup_update()

    def _startup_update_ready(self, payload) -> None:
        return self.app_updates.startup_update_ready(payload)

    def _set_app_update(self, offer):
        return self.app_updates.set_app_update(offer)

    def _set_plugin_updates(self, offers):
        return self.app_updates.set_plugin_updates(offers)

    def _mark_updates(self):
        return self.app_updates.mark_updates()

    def _unread_app_update(self):
        return self.app_updates.unread_app_update()

    def _unread_plugin_updates(self):
        return self.app_updates.unread_plugin_updates()

    def _remember_updates(self, versions):
        return self.app_updates.remember_updates(versions)

    def _check_startup_plugins(self):
        return self.app_updates.check_startup_plugins()

    def _startup_plugins_ready(self, payload):
        return self.app_updates.startup_plugins_ready(payload)

    def _startup_plugins_finished(self):
        return self.app_updates.startup_plugins_finished()

    def _show_update_notice(self):
        return self.app_updates.show_update_notice()

    def _startup_update_failed(self, payload) -> None:
        return self.app_updates.startup_update_failed(payload)

    def _startup_update_finished(self) -> None:
        return self.app_updates.startup_update_finished()

    def _room_browser_url(self, room: dict) -> str:
        return self.room_placement.room_browser_url(room)

    def _open_room_browser(self, url: str) -> None:
        return self.room_placement.open_room_browser(url)

    def _normalize_room_input(self, text: str) -> str | None:
        return self.room_placement.normalize_room_input(text)

    # ---- 界面状态 ----
    def _restore_ui(self) -> None:
        self.sidebar.navigation.restore_order((self.state.get('ui') or {}).get('sidebar_tool_order'))
        self.sidebar.workspace_controls.restore_pins(
            (self.state.get('ui') or {}).get('workspace_pins'))
        self.sidebar.watch_history = WatchHistory(self.state.get("watch_history"))
        geometry = self.state.get("geometry")
        if geometry:
            try:
                self.restoreGeometry(QByteArray.fromBase64(geometry.encode("ascii")))
            except Exception:  # noqa: BLE001
                pass
        if (self.state.get("ui") or {}).get("sidebar_collapsed"):
            self.sidebar.set_collapsed(True, animate=False)
        self.sidebar.set_import_order(self.state.get("import_order") or [])
        self.sidebar.set_custom_order(self.state.get("custom_order") or [])
        self.sidebar.set_sort_mode(str(self.state.get("sort") or "custom"), notify=False)
        self.sidebar.apply_pins(self.state.get("pinned") or [])
        self.sidebar.set_folders(self.state.get("follow_folders") or [])
        self.shortcuts = dict(DEFAULT_SHORTCUTS)
        self.shortcuts.update((self.state.get("ui") or {}).get("shortcuts") or {})
        # 旧版画面弹幕的默认键为 D，随本次默认键调整到 B；其他自定义键保留。
        if (not (self.state.get("ui") or {}).get("danmaku_shortcut_default_b")
                and self.shortcuts.get("video_danmaku") == "D"):
            self.shortcuts["video_danmaku"] = "B"
        self._refresh_shortcuts()
        # 布局按方向分别记（老配置的 layout 键在 __init__ 里已经并到横屏那格）；
        # 第一次启动（配置里还没有这一项）＝ 第一次启动的默认布局
        ui = self.state.setdefault("ui", {})
        ui.setdefault("layout_landscape", layouts.FIRST_LAYOUT)
        ui.setdefault("layout_portrait", layouts.PORTRAIT_AUTO)

    # ---- 竖屏 / 横屏 ----
    def _build_arrangement(self, orientation: str) -> None:
        """按方向重新摆放侧栏和画面墙。

        横屏：侧栏在左（固定宽）+ 右侧画面墙。
        竖屏：侧栏变成顶部横栏（撑满宽）+ 下面画面墙。
        """
        return self.window_layout.build_arrangement(orientation)

    def is_portrait(self) -> bool:
        """窗口比高度矮（含接近方形）就算竖屏。"""
        width, height = max(self.width(), 1), max(self.height(), 1)
        return width <= height * PORTRAIT_MAX_RATIO

    def _saved_layout(self, orientation: str) -> str:
        return self.window_layout.saved_layout(orientation)

    @staticmethod
    def _layout_fits(layout_id: str, portrait: bool) -> bool:
        """这个布局能不能用在这个方向上。

        竖屏预设只会在竖屏下摆对（它是「主画面 16:9 + 小画面自动排」）；
        横屏的等分布局在竖屏下会把格子拉成竖长条。所以两边不能混用 ——
        混用就是拖回横屏后画面错位的原因。
        """
        if layout_id == "auto":
            return False
        return layouts.is_portrait_layout(layout_id) == bool(portrait)

    def _apply_orientation(self, orientation: str | None = None) -> None:
        """按窗口方向换排布（顶部横栏 / 左侧栏）和布局预设。"""
        return self.window_layout.apply_orientation(orientation)

    def resizeEvent(self, event) -> None:
        if (getattr(self, "_interactive_resize", False)
                and hasattr(self, "wall") and event.size() != event.oldSize()):
            self.wall.set_interactive_resize(True)
        super().resizeEvent(event)
        if (getattr(self, "_fullscreen_tile", None) is not None
                or not hasattr(self, "orientation") or self._closing
                or self._settling_resize or event.size() == event.oldSize()):
            return
        self._resize_dirty = True
        if self._startup_layout_pending:
            self._finish_interactive_resize()
        elif not self._interactive_resize:
            self._resize_idle_timer.start()

    def nativeEvent(self, event_type, message):
        if sys.platform == "win32" and QApplication.platformName() == "windows":
            from ctypes import wintypes

            msg = wintypes.MSG.from_address(int(message))
            # Keep caption dragging on the real HWND. Replacing it with a
            # preview at the drag threshold causes a visible window handoff.
            if msg.message == 0x0231:  # WM_ENTERSIZEMOVE
                self._begin_interactive_resize()
            elif msg.message == 0x0232:  # WM_EXITSIZEMOVE
                self._finish_interactive_resize()
            elif msg.message == 0x0005:  # WM_SIZE: maximize/restore may cross orientation
                previous = self._native_size_state
                self._native_size_state = int(msg.wParam)
                # Qt can resize child layouts before MainWindow.resizeEvent.
                # Arm the coalesced wall path before returning this native size.
                if (msg.wParam in (0, 2) and self._interactive_resize
                        and hasattr(self, "wall") and not self._closing
                        and not self._startup_layout_pending and self._fullscreen_tile is None):
                    self.wall.set_interactive_resize(True)
                    self._resize_dirty = True
                if msg.wParam == 2 or msg.wParam == 0 and previous == 2:
                    if (hasattr(self, "wall") and not self._closing
                            and not self._settling_resize and not self._startup_layout_pending
                            and self._fullscreen_tile is None):
                        self.wall.set_interactive_resize(True)
                        self._resize_dirty = True
                        # A restore can arrive after WM_ENTERSIZEMOVE. Only
                        # WM_EXITSIZEMOVE may settle an active native gesture.
                        if not self._interactive_resize:
                            self._resize_idle_timer.start()
        return super().nativeEvent(event_type, message)

    def _begin_interactive_resize(self) -> None:
        return self.window_layout.begin_interactive_resize()

    def _finish_interactive_resize(self) -> None:
        return self.window_layout.finish_interactive_resize()

    def _resize_orientation(self) -> str:
        return self.window_layout.resize_orientation(enter_ratio=PORTRAIT_ENTER_RATIO, exit_ratio=PORTRAIT_EXIT_RATIO)

    def hideEvent(self, event) -> None:
        self._resize_on_show = self._resize_on_show or self._resize_dirty
        self._cancel_interactive_resize()
        super().hideEvent(event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh_theme()
        if self._startup_layout_pending:
            self._finish_interactive_resize()
        elif self._resize_on_show and not self._closing:
            self._resize_on_show = False
            self._resize_dirty = True
            self._resize_idle_timer.start()

    def paintEvent(self, event) -> None:
        # Initial maximize messages must settle before the first visible frame;
        # later user resizes retain the existing coalesced path.
        self._startup_layout_pending = False
        super().paintEvent(event)

    def show_initial_maximized(self) -> None:
        # Windows can expose a maximized HWND before Qt receives its final
        # resize event. Size the hidden tree first, including the native caption.
        return self.window_layout.show_initial_maximized()

    def refresh_theme(self) -> None:
        window_fullscreen.sync_titlebar(self)

    def _cancel_interactive_resize(self) -> None:
        return self.window_layout.cancel_interactive_resize()

    # ---- 设置 ----
    def poll_interval_ms(self) -> int:
        minutes = int(self.settings.get("poll_minutes", 1) or 1)
        return max(1, min(30, minutes)) * 60_000

    def set_appearance(self, mode: str) -> None:
        return self.settings_control.set_appearance(mode)

    def _open_sidebar_settings(self):
        return self.settings_control.open_sidebar_settings()

    def _sidebar_card_mode_changed(self, enabled):
        return self.settings_control.sidebar_card_mode_changed(enabled)

    def _sc_preview_context(self):
        return self.settings_control.sc_preview_context()

    def _get_settings_process(self):
        return self.settings_control.get_settings_process()

    def _remote_settings_saved(self, changes):
        return self.settings_control.remote_settings_saved(changes)

    def _settings_host_request(self, message):
        return self.settings_control.settings_host_request(message)

    def _close_settings_host(self):
        return self.settings_control.close_settings_host()

    def _get_update_page(self, settings):
        return self.settings_control.get_update_page(settings)

    def _create_settings_dialog(self, settings=None, shortcuts=None):
        return self.settings_control.create_settings_dialog(settings, shortcuts, dialog_class=SettingsDialog)

    def open_settings(self, page: str = "general") -> bool:
        """一个窗口里选类别（常规 / 快捷键），和 Adobe 那类设置一样。"""
        return self.settings_control.open_settings(page, dialog_class=SettingsDialog)

    def _apply_settings_dialog(self, dialog, plugins_before):
        return self.settings_control.apply_settings_dialog(dialog, plugins_before, dialog_class=SettingsDialog)

    def refresh_skin(self):
        self.skin_controller.refresh()

    def set_skin(self, values):
        return self.settings_control.set_skin(values)

    def set_skin_parts(self, values):
        return self.settings_control.set_skin_parts(values)

    def _sync_platform_rooms(self) -> None:
        return self.room_placement.sync_platform_rooms()

    def current_state(self) -> dict:
        cookies = bili._cookies()
        return {
            "version": config_module.STATE_VERSION,
            "room_presets": deepcopy(self.room_presets),
            "user_notice_accepted": bool(self.state.get("user_notice_accepted", False)),
            "suspended_platform_rooms": self.state.get("suspended_platform_rooms", {}),
            "sessdata": cookies.get("SESSDATA", ""),
            "bili_jct": cookies.get("bili_jct", ""),
            "buvid3": cookies.get("buvid3", ""),
            "rooms": [str(room.get("room_id")) for room in self.sidebar.rooms()],
            "platform_rooms": {
                str(room["room_id"]): {key: room.get(key, "") for key in
                                       (("uname", "title", "platform", "playback_mode") +
                                        (("display_room_id",) if room.get("display_room_id") else ()) +
                                        (("anchor_uid", "sec_uid", "follow_account_ref", "resolved_room_id", "face")
                                         if room.get("platform") == "douyin" else ()))}
                for room in self.sidebar.rooms() if ":" in str(room.get("room_id") or "")
            },
            # 空格子也要存，下次打开还是原来的布局
            "wall": [
                {
                    "room_id": str(tile.room.get("room_id") or ""),
                    "muted": self._fullscreen_audio_saved.get(tile, bool(tile.muted)),
                    # 音量属于格子；即使格子为空也要保存，重启后继续沿用。
                    "volume": int(tile.volume),
                    "quality": int(tile.quality),
                    "audio_channel": int(tile.audio_channel),
                    "codec_overrides": dict(tile.codec_overrides),
                    "video_danmaku_enabled": tile.danmaku_button.isChecked(),
                    "video_danmaku_overrides": config_module.video_danmaku_overrides(tile.video_danmaku_overrides),
                }
                for tile in self.wall.tiles if not tile.property('pictureInPictureTemporary')
            ],
            "ui": {
                "picture_in_picture": self.picture_in_picture.state(),
                "tray_hint_shown": self._tray_hint_shown,
                "room_preset_id": self._active_room_preset_id,
                "sidebar_collapsed": self.sidebar.collapsed,
                "workspace_pins": self.sidebar.workspace_controls.pin_state(),
                "sidebar_tool_order": self.sidebar.navigation.order_state(),
                "layout_landscape": self._saved_layout("landscape"),
                "layout_portrait": self._saved_layout("portrait"),
                "corner_ratios": self.wall.corner_ratios(),
                "layout_ratios": self.wall.layout_ratios(),
                "pane_layouts": self.wall.pane_danmaku.state(),
                "shortcuts": dict(self.shortcuts),
                "danmaku_shortcut_default_b": True,
            },
            "pinned": list(self.sidebar.pinned),
            "sort": self.sidebar.sort_mode,
            "import_order": list(self.sidebar.import_order),
            "custom_order": list(self.sidebar.custom_order),
            "follow_folders": self.sidebar.folder_state(),
            "watch_history": self.sidebar.watch_history.state(),
            "settings": dict(self.settings),
            "emoticon_order": deepcopy(self.state.get("emoticon_order", {})),
            "geometry": str(self.saveGeometry().toBase64(),
                            "ASCII"),
            # 插件自己的配置项，以及「启用了哪些插件」（None = 全启用）
            "plugins": self.plugins.plugin_settings,
            "plugins_enabled": (None if self.plugins.enabled is None
                                else sorted(self.plugins.enabled)),
        }

    def _check_audio_output_device(self) -> None:
        return self.stream_playback.check_audio_output_device()

    def closeEvent(self, event) -> None:
        if self._tray.handle_close(event):
            return
        self.picture_in_picture.restore()
        # 先隐藏界面，再逐路终止播放并等待后台任务收尾。
        t0 = time.perf_counter()
        for dialog in list(self._codec_dialogs.values()):
            dialog.close()
        for dialog in list(self._stream_info_dialogs.values()):
            dialog.close()
        if self._fullscreen_tile is not None:
            self._exit_fullscreen()
        self._fullscreen_cursor.stop()
        self.hide()
        hide_ms = (time.perf_counter() - t0) * 1000
        # 迟到的取流回调不得访问正在释放的播放器。
        self._closing = True
        self._tray.shutdown()
        if getattr(self, "_settings_process", None) is not None:
            self._settings_process.stop()
        if getattr(self, '_app_update_page', None) is not None:
            self._app_update_page.stop()
        self._watch_history_timer.stop()
        self._startup_update_timer.stop()
        if self._startup_update_task is not None:
            self._startup_update_task.requestInterruption()
        if self._startup_plugin_task is not None:
            self._startup_plugin_task.requestInterruption()
        if self._update_notice is not None:
            self._update_notice.dismiss()
        follow_loader = getattr(self, "_follow_loader", None)
        if getattr(follow_loader, "platform", None) is not None:
            follow_loader.cancel()
        for thread in list(self._platform_info_running):
            thread.requestInterruption()
        self._stats_refresh_timer.stop()
        self.recorder.shutdown()
        self._audio_audit_timer.stop()      # 收尾期间别再去碰正在释放的播放器
        self._audio_device_timer.stop()
        self._record_clock.stop()
        self._super_chat_timer.stop()
        watchdog.stop()
        self.plugins.emit(plugin_api.EVENT_CLOSING)
        self.skin_controller.stop()
        self.plugins.unload()
        config_module.save(self.current_state())
        self.stop_danmaku()
        self.hover_preview.stop()
        self.playback_recovery.shutdown()
        players = list(self.players.values())
        self.players.clear()
        for player in players:
            player.release()
        self._wait_background()
        # 接收线程可能在关闭期间补齐设备 Cookie，收尾后再保存它。
        if self.state.get("buvid3", "") != bili._cookies().get("buvid3", ""):
            config_module.save(self.current_state())
        if self._startup_update_task is not None:
            self._startup_update_task.wait()
        if self._startup_plugin_task is not None:
            self._startup_plugin_task.wait()
        self._resolvers.clear()
        self._resolvers_running.clear()
        total_ms = (time.perf_counter() - t0) * 1000
        print(f"[关闭] 窗口 {hide_ms:.1f} ms 内隐藏；收尾（释放播放器+等线程）共 {total_ms:.1f} ms",
              file=sys.stderr, flush=True)
        super().closeEvent(event)
        app = QApplication.instance()
        if not app.quitOnLastWindowClosed():
            app.quit()

    def _wait_background(self) -> None:
        """等在跑的线程收尾；线程还在跑就析构，Qt 会直接崩。"""
        names = ("_account_loader", "_account_avatar_loader", "_room_avatar_loader",
                 "_status_avatar_loader", "_follow_avatar_loader", "_follow_loader",
                 "_cover_cache_loader", "_avatar_cache_loader",
                 "_cover_loader", "_aside_cover_loader",
                 "_poller", "_stats_poller")
        threads = [getattr(self, name, None) for name in names]
        threads.extend(self._avatar_loaders)
        threads.extend(self._super_chat_snapshots.values())
        threads.extend(self._super_chat_retired)
        threads.extend(self._resolvers_running)
        threads.extend(self._danmaku_retired)
        preview_threads = list(self.hover_preview._resolvers_running)
        threads.extend(preview_threads)
        deadline = time.time() + 2.5
        for thread in threads:
            if thread is None or not self._loader_running(thread):
                continue
            try:
                thread.wait(max(120, int((deadline - time.time()) * 1000)))
            except RuntimeError:             # 已被 Qt 回收
                pass
        self._avatar_loaders.clear()
        for thread in list(self._super_chat_retired) + list(self._super_chat_snapshots.values()):
            if self._loader_running(thread):
                thread.wait()
        self._super_chat_retired.clear()
        for thread in list(self._danmaku_retired):
            if self._loader_running(thread):
                thread.wait()
        self._danmaku_retired.clear()
        platform_threads = [thread for thread in list(self._resolvers_running) + preview_threads
                            if getattr(thread, "platform", None) is not None]
        poller = self._poller
        if poller is not None and getattr(poller, "platforms", None):
            platform_threads.append(poller)
        follow_loader = getattr(self, "_follow_loader", None)
        if getattr(follow_loader, "platform", None) is not None:
            platform_threads.append(follow_loader)
        for thread in platform_threads:
            if self._loader_running(thread):
                thread.wait()
        # 新增的平台查房间请求有超时；窗口已隐藏，等请求正常收尾再析构 QThread。
        for thread in list(self._platform_info_running):
            if self._loader_running(thread):
                thread.wait()
        self._platform_info_running.clear()

    def _clear_expanded_slots(self, layout_id: str) -> None:
        return self.window_layout.clear_expanded_slots(layout_id)

    def _prioritize_live_tiles(self, layout_id: str) -> None:
        """缩小布局时，用后面的开播格子填前面的未开播位置。"""
        return self.window_layout.prioritize_live_tiles(layout_id)

    def _on_layout_changed(self, layout_id: str) -> None:
        return self.window_layout.on_layout_changed(layout_id)

    def room_preset_snapshot(self):
        return self.room_preset_control.snapshot()

    def save_room_preset(self, name, preset_id=None):
        return self.room_preset_control.save(name, preset_id)

    def rename_room_preset(self, preset_id, name):
        return self.room_preset_control.rename(preset_id, name)

    def delete_room_preset(self, preset_id):
        return self.room_preset_control.delete(preset_id)

    def apply_room_preset(self, preset_id):
        return self.room_preset_control.apply(preset_id)

    def _reshape_window(self, portrait: bool) -> None:
        """把主窗口改成竖屏/横屏的形状（宽高对调，并夹在当前屏幕里）。

        窗口尺寸系统（Alt+Tab / 任务栏预览）拿的是**窗口本身**的形状：竖屏排布
        塞在横屏窗口里，预览就是一张拉伸的横屏。所以选另一个方向的布局时顺手把
        窗口也摆成那个方向；最大化状态下先还原，否则改不动尺寸。
        """
        return self.window_layout.reshape_window(portrait)

    def _on_pin_changed(self, pinned: list) -> None:
        self.state["pinned"] = list(pinned)
        config_module.save(self.current_state())

    def _on_sort_changed(self, mode: str) -> None:
        self.state["sort"] = mode
        self.state["import_order"] = list(self.sidebar.import_order)
        config_module.save(self.current_state())
        print(f"[排序] 关注列表改为：{dict(self.sidebar.SORT_MODES).get(mode, mode)}",
              file=sys.stderr, flush=True)

    def _on_order_changed(self) -> None:
        config_module.save(self.current_state())

    def _tick_watch_history(self):
        return self.room_placement.tick_watch_history()

    # ---- 播放 ----
    def _start_startup_tiles(self) -> None:
        return self.stream_playback.start_startup_tiles()

    def start_all(self) -> None:
        return self.stream_playback.start_all()

    def apply_quality_policy(self, *, restart: bool = True) -> list:
        """有主次布局时：主画面自动用原画，其余用 720P。"""
        return self.stream_playback.apply_quality_policy(restart=restart)

    def start_tile(self, tile, *, stream_quality: int | None = None) -> None:
        return self.stream_playback.start_tile(tile, stream_quality=stream_quality, resolver_type=StreamResolver)

    def _on_resolver_finished(self, tile, resolver) -> None:
        return self.stream_playback.resolver_finished(tile, resolver)

    def _play_on(self, tile, url: str, quality: int = 0, profile: str = "web",
                 options: list | None = None, headers: dict | None = None,
                 room_id: str = "", requested_quality: int = 0,
                 source_codec: str | None = None) -> None:
        return self.stream_playback.play_on(tile, url, quality, profile, options, headers,
            room_id, requested_quality, source_codec, player_type=TilePlayer)

    def _on_auto_quality(self, player, quality: int) -> None:
        return self.stream_playback.auto_quality(player, quality)

    def _on_decoder_fallback(self, player, mode: str) -> None:
        return self.codec_control.decoder_fallback(player, mode)

    def _emit_stream_resolved(self, tile, quality: int = 0) -> None:
        """把「这一格现在播的是哪路流」告诉插件（录像等要靠它拉同一路流）。"""
        return self.stream_playback.emit_stream_resolved(tile, quality)

    def media_options(self, tile=None) -> tuple[str, ...]:
        """按设置给每一路画面墙媒体选择 播放器 解码方式。"""
        return self.codec_control.media_options(tile)

    def _codec_settings(self, tile=None) -> dict:
        return self.codec_control.codec_settings(tile)

    def _is_bili_tile(self, tile) -> bool:
        return self.codec_control.is_bili_tile(tile)

    def _restart_codec_tile(self, tile) -> None:
        return self.codec_control.restart_codec_tile(tile)

    def _tile_codecs_changed(self, tile, before: dict) -> bool:
        return self.codec_control.tile_codecs_changed(tile, before)

    def _set_tile_codecs(self, tile, values: dict) -> None:
        return self.codec_control.set_tile_codecs(tile, values)

    def _keep_tile_codec(self, tile, requested: str, retained: str, *, unavailable: bool,
                         quality_note: str = "") -> None:
        return self.codec_control.keep_tile_codec(tile, requested, retained,
            unavailable=unavailable, quality_note=quality_note)

    def _codec_status(self, tile) -> str:
        return self.codec_control.codec_status(tile)

    def _open_tile_codecs(self, tile) -> None:
        return self.codec_control.open_tile_codecs(tile, dialog_type=CodecSettingsDialog)

    def _stream_info_snapshot(self, tile):
        return self.codec_control.stream_info_snapshot(tile)

    def _open_tile_stream_info(self, tile):
        return self.codec_control.open_tile_stream_info(tile)

    def _on_resolve_failed(self, tile, reason: str, requested_quality: int = 0,
                           *, login_required=False) -> None:
        return self.stream_playback.resolve_failed(tile, reason, requested_quality, login_required=login_required)

    def _on_player_state(self, tile, state: str) -> None:
        return self.stream_playback.on_player_state(tile, state)

    def _reset_stable_huya_retry(self, tile, player, generation):
        return self.playback_recovery.reset_stable_retry(tile, player, generation)

    def _on_picture_frozen(self, tile) -> None:
        return self.playback_recovery.picture_frozen(tile)

    def _retry_frozen_picture(self, tile) -> None:
        return self.playback_recovery.retry_frozen_picture(tile)

    def _on_picture_activity(self, tile) -> None:
        return self.playback_recovery.picture_activity(tile)

    def _clear_freeze_recovery(self, tile) -> None:
        return self.playback_recovery.clear_freeze(tile)

    def _schedule_retry(self, tile) -> None:
        return self.playback_recovery.schedule_retry(tile)

    def _retry_now(self, tile) -> None:
        return self.playback_recovery.retry_now(tile)

    def _stop_tile(self, tile) -> None:
        return self.stream_playback.stop_tile(tile)

    def _match_sync_holds(self, tile):
        return self.stream_playback.match_sync_holds(tile)

    def set_match_sync_playback(self, active):
        """Release hidden watching sessions, preserving independent recordings."""
        return self.stream_playback.set_match_sync_playback(active)

    def _sync_tile_playback(self, *, start_visible: bool = False) -> None:
        """只让**看得见**的格子播放。

        布局从 9 格换成 6 格时，多出来的格子以前只是 ``setVisible(False)``：播放器
        一步没停，还在解码、**还在出声**（用户报「没显示出来的格子也在响」）。这里
        把当前布局放不下的停掉；已选择的可见房间按需起播，新增位置保持空白。
        """
        return self.stream_playback.sync_tile_playback(start_visible=start_visible)

    def _offline_tile(self, tile) -> None:
        """这一路下播：停掉播放（画面变黑），格子继续留给它，等重新开播自动接上。"""
        return self.stream_playback.offline_tile(tile)

    def _tile_of(self, room_id: str):
        return self.stream_playback.tile_of(room_id)

    def _sender_tile(self):
        """发信号的那个格子；不是格子发的（定时器之类）返回 None。

        定位操作对象**别用 room_id 反查**：同一个直播间占了两个格子时（配置里
        存重了、或同一张卡片被拖上两次），反查只命中列表里第一个 —— 于是「静音
        这一格」把另一格的播放器静音了，这一格反倒还在出声，而标志是画在自己
        身上的、照样亮着。用户报的「开这格静音，旁边那格声音不对」就是这个。
        这些信号都是直接连接的，sender() 可靠；反查只留作兜底。
        """
        return self.stream_playback.sender_tile()

    def _prepare_room(self, room: dict) -> dict:
        """给新建格子补初始声音；已有格子的静音和音量由 Tile 保留。"""
        return self.room_placement.prepare_room(room)

    def _room_dict(self, room_id: str) -> dict | None:
        return self.room_placement.room_dict(room_id)

    # ---- 拖拽 ----
    def _on_room_dropped(self, tile, room_id: str) -> None:
        return self.room_placement.drop_room(tile, room_id)

    def _on_tile_swapped(self, source_room_id: str, target_tile) -> None:
        return self.room_placement.swap_tiles(source_room_id, target_tile)

    def _hot_swap(self, source, target) -> bool:
        return self.room_placement.hot_swap(source, target)

    def _tile_of_player(self, player):
        """播放器现在挂在哪个格子上（格子换位置之后连接不用重接，靠这个现查）。"""
        return self.stream_playback.tile_of_player(player)

    # ---- 直播状态轮询 ----
    def refresh_stats(self) -> None:
        return self.room_status.refresh_stats(StatsPoller)

    def _on_stats_finished(self, poller) -> None:
        return self.room_status.stats_finished(poller)

    def _on_stats_updated(self, stats: dict) -> None:
        return self.room_status.apply_stats(stats)

    def refresh_status(self, *, force: bool = False) -> None:
        return self.room_status.refresh_status(StatusPoller, force=force)

    def _on_poller_finished(self, poller) -> None:
        return self.room_status.status_finished(poller)

    def _on_status_failed(self, reason: str) -> None:
        return self.room_status.status_failed(reason)

    def refresh_follow(self) -> None:
        return self.room_status.refresh_follow()

    def _on_status_updated(self, status: dict) -> None:
        return self.room_status.apply_status(status)

    # ---- 全局操作 ----
    def _on_tile_clicked(self, room: dict) -> None:
        # 信号带过来的字典是副本，用房间号比较（不能比较对象身份）
        return self.stream_playback.on_tile_clicked(room)

    # ---- 单个格子的操作 ----
    def _on_volume_changed(self, room: dict, value: int) -> None:
        return self.stream_playback.on_volume_changed(room, value)

    def _on_audio_changed(self, room: dict, value: int) -> None:
        return self.stream_playback.on_audio_changed(room, value)

    def _on_quality_changed(self, room: dict, quality: int) -> None:
        # 注意：Qt 信号传过来的 dict 是副本，必须写回格子自己的字典
        return self.stream_playback.on_quality_changed(room, quality)

    def _on_mute_changed(self, room: dict, muted: bool) -> None:
        return self.stream_playback.on_mute_changed(room, muted)

    def _replay_scope(self) -> str:
        return self.capture_control.replay_scope()

    def _recording_enabled(self) -> bool:
        return self.capture_control.recording_enabled()

    def _sync_recording_switch(self) -> None:
        return self.capture_control.sync_recording_switch()

    def _replay_enabled(self) -> bool:
        return self.capture_control.replay_enabled()

    def _replay_max_tiles(self) -> int:
        return self.capture_control.replay_max_tiles()

    def _drop_pure_caches(self, *, preserve_manual: bool = False) -> None:
        return self.capture_control.drop_pure_caches(preserve_manual=preserve_manual)

    def _sync_replay_scope(self) -> None:
        return self.capture_control.sync_replay_scope()

    def _audit_audio(self) -> None:
        """保持每格的独立音量、静音和声道。"""
        return self.stream_playback.audit_audio()

    def _on_reload(self, room: dict) -> None:
        return self.stream_playback.on_reload(room)

    def _on_pause_toggled(self, room: dict) -> None:
        return self.stream_playback.on_pause_toggled(room)

    def _report_fullscreen_cost(self, action: str, started: float, covered: float,
                                switched: float, done: float) -> None:
        """打一行分段耗时。

        记录窗口样式与格子布局的耗时；实时视频在切换期间保持播放。
        有这几个数，下次再觉得卡就知道该动哪一段，而不是从头猜。
        """
        return self.fullscreen_control.report_fullscreen_cost(action, started, covered, switched, done)

    def _sync_fullscreen_audio(self) -> None:
        return self.fullscreen_control.sync_fullscreen_audio()

    def _upgrade_fullscreen_quality(self, tile: Tile) -> bool:
        return self.fullscreen_control.upgrade_fullscreen_quality(tile)

    def _on_fullscreen(self, tile: Tile) -> None:
        return self.fullscreen_control.on_fullscreen(tile)

    def _exit_fullscreen(self) -> None:
        return self.fullscreen_control.exit_fullscreen()

    def _clear_tile_room(self, tile: Tile) -> None:
        return self.room_placement.clear_tile_room(tile)

    def _clear_wall(self) -> None:
        self.wall_removal.toggle_menu()

    def _on_close_tile(self, room: dict) -> None:
        """关掉这一路，但留下空格子等新的直播间拖进来。"""
        return self.room_placement.on_close_tile(room)

    def _wire_tile(self, tile) -> None:
        if hasattr(self, 'plugins'):
            self.plugins.attach_tile(tile)
        # 格子创建时接线一次；之后填入或替换房间不再重复连接。
        if getattr(tile, "_actions_wired", False):
            return
        for attribute, key in (('pause_button', 'pause'), ('volume_button', 'volume'),
                ('danmaku_button', 'danmaku'), ('danmaku_settings_button', 'danmaku_settings'),
                ('recording_button', 'recording'), ('fullscreen_button', 'fullscreen')):
            button = getattr(tile, attribute)
            button.setProperty('skinPart', 'buttons.' + key)
            button.setProperty('skinIconOnly', key in ('pause', 'volume', 'danmaku_settings', 'fullscreen'))
        tile.qualityChanged.connect(self._on_quality_changed)
        tile.codecSettingsRequested.connect(lambda t=tile: self._open_tile_codecs(t))
        tile.streamInfoRequested.connect(lambda t=tile: self._open_tile_stream_info(t))
        tile.muteToggled.connect(self._on_mute_changed)
        tile.volumeChanged.connect(self._on_volume_changed)
        tile.audioChannelChanged.connect(self._on_audio_changed)
        tile.reloadRequested.connect(self._on_reload)
        tile.pauseToggled.connect(self._on_pause_toggled)
        if not getattr(tile, "_recording_wired", False):
            tile.recordingRequested.connect(lambda t=tile: self._toggle_recording(t))
            tile._recording_wired = True
        # 录制总开关关掉时，新格子也别露出「● 录制」按钮
        setter = getattr(tile, "set_recording_available", None)
        if setter is not None:
            setter(self._recording_enabled())
        tile.fullscreenRequested.connect(self._on_fullscreen)
        tile.closeRequested.connect(self._on_close_tile)
        tile.pluginMenuRequested.connect(lambda t=tile: self._fill_plugin_menu(t))
        tile.apply_video_danmaku_settings(self.settings)
        tile.video_danmaku.superChatSettingsChanged.connect(self._on_video_danmaku_settings_changed)
        tile.video_danmaku.superChatDismissed.connect(lambda chat_id, t=tile: self._dismiss_super_chat(str(t.room.get('room_id') or ''), chat_id))
        tile.videoDanmakuChanged.connect(self._on_video_danmaku_changed)
        tile.videoDanmakuSettingsChanged.connect(self._on_video_danmaku_settings_changed)
        tile.videoDanmakuAdvancedRequested.connect(lambda: self.open_settings("danmaku"))
        tile._actions_wired = True


    def _fill_plugin_menu(self, tile) -> None:
        """右键菜单弹出前，收集本体录制和插件操作。"""
        manager = getattr(self, "plugins", None)
        collected = []
        session = self.recorder.sessions.get(tile)
        if not self._recording_enabled():
            pass                        # 录制总开关关掉：菜单里不放录制项
        elif session and session.recording:
            collected.append(("● 停止录制这一路", lambda t=tile: self.recorder.stop(t)))
        else:
            collected.append(("● 开始录制这一路", lambda t=tile:
                              self._start_capture(t, recording=True)))
        if self._replay_enabled():
            if session:
                minutes = int(session.settings.get("recording_replay_minutes", 3))
                collected.append((f"保存最近约 {minutes} 分钟", lambda t=tile:
                                  self.recorder.save_replay(t)))
                if not session.recording:
                    collected.append(("停止即时回放缓存", lambda t=tile: self._stop_replay(t)))
            elif tile.room.get("room_id"):
                collected.append(("开启即时回放缓存", lambda t=tile: self._start_replay(t)))
        if manager is not None:
            for label, callback, name in manager.tile_actions(tile):
                collected.append((label, lambda cb=callback: manager.run_action(cb)))
        tile.plugin_actions = collected

    def _start_replay(self, tile) -> None:
        return self.capture_control.start_replay(tile)

    def _stop_replay(self, tile) -> None:
        return self.capture_control.stop_replay(tile)

    def _toggle_recording(self, tile) -> None:
        return self.capture_control.toggle_recording(tile)

    def _start_capture(self, tile, *, recording: bool) -> None:
        return self.capture_control.start_capture(tile, recording=recording)

    def _refresh_recording_source(self, session) -> None:
        return self.capture_control.refresh_recording_source(session, resolver_type=StreamResolver)

    def _finish_pending_capture(self, tile) -> None:
        return self.capture_control.finish_pending_capture(tile)

    def _restore_capture_quality(self, tile) -> None:
        return self.capture_control.restore_capture_quality(tile)

    def _record_state_changed(self, tile) -> None:
        return self.capture_control.record_state_changed(tile)

    def _tick_record_clock(self) -> None:
        return self.capture_control.tick_record_clock()

    def _record_notice(self, message: str, room=None) -> None:
        return self.notice_control.record_notice(message, room)

    def _show_notice(self, message: str, *, rooms=(), kind="info", on_click=None, file_path=None,
                     notice_key=None, pending=False, auto_room_link=True) -> None:
        return self.notice_control.show_notice(message, rooms=rooms, kind=kind, on_click=on_click, file_path=file_path, notice_key=notice_key, pending=pending, auto_room_link=auto_room_link)

    def _place_live_notice_rooms(self, rooms):
        self.room_placement.place_live_notice_rooms(rooms)

    # ---- 房间增删 ----
    def open_add_room(self) -> None:
        return self.room_placement.open_add_room(dialog_type=AddRoomDialog)

    def _add_room_id(self, room_id: str, *, folder_id: str = "") -> None:
        return self.room_placement.add_room_id(room_id, folder_id=folder_id, resolver_type=InfoResolver)

    def _on_platform_room_failed(self, resolver, platform, room_id, *, folder_id=""):
        return self.room_placement.on_platform_room_failed(resolver, platform, room_id, folder_id=folder_id)

    def _on_room_added(self, room: dict, *, folder_id: str = "") -> None:
        return self.room_placement.on_room_added(room, folder_id=folder_id, max_tiles=MAX_TILES)

    def add_to_wall(self, room: dict, *, empty_only=False) -> None:
        return self.room_placement.add_to_wall(room, empty_only=empty_only, max_tiles=MAX_TILES)

    def remove_room(self, room: dict) -> None:
        return self.room_placement.remove_room(room)

    def remove_rooms(self, rooms: list) -> None:
        return self.room_placement.remove_rooms(rooms)

    # ---- 登录 / 导入关注 ----
    def _follow_platforms(self) -> dict:
        return self.account_control.follow_platforms()

    def _account_dialog_platforms(self) -> dict:
        return self.account_control.account_dialog_platforms()

    def _login_choices(self) -> list:
        return self.account_control.login_choices()

    def _account_platforms(self) -> dict:
        return self.account_control.account_platforms()

    def _account_kind(self) -> str:
        return self.account_control.account_kind()

    def _restore_platform_accounts(self) -> None:
        return self.account_control.restore_platform_accounts()

    def _cache_douyin_follows(self, rooms, *, pending=None) -> None:
        return self.account_control.cache_douyin_follows(rooms, pending=pending)

    def _render_account(self, *, load_avatar=True) -> None:
        return self.account_control.render_account(load_avatar=load_avatar, cached_avatar=load_cached_avatar)

    def _load_account_avatar(self, kind, account):
        return self.account_control.load_account_avatar(kind, account, avatar_type=AvatarLoader)

    def refresh_account(self, *, retry: bool = True) -> None:
        """刷新侧栏底部的账号信息。"""
        return self.account_control.refresh_account(retry=retry, loader_type=AccountLoader)

    def _on_account_loaded(self, account: dict) -> None:
        return self.account_control.on_account_loaded(account)

    def _clear_platform_account(self, kind: str) -> None:
        return self.account_control.clear_platform_account(kind)

    def load_cached_covers(self) -> None:
        return self.room_images.load_cached_covers(CachedCoverLoader)

    def load_cached_avatars(self) -> None:
        return self.room_images.load_cached_avatars(CachedAvatarLoader)

    def load_room_avatars(self) -> None:
        return self.room_images.load_room_avatars()

    def load_avatars_for(self, rooms: list) -> None:
        return self.room_images.load_avatars_for(rooms)

    def _load_room_banners(self, rooms):
        return self.room_images.load_banners(rooms)

    def _on_room_banner(self, room_id, pixmap):
        return self.room_images.apply_banner(room_id, pixmap)

    def _on_room_artwork(self, room_id, pixmap, kind):
        return self.room_images.apply_artwork(room_id, pixmap, kind)

    def _start_avatar_loader(self, items: dict, slot, subdir: str = "avatars"):
        return self.room_images.start_loader(items, slot, AvatarLoader, subdir=subdir)

    @staticmethod
    def _loader_running(loader) -> bool:
        try:
            return loader.isRunning()
        except RuntimeError:                 # 已经被 Qt 回收
            return False

    def _on_room_avatar(self, room_id: str, pixmap) -> None:
        return self.room_images.apply_avatar(room_id, pixmap)

    def _on_room_cover(self, room_id: str, pixmap) -> None:
        return self.room_images.apply_cover(room_id, pixmap)

    def logout(self, kind=None) -> None:
        return self.account_control.logout(kind)

    def open_login(self, platform_kind=None, *, reauthenticate=False) -> None:
        return self.account_control.open_login(platform_kind, reauthenticate=reauthenticate)

    def _open_account_dialog(self, providers, *, import_follows=False, platform_kind="bilibili",
                             reauthenticate=False):
        return self.account_control.open_account_dialog(providers, import_follows=import_follows, platform_kind=platform_kind, reauthenticate=reauthenticate)

    def _update_bilibili_credentials(self, changes: dict) -> None:
        return self.account_control.update_bilibili_credentials(changes)

    def _on_login(self, sessdata: str) -> None:
        return self.account_control.on_login(sessdata)

    def open_import_follows(self) -> None:
        return self.account_control.open_import_follows()

    def _import_selected_follows(self, selected: list, *, folder_id: str = "",
                                 removed_ids=(), move_existing=False, folder_room_ids=None, pending_count=0) -> None:
        return self.account_control.import_selected_follows(selected, folder_id=folder_id, removed_ids=removed_ids, move_existing=move_existing, folder_room_ids=folder_room_ids, pending_count=pending_count)

    def _finish_follow_import(self, selected, added_rooms, *, folder_id, move_existing,
                              folder_room_ids=None, pending_count):
        return self.account_control.finish_follow_import(selected, added_rooms, folder_id=folder_id, move_existing=move_existing, folder_room_ids=folder_room_ids, pending_count=pending_count)

    def _refresh_meta(self) -> None:
        """只负责画面墙的显隐（右侧原来那行文字已经去掉，画面填满）。"""
        return self.account_control.refresh_meta()

    def _connect_danmaku_panel(self, panel):
        return self.danmaku_lifecycle.connect_danmaku_panel(panel)

    def switch_tile_to_danmaku(self, cell=-1):
        return self.danmaku_lifecycle.switch_tile_to_danmaku(cell)

    def _apply_pane_menu(self, bindings):
        return self.danmaku_lifecycle.apply_pane_menu(bindings)

    def configure_wall_panes(self, bindings):
        return self.danmaku_lifecycle.configure_wall_panes(bindings)

    def _pane_configuration_changed(self):
        return self.danmaku_lifecycle.pane_configuration_changed()

    # ---- 弹幕 ----
    def _danmaku_target_room(self) -> dict:
        """弹幕格跟着主画面走；没有主画面就跟第一路有人的画面。"""
        return self.danmaku_lifecycle.danmaku_target_room()

    def sync_danmaku(self) -> None:
        return self.danmaku_lifecycle.sync_danmaku()

    def _on_video_danmaku_changed(self, enabled: bool) -> None:
        return self.danmaku_lifecycle.on_video_danmaku_changed(enabled)

    def _on_video_danmaku_settings_changed(self, values: dict) -> None:
        return self.danmaku_lifecycle.on_video_danmaku_settings_changed(values)

    def start_danmaku(self, room_id: str, uname: str = "") -> None:
        return self.danmaku_lifecycle.start_danmaku(room_id, uname)

    def _ensure_danmaku_client(self, room_id: str, *, for_panel: bool = False):
        return self.danmaku_lifecycle._ensure_danmaku_client(room_id, client_type=DanmakuClient, for_panel=for_panel)

    def _load_super_chat_snapshot(self, room_id: str, client=None) -> None:
        return self.danmaku_lifecycle._load_super_chat_snapshot(room_id, client, snapshot_type=SuperChatSnapshot)

    def _on_super_chat_snapshot(self, room_id: str, events: list, *, source=None) -> None:
        return self.danmaku_lifecycle._on_super_chat_snapshot(room_id, events, source=source)

    def _on_super_chat_snapshot_finished(self, room_id: str, source) -> None:
        return self.danmaku_lifecycle._on_super_chat_snapshot_finished(room_id, source)

    def _on_danmaku_finished(self, room_id: str, source) -> None:
        return self.danmaku_lifecycle._on_danmaku_finished(room_id, source)

    def stop_danmaku(self) -> None:
        return self.danmaku_lifecycle.stop_danmaku()

    def _stop_danmaku_client(self, room_id: str) -> None:
        return self.danmaku_lifecycle._stop_danmaku_client(room_id)

    def apply_danmaku_settings(self) -> None:
        """把设置里的弹幕字体、字号、保留条数交给弹幕格。"""
        return self.danmaku_lifecycle.apply_danmaku_settings()

    def _on_danmaku_font_size(self, value: int) -> None:
        """面板上拖了字号：记住并延迟写盘（拖一次会发很多次信号）。"""
        return self.danmaku_lifecycle.on_danmaku_font_size(value)

    def apply_preview_settings(self) -> None:
        """关注列表样式与悬停预览开关。"""
        return self.settings_control.apply_preview_settings()

    def _danmaku_blocked(self, text: str) -> bool:
        """命中屏蔽词就不显示这条弹幕（大小写不敏感）。"""
        return self.danmaku_lifecycle.danmaku_blocked(text)

    def _on_danmaku_message(self, source, event: dict) -> None:
        return self.danmaku_lifecycle.on_danmaku_message(source, event)

    def _dismiss_super_chat(self, room_id: str, chat_id: str) -> None:
        return self.danmaku_lifecycle.dismiss_super_chat(room_id, chat_id)

    def _publish_super_chats(self, room_id: str) -> None:
        return self.danmaku_lifecycle.publish_super_chats(room_id)

    def _tick_super_chats(self) -> None:
        return self.danmaku_lifecycle.tick_super_chats()

    def _on_danmaku_status(self, source, text: str) -> None:
        return self.danmaku_lifecycle.on_danmaku_status(source, text)

    # ---- 快捷键 ----
    def _refresh_shortcuts(self) -> None:
        return self.shortcut_control.refresh_shortcuts()

    def _sync_input_shortcuts(self, *_args) -> None:
        return self.shortcut_control.sync_input_shortcuts(*_args)

    def _tile_under_cursor(self):
        """鼠标现在压在哪一格的画面上（没有就 None）。

        **不能用 QApplication.widgetAt**：格子的画面区是 播放器 的原生窗口，不是 Qt
        控件；鼠标停在画面上时 widgetAt 拿不到那一格（顶多给回主窗口），
        于是 F（全屏）/ M / Alt+M 全都按不动 —— 用户报的「切换画布完全失效」
        就是这个。改成拿光标全局坐标和每个格子的矩形比，跟画面是不是原生窗口无关。
        """
        return self.shortcut_control.tile_under_cursor()

    def keyPressEvent(self, event) -> None:
        pressed = QKeySequence(event.keyCombination()).toString()
        if pressed == self.shortcuts.get("danmaku_input") or (
                pressed == "Enter" and self.shortcuts.get("danmaku_input") == "Return"):
            super().keyPressEvent(event)
            return
        if not self._handle_shortcut(pressed):
            super().keyPressEvent(event)

    def _handle_shortcut(self, pressed: str) -> bool:
        return self.shortcut_control.handle_shortcut(pressed)

    def _toggle_mute_under_cursor(self) -> None:
        """M：静音 / 取消静音鼠标所在的那一路（只动这一路，别的格子不变）。"""
        return self.shortcut_control.toggle_mute_under_cursor()

    def _cycle_audio_under_cursor(self) -> None:
        """E：鼠标所在格子依次启用双声道、左声道、右声道、静音。"""
        return self.shortcut_control.cycle_audio_under_cursor()

    def _toggle_solo_audio(self) -> None:
        """Alt+M：只让鼠标悬停的那一路有声，其他格子一律静音。

        鼠标不在任何格子上时等于「全部静音」——这也是想安静下来时最顺手的按法。
        """
        return self.shortcut_control.toggle_solo_audio()


def _launch_restart() -> bool:
    arguments = list(sys.argv[1:])
    if not getattr(sys, "frozen", False):
        arguments.insert(0, os.path.join(config_module.REPO, "main.py"))
    started, _pid = QProcess.startDetached(sys.executable, arguments, config_module.REPO)
    return started


def _launch_update(plan_path) -> bool:
    import json
    with open(plan_path, encoding="utf-8") as handle:
        plan = json.load(handle)
    executable = os.path.join(plan["stage"], plan["new_exe"])
    started, _pid = QProcess.startDetached(executable, ["--apply-update", plan_path], plan["stage"])
    return started


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    t0 = time.perf_counter()                # 量化启动耗时：窗口多久才出现
    try:                                    # 控制台可能是 GBK，避免房间名里的特殊字符导致崩溃
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass
    app = QApplication(argv)
    instance = None
    if getattr(sys, "frozen", False):
        try:
            instance = SingleInstance(app)
            if not instance.start():
                return 0
        except (OSError, RuntimeError) as error:
            QMessageBox.critical(None, "无法启动软件", str(error))
            return 1
    log_path = setup_file_log()
    from .localization import install_chinese_translations
    install_chinese_translations(app)
    app.setApplicationName(version_module.DISPLAY_NAME)
    app.setStyleSheet(theme.qss())
    for icon_path in (os.path.join(config_module.REPO, "assets", "favicon.ico"),
                      os.path.join(config_module.REPO, "favicon.ico")):
        if os.path.isfile(icon_path):        # 有图标文件就用，没有也不影响启动
            app.setWindowIcon(QIcon(icon_path))
            break

    state = config_module.load()
    theme.apply((state.get("settings") or {}).get("appearance_mode", "dark"))
    from .user_notice import confirm_user_notice
    confirm_user_notice(state)
    from .update_install import clean_previous
    clean_previous(config_module.REPO, config_module.data_root())
    from .legacy_cleanup import start_legacy_cleanup
    start_legacy_cleanup(config_module.REPO)
    t_load = time.perf_counter()
    settings = dict(config_module.DEFAULT_SETTINGS)
    settings.update(state.get("settings") or {})
    # 诊断：把注入本进程的第三方模块（FPS Monitor / RTSS / 游戏覆盖层这类会 hook
    # 画面的工具）写进日志，方便排查「画面莫名崩溃」时确认现场。只记录，不改行为。
    _paths = overlay.module_paths()
    _hits = overlay.overlays(_paths)
    _foreign = overlay.foreign_modules(_paths)
    if _foreign:
        print(f"[覆盖层] 进程内非系统注入模块：{_foreign}", file=sys.stderr, flush=True)
    if _hits:
        print(f"[覆盖层] 检测到可能 hook 画面的工具：{_hits}",
              file=sys.stderr, flush=True)
    sidebar, wall = config_module.build_rooms(state) if state else ([], [])
    t_rooms = time.perf_counter()
    print(f"关注房间 {len(sidebar)} 个，画面墙 {len(wall)} 个格子"
          + ("" if state else "（全新配置）"))
    decode_mode = settings.get("decode_mode") or (
        "auto" if settings.get("hw_decode", True) else "none")
    print(f"[播放器] libmpv {TilePlayer.backend_version()} 解码方式={decode_mode}",
          file=sys.stderr, flush=True)

    window = MainWindow(sidebar, wall,
                        layout_id=(state.get("ui") or {}).get("layout") or "",
                        state=state)
    from .on_demand_diagnostics import DiagnosticEndpoint
    window._on_demand_diagnostics = DiagnosticEndpoint(
        window, os.path.join(config_module.data_root(), 'logs'), config_module.REPO)
    app.setQuitOnLastWindowClosed(False)
    t_window = time.perf_counter()
    # 界面卡死看门狗：主线程靠这个 QTimer 报平安，卡死时日志里会留下所有线程的调用栈
    session = diagnostics.get_session()
    watchdog.start(session.crash_path if session else log_path)
    ticker = QTimer(window)
    ticker.setInterval(watchdog.TICK_MS)
    ticker.timeout.connect(watchdog.tick)
    ticker.start()
    window.show_initial_maximized()
    if instance is not None:
        instance.set_restore(lambda: restore_main_window(window))
    if config_module.DATA_MIGRATION_ERROR:
        QMessageBox.warning(window, '数据迁移未完成', config_module.DATA_MIGRATION_ERROR)
    t_show = time.perf_counter()
    print(f"[启动] 配置加载 {(t_load - t0) * 1000:.0f} ms | "
          f"房间占位 {(t_rooms - t_load) * 1000:.0f} ms | "
          f"界面构建 {(t_window - t_rooms) * 1000:.0f} ms | "
          f"窗口显示 {(t_show - t0) * 1000:.0f} ms",
          file=sys.stderr, flush=True)
    code = app.exec()
    settings_process = getattr(window, '_settings_process', None)
    settings_stopped = settings_process is None or settings_process.finish()
    watchdog.stop()
    if session is not None:
        faulthandler.enable(file=session.crash_handle, all_threads=True)
    if instance is not None:
        instance.close()  # A settings restart must acquire a new instance lock.
    if window._update_plan:
        update_error = '无法启动更新助手，原程序已保留，请稍后重新下载更新。'
        try:
            if not settings_stopped:
                raise OSError('独立设置进程尚未退出，更新未执行；请完全退出软件后重试。')
            launched = _launch_update(window._update_plan)
        except (OSError, ValueError) as error:
            launched = False
            update_error = str(error)
            print(f"[更新] 启动助手失败：{error}", file=sys.stderr, flush=True)
        if not launched:
            QMessageBox.critical(None, "更新未执行", update_error)
    elif window._restart_requested and not _launch_restart():
        QMessageBox.critical(None, "重启失败", "无法重新启动软件，请手动打开程序。设置已保存。")
    # 关窗时可能还有网络线程在收尾，Qt / 播放器 的析构顺序会偶发崩在退出瞬间，
    # 配置在 closeEvent 里已经存好了，这里直接退出进程最稳。
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:  # noqa: BLE001
        pass
    diagnostics.close()
    os._exit(code)


if __name__ == "__main__":
    raise SystemExit(main())
