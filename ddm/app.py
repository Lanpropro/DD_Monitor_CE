"""应用外壳：左侧房间列表 + 右侧画面墙。

画面墙上的每个格子是一个"播放位"：关掉某一路会留下空格子，等着把侧栏里的
直播间拖进来；播放器按格子持有，和房间号解耦。
"""
import os
import sys
import time
import webbrowser
from urllib.parse import urlsplit

from PySide6.QtCore import QByteArray, Qt, QTimer
from PySide6.QtGui import QCursor, QIcon, QKeySequence, QPixmap
from PySide6.QtWidgets import (
    QApplication, QBoxLayout, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QStackedWidget,
    QVBoxLayout, QWidget,
)

from . import bili
from . import config as config_module
from . import layouts
from . import overlay
from . import plugins as plugin_api
from . import theme
from . import version as version_module
from . import watchdog
from . import window_fullscreen
from .audio_output import linear_to_vlc_volume
from .danmaku import DanmakuClient
from .bili import (
    AccountLoader, FollowLoader, InfoResolver, StatsPoller, StatusPoller, StreamResolver,
)
from .dialogs import (
    SHORTCUT_ACTIONS, AddRoomDialog, FollowImportDialog, SettingsDialog,
)
from .images import AvatarLoader, CachedCoverLoader
from . import player as player_module
from .player import TilePlayer
from .preview import HoverPreview
from .recording import RecordingManager
from .widgets import Sidebar, Tile, WallGrid

#: 音频巡检间隔（毫秒）：格子记的静音 / 音量和播放器**实际**的值走散了就按格子重下发
AUDIO_AUDIT_MS = 2_000

MAX_TILES = 16
POLL_INTERVAL_MS = 60_000        # 关注列表状态轮询：1 分钟
#: 窗口「宽 / 高」小于这个值就按竖屏处理（含接近方形）
PORTRAIT_MAX_RATIO = 0.9
RETRY_BASE_SECONDS = 5           # 断流后的重连间隔（指数退避）
RETRY_MAX_SECONDS = 60
FREEZE_RETRY_SECONDS = 5         # 自动刷新后仍静止时的再次刷新间隔
DEFAULT_SHORTCUTS = {key: default for key, _label, default in SHORTCUT_ACTIONS}


def setup_file_log() -> str:
    """把标准错误同时写进 logs/ddm-日期.log，方便排查（控制台可能被关掉）。"""
    log_dir = os.path.join(config_module.REPO, "logs")
    os.makedirs(log_dir, exist_ok=True)
    path = os.path.join(log_dir, f"ddm-{time.strftime('%Y-%m-%d')}.log")
    original = sys.stderr
    try:
        handle = open(path, "a", encoding="utf-8", buffering=1)
    except Exception:  # noqa: BLE001
        return ""

    class _Tee:
        def write(self, data: str) -> int:
            if original is not None:
                try:
                    original.write(data)
                except Exception:  # noqa: BLE001
                    pass
            try:
                handle.write(data)
            except Exception:  # noqa: BLE001
                pass
            return len(data)

        def flush(self) -> None:
            if original is not None:
                try:
                    original.flush()
                except Exception:  # noqa: BLE001
                    pass

    sys.stderr = _Tee()
    print(f"日志文件: {path}", file=sys.stderr)
    return path

EMPTY_HINT = ("还没有直播间\n\n"
              "点左下角「+ 添加直播间」填房间号，\n"
              "或者用「导入关注」从 B 站账号导入")


class MainWindow(QMainWindow):
    def __init__(self, rooms: list[dict], wall_rooms: list[dict] | None = None,
                 layout_id: str = "", state: dict | None = None):
        super().__init__()
        self.setWindowTitle(f"{version_module.DISPLAY_NAME} {version_module.VERSION_TAG}")
        self.setFocusPolicy(Qt.StrongFocus)     # 让窗口能接收快捷键
        self.rooms = rooms
        self.state = state or {}
        self.layout_id = layout_id
        self.players: dict[object, TilePlayer] = {}      # 按格子持有播放器
        self._resolvers: dict[object, StreamResolver] = {}
        #: 正在关窗。取流线程的 resolved 是队列连接，关窗之后还会再投递一次；
        #: 那时候播放器已经 release 了，谁再碰它就是野指针（见 closeEvent）
        self._closing = False
        self._avatar_loaders: list = []                 # 头像下载线程，关窗时要等它们
        self._poller = None
        self._refresh_queued = False
        self._stats_poller = None
        self._retry_count: dict[object, int] = {}
        self._retry_timers: dict[object, QTimer] = {}
        self._freeze_refreshed: set[object] = set()
        self._freeze_retry_timers: dict[object, QTimer] = {}
        self._fullscreen_tile: Tile | None = None
        self._fullscreen_was_maximized = False
        self._native_fullscreen_state = None
        self._fullscreen_saved_geometry = None
        self._fullscreen_cover: QLabel | None = None
        self._fullscreen_cover_started = 0.0
        self._fullscreen_cover_timer = QTimer(self)
        self._fullscreen_cover_timer.setSingleShot(True)
        self._fullscreen_cover_timer.timeout.connect(self._clear_fullscreen_cover)
        self._danmaku: DanmakuClient | None = None      # 弹幕格当前连的那一路
        self._danmaku_room = ""
        self.shortcuts = dict(DEFAULT_SHORTCUTS)
        self.settings = dict(config_module.DEFAULT_SETTINGS)
        self.settings.update(self.state.get("settings") or {})
        self.settings.pop("auto_reconnect", None)  # 旧配置的开关不再控制内置重连
        self.settings.pop("recording_backup_dir", None)
        self.settings.pop("recording_ffmpeg", None)
        self.recorder = RecordingManager(self.settings, self)
        self.recorder.notice.connect(self._record_notice)
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
            else self._saved_layout("landscape"))

        #: 画面墙那一块（画面墙 + 空态提示），横竖两套排布共用它
        self._content = QWidget()
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_layout.addWidget(self.wall, 1)
        content_layout.addWidget(self.empty_hint, 1)

        self.setCentralWidget(root)
        self.orientation = ""                  # 由 _apply_orientation 填
        #: 各方向「切走之前在用的布局」：切回来时还原，别被容量折算换掉
        self._layout_by_orientation: dict[str, str] = {}
        self._build_arrangement("landscape")
        #: 构造时显式指定的布局（交给 _apply_orientation 决定用哪个方向的）
        self._pending_layout = ""

        # 信号接线
        self.sidebar.roomSelected.connect(self.wall.tileClicked.emit)
        self.sidebar.addRoomClicked.connect(self.open_add_room)
        self.sidebar.importFollowsClicked.connect(self.open_import_follows)
        self.sidebar.addToWallRequested.connect(self.add_to_wall)
        self.sidebar.removeRequested.connect(self.remove_room)
        self.sidebar.openBrowserRequested.connect(self._open_room_browser)
        self.sidebar.deleteRequested.connect(self.remove_rooms)
        self.sidebar.logoutRequested.connect(self.logout)
        self.sidebar.pinChanged.connect(self._on_pin_changed)
        self.sidebar.sortChanged.connect(self._on_sort_changed)
        self.sidebar.refreshRequested.connect(self.refresh_follow)
        self.sidebar.settingsRequested.connect(self.open_settings)
        self.sidebar.layoutChosen.connect(self._on_layout_changed)
        self.sidebar.set_layout_name(self.wall.layout_id)
        self.wall.danmaku.fontSizeChanged.connect(self._on_danmaku_font_size)
        # 悬停预览：鼠标在关注列表的直播上停 2 秒弹个小画面
        self.hover_preview = HoverPreview(self.sidebar, self)
        self.sidebar.previewHovered.connect(self.hover_preview.on_hover)
        self.sidebar.previewUnhovered.connect(self.hover_preview.on_unhover)
        # 拖字号滑块时别每一步都写配置，停手后再存
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(700)
        self._save_timer.timeout.connect(lambda: config_module.save(self.current_state()))
        # 音频巡检：`audio_set_mute` / `audio_set_volume` 是在 aout 上生效的，而 aout
        # 要等真正开始播放才建。补设置靠 play() 后那几次重试 + 看门狗，个别机器上
        # （慢启动、断流重连、切音频输出路径）会错过窗口，于是「静音标志亮着、声音
        # 还在」—— 用户报的「音频连在一起」就是这一类。这里定时比一遍，走散了就按
        # **格子**的值重新下发（格子是权威）。
        self._audio_audit_timer = QTimer(self)
        self._audio_audit_timer.setInterval(AUDIO_AUDIT_MS)
        self._audio_audit_timer.timeout.connect(self._audit_audio)
        self._audio_audit_timer.start()
        #: 各格开始录制的时刻（monotonic），用来刷「● REC 旁边的录制时长」
        self._recording_since: dict = {}
        self._record_clock = QTimer(self)
        self._record_clock.setInterval(1000)
        self._record_clock.timeout.connect(self._tick_record_clock)
        self._record_clock.start()
        self.wall.tileClicked.connect(self._on_tile_clicked)
        self.wall.roomDropped.connect(self._on_room_dropped)
        self.wall.tileSwapped.connect(self._on_tile_swapped)
        for tile in self.wall.tiles:
            self._wire_tile(tile)

        bili.set_sessdata(self.state.get("sessdata", ""))
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
        self.plugins.load()
        self.sidebar.browser_url_resolver = self._room_browser_url
        print(f"[插件] {self.plugins.summary}", file=sys.stderr, flush=True)
        for entry, reason in self.plugins.skipped:
            print(f"[插件] 跳过 {entry}：{reason}", file=sys.stderr, flush=True)
        QTimer.singleShot(0, lambda: self.plugins.emit(plugin_api.EVENT_STARTED))

        QTimer.singleShot(0, self.start_all)
        # 封面先用本地留的那张顶上去（纯读文件、不联网），别让卡片空着等状态轮询
        QTimer.singleShot(120, self.load_cached_covers)
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
        QTimer.singleShot(3000, self.refresh_stats)

    def _room_browser_url(self, room: dict) -> str:
        room_id = str(room.get("room_id") or "")
        if room_id.isascii() and room_id.isdecimal():
            return f"https://live.bilibili.com/{room_id}"
        kind, separator, raw_id = room_id.partition(":")
        platform = self.plugins.platforms.get(kind) if separator and raw_id else None
        if platform is None:
            return ""
        try:
            url = platform.room_url(room_id)
            parts = urlsplit(url)
            return url if parts.scheme in ("http", "https") and parts.netloc else ""
        except Exception:  # noqa: BLE001
            return ""

    def _open_room_browser(self, url: str) -> None:
        webbrowser.open(url)

    # ---- 界面状态 ----
    def _restore_ui(self) -> None:
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
        self.shortcuts = dict(DEFAULT_SHORTCUTS)
        self.shortcuts.update((self.state.get("ui") or {}).get("shortcuts") or {})
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
        layout = self._root_layout
        # 只改变同一个根布局的排列方向。侧栏和画面墙始终挂在 root 下，
        # VLC 正在使用的原生视频 HWND 就不会因换父窗口而被 Qt 销毁。
        layout.setDirection(
            QBoxLayout.TopToBottom if orientation == "portrait"
            else QBoxLayout.LeftToRight
        )
        if layout.indexOf(self.sidebar) < 0:
            layout.addWidget(self.sidebar)
        if layout.indexOf(self._content) < 0:
            layout.addWidget(self._content, 1)
        layout.setStretch(layout.indexOf(self.sidebar), 0)
        layout.setStretch(layout.indexOf(self._content), 1)
        if orientation == "landscape":
            self.sidebar.setMaximumHeight(16_777_215)
        self.sidebar.set_side("top" if orientation == "portrait" else "left")
        # 换完排布再同步一次可见性：收起/展开只影响「露哪些控件」，
        # 而 set_collapsed 在换排布之前就设过了，不补这一下头像排不会露出来。
        self.sidebar._sync_top_mode()      # noqa: SLF001
        self.wall.relayout(force=True)

    def is_portrait(self) -> bool:
        """窗口比高度矮（含接近方形）就算竖屏。"""
        width, height = max(self.width(), 1), max(self.height(), 1)
        return width <= height * PORTRAIT_MAX_RATIO

    def _saved_layout(self, orientation: str) -> str:
        ui = self.state.get("ui") or {}
        saved = str(ui.get(f"layout_{orientation}") or "")
        if not saved:
            # 配置里还没有这一项 = 第一次启动（或从很老的配置升上来）：
            # 用第一次启动的默认布局，别退成兜底的九分
            return (layouts.FIRST_LAYOUT if orientation == "landscape"
                    else layouts.PORTRAIT_AUTO)
        # 老配置里的 "auto"（以及任何已经删掉的布局 id）折算成兜底布局：
        # 「自动」已经按用户要求从菜单里去掉了
        if saved not in layouts.BY_ID:
            return layouts.DEFAULT_LAYOUT
        return saved

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

    def _apply_orientation(self) -> None:
        """按窗口方向换排布（顶部横栏 / 左侧栏）和布局预设。"""
        orientation = "portrait" if self.is_portrait() else "landscape"
        # 启动后第一次定方向？**要在下面写 self.orientation 之前取**，
        # 否则 first 永远是 False，第一次也会走「对映」那条路。
        first = not self.orientation
        changed = orientation != self.orientation
        if changed:
            self._build_arrangement(orientation)
        # 切走之前正在用的那套，记在**原来那个方向**名下：用户转个方向逛一圈再转回来，
        # 原来那边的布局得原样还在，不能靠「按容量折算」猜回来。
        if self.orientation and changed:
            self._layout_by_orientation[self.orientation] = self.wall.layout_id
        self.orientation = orientation
        portrait = orientation == "portrait"

        # 竖屏不再强制「收起」：顶部横栏本来就只占一条，横屏的收起语义（60px 窄条）
        # 混进来会在拖回横屏时留下一堆隐藏控件。竖屏保持展开（头像排 + 按钮行）。
        self.sidebar.set_collapsed(False, animate=False)

        saved = self._saved_layout(orientation)
        # 调用方显式指定的布局：只认和当前方向匹配的那次，认完就清掉
        pending = getattr(self, "_pending_layout", "")
        if pending and self._layout_fits(pending, portrait):
            layout_id = pending
            self._pending_layout = ""
        elif first:
            # 启动：配置里存过哪套就用哪套（第一次启动就是 FIRST_LAYOUT /
            # PORTRAIT_AUTO）；只有存的那套跟当前方向不匹配（老配置、
            # 或者上次是在另一个方向下用的）才按「对映」折算一套出来。
            layout_id = saved if self._layout_fits(saved, portrait) else (
                layouts.counterpart(self.wall.layout_id, portrait)
                or (layouts.PORTRAIT_AUTO if portrait else layouts.FIRST_LAYOUT))
        else:
            # 回自己待过的方向：先把「切走之前在用的那套」摆回来。横屏的
            # 「主画面 + 5 小环绕」和「六分」都是 6 路，只按容量折算的话，从竖屏
            # 切回来会被换成六分 —— 用户报的「布局被改了」就是这个。
            remembered = self._layout_by_orientation.get(orientation, "")
            if remembered and self._layout_fits(remembered, portrait):
                layout_id = remembered
            else:
                # 本次会话第一次进这个方向：跟着当前这套找最相似的那套
                # （横屏 1+2 ↔ 竖屏 1+2，弹幕对弹幕），不能退成「自动」。
                # 这一步要压过配置里存的那个值 —— 用户报的正是这个：
                # 横屏 1+2 拖成竖屏，结果用了以前在竖屏存过的「1+2+弹幕」。
                mapped = layouts.counterpart(self.wall.layout_id, portrait)
                if mapped:
                    layout_id = mapped
                elif self._layout_fits(saved, portrait):
                    layout_id = saved
                else:
                    layout_id = layouts.PORTRAIT_AUTO if portrait else layouts.DEFAULT_LAYOUT
        if layout_id != self.wall.layout_id:
            self.wall.set_layout(layout_id)
            self.sidebar.set_layout_name(layout_id)
        # 换了排布/换了布局，画面墙的尺寸和格子可见性都要重算一次
        self.wall.relayout(force=True)
        self._sync_tile_playback()
        print(f"[方向] {'竖屏' if portrait else '横屏'}　布局={layout_id}",
              file=sys.stderr, flush=True)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._fullscreen_tile is not None:
            return
        # 只有方向真的翻转时才动手，避免每次拖窗口都重排
        if getattr(self, "orientation", "") != ("portrait" if self.is_portrait()
                                                else "landscape"):
            self._apply_orientation()

    # ---- 设置 ----
    def poll_interval_ms(self) -> int:
        minutes = int(self.settings.get("poll_minutes", 1) or 1)
        return max(1, min(30, minutes)) * 60_000

    def open_settings(self, page: str = "general") -> bool:
        """一个窗口里选类别（常规 / 快捷键），和 Adobe 那类设置一样。"""
        dialog = SettingsDialog(self.settings, self.shortcuts, self)
        if page == "recording":
            dialog.nav.setCurrentRow(2)
        if dialog.exec() != SettingsDialog.Accepted:
            return False
        hw_before = bool(self.settings.get("hw_decode", True))
        self.settings.update(dialog.settings())
        self.shortcuts = dialog.shortcuts()
        self.state["settings"] = dict(self.settings)
        self.state.setdefault("ui", {})["shortcuts"] = dict(self.shortcuts)
        self._poll_timer.setInterval(self.poll_interval_ms())
        for player in self.players.values():
            player.freeze_watch = bool(self.settings.get("freeze_watch", True))
        if bool(self.settings.get("hw_decode", True)) != hw_before:
            # 硬解开关是 media 级选项：改完得让每一路重新取一次流才生效
            print(f"[设置] 硬件解码改成 "
                  f"{'开' if self.settings.get('hw_decode') else '关（软解）'}"
                  f"，重新取流各路画面", file=sys.stderr, flush=True)
            for tile in self.wall.tiles:
                if tile.room.get("room_id") and tile.room.get("live"):
                    self.start_tile(tile)
        config_module.save(self.current_state())
        # 两个总开关改完要立刻生效：录制开关还可能停掉正在录的会话
        self._sync_recording_switch()
        self._sync_replay_scope()
        self.apply_danmaku_settings()
        self.apply_preview_settings()
        print(f"[设置] {self.settings} 快捷键 {self.shortcuts}", file=sys.stderr, flush=True)
        return True

    def current_state(self) -> dict:
        return {
            "version": config_module.STATE_VERSION,
            "sessdata": bili.SESSION_DATA,
            "rooms": [str(room.get("room_id")) for room in self.sidebar.rooms()],
            # 空格子也要存，下次打开还是原来的布局
            "wall": [
                {
                    "room_id": str(tile.room.get("room_id") or ""),
                    "muted": bool(tile.muted),
                    # 音量属于格子；即使格子为空也要保存，重启后继续沿用。
                    "volume": int(tile.volume),
                    "quality": int(tile.quality),
                    "audio_channel": int(tile.audio_channel),
                }
                for tile in self.wall.tiles
            ],
            "ui": {
                "sidebar_collapsed": self.sidebar.collapsed,
                "layout_landscape": self._saved_layout("landscape"),
                "layout_portrait": self._saved_layout("portrait"),
                "shortcuts": dict(self.shortcuts),
            },
            "pinned": list(self.sidebar.pinned),
            "sort": self.sidebar.sort_mode,
            "import_order": list(self.sidebar.import_order),
            "custom_order": list(self.sidebar.custom_order),
            "settings": dict(self.settings),
            "geometry": str((self._fullscreen_saved_geometry or self.saveGeometry()).toBase64(),
                            "ASCII"),
            # 插件自己的配置项，以及「启用了哪些插件」（None = 全启用）
            "plugins": self.plugins.plugin_settings,
            "plugins_enabled": (None if self.plugins.enabled is None
                                else sorted(self.plugins.enabled)),
        }

    def closeEvent(self, event) -> None:
        # 【关闭提速】最开头先把窗口藏起来：release() 要逐格调用 stop()/
        # set_hwnd(0)/release()（每格都是主线程上的阻塞 libvlc 调用，上百毫秒
        # 量级），不先藏起来，用户就会眼睁睁看着画面一格一格被拆掉。先 hide()
        # 把窗口连同所有格子的原生画面瞬间藏掉，后面的收尾用户完全看不见。
        t0 = time.perf_counter()
        self._clear_fullscreen_cover()
        self.hide()
        if self._native_fullscreen_state is not None:
            window_fullscreen.exit(self, self._native_fullscreen_state)
            self._native_fullscreen_state = None
        hide_ms = (time.perf_counter() - t0) * 1000
        # 关窗前先把「正在关闭」钉住，并**清空**播放器表：release() 只是把
        # libvlc 实例还回去，self.players 里还留着它的话，取流线程排队中的
        # resolved 会在关窗后再投递一次，_play_on 就从表里拿到已经释放的实例
        # —— logs/ddm-2026-09-18.log 里那次 access violation（_play_on →
        # set_volume → libvlc_audio_set_volume，写 0x24）就是这么来的。
        self._closing = True
        self.recorder.shutdown()
        self._audio_audit_timer.stop()      # 收尾期间别再去碰正在释放的播放器
        self._record_clock.stop()
        watchdog.stop()
        self.plugins.emit(plugin_api.EVENT_CLOSING)
        self.plugins.unload()
        config_module.save(self.current_state())
        self.stop_danmaku()
        self.hover_preview.stop()
        for timer in self._freeze_retry_timers.values():
            timer.stop()
        self._freeze_retry_timers.clear()
        players = list(self.players.values())
        self.players.clear()
        for player in players:
            player.release()
        self._wait_background()
        self._resolvers.clear()
        total_ms = (time.perf_counter() - t0) * 1000
        print(f"[关闭] 窗口 {hide_ms:.1f} ms 内隐藏；收尾（释放播放器+等线程）共 {total_ms:.1f} ms",
              file=sys.stderr, flush=True)
        super().closeEvent(event)

    def _wait_background(self) -> None:
        """等在跑的线程收尾；线程还在跑就析构，Qt 会直接崩。"""
        names = ("_account_loader", "_account_avatar_loader", "_room_avatar_loader",
                 "_status_avatar_loader", "_follow_avatar_loader", "_follow_loader",
                 "_cover_cache_loader", "_cover_loader", "_aside_cover_loader",
                 "_poller", "_stats_poller")
        threads = [getattr(self, name, None) for name in names]
        threads.extend(self._avatar_loaders)
        threads.extend(self._resolvers.values())
        deadline = time.time() + 2.5
        for thread in threads:
            if thread is None or not self._loader_running(thread):
                continue
            try:
                thread.wait(max(120, int((deadline - time.time()) * 1000)))
            except RuntimeError:             # 已被 Qt 回收
                pass
        self._avatar_loaders.clear()

    def _on_layout_changed(self, layout_id: str) -> None:
        # 换画面墙摆放方式；**选了另一个方向的布局就把窗口也改成那个形状** ——
        # 用户要的是「切成竖屏后，alt+tab 里的窗口预览也是竖的」，
        # 而不是把一个竖屏排布塞在横屏窗口里（那样 alt+tab 就是一张拉伸的横屏）。
        want_portrait = layouts.is_portrait_layout(layout_id)
        if want_portrait != (self.orientation == "portrait"):
            print(f"[布局] {layout_id} 是给{'竖屏' if want_portrait else '横屏'}的，"
                  f"把窗口也改成{'竖屏' if want_portrait else '横屏'}的",
                  file=sys.stderr, flush=True)
            # 转窗口会同步触发 _apply_orientation，而那里会把「切走前的记忆」摆回来，
            # 把用户刚选的这套顶掉 —— 先挂成 pending，让它认这个选择
            self._pending_layout = layout_id
            self._reshape_window(want_portrait)
        self.wall.set_layout(layout_id)
        self.wall.relayout(force=True)
        self.sidebar.set_layout_name(self.wall.layout_id)
        # 记在**当前方向**名下：横屏选的布局不该被竖屏覆盖，反之亦然
        key = f"layout_{self.orientation or 'landscape'}"
        self.state.setdefault("ui", {})[key] = layout_id
        self.apply_quality_policy()
        self._sync_tile_playback(start_visible=True)
        self._refresh_meta()

    def _reshape_window(self, portrait: bool) -> None:
        """把主窗口改成竖屏/横屏的形状（宽高对调，并夹在当前屏幕里）。

        窗口尺寸系统（Alt+Tab / 任务栏预览）拿的是**窗口本身**的形状：竖屏排布
        塞在横屏窗口里，预览就是一张拉伸的横屏。所以选另一个方向的布局时顺手把
        窗口也摆成那个方向；最大化状态下先还原，否则改不动尺寸。
        """
        if self.isMaximized():
            self.showNormal()
        screen = self.screen() or QApplication.primaryScreen()
        area = screen.availableGeometry() if screen is not None else None
        width, height = max(self.width(), 480), max(self.height(), 360)
        if portrait:
            new_height = max(height, width)                 # 高的那一维当高度
            if area is not None:
                new_height = min(new_height, area.height())  # 先夹进屏幕
            new_width = max(360, int(new_height * 9 / 16))   # 再按 9:16 算宽度
            if area is not None:
                new_width = min(new_width, area.width())
        else:
            new_width = max(width, height)                  # 宽的那一维当宽度
            if area is not None:
                new_width = min(new_width, area.width())
            new_height = max(360, int(new_width * 9 / 16))
            if area is not None:
                new_height = min(new_height, area.height())
        # 别让窗口跑到屏幕外：贴进可用区域
        left, top = self.x(), self.y()
        if area is not None:
            left = min(max(left, area.left()), max(area.left(), area.right() - new_width))
            top = min(max(top, area.top()), max(area.top(), area.bottom() - new_height))
            self.move(left, top)
        self.resize(new_width, new_height)
        print(f"[窗口] 改成 {'竖屏' if portrait else '横屏'} {new_width}x{new_height}",
              file=sys.stderr, flush=True)

    def _on_pin_changed(self, pinned: list) -> None:
        self.state["pinned"] = list(pinned)
        config_module.save(self.current_state())

    def _on_sort_changed(self, mode: str) -> None:
        self.state["sort"] = mode
        self.state["import_order"] = list(self.sidebar.import_order)
        config_module.save(self.current_state())
        print(f"[排序] 关注列表改为：{dict(self.sidebar.SORT_MODES).get(mode, mode)}",
              file=sys.stderr, flush=True)

    # ---- 播放 ----
    def start_all(self) -> None:
        # 启动阶段先静默写好主次画质，再统一启动；否则 set_quality 的信号会
        # 先取一次流，下面的循环又取一次，同一格两个 resolver 会互相抢播放器。
        self.apply_quality_policy(restart=False)
        for tile in self.wall.tiles:
            self.start_tile(tile)

    def apply_quality_policy(self, *, restart: bool = True) -> list:
        """有主次布局时：主画面自动用原画，其余用 720P。"""
        changed = []
        if not self.settings.get("auto_quality", True):
            return changed
        main = self.wall.main_index()
        if main is None:
            return changed
        for index, tile in enumerate(self.wall.tiles):
            if not tile.room.get("room_id"):
                continue
            if tile in self._capture_quality:
                continue
            target = 10000 if index == main else 250
            if tile.quality != target:
                print(f"[画质策略] {tile.room.get('uname')} -> "
                      f"{'原画' if target == 10000 else '720P'}", file=sys.stderr, flush=True)
                blocked = tile.blockSignals(True)
                try:
                    tile.set_quality(target)
                finally:
                    tile.blockSignals(blocked)
                tile.room["quality"] = target
                changed.append(tile)
                if restart and tile.room.get("live"):
                    self.start_tile(tile)
        return changed

    def start_tile(self, tile) -> None:
        if self._closing:
            return                    # 关窗途中别再起取流/播放器
        room = tile.room or {}
        room_id = str(room.get("room_id") or "")
        if not room_id:
            return
        if not room.get("live"):
            tile.set_status("未开播")
            return
        player = self.players.get(tile)
        if player is not None:
            player.freeze_watch = bool(self.settings.get("freeze_watch", True))
        tile.set_paused(False)        # 重新取流就恢复播放状态
        tile.set_status("连接中…")
        # 以格子上的画质为准（信号带过来的字典是副本，不能当数据源）
        quality = int(tile.quality or room.get("quality", 250))
        resolver = StreamResolver(room_id, quality, self)
        resolver.resolved.connect(
            lambda _rid, url, qn, profile, options, t=tile:
            self._play_on(t, url, qn, profile, options, headers=resolver.headers,
                          room_id=room_id, requested_quality=quality))
        resolver.failed.connect(lambda rid, reason, t=tile, q=quality:
                                self._on_resolve_failed(t, reason, requested_quality=q))
        resolver.finished.connect(lambda t=tile: self._resolvers.pop(t, None))
        self._resolvers[tile] = resolver
        resolver.start()
        self.refresh_stats()          # 人数不用等下一轮轮询，立刻拉一次

    def _play_on(self, tile, url: str, quality: int = 0, profile: str = "web",
                 options: list | None = None, headers: dict | None = None,
                 room_id: str = "", requested_quality: int = 0) -> None:
        if self._closing:
            # 关窗后迟到的取流回调：播放器已经 release，碰它就是野指针
            return
        if room_id and str(tile.room.get("room_id") or "") != str(room_id):
            return                    # 迟到的取流结果（格子已经换台/被换走了）
        if requested_quality and int(tile.quality) != requested_quality:
            return                    # 画质已切换，旧请求不能覆盖新流
        if options:
            tile.set_quality_options(options)
        if quality:
            tile.set_actual_quality(quality)
        player = self.players.get(tile)
        if player is None:
            player = TilePlayer(tile.video, self)
            # 连接里不锁死格子：秒切之后播放器会挂到别的格子上，回调现查
            player.stateChanged.connect(
                lambda state, p=player:
                self._on_player_state(self._tile_of_player(p), state))
            player.pictureActivity.connect(
                lambda p=player: self._on_picture_activity(self._tile_of_player(p)))
            self.players[tile] = player
        player.freeze_watch = bool(self.settings.get("freeze_watch", True))
        player.set_volume(int(tile.volume))
        player.set_audio_channel(int(tile.audio_channel))
        player.set_muted(tile.muted)
        # 把这一路的取流结果记在格子和播放器上：插件（录像等）要拿它去拉同一路流；
        # 播放器上那份是给「秒切」用的 —— 画面搬走时取流结果跟着一起走。
        room = tile.room or {}
        tile.stream_url = url
        tile.stream_profile = profile
        tile.stream_headers = dict(headers or TilePlayer.PROFILE_HEADERS.get(
            profile, TilePlayer.PROFILE_HEADERS["web"]))
        player.stream_url = tile.stream_url
        player.stream_profile = profile
        player.stream_headers = dict(tile.stream_headers)
        player.actual_quality = int(quality or 0)
        player.play(url, profile, tile.stream_headers,
                    options=self.media_options())
        self.recorder.on_resolved(tile)
        if tile in self._pending_capture:
            self._finish_pending_capture(tile)
        self._emit_stream_resolved(tile, quality)
        # 直播起来了：即时回放该开的就在这里开，不用用户手动点
        self._sync_replay_scope()

    def _emit_stream_resolved(self, tile, quality: int = 0) -> None:
        """把「这一格现在播的是哪路流」告诉插件（录像等要靠它拉同一路流）。"""
        room = tile.room or {}
        self.plugins.emit(
            plugin_api.EVENT_STREAM_RESOLVED,
            source=plugin_api.StreamSource(
                room_id=str(room.get("room_id") or ""),
                url=str(tile.stream_url or ""),
                quality=int(quality or 0),
                channel=str(tile.stream_profile or "web"),
                headers=dict(tile.stream_headers or {}),
                platform=str(room.get("platform") or "bilibili"),
                uname=str(room.get("uname") or ""),
                title=str(room.get("title") or ""),
            ),
            tile=tile,
        )

    def media_options(self) -> tuple[str, ...]:
        """按设置给每一路 media 的额外选项。

        现在只有「硬件解码」：关掉时改用软解。VLC 在个别显卡驱动上硬解会卡住
        甚至访问违例（用户那边的看门狗日志里就是 libvlc 调用卡了 6.5 秒 +
        一次 access violation），关掉硬解是最省事的排查手段。
        """
        if self.settings.get("hw_decode", True):
            return ()
        return (player_module.HW_DECODE_OFF_OPTION,)

    def _on_resolve_failed(self, tile, reason: str, requested_quality: int = 0) -> None:
        if self._closing:
            return                    # 关窗后迟到的取流失败：别再拉轮询线程
        if requested_quality and int(tile.quality) != requested_quality:
            return
        if tile in self._pending_capture:
            self._pending_capture.pop(tile)
            self._record_notice(f"原画取流失败，录制未开始：{reason}")
            self._restore_capture_quality(tile)
            return
        tile.set_status("连接失败")
        print(f"[取流失败] {tile.room.get('uname')}: {reason}")
        self.plugins.emit(plugin_api.EVENT_STREAM_FAILED, tile=tile, reason=reason,
                          room=dict(tile.room or {}))
        self.refresh_status()       # 取不到流时立刻确认是否已经下播
        if tile in self._freeze_refreshed:
            self._on_picture_frozen(tile)

    def _on_player_state(self, tile, state: str) -> None:
        if tile is None:
            return                        # 播放器已经不在任何格子上（刚被停掉）
        if not tile.room.get("room_id"):
            return
        if state == "playing":
            tile.set_video_active(True)
            tile.set_buffering(False)
            tile.set_status("")
            tile.start_elapsed_timer()
            self._retry_count.pop(tile, None)
            player = self.players.get(tile)
            if player is not None:
                # 声道要在音频输出模块起来之后再设一次，否则会被初始化冲掉
                player.reapply_audio_channel()
            self.plugins.emit(plugin_api.EVENT_TILE_PLAYING, tile=tile,
                              room=dict(tile.room or {}))
        elif state == "connecting":
            tile.set_video_active(False)
            tile.set_status("连接中…")
        elif state == "buffering":
            tile.set_buffering(True)         # 卡顿时也显示缓冲动画
        elif state == "frozen":
            self._on_picture_frozen(tile)
        elif state == "error":
            self._clear_freeze_recovery(tile)
            tile.set_video_active(False)
            tile.stop_elapsed_timer()
            self.refresh_status()           # 断流可能来自下播，立即向接口确认
            self._schedule_retry(tile)
        else:
            tile.set_video_active(False)
            tile.stop_elapsed_timer()
        tile.raise_overlays()

    def _on_picture_frozen(self, tile) -> None:
        """静止约 2 秒先立即刷新；仍静止则提示，并每 5 秒再次刷新。"""
        if not tile.room.get("room_id") or tile.paused:
            return
        if tile not in self._freeze_refreshed:
            self._freeze_refreshed.add(tile)
            tile.set_status("画面停止更新，正在自动刷新…")
            print(f"[画面静止] {tile.room.get('uname')} 自动刷新",
                  file=sys.stderr, flush=True)
            self.refresh_status()           # 静止可能来自下播；接口确认后会同步清屏和侧栏
            self.start_tile(tile)
            return
        if tile in self._freeze_retry_timers:
            return
        tile.set_status(f"画面仍停止更新，{FREEZE_RETRY_SECONDS} 秒后再次刷新…")
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda t=tile: self._retry_frozen_picture(t))
        self._freeze_retry_timers[tile] = timer
        timer.start(FREEZE_RETRY_SECONDS * 1000)

    def _retry_frozen_picture(self, tile) -> None:
        self._freeze_retry_timers.pop(tile, None)
        if not tile.room.get("room_id") or tile.paused:
            return
        tile.set_status("画面仍停止更新，正在再次刷新…")
        print(f"[画面静止] {tile.room.get('uname')} 5 秒后再次刷新",
              file=sys.stderr, flush=True)
        self.start_tile(tile)

    def _on_picture_activity(self, tile) -> None:
        """画面重新变化后结束静止恢复流程，不再执行排队中的刷新。"""
        if tile is None:
            return                        # 播放器已经不在任何格子上
        was_recovering = tile in self._freeze_refreshed
        self._clear_freeze_recovery(tile)
        if was_recovering:
            tile.set_status("")
            print(f"[画面恢复] {tile.room.get('uname')} 已恢复更新",
                  file=sys.stderr, flush=True)

    def _clear_freeze_recovery(self, tile) -> None:
        timer = self._freeze_retry_timers.pop(tile, None)
        if timer is not None:
            timer.stop()
            timer.deleteLater()
        self._freeze_refreshed.discard(tile)

    def _schedule_retry(self, tile) -> None:
        """断流自动重连：5 秒起，逐次翻倍，最多 60 秒。"""
        if not tile.room.get("room_id"):
            return
        attempt = self._retry_count.get(tile, 0) + 1
        self._retry_count[tile] = attempt
        delay = min(RETRY_BASE_SECONDS * (2 ** (attempt - 1)), RETRY_MAX_SECONDS)
        tile.set_status(f"断流，{delay} 秒后重连（第 {attempt} 次）")
        timer = self._retry_timers.pop(tile, None)
        if timer is not None:
            timer.stop()
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.timeout.connect(lambda t=tile: self._retry_now(t))
        self._retry_timers[tile] = timer
        timer.start(delay * 1000)

    def _retry_now(self, tile) -> None:
        self._retry_timers.pop(tile, None)
        if tile.room.get("room_id"):
            print(f"[重连] {tile.room.get('uname')} 第 {self._retry_count.get(tile, 1)} 次",
                  file=sys.stderr, flush=True)
            self.start_tile(tile)

    def _stop_tile(self, tile) -> None:
        self._clear_freeze_recovery(tile)
        player = self.players.pop(tile, None)
        if player is not None:
            player.release()
        resolver = self._resolvers.pop(tile, None)
        if resolver is not None:
            # 只作废、不强杀：terminate() 会带走线程本地存储和锁，主线程可能
            # 整个卡死（窗口不动也不退出，用户看到的就是「直接崩了」）
            resolver.cancel()
        self.plugins.emit(plugin_api.EVENT_TILE_STOPPED, tile=tile,
                          room=dict(tile.room or {}))

    def _sync_tile_playback(self, *, start_visible: bool = False) -> None:
        """只让**看得见**的格子播放。

        布局从 9 格换成 6 格时，多出来的格子以前只是 ``setVisible(False)``：播放器
        一步没停，还在解码、**还在出声**（用户报「没显示出来的格子也在响」）。这里
        把当前布局放不下的停掉；换回大布局、格子重新露出来时再接上。
        """
        if not getattr(self, "plugins", None):
            start_visible = False       # 构造期间插件还没装好，不能在这里起流
        for tile in self.wall.tiles:
            player = self.players.get(tile)
            if tile.isVisible():
                if start_visible and player is None and tile.room.get("live"):
                    self.start_tile(tile)
            else:
                self._pending_capture.pop(tile, None)
                self.recorder.stop(tile)
                if tile not in self.recorder.sessions:
                    self._restore_capture_quality(tile)
                if player is None:
                    continue
                print(f"[布局] {tile.room.get('uname')} 当前布局放不下，先停播",
                      file=sys.stderr, flush=True)
                self._stop_tile(tile)

    def _offline_tile(self, tile) -> None:
        """这一路下播：停掉播放（画面变黑），格子继续留给它，等重新开播自动接上。"""
        timer = self._retry_timers.pop(tile, None)
        if timer is not None:
            timer.stop()
        self._retry_count.pop(tile, None)
        self._pending_capture.pop(tile, None)
        self.recorder.stop(tile)
        self._stop_tile(tile)
        tile.set_offline()
        if tile not in self.recorder.sessions:
            self._restore_capture_quality(tile)
        print(f"[下播] {tile.room.get('uname')} 画面已清空，格子保留",
              file=sys.stderr, flush=True)

    def _tile_of(self, room_id: str):
        return next((tile for tile in self.wall.tiles
                     if str(tile.room.get("room_id") or "") == str(room_id)), None)

    def _sender_tile(self):
        """发信号的那个格子；不是格子发的（定时器之类）返回 None。

        定位操作对象**别用 room_id 反查**：同一个直播间占了两个格子时（配置里
        存重了、或同一张卡片被拖上两次），反查只命中列表里第一个 —— 于是「静音
        这一格」把另一格的播放器静音了，这一格反倒还在出声，而标志是画在自己
        身上的、照样亮着。用户报的「开这格静音，旁边那格声音不对」就是这个。
        这些信号都是直接连接的，sender() 可靠；反查只留作兜底。
        """
        sender = self.sender()
        return sender if isinstance(sender, Tile) else None

    def _prepare_room(self, room: dict) -> dict:
        """给新建格子补初始声音；已有格子的静音和音量由 Tile 保留。"""
        if "muted" not in room:
            room["muted"] = bool(self.settings.get("default_muted", True))
        if "volume" not in room:
            room["volume"] = int(self.settings.get(
                "default_volume", config_module.DEFAULT_VOLUME))
        room.setdefault("quality", 250)
        return room

    def _room_dict(self, room_id: str) -> dict | None:
        room_id = str(room_id)
        for room in self.sidebar.rooms():
            if str(room.get("room_id")) == room_id:
                return room
        return bili.room_info(room_id)

    # ---- 拖拽 ----
    def _on_room_dropped(self, tile, room_id: str) -> None:
        room = self._room_dict(room_id)
        if not room:
            print(f"拖入的直播间 {room_id} 查询失败")
            return
        self._prepare_room(room)
        other = self._tile_of(room_id)
        if other is not None and other is not tile and self._hot_swap(other, tile):
            # 拖进来的这个直播间本来就在别的格子里：两边直接对调画面
            print(f"{room.get('uname')} ↔ 第 {self.wall.tiles.index(tile) + 1} 个格子",
                  file=sys.stderr, flush=True)
            return
        to_start = []
        if other is not None and other is not tile:
            # 已经在别的格子里：两边交换，避免同一个直播间出现两次
            previous = dict(tile.room) if tile.room.get("room_id") else None
            self.recorder.stop(other)
            self._stop_tile(other)
            other.set_room(previous)
            if previous and previous.get("room_id"):
                to_start.append(other)
        self.recorder.stop(tile)
        self._stop_tile(tile)
        tile.set_room(room)
        to_start.append(tile)
        restarted = self.apply_quality_policy()
        for candidate in to_start:
            if candidate not in restarted:
                self.start_tile(candidate)
        self._refresh_meta()
        print(f"{room.get('uname')} → 第 {self.wall.tiles.index(tile) + 1} 个格子")

    def _on_tile_swapped(self, source_room_id: str, target_tile) -> None:
        """把来源格子里的直播间和目标格子互换（也包括拖到空格子上）。

        两边都在播的时候走**秒切**：播放器和它绑定的原生窗口都还在，只是换个
        格子挂上去 —— 不重新取流、不重新缓冲，画面直接对调。有一边没有播放器
        （空格子、取流还没回来）或者要换音频输出路径时，退回「停掉再各自起」。
        """
        source = self._tile_of(source_room_id)
        if source is None or source is target_tile:
            return
        if self._hot_swap(source, target_tile):
            return
        first, second = dict(source.room), dict(target_tile.room)
        self.recorder.stop(source)
        self.recorder.stop(target_tile)
        self._stop_tile(source)
        self._stop_tile(target_tile)
        source.set_room(second if second.get("room_id") else None)
        target_tile.set_room(first if first.get("room_id") else None)
        restarted = self.apply_quality_policy()
        for tile in (source, target_tile):
            if tile.room.get("room_id") and tile not in restarted:
                self.start_tile(tile)
        self._refresh_meta()
        print("两个格子的直播间已互换")

    def _hot_swap(self, source, target) -> bool:
        """两个格子互换：**把两个格子本身换个位置**，播放器一个都不动。

        为什么不搬播放器：实测（work/probe_sethwnd.py、work/repro_canvas_swap2.py）
        正在播的时候 `set_hwnd` 到别的窗口，画面不会乖乖跟过去 —— 旧窗口留着最后一帧、
        新窗口里只铺一小块；改用「关掉视频轨重建」能让画面动，但 VLC 会另外冒一个
        独立的播放窗（用户看到的「悬浮窗」，还会把另一格弄黑）。
        格子换位置就没这些事：画面、控制条、原生窗口一起搬，媒体一直在播，
        连 set_hwnd 都不用碰。
        """
        source_player = self.players.get(source)
        target_player = self.players.get(target)
        source_live = bool(source.room.get("room_id") and source.room.get("live"))
        target_live = bool(target.room.get("room_id") and target.room.get("live"))
        if not source_live and not target_live:
            return False
        if (source_live and source_player is None) or (target_live and target_player is None):
            return False                       # 取流还没回来，没有画面可换
        tiles = self.wall.tiles
        try:
            first_index, second_index = tiles.index(source), tiles.index(target)
        except ValueError:
            return False
        # 1) 两个格子换位置（房间里的一切跟着格子走：画质、取流结果、计时都还在）
        tiles[first_index], tiles[second_index] = tiles[second_index], tiles[first_index]
        # 2) 音量 / 静音 / 声道属于**格子（位置）**，不跟着主播走：
        #    两个格子的这几项设置对调，再把它们下发给自己那个（没挪窝的）播放器
        source.volume, target.volume = target.volume, source.volume
        source.muted, target.muted = target.muted, source.muted
        source.audio_channel, target.audio_channel = \
            target.audio_channel, source.audio_channel
        for tile in (source, target):
            tile.room["volume"] = tile.volume
            tile.room["muted"] = tile.muted
            tile.room["audio_channel"] = tile.audio_channel
            player = self.players.get(tile)
            if player is None:
                continue
            player.set_volume(int(tile.volume))
            player.set_muted(tile.muted)
            player.set_audio_channel(int(tile.audio_channel))
            player.reapply_audio_channel()
            tile.sync_audio_ui()            # 值换位了，音量条控件要跟着重画
            tile.raise_overlays()
        self.wall.relayout(force=True)         # 换完位置重新摆一遍
        for tile in (source, target):
            tile.raise_overlays()
        self._refresh_meta()
        print("两个格子的画面已秒切（格子互换位置，媒体没有中断）",
              file=sys.stderr, flush=True)
        return True

    def _tile_of_player(self, player):
        """播放器现在挂在哪个格子上（格子换位置之后连接不用重接，靠这个现查）。"""
        for tile, candidate in self.players.items():
            if candidate is player:
                return tile
        return None

    # ---- 直播状态轮询 ----
    def refresh_stats(self) -> None:
        """取画面墙上各房间的"看过"人数（wbi 签名接口，和网页显示一致）。"""
        try:
            if self._stats_poller is not None and self._stats_poller.isRunning():
                return
        except RuntimeError:
            self._stats_poller = None
        room_ids = [str(tile.room.get("room_id")) for tile in self.wall.tiles
                    if tile.room.get("room_id") and tile.room.get("live")]
        if not room_ids:
            return
        poller = StatsPoller(room_ids, self)
        poller.updated.connect(self._on_stats_updated)
        poller.finished.connect(self._on_stats_finished)
        self._stats_poller = poller
        poller.start()

    def _on_stats_finished(self) -> None:
        poller = self._stats_poller
        self._stats_poller = None
        if poller is not None:
            poller.deleteLater()

    def _on_stats_updated(self, stats: dict) -> None:
        for tile in self.wall.tiles:
            info = stats.get(str(tile.room.get("room_id") or ""))
            if info and info.get("online_text"):
                tile.set_watched(info["online_text"])

    def refresh_status(self, *, force: bool = False) -> None:
        try:
            if self._poller is not None and self._poller.isRunning():
                if force:
                    self._refresh_queued = True
                return
        except RuntimeError:                 # 对象已被 Qt 回收
            self._poller = None
        room_ids = [str(room.get("room_id")) for room in self.sidebar.rooms()]
        if not room_ids:
            return
        poller = StatusPoller(room_ids, self)
        poller.updated.connect(self._on_status_updated)
        if hasattr(poller, "failed"):
            poller.failed.connect(self._on_status_failed)
        poller.finished.connect(self._on_poller_finished)
        self._poller = poller
        poller.start()

    def _on_poller_finished(self) -> None:
        poller = self._poller
        self._poller = None
        if poller is not None:
            poller.deleteLater()
        if self._refresh_queued:
            self._refresh_queued = False
            self.refresh_status()
            return
        self.sidebar.set_refreshing(False)

    def _on_status_failed(self, reason: str) -> None:
        print(f"[状态刷新失败] {reason}", file=sys.stderr, flush=True)
        self.sidebar.count_label.setText("状态刷新失败 · 点击重试")

    def refresh_follow(self) -> None:
        """侧栏的「刷新」：立刻拉一次直播状态，并把还没显示的头像补上。"""
        self.sidebar.set_refreshing(True)
        self.refresh_status(force=True)
        self.load_room_avatars()
        if self._poller is None:            # 列表是空的，没真的开轮询
            self.sidebar.set_refreshing(False)

    def _on_status_updated(self, status: dict) -> None:
        # 画面格可能直接持有侧栏条目的 room 字典。必须先记住两边旧状态，
        # 否则先更新画面格会让侧栏误以为状态没有变化，徽标仍停在“直播中”。
        tile_was_live = {tile: bool(tile.room.get("live")) for tile in self.wall.tiles}
        item_was_live = {item: bool(item.room.get("live")) for item in self.sidebar._items}
        faces: dict[str, str] = {}
        covers: dict[str, str] = {}
        for tile in self.wall.tiles:
            info = status.get(str(tile.room.get("room_id") or ""))
            if not info:
                continue
            was_live = tile_was_live[tile]
            tile.set_live(info["live"], info["viewers"])
            if info.get("uname") or info.get("title"):
                tile.set_uname_title(info.get("uname", ""), info.get("title", ""))
            if info.get("live_start_ts"):
                tile.room["live_start_ts"] = info["live_start_ts"]
            if was_live and not info["live"]:
                self._offline_tile(tile)          # 刚下播：黑屏但保留这一格
                self.plugins.emit(plugin_api.EVENT_ROOM_OFFLINE, tile=tile,
                                  room=dict(tile.room or {}))
            elif not was_live and info["live"]:
                print(f"[开播] {tile.room.get('uname')} 自动开始播放",
                      file=sys.stderr, flush=True)
                self.plugins.emit(plugin_api.EVENT_ROOM_LIVE, tile=tile,
                                  room=dict(tile.room or {}))
                self.start_tile(tile)             # 重新开播：自动接上
                self.refresh_stats()              # 刚开播：马上补一次在线人数
        just_went_live: list = []
        for item in self.sidebar._items:            # noqa: SLF001
            info = status.get(str(item.room.get("room_id")))
            if not info:
                continue
            was_live = item_was_live[item]
            if info["title"]:
                item.set_title(info["title"])
            if info.get("uname"):
                item.set_uname(info["uname"])
            cover = info.get("cover_url") or ""
            if cover and cover != item.room.get("cover_url"):
                item.room["cover_url"] = cover      # 开播/下播后封面会变，缩略图跟着换
                covers[str(item.room.get("room_id"))] = cover
            if info["live"] and not was_live:
                # 刚开播：马上置位并重排，让「开播优先」先把卡片挪上去；
                # 动效等重排落地后再播，否则水滴会留在卡片原来的行上（两者错开）。
                # 只有**本来就知道是没开播**的才算「刚开播」：启动时占位条目
                # （live_known=False）第一次补上真实状态不算，否则一开软件满列表
                # 冒气泡／弹提醒 —— 用户要的是「开播时」的提示。
                if self.settings.get("live_alert", True) and item.room.get("live_known", True):
                    item.room["live"] = True        # 徽标由动效砸中时再换
                    just_went_live.append(item)
                else:
                    item.set_live(True)
            else:
                # 即使数据字典已被画面格更新，也要强制刷新侧栏徽标样式和文字。
                item.set_live(info["live"])
            face = info.get("face")
            if face and face != item.room.get("face"):
                item.room["face"] = face
                faces[str(item.room.get("room_id"))] = face
            item.room["live_known"] = True          # 这一路的直播状态从此算已知
        self.sidebar.resort()               # 「开播优先」要跟着开播状态重排
        self._sync_replay_scope()           # 回放范围设成「所有格子」时在这里补开缓存
        if just_went_live:                  # 排完再播动效：水滴落在卡片的新位置上
            self.sidebar.play_live_alerts(just_went_live)
        if covers:
            self._aside_cover_loader = self._start_avatar_loader(
                covers, self._on_room_cover, subdir="covers")
        if faces:
            loader = AvatarLoader(faces, self)
            loader.loaded.connect(self._on_room_avatar)
            loader.finished.connect(loader.deleteLater)
            self._status_avatar_loader = loader
            loader.start()

    # ---- 全局操作 ----
    def _on_tile_clicked(self, room: dict) -> None:
        # 信号带过来的字典是副本，用房间号比较（不能比较对象身份）
        room_id = str(room.get("room_id") or "")
        for tile in self.wall.tiles:
            tile.set_focused(bool(room_id) and str(tile.room.get("room_id") or "") == room_id)
        self.sidebar.select_room(room)

    # ---- 单个格子的操作 ----
    def _on_volume_changed(self, room: dict, value: int) -> None:
        tile = self._sender_tile() or self._tile_of(str(room.get("room_id")))
        player = self.players.get(tile) if tile is not None else None
        if player is not None:
            player.set_volume(value)
        self._save_timer.start()       # 滑块停下 700ms 后保存每个格子的音量

    def _on_audio_changed(self, room: dict, value: int) -> None:
        tile = self._sender_tile() or self._tile_of(str(room.get("room_id")))
        player = self.players.get(tile) if tile is not None else None
        if player is not None:
            if player.needs_audio_restart(value):
                # libVLC 要求 audio callbacks 在播放前设置；默认输出与左右路由
                # 之间切换时重建这一格，不能在运行中的播放器上硬换回调。
                self._stop_tile(tile)
                if tile.room.get("live"):
                    self.start_tile(tile)
                self._save_timer.start()
                return
            player.set_audio_channel(value)
            # 播放中的这一路要等音频输出模块起来后再补一次，否则会被初始化冲掉
            player.reapply_audio_channel()
        self._save_timer.start()       # 声道属于格子，和音量一起记住

    def _on_quality_changed(self, room: dict, quality: int) -> None:
        # 注意：Qt 信号传过来的 dict 是副本，必须写回格子自己的字典
        tile = self._sender_tile() or self._tile_of(str(room.get("room_id")))
        if tile is None:
            return
        if tile in self._capture_quality and quality != 10000:
            blocked = tile.blockSignals(True)
            try:
                tile.set_quality(10000)
            finally:
                tile.blockSignals(blocked)
            return
        tile.quality = quality
        tile.room["quality"] = quality
        if tile.room.get("live"):
            self.start_tile(tile)

    def _on_mute_changed(self, room: dict, muted: bool) -> None:
        tile = self._sender_tile() or self._tile_of(str(room.get("room_id")))
        player = self.players.get(tile) if tile is not None else None
        if player is not None:
            player.set_muted(muted)
        self._save_timer.start()       # 静音也是格子状态，和音量一起记住

    def _replay_scope(self) -> str:
        """即时回放的适用范围：``recorded``（只跟录制走）或 ``all``（所有格子）。"""
        scope = str(self.settings.get("recording_replay_scope", "recorded") or "")
        return scope if scope in ("recorded", "all") else "recorded"

    def _recording_enabled(self) -> bool:
        """录制功能总开关。关掉时不起新录制，已经在录的正常收尾。"""
        return bool(self.settings.get("recording_enabled", True))

    def _sync_recording_switch(self) -> None:
        """按录制总开关收起「● 录制」按钮，并停掉正在录制的会话。

        停的是**正常收尾**（走 recorder.stop()，已录到的分段照样导出成文件），
        不是丢弃 —— 关开关的意图是「不想再录了」，不是「把刚才录的删掉」。
        """
        enabled = self._recording_enabled()
        if not enabled:
            self._pending_capture.clear()       # 还在等原画的那几格也别等了
        for tile in self.wall.tiles:
            setter = getattr(tile, "set_recording_available", None)
            if setter is not None:
                setter(enabled)
            if enabled:
                continue
            session = self.recorder.sessions.get(tile)
            if session is not None and session.recording:
                self.recorder.stop(tile)

    def _replay_enabled(self) -> bool:
        """即时回放总开关；关掉时既不开缓存，也不提供「保存最近 N 分钟」。"""
        return bool(self.settings.get("recording_replay_enabled", True))

    def _replay_max_tiles(self) -> int:
        """``all`` 时最多给几格开缓存；<= 0 表示不限制。"""
        try:
            return int(self.settings.get("recording_replay_max_tiles", 3))
        except (TypeError, ValueError):
            return 3

    def _drop_pure_caches(self) -> None:
        """停掉所有「纯缓存」会话；录制中的留着 —— 它本来就在写分段。"""
        for tile in self.wall.tiles:
            session = self.recorder.sessions.get(tile)
            if session is not None and not session.recording:
                self.recorder.stop(tile)

    def _sync_replay_scope(self) -> None:
        """按「即时回放总开关 + 范围」自动开 / 关各格的缓存。

        ``recorded``：只跟着录制走。录制中的格子本来就在写分段，直接就能导出回放，
        所以什么都不用开；纯缓存的会话（以前手动开的）会被停掉。
        ``all``：所有播放中的格子都开一份缓存，随时都能「保存最近 N 分钟」，
        但**最多开 ``recording_replay_max_tiles`` 格** —— 每开一格都是再拉一路
        同样的流（带宽翻倍）加一个 ffmpeg 进程（约 155 MB 内存）。用户实测过
        8 格全开：16 路同时下载、1.2 GB 常驻内存，打网游时延迟直接抖起来。

        注意这里**直接调 recorder.start()**、不走 ``_start_capture()`` —— 后者会为了
        录制把画质锁到原画，而「所有格子都锁原画」会把带宽吃光。
        """
        if not self._replay_enabled() or self._replay_scope() != "all":
            # 总开关关掉、或范围收窄成 recorded：不只不开新的，纯缓存的也要停掉
            self._drop_pure_caches()
            return
        if not bool(str(self.settings.get("recording_dir") or "").strip()):
            return                                  # 没配保存目录，缓存没地方写
        limit = self._replay_max_tiles()
        # 额度按「已经在缓存的格子」现数（用户手动录制的那些不占额度）。
        # 每轮重数一遍，所以某个格子的缓存停掉之后，额度会自动让给后面的格子。
        cached = sum(1 for session in self.recorder.sessions.values()
                     if not session.recording)
        for tile in self.wall.tiles:
            if tile in self.recorder.sessions:
                continue                            # 已经有会话（录制或缓存）
            if limit > 0 and cached >= limit:
                break                               # 额度用完，剩下的格子先不缓存
            if not tile.isVisible() or not tile.room.get("live"):
                continue
            if not tile.room.get("room_id") or not tile.stream_url:
                continue                            # 还没取到流，等下一轮
            if self.recorder.start(tile, recording=False):
                cached += 1

    def _audit_audio(self) -> None:
        """巡检：格子记的静音 / 音量，和播放器**实际**的值有没有走散。

        格子是权威（用户是按格子调的），走散了就按格子重新下发一次。需要这条
        兜底是因为：`audio_set_mute` / `audio_set_volume` 作用在 aout 上，而 aout
        要等真正开始播放才建 —— 补设置只能靠 `play()` 后那几次重试加看门狗，
        慢启动 / 断流重连 / 切音频输出路径时可能整个错过那个窗口，结果就是
        「静音标志亮着、这一格却还在出声」，用户听起来像「格子之间的音频连在
        一起」。走散时打一行 `[音频]`，下次复现能直接从日志看出是哪一格、差多少。
        """
        for tile in self.wall.tiles:
            player = self.players.get(tile)
            if player is None or not tile.room.get("room_id"):
                continue
            if getattr(player, "silent", False) or getattr(player, "_released", False):
                continue
            vlc = getattr(player, "player", None)
            if vlc is None:
                continue
            name = tile.room.get("uname") or tile.room.get("room_id")
            try:
                actual_mute = int(vlc.audio_get_mute())
            except Exception:                      # noqa: BLE001
                continue
            if actual_mute < 0:                    # aout 还没起来，这个接口答不了
                continue
            if bool(actual_mute) != bool(tile.muted):
                print(f"[音频] {name} 静音走散：格子={bool(tile.muted)} "
                      f"播放器={bool(actual_mute)} → 按格子重新下发",
                      file=sys.stderr, flush=True)
                player.set_muted(bool(tile.muted))
                continue
            if tile.muted:
                continue                           # 静音时音量本来就是 0，不必比
            if getattr(player, "uses_pcm_routing", False):
                continue        # PCM 路由下 VLC 不管音量（实测），比了会误判
            try:
                actual_volume = int(vlc.audio_get_volume())
            except Exception:                      # noqa: BLE001
                continue
            if actual_volume < 0:
                continue
            expected = linear_to_vlc_volume(int(tile.volume))
            if abs(actual_volume - expected) > 1:
                print(f"[音频] {name} 音量走散：格子={tile.volume}（应为 {expected}）"
                      f" 播放器={actual_volume} → 按格子重新下发",
                      file=sys.stderr, flush=True)
                player.set_volume(int(tile.volume))

    def _on_reload(self, room: dict) -> None:
        tile = self._tile_of(str(room.get("room_id")))
        if tile is not None:
            self._clear_freeze_recovery(tile)
            self.start_tile(tile)

    def _on_pause_toggled(self, room: dict) -> None:
        tile = self._tile_of(str(room.get("room_id")))
        if tile is None:
            return
        paused = not tile.paused
        tile.set_paused(paused)
        player = self.players.get(tile)
        if player is not None:
            player.set_paused(paused)
        print(f"[暂停] {tile.room.get('uname')} -> {'暂停' if paused else '继续'}",
              file=sys.stderr, flush=True)

    def _grab_fullscreen_frame(self) -> tuple[QPixmap, object] | None:
        if sys.platform != "win32" or QApplication.platformName() != "windows":
            return None
        screen = self.screen()
        frame = screen.grabWindow(0)
        if frame.isNull():
            return None
        image = frame.toImage()
        samples = ((0, 0), (image.width() // 2, image.height() // 2),
                   (image.width() - 1, image.height() - 1))
        if all(image.pixelColor(x, y).value() < 4 for x, y in samples):
            return None  # 没有交互桌面时，Qt 截屏可能只返回黑图
        return frame, screen.geometry()

    def _hold_fullscreen_frame(self) -> None:
        self._fullscreen_cover_timer.stop()
        self._fullscreen_cover_started = time.perf_counter()
        if self._fullscreen_cover is not None:
            return
        captured = self._grab_fullscreen_frame()
        if captured is None:
            return
        frame, geometry = captured
        cover = QLabel()
        cover.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint |
                             Qt.WindowStaysOnTopHint | Qt.WindowTransparentForInput)
        cover.setAttribute(Qt.WA_ShowWithoutActivating, True)
        cover.setScaledContents(True)
        cover.setPixmap(frame)
        cover.setGeometry(geometry)
        self._fullscreen_cover = cover
        cover.show()
        QApplication.processEvents()

    def _release_fullscreen_frame(self) -> None:
        if self._fullscreen_cover is not None:
            elapsed_ms = int((time.perf_counter() - self._fullscreen_cover_started) * 1000)
            self._fullscreen_cover_timer.start(max(16, 120 - elapsed_ms))

    def _clear_fullscreen_cover(self) -> None:
        self._fullscreen_cover_timer.stop()
        cover = self._fullscreen_cover
        self._fullscreen_cover = None
        if cover is not None:
            cover.close()
            cover.deleteLater()

    def _on_fullscreen(self, tile: Tile) -> None:
        if tile not in self.wall.tiles or not tile.room.get("room_id"):
            return
        if self._fullscreen_tile is tile:
            self._exit_fullscreen()
            return
        if self._fullscreen_tile is not None:
            return
        self._hold_fullscreen_frame()
        self._fullscreen_was_maximized = self.isMaximized()
        self._fullscreen_saved_geometry = self.saveGeometry()
        self._fullscreen_tile = tile
        self.centralWidget().setUpdatesEnabled(False)
        try:
            self.sidebar.hide()
            self.empty_hint.hide()
            self.wall.set_fullscreen_tile(tile)
            tile.fullscreen_button.setToolTip("退出全屏（F / Esc）")
            if sys.platform == "win32" and QApplication.platformName() == "windows":
                self._native_fullscreen_state = window_fullscreen.enter(self)
            else:
                self.showFullScreen()
        finally:
            self.centralWidget().setUpdatesEnabled(True)
            self._release_fullscreen_frame()

    def _exit_fullscreen(self) -> None:
        tile = self._fullscreen_tile
        if tile is None:
            return
        self._hold_fullscreen_frame()
        self.centralWidget().setUpdatesEnabled(False)
        try:
            if self._native_fullscreen_state is not None:
                window_fullscreen.exit(self, self._native_fullscreen_state)
                self._native_fullscreen_state = None
            elif self._fullscreen_was_maximized:
                self.showMaximized()
            else:
                self.showNormal()
            self._fullscreen_tile = None
            self._fullscreen_saved_geometry = None
            self.sidebar.show()
            self.wall.set_fullscreen_tile(None)
        finally:
            self.centralWidget().setUpdatesEnabled(True)
            self._release_fullscreen_frame()
        if self.orientation != ("portrait" if self.is_portrait() else "landscape"):
            self._apply_orientation()
        tile.fullscreen_button.setToolTip("全屏查看这一路（F）")
        self._refresh_meta()

    def _on_close_tile(self, room: dict) -> None:
        """关掉这一路，但留下空格子等新的直播间拖进来。"""
        tile = self._tile_of(str(room.get("room_id")))
        if tile is None:
            return
        self._pending_capture.pop(tile, None)
        self.recorder.stop(tile)
        self._stop_tile(tile)
        tile.set_room(None)
        if tile not in self.recorder.sessions:
            self._restore_capture_quality(tile)
        self._refresh_meta()
        print(f"已关闭 {room.get('uname')}，格子已清空")

    def _wire_tile(self, tile) -> None:
        tile.qualityChanged.connect(self._on_quality_changed)
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
        if session and self._replay_enabled():
            # 即时回放跟着直播自动开（见 _sync_replay_scope），所以菜单里不再放
            # 「开启/关闭即时回放缓存」两个开关，只留这一个「保存」。
            # 设置里把即时回放整个关掉时，这一项也不出现。
            minutes = int(session.settings.get("recording_replay_minutes", 3))
            collected.append((f"保存最近约 {minutes} 分钟", lambda t=tile:
                              self.recorder.save_replay(t)))
        if manager is not None:
            for label, callback, name in manager.tile_actions(tile):
                collected.append((label, lambda cb=callback: manager.run_action(cb)))
        tile.plugin_actions = collected

    def _toggle_recording(self, tile) -> None:
        if tile in self._pending_capture:
            self._pending_capture.pop(tile)
            self._restore_capture_quality(tile)
            return
        session = self.recorder.sessions.get(tile)
        if session and session.recording:
            self.recorder.stop(tile)
        else:
            self._start_capture(tile, recording=True)

    def _start_capture(self, tile, *, recording: bool) -> None:
        if recording and not self._recording_enabled():
            self._record_notice("录制功能已在「设置 → 录制」里关闭")
            return
        if tile in self._pending_capture:
            return
        if not str(self.settings.get("recording_dir") or "").strip():
            if not self.open_settings("recording"):
                return
            if not str(self.settings.get("recording_dir") or "").strip():
                self._record_notice("请先选择录制保存目录")
                return
        if not self.settings.get("recording_lock_quality", True):
            self.recorder.start(tile, recording=recording)
            return
        if tile in self.recorder.sessions:
            self.recorder.start(tile, recording=recording)
            return
        if not tile.room.get("live") or not tile.isVisible():
            self.recorder.start(tile, recording=recording)
            return
        self._capture_quality[tile] = (str(tile.room.get("room_id") or ""), int(tile.quality))
        self._pending_capture[tile] = recording
        tile.quality_button.setEnabled(False)
        tile.quality_locked = True
        if tile.quality == 10000 and tile.actual_quality == 10000 and tile.stream_url:
            self._finish_pending_capture(tile)
            return
        if tile.quality != 10000:
            blocked = tile.blockSignals(True)
            try:
                tile.set_quality(10000)
            finally:
                tile.blockSignals(blocked)
            tile.room["quality"] = 10000
        self.start_tile(tile)

    def _finish_pending_capture(self, tile) -> None:
        recording = self._pending_capture.pop(tile)
        if tile.actual_quality != 10000:
            self._record_notice("直播源未提供原画，录制未开始")
            self._restore_capture_quality(tile)
        elif not self.recorder.start(tile, recording=recording):
            self._restore_capture_quality(tile)

    def _restore_capture_quality(self, tile) -> None:
        previous = self._capture_quality.pop(tile, None)
        if previous is None:
            return
        tile.quality_locked = False
        tile.quality_button.setEnabled(True)
        room_id, before = previous
        if str(tile.room.get("room_id") or "") != room_id:
            return
        if before != tile.quality:
            blocked = tile.blockSignals(True)
            try:
                tile.set_quality(before)
            finally:
                tile.blockSignals(blocked)
            tile.room["quality"] = before
            if tile.room.get("live") and tile.isVisible() and not self._closing:
                self.start_tile(tile)

    def _record_state_changed(self, tile) -> None:
        session = self.recorder.sessions.get(tile)
        if session is None and tile not in self._pending_capture:
            self._restore_capture_quality(tile)
        recording = bool(session and session.recording and not session.stopping)
        state = "record" if recording else (
            "cache" if session and not session.stopping else "")
        tile.set_recording_state(state)
        if recording:
            # 记下开录时刻，交给 _tick_record_clock() 每秒刷「● REC 00:12:34」
            self._recording_since[tile] = float(
                getattr(session, "started_at", 0.0) or time.monotonic())
        else:
            self._recording_since.pop(tile, None)
            tile.set_recording_elapsed("")
        self._tick_record_clock()

    def _tick_record_clock(self) -> None:
        """刷新每格的录制时长（REC 旁边那个）。"""
        now = time.monotonic()
        for tile in self.wall.tiles:
            started = self._recording_since.get(tile)
            if started is None:
                continue
            seconds = max(0, int(now - started))
            hours, rest = divmod(seconds, 3600)
            minutes, secs = divmod(rest, 60)
            tile.set_recording_elapsed(
                f"{hours:d}:{minutes:02d}:{secs:02d}" if hours
                else f"{minutes:02d}:{secs:02d}")

    def _record_notice(self, message: str) -> None:
        if self._closing:
            return
        if any(word in message for word in ("磁盘", "空间不足", "找不到 FFmpeg",
                                            "启动失败", "续录失败", "导出失败",
                                            "连接中", "只能录制", "正在结束", "保存目录", "原画")):
            box = QMessageBox(QMessageBox.Warning, "录制提醒", message,
                              QMessageBox.Ok, self)
            box.setAttribute(Qt.WA_DeleteOnClose)
            box.open()

    # ---- 房间增删 ----
    def open_add_room(self) -> None:
        dialog = AddRoomDialog(self)
        if dialog.exec() != AddRoomDialog.Accepted:
            return
        room_id = dialog.room_id
        if any(str(room.get("room_id")) == room_id for room in self.sidebar.rooms()):
            print(f"房间 {room_id} 已在关注列表里")
            return
        print(f"正在查询房间 {room_id} ...")
        resolver = InfoResolver(room_id, self)
        resolver.resolved.connect(self._on_room_added)
        resolver.failed.connect(lambda rid: print(f"房间 {rid} 查询失败"))
        resolver.finished.connect(resolver.deleteLater)
        resolver.start()

    def _on_room_added(self, room: dict) -> None:
        if self.sidebar.add_room(room):
            self.load_avatars_for([room])       # 新加的房间立刻显示头像
        print(f"已添加 {room.get('uname')}（{'直播中' if room.get('live') else '未开播'}）")
        if len(self.wall.tiles) < MAX_TILES:
            self.add_to_wall(room)
        self._refresh_meta()

    def add_to_wall(self, room: dict) -> None:
        self._prepare_room(room)
        room_id = str(room.get("room_id"))
        if self._tile_of(room_id) is not None:
            print(f"{room.get('uname')} 已经在画面墙上")
            return
        empty = next((tile for tile in self.wall.tiles if not tile.room.get("room_id")), None)
        if empty is not None:                      # 优先填空位
            self.recorder.stop(empty)
            self._stop_tile(empty)
            empty.set_room(room)
            self._wire_tile(empty)
            self.start_tile(empty)
            self.plugins.emit(plugin_api.EVENT_TILE_ADDED, tile=empty,
                              room=dict(empty.room or {}))
            self._refresh_meta()
            self.refresh_stats()               # 新加的一路马上拉在线人数，不用等下一轮
            return
        if len(self.wall.tiles) >= MAX_TILES:
            print(f"画面墙已满（{MAX_TILES} 路）")
            return
        tile = self.wall.add_room(room)
        self._wire_tile(tile)
        self.start_tile(tile)
        self.plugins.emit(plugin_api.EVENT_TILE_ADDED, tile=tile,
                          room=dict(tile.room or {}))
        self._refresh_meta()
        self.refresh_stats()

    def remove_room(self, room: dict) -> None:
        tile = self._tile_of(str(room.get("room_id")))
        if tile is not None:
            self.plugins.emit(plugin_api.EVENT_TILE_REMOVED, tile=tile,
                              room=dict(tile.room or {}))
            self.recorder.stop(tile)
            self._stop_tile(tile)
            self.wall.remove_room(tile.room)
        self.sidebar.remove_room(room)
        self._refresh_meta()
        print(f"已移除 {room.get('uname')}")

    def remove_rooms(self, rooms: list) -> None:
        for room in rooms:
            self.remove_room(room)
        print(f"多选删除完成，共 {len(rooms)} 个")

    # ---- 登录 / 导入关注 ----
    def refresh_account(self) -> None:
        """刷新侧栏底部的账号信息。"""
        if not bili.SESSION_DATA:
            self.sidebar.clear_account()
            return
        loader = AccountLoader(self)
        loader.loaded.connect(self._on_account_loaded)
        loader.finished.connect(loader.deleteLater)
        self._account_loader = loader
        loader.start()

    def _on_account_loaded(self, account: dict) -> None:
        self.sidebar.set_account(account.get("uname", ""), None)
        face = account.get("face") or ""
        if not face:
            return
        loader = AvatarLoader({"account": face}, self)
        loader.loaded.connect(lambda _key, pixmap: self.sidebar.set_account(
            account.get("uname", ""), pixmap))
        loader.finished.connect(loader.deleteLater)
        self._account_avatar_loader = loader
        loader.start()

    def load_cached_covers(self) -> None:
        """先把「上次那张封面」摆上（纯本地读文件，不联网、不等状态轮询）。

        启动时 ``build_rooms`` 只给占位条目、主播没开播时接口也不给封面；靠
        ``cache/covers/room/<房间号>.png`` 里留的那张，卡片一出来就有图。等状态
        刷新拿到真 URL，``load_room_avatars`` / ``_on_status_updated`` 会换成最新的。
        """
        rooms = self.sidebar.rooms()
        room_ids = [str(room.get("room_id")) for room in rooms if room.get("room_id")]
        if not room_ids:
            return
        loader = CachedCoverLoader(room_ids, self)
        loader.loaded.connect(self._on_room_cover)
        loader.finished.connect(loader.deleteLater)
        self._cover_cache_loader = loader
        loader.start()

    def load_room_avatars(self) -> None:
        """把关注列表里的主播头像和封面缩略图换成真实的。"""
        rooms = self.sidebar.rooms()
        faces = {str(room.get("room_id")): room.get("face")
                 for room in rooms if room.get("face")}
        covers = {str(room.get("room_id")): room.get("cover_url")
                  for room in rooms if room.get("cover_url")}
        self._room_avatar_loader = self._start_avatar_loader(faces, self._on_room_avatar)
        self._cover_loader = self._start_avatar_loader(covers, self._on_room_cover,
                                                       subdir="covers")

    def load_avatars_for(self, rooms: list) -> None:
        """刚加进来的房间立刻取头像和封面，不用等下一轮状态刷新。"""
        faces = {str(room.get("room_id")): room.get("face")
                 for room in rooms if room.get("face")}
        covers = {str(room.get("room_id")): room.get("cover_url")
                  for room in rooms if room.get("cover_url")}
        self._start_avatar_loader(faces, self._on_room_avatar)
        self._start_avatar_loader(covers, self._on_room_cover, subdir="covers")

    def _start_avatar_loader(self, items: dict, slot, subdir: str = "avatars"):
        """统一的头像下载：线程都留个引用，关窗时好等它们收尾。"""
        if not items:
            return None
        loader = AvatarLoader(items, self, subdir=subdir)
        loader.loaded.connect(slot)
        loader.finished.connect(loader.deleteLater)
        self._avatar_loaders = [item for item in self._avatar_loaders
                                if self._loader_running(item)]
        self._avatar_loaders.append(loader)
        loader.start()
        return loader

    @staticmethod
    def _loader_running(loader) -> bool:
        try:
            return loader.isRunning()
        except RuntimeError:                 # 已经被 Qt 回收
            return False

    def _on_room_avatar(self, room_id: str, pixmap) -> None:
        for item in self.sidebar._items:            # noqa: SLF001
            if str(item.room.get("room_id")) == str(room_id):
                item.thumb.set_face(pixmap)
                # 竖屏顶部横栏的头像排用的是同一张图（那边不走 NavItem）
                self.sidebar.set_room_face(room_id, pixmap)
                return

    def _on_room_cover(self, room_id: str, pixmap) -> None:
        for item in self.sidebar._items:            # noqa: SLF001
            if str(item.room.get("room_id")) == str(room_id):
                item.thumb.set_cover(pixmap)
                return

    def logout(self) -> None:
        bili.set_sessdata("")
        self.state["sessdata"] = ""
        self.sidebar.clear_account()
        config_module.save(self.current_state())
        print("已退出登录", file=sys.stderr, flush=True)

    def open_login(self) -> None:
        from .login import LoginWindow      # 延迟导入：QtWebEngine 比较重

        window = LoginWindow(self)
        window.sessionData.connect(self._on_login)
        window.exec()

    def _on_login(self, sessdata: str) -> None:
        bili.set_sessdata(sessdata)
        self.state["sessdata"] = sessdata
        config_module.save(self.current_state())
        self.refresh_account()
        # 之前是匿名连的弹幕，服务端会把用户名打码；登录后重连一次
        self.stop_danmaku()
        self.sync_danmaku()
        print(f"登录成功，已保存登录状态（{len(sessdata)} 字符）", file=sys.stderr, flush=True)

    def open_import_follows(self) -> None:
        if not bili.SESSION_DATA:
            print("导入关注需要先登录，打开登录窗口", file=sys.stderr, flush=True)
            self.open_login()
            if not bili.SESSION_DATA:
                print("未获取到登录状态，导入流程取消", file=sys.stderr, flush=True)
                return
        else:
            print("已登录，直接拉取关注列表", file=sys.stderr, flush=True)
        self.import_button_busy(True)
        self._follow_loader = FollowLoader(self)
        self._follow_loader.loaded.connect(self._on_follows_loaded)
        self._follow_loader.failed.connect(self._on_follows_failed)
        self._follow_loader.finished.connect(self._follow_loader.deleteLater)
        self._follow_loader.start()

    def import_button_busy(self, busy: bool) -> None:
        self.sidebar.import_button.setEnabled(not busy)
        self.sidebar.import_button.setText("拉取中…" if busy else "导入关注")

    def _on_follows_failed(self, reason: str) -> None:
        self.import_button_busy(False)
        print(f"拉取关注列表失败: {reason}")

    def _on_follows_loaded(self, rooms: list) -> None:
        self.import_button_busy(False)
        existing = {str(room.get("room_id")) for room in self.sidebar.rooms()}
        dialog = FollowImportDialog(rooms, existing, self)
        faces = {str(room["room_id"]): room.get("face")
                 for room in rooms if room.get("face")}
        if faces:
            loader = AvatarLoader(faces, self)
            loader.loaded.connect(dialog.set_avatar)
            loader.finished.connect(loader.deleteLater)
            self._follow_avatar_loader = loader
            loader.start()
            # 先等第一批头像下载完（同一批会写进本地缓存，下次就直接有了）
            deadline = time.time() + 1.5
            while time.time() < deadline:
                QApplication.processEvents()
                time.sleep(0.03)
        if dialog.exec() != FollowImportDialog.Accepted:
            return
        selected = dialog.selected()
        added = sum(1 for room in selected if self.sidebar.add_room(room))
        self.load_avatars_for(selected)          # 导入后立刻补头像
        self._refresh_meta()
        print(f"导入完成：选中 {len(selected)} 个，新增 {added} 个")

    def _refresh_meta(self) -> None:
        """只负责画面墙的显隐（右侧原来那行文字已经去掉，画面填满）。"""
        self.sidebar.set_wall_rooms(
            str(tile.room.get("room_id") or "") for tile in self.wall.tiles)
        self.wall.setVisible(bool(self.wall.tiles))
        self.empty_hint.setVisible(not self.wall.tiles)
        self.sync_danmaku()

    # ---- 弹幕 ----
    def _danmaku_target_room(self) -> dict:
        """弹幕格跟着主画面走；没有主画面就跟第一路有人的画面。"""
        tiles = self.wall.tiles
        main = self.wall.main_index()
        if main is not None and 0 <= main < len(tiles):
            return tiles[main].room or {}
        for tile in tiles:
            if tile.room.get("room_id"):
                return tile.room
        return {}

    def sync_danmaku(self) -> None:
        """让弹幕连接对上当前布局/主画面（布局里没有弹幕格就断开）。"""
        panel = self.wall.danmaku
        if not self.wall.has_danmaku:
            self.stop_danmaku()
            return
        room = self._danmaku_target_room()
        room_id = str(room.get("room_id") or "")
        if room_id and room_id == self._danmaku_room and self._danmaku is not None:
            return
        self.stop_danmaku()
        if not room_id:
            panel.set_placeholder("把直播间拖到主画面，这里就会显示它的弹幕")
            return
        self.start_danmaku(room_id, room.get("uname", ""))

    def start_danmaku(self, room_id: str, uname: str = "") -> None:
        panel = self.wall.danmaku
        panel.set_placeholder(f"正在连接 {uname or room_id} 的弹幕…")
        panel.set_status("连接中…")
        client = DanmakuClient(room_id, self)
        client.message.connect(
            lambda event, source=client: self._on_danmaku_message(source, event))
        client.status.connect(
            lambda text, source=client: self._on_danmaku_status(source, text))
        client.finished.connect(client.deleteLater)
        self._danmaku = client
        self._danmaku_room = str(room_id)
        client.start()
        print(f"[弹幕] 开始接收 {uname or room_id}（房间 {room_id}）",
              file=sys.stderr, flush=True)

    def stop_danmaku(self) -> None:
        client = self._danmaku
        self._danmaku = None
        self._danmaku_room = ""
        if client is None:
            return
        client.stop()
        try:
            if client.isRunning():
                client.wait(2000)         # 线程还在跑就析构，Qt 会直接崩
        except RuntimeError:
            pass

    def apply_danmaku_settings(self) -> None:
        """把设置里的弹幕字体、字号、保留条数交给弹幕格。"""
        self.wall.danmaku.apply_style(
            str(self.settings.get("danmaku_font") or ""),
            int(self.settings.get("danmaku_font_size") or 13))
        self.wall.danmaku.set_max_blocks(
            int(self.settings.get("danmaku_max_blocks") or 300))

    def _on_danmaku_font_size(self, value: int) -> None:
        """面板上拖了字号：记住并延迟写盘（拖一次会发很多次信号）。"""
        self.settings["danmaku_font_size"] = int(value)
        self._save_timer.start()

    def apply_preview_settings(self) -> None:
        """关注列表样式与悬停预览开关。"""
        before = self.sidebar.card_mode
        self.sidebar.set_compact_policy(
            bool(self.settings.get("sidebar_card_mode", True)),
            bool(self.settings.get("sidebar_auto_compact", True)),
            int(self.settings.get("sidebar_compact_threshold", 18)),
        )
        if self.sidebar.card_mode != before:
            self.hover_preview.stop()
        self.hover_preview.enabled = bool(self.settings.get("preview_on_hover", True))
        if not self.hover_preview.enabled:
            self.hover_preview.stop()

    def _danmaku_blocked(self, text: str) -> bool:
        """命中屏蔽词就不显示这条弹幕（大小写不敏感）。"""
        words = [str(word).strip() for word in (self.settings.get("danmaku_block_words") or [])]
        words = [word for word in words if word]
        if not words:
            return False
        lowered = str(text).lower()
        return any(word.lower() in lowered for word in words)

    def _on_danmaku_message(self, source, event: dict) -> None:
        if source is not self._danmaku:
            return                         # 已切换房间，忽略旧线程排队中的消息
        kind = event.get("kind") or "danmaku"
        if kind == "danmaku" and self._danmaku_blocked(event.get("text") or ""):
            return
        self.wall.danmaku.add_event(event)
        self.plugins.emit(plugin_api.EVENT_DANMAKU, room_id=self._danmaku_room,
                          message=dict(event))

    def _on_danmaku_status(self, source, text: str) -> None:
        if source is not self._danmaku:
            return                         # 旧连接不能覆盖当前连接的状态
        self.wall.danmaku.set_status(text)
        self.plugins.emit(plugin_api.EVENT_DANMAKU_STATUS,
                          room_id=self._danmaku_room, status=text)

    # ---- 快捷键 ----
    def _tile_under_cursor(self):
        """鼠标现在压在哪一格的画面上（没有就 None）。

        **不能用 QApplication.widgetAt**：格子的画面区是 VLC 的原生窗口，不是 Qt
        控件；鼠标停在画面上时 widgetAt 拿不到那一格（顶多给回主窗口），
        于是 F（全屏）/ M / Alt+M 全都按不动 —— 用户报的「切换画布完全失效」
        就是这个。改成拿光标全局坐标和每个格子的矩形比，跟画面是不是原生窗口无关。
        """
        point = QCursor.pos()
        tiles = self.wall.tiles if hasattr(self, "wall") else []
        for tile in tiles:
            if not tile.isVisible():
                continue
            if tile.rect().contains(tile.mapFromGlobal(point)):
                return tile
        return None

    def keyPressEvent(self, event) -> None:
        pressed = QKeySequence(event.keyCombination()).toString()
        shortcuts = self.shortcuts
        if pressed and pressed == shortcuts.get("focus"):
            if self._fullscreen_tile is not None:
                self._exit_fullscreen()
            else:
                tile = self._tile_under_cursor()
                if tile is not None and tile.room.get("room_id"):
                    self._on_fullscreen(tile)
        elif pressed and pressed == shortcuts.get("mute"):
            self._toggle_mute_under_cursor()
        elif pressed and pressed == shortcuts.get("solo"):
            self._toggle_solo_audio()
        elif pressed and pressed == shortcuts.get("restore") and self._fullscreen_tile:
            self._exit_fullscreen()
        else:
            super().keyPressEvent(event)

    def _toggle_mute_under_cursor(self) -> None:
        """M：静音 / 取消静音鼠标所在的那一路（只动这一路，别的格子不变）。"""
        target = self._tile_under_cursor()
        if target is None or not target.room.get("room_id"):
            return
        target.set_muted(not target.muted)
        print(f"[快捷键] {target.room.get('uname')} "
              f"{'已静音' if target.muted else '已取消静音'}",
              file=sys.stderr, flush=True)

    def _toggle_solo_audio(self) -> None:
        """Alt+M：只让鼠标悬停的那一路有声，其他格子一律静音。

        鼠标不在任何格子上时等于「全部静音」——这也是想安静下来时最顺手的按法。
        """
        target = self._tile_under_cursor()
        if target is not None and not target.room.get("room_id"):
            target = None
        for tile in self.wall.tiles:
            tile.set_muted(tile is not target)
        if target is not None:
            print(f"[快捷键] 只保留 {target.room.get('uname')} 的声音",
                  file=sys.stderr, flush=True)
        else:
            print("[快捷键] 全部静音", file=sys.stderr, flush=True)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    t0 = time.perf_counter()                # 量化启动耗时：窗口多久才出现
    try:                                    # 控制台可能是 GBK，避免房间名里的特殊字符导致崩溃
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass
    log_path = setup_file_log()
    app = QApplication(argv)
    app.setApplicationName(version_module.DISPLAY_NAME)
    app.setStyleSheet(theme.qss())
    for icon_path in (os.path.join(config_module.REPO, "assets", "favicon.ico"),
                      os.path.join(config_module.REPO, "favicon.ico")):
        if os.path.isfile(icon_path):        # 有图标文件就用，没有也不影响启动
            app.setWindowIcon(QIcon(icon_path))
            break

    state = config_module.load()
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
    # libvlc 放到后台线程去建：第一次运行要扫 200 多个 VLC 插件，用户机器上
    # 这一步在主线程里卡了 4.5 秒（看门狗日志），界面就跟着冻住。悬停预览
    # 关掉时第二个实例不用建，省一点内存。
    TilePlayer.warm_up_vlc(preview=bool(settings.get("preview_on_hover", True)))
    sidebar, wall = config_module.build_rooms(state) if state else ([], [])
    t_rooms = time.perf_counter()
    print(f"关注房间 {len(sidebar)} 个，画面墙 {len(wall)} 个格子"
          + ("" if state else "（全新配置）"))
    print(f"[VLC] libvlc {TilePlayer.vlc_version()} 硬件解码="
          f"{'开' if settings.get('hw_decode', True) else '关（软解）'}",
          file=sys.stderr, flush=True)

    window = MainWindow(sidebar, wall,
                        layout_id=(state.get("ui") or {}).get("layout") or "",
                        state=state)
    t_window = time.perf_counter()
    # 界面卡死看门狗：主线程靠这个 QTimer 报平安，卡死时日志里会留下所有线程的调用栈
    watchdog.start(log_path)
    ticker = QTimer(window)
    ticker.setInterval(watchdog.TICK_MS)
    ticker.timeout.connect(watchdog.tick)
    ticker.start()
    window.resize(1600, 900)
    window.showMaximized()
    t_show = time.perf_counter()
    print(f"[启动] 配置加载 {(t_load - t0) * 1000:.0f} ms | "
          f"房间占位 {(t_rooms - t_load) * 1000:.0f} ms | "
          f"界面构建 {(t_window - t_rooms) * 1000:.0f} ms | "
          f"窗口显示 {(t_show - t0) * 1000:.0f} ms",
          file=sys.stderr, flush=True)
    code = app.exec()
    watchdog.stop()
    # 关窗时可能还有网络线程在收尾，Qt / VLC 的析构顺序会偶发崩在退出瞬间，
    # 配置在 closeEvent 里已经存好了，这里直接退出进程最稳。
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:  # noqa: BLE001
        pass
    os._exit(code)


if __name__ == "__main__":
    raise SystemExit(main())
