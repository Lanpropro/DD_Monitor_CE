"""应用外壳：左侧房间列表 + 右侧画面墙。

画面墙上的每个格子是一个"播放位"：关掉某一路会留下空格子，等着把侧栏里的
直播间拖进来；播放器按格子持有，和房间号解耦。
"""
import os
import sys
import time

from PySide6.QtCore import QByteArray, Qt, QTimer
from PySide6.QtGui import QCursor, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QMainWindow, QStackedWidget, QVBoxLayout, QWidget,
)

from . import bili
from . import config as config_module
from . import layouts
from . import plugins as plugin_api
from . import theme
from .danmaku import DanmakuClient
from .bili import (
    AccountLoader, FollowLoader, InfoResolver, StatsPoller, StatusPoller, StreamResolver,
)
from .dialogs import (
    SHORTCUT_ACTIONS, AddRoomDialog, FollowImportDialog, SettingsDialog,
)
from .images import AvatarLoader
from .player import TilePlayer
from .preview import HoverPreview
from .widgets import Sidebar, Tile, WallGrid

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
                 layout_id: str = "auto", state: dict | None = None):
        super().__init__()
        self.setWindowTitle("DD 监控室")
        self.setFocusPolicy(Qt.StrongFocus)     # 让窗口能接收快捷键
        self.rooms = rooms
        self.state = state or {}
        self.layout_id = layout_id
        self.players: dict[object, TilePlayer] = {}      # 按格子持有播放器
        self._resolvers: dict[object, StreamResolver] = {}
        self._avatar_loaders: list = []                 # 头像下载线程，关窗时要等它们
        self._poller = None
        self._stats_poller = None
        self._retry_count: dict[object, int] = {}
        self._retry_timers: dict[object, QTimer] = {}
        self._freeze_refreshed: set[object] = set()
        self._freeze_retry_timers: dict[object, QTimer] = {}
        self._previous_layout: str | None = None
        self._danmaku: DanmakuClient | None = None      # 弹幕格当前连的那一路
        self._danmaku_room = ""
        self.shortcuts = dict(DEFAULT_SHORTCUTS)
        self.settings = dict(config_module.DEFAULT_SETTINGS)
        self.settings.update(self.state.get("settings") or {})

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
        )

        self.empty_hint = QLabel(EMPTY_HINT)
        self.empty_hint.setObjectName("EmptyHint")
        self.empty_hint.setAlignment(Qt.AlignCenter)
        # 没有显式墙面房间时，墙面应从空位开始；关注列表不等于已上墙房间。
        # 否则布局变大时，原本隐藏的关注会被误显示成新格子的主播。
        self.wall = WallGrid(wall_rooms if wall_rooms is not None else [], layout_id)

        #: 画面墙那一块（画面墙 + 空态提示），横竖两套排布共用它
        self._content = QWidget()
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        content_layout.addWidget(self.wall, 1)
        content_layout.addWidget(self.empty_hint, 1)

        self.setCentralWidget(root)
        self.orientation = ""                  # 由 _apply_orientation 填
        self._build_arrangement("landscape")
        #: 构造时显式指定的布局（交给 _apply_orientation 决定用哪个方向的）
        self._pending_layout = ""

        # 信号接线
        self.sidebar.roomSelected.connect(self.wall.tileClicked.emit)
        self.sidebar.addRoomClicked.connect(self.open_add_room)
        self.sidebar.importFollowsClicked.connect(self.open_import_follows)
        self.sidebar.addToWallRequested.connect(self.add_to_wall)
        self.sidebar.removeRequested.connect(self.remove_room)
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
        print(f"[插件] {self.plugins.summary}", file=sys.stderr, flush=True)
        for entry, reason in self.plugins.skipped:
            print(f"[插件] 跳过 {entry}：{reason}", file=sys.stderr, flush=True)
        QTimer.singleShot(0, lambda: self.plugins.emit(plugin_api.EVENT_STARTED))

        QTimer.singleShot(0, self.start_all)
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
        # 布局按方向分别记：老配置只有一个 layout，当作横屏的
        ui = self.state.setdefault("ui", {})
        if "layout" in ui and "layout_landscape" not in ui:
            ui["layout_landscape"] = ui.pop("layout")
        ui.setdefault("layout_landscape", "auto")
        ui.setdefault("layout_portrait", "auto")

    # ---- 竖屏 / 横屏 ----
    def _build_arrangement(self, orientation: str) -> None:
        """按方向重新摆放侧栏和画面墙。

        横屏：侧栏在左（固定宽）+ 右侧画面墙。
        竖屏：侧栏变成顶部横栏（撑满宽）+ 下面画面墙。
        """
        layout = self._root_layout
        while layout.count():
            layout.takeAt(0)
        # 侧栏和画面墙里有些控件是原生窗口（VLC 视频、浮标、控制条）。原生窗口在
        # 换父容器/换布局时容易脱离父窗口，变成一个单独留着的小悬浮窗 ——
        # 换排布前先降级成普通控件，换完再让各自恢复。
        self._demote_native_windows()
        # 竖屏的容器布局也要清空：`_content` 挂在它里面，不清掉的话
        # 再 addWidget 到根布局会两个布局抢同一个控件，结果谁都没挂上
        portrait_layout = getattr(self, "_portrait_layout", None)
        if portrait_layout is not None:
            while portrait_layout.count():
                portrait_layout.takeAt(0)
        if orientation == "portrait":
            if getattr(self, "_portrait_host", None) is None:
                self._portrait_host = QWidget()
                self._portrait_layout = QVBoxLayout(self._portrait_host)
                self._portrait_layout.setContentsMargins(0, 0, 0, 0)
                self._portrait_layout.setSpacing(0)
                portrait_layout = self._portrait_layout
            self._portrait_layout.addWidget(self.sidebar)
            self._portrait_layout.addWidget(self._content, 1)
            layout.addWidget(self._portrait_host)
        else:
            # 横屏：把侧栏从竖屏容器里取出来挂回根布局
            central = self.centralWidget()
            self.sidebar.setParent(central)
            self._content.setParent(central)
            self.sidebar.setMaximumHeight(16_777_215)
            layout.addWidget(self.sidebar)
            layout.addWidget(self._content, 1)
        self.sidebar.set_side("top" if orientation == "portrait" else "left")
        # 换完排布再同步一次可见性：收起/展开只影响「露哪些控件」，
        # 而 set_collapsed 在换排布之前就设过了，不补这一下头像排不会露出来。
        self.sidebar._sync_top_mode()      # noqa: SLF001
        # 排布换完再让画面墙重算并提回原生窗口（换父容器会让它们掉出原生状态）
        self.wall.relayout(force=True)
        self._promote_native_windows()
        self._adopt_stray_tiles()          # 换完再兜一次，收掉中途漏出去的

    def _demote_native_windows(self) -> None:
        """换排布前把画面墙里的原生窗口降级，免得多出一个单独留着的悬浮窗。

        原生窗口（VLC 视频区、浮标、控制条）一旦脱离父窗口就会自己留一个顶层
        小窗口。切方向要重新挂父容器，所以先降级；各自的 showEvent 会再提回原生。
        """
        for tile in self.wall.tiles:
            widgets = (tile.video, tile.stream_badge, tile.title_badge,
                       tile.time_badge, tile.controls, tile.spinner,
                       tile.pause_overlay)
            # hide() 会改变控件自己的显隐状态；先记住真实意图，提回原生窗口时
            # 才不会把「连接中」「已暂停」或悬停控制条一股脑全部显示/隐藏。
            if not hasattr(tile, "_native_visibility"):
                tile._native_visibility = [
                    (widget, not widget.isHidden())
                    for widget in widgets if widget is not None
                ]
            player = self.players.get(tile)
            if player is not None and hasattr(player, "invalidate_binding"):
                player.invalidate_binding()
            # 隐藏的格子也要处理：它们虽然当前不可见，但换父容器时
            # 一旦被 Qt 提成原生窗口，就会变成一个单独留着的 344x344 悬浮窗
            tile.setAttribute(Qt.WA_NativeWindow, False)
            tile.hide()
            for widget in widgets:
                if widget is None or not widget.testAttribute(Qt.WA_NativeWindow):
                    continue
                widget.setAttribute(Qt.WA_NativeWindow, False)
                widget.hide()          # 先藏起来，避免降级瞬间闪一个独立窗口
        # 兜底：已经变成顶层窗口的格子也收掉（换父容器失败时会漏出去）
        self._adopt_stray_tiles()

    def _adopt_stray_tiles(self) -> None:
        """把漏成顶层窗口的格子收回来挂到画面墙上。

        原生窗口一旦脱离父窗口就会自己变成一个顶层小窗口（用户看到的
        「单独留着的悬浮窗」就是它）。每次换完排布都要兜一次。
        """
        for widget in QApplication.topLevelWidgets():
            if isinstance(widget, Tile) and widget is not self:
                widget.setAttribute(Qt.WA_NativeWindow, False)
                widget.hide()
                widget.setParent(self.wall)


    def _promote_native_windows(self) -> None:
        """换完排布把原生窗口提回来（和 _demote_native_windows 成对）。"""
        for tile in self.wall.tiles:
            widgets = (tile.video, tile.stream_badge, tile.title_badge,
                       tile.time_badge, tile.controls, tile.spinner,
                       tile.pause_overlay)
            saved = getattr(tile, "_native_visibility", None)
            if saved is None:
                saved = [(widget, not widget.isHidden())
                         for widget in widgets if widget is not None]
            elif hasattr(tile, "_native_visibility"):
                del tile._native_visibility

            # 布局容量外的格子只恢复自己的显隐意图；等以后真的显示时，
            # Tile.showEvent 会把需要的叠层提成原生窗口。
            if tile.isHidden():
                for widget, visible in saved:
                    widget.setVisible(visible)
                continue

            # 先恢复实际显隐状态，再按新尺寸排版。播放器重新绑定可能把 VLC
            # 原生视频窗口抬到最上层，所以最后再 raise 可见叠层。
            for widget, visible in saved:
                if widget is not tile.video and not widget.testAttribute(Qt.WA_NativeWindow):
                    widget.setAttribute(Qt.WA_NativeWindow, True)
                widget.setVisible(visible)
            tile.layout_areas() if hasattr(tile, "layout_areas") else tile._layout_areas()
            player = self.players.get(tile)
            if player is not None:
                player.bind()
            for widget, _visible in saved:
                if widget is not tile.video and not widget.isHidden():
                    widget.raise_()

    def is_portrait(self) -> bool:
        """窗口比高度矮（含接近方形）就算竖屏。"""
        width, height = max(self.width(), 1), max(self.height(), 1)
        return width <= height * PORTRAIT_MAX_RATIO

    def _saved_layout(self, orientation: str) -> str:
        ui = self.state.get("ui") or {}
        return str(ui.get(f"layout_{orientation}") or "auto")

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
        if orientation != self.orientation:
            self._build_arrangement(orientation)
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
        elif not self._layout_fits(saved, portrait):
            # 配置里的布局不适合这个方向（比如竖屏选了竖屏预设，现在拖回横屏）：
            # 回落到该方向的自动布局，别把不合适的预设硬套上去
            layout_id = layouts.PORTRAIT_AUTO if portrait else "auto"
        else:
            layout_id = saved
        if layout_id != self.wall.layout_id:
            self.wall.set_layout(layout_id)
            self.sidebar.set_layout_name(layout_id)
        # 换了排布/换了布局，画面墙的尺寸和格子可见性都要重算一次
        self.wall.relayout(force=True)
        # set_layout() 可能在 _build_arrangement() 之后才把新方向的格子显示出来；
        # 这些格子和视频区都要在最终排布完成后再恢复原生状态。
        self._promote_native_windows()
        self._adopt_stray_tiles()
        print(f"[方向] {'竖屏' if portrait else '横屏'}　布局={layout_id}",
              file=sys.stderr, flush=True)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # 只有方向真的翻转时才动手，避免每次拖窗口都重排
        if getattr(self, "orientation", "") != ("portrait" if self.is_portrait()
                                                else "landscape"):
            self._apply_orientation()

    # ---- 设置 ----
    def poll_interval_ms(self) -> int:
        minutes = int(self.settings.get("poll_minutes", 1) or 1)
        return max(1, min(30, minutes)) * 60_000

    def open_settings(self) -> None:
        """一个窗口里选类别（常规 / 快捷键），和 Adobe 那类设置一样。"""
        dialog = SettingsDialog(self.settings, self.shortcuts, self)
        if dialog.exec() != SettingsDialog.Accepted:
            return
        self.settings.update(dialog.settings())
        self.shortcuts = dialog.shortcuts()
        self.state["settings"] = dict(self.settings)
        self.state.setdefault("ui", {})["shortcuts"] = dict(self.shortcuts)
        self._poll_timer.setInterval(self.poll_interval_ms())
        for player in self.players.values():
            player.freeze_watch = bool(self.settings.get("freeze_watch", True))
        config_module.save(self.current_state())
        self.apply_danmaku_settings()
        self.apply_preview_settings()
        print(f"[设置] {self.settings} 快捷键 {self.shortcuts}", file=sys.stderr, flush=True)

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
            "geometry": str(self.saveGeometry().toBase64(), "ASCII"),
            # 插件自己的配置项，以及「启用了哪些插件」（None = 全启用）
            "plugins": self.plugins.plugin_settings,
            "plugins_enabled": (None if self.plugins.enabled is None
                                else sorted(self.plugins.enabled)),
        }

    def closeEvent(self, event) -> None:
        self.plugins.emit(plugin_api.EVENT_CLOSING)
        self.plugins.unload()
        config_module.save(self.current_state())
        self.stop_danmaku()
        self.hover_preview.stop()
        for timer in self._freeze_retry_timers.values():
            timer.stop()
        self._freeze_retry_timers.clear()
        for player in self.players.values():
            player.release()
        self._wait_background()
        super().closeEvent(event)

    def _wait_background(self) -> None:
        """等在跑的线程收尾；线程还在跑就析构，Qt 会直接崩。"""
        names = ("_account_loader", "_account_avatar_loader", "_room_avatar_loader",
                 "_status_avatar_loader", "_follow_avatar_loader", "_follow_loader",
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
        # 只换画面墙的摆放方式，**不动窗口方向**：窗口是什么形状由用户拖，
        # 套用竖屏预设不会把窗口变竖，所以摆放必须跟着窗口走，否则画面会被压扁。
        want_portrait = layouts.is_portrait_layout(layout_id)
        if want_portrait != (self.orientation == "portrait"):
            print(f"[布局] {layout_id} 是给{'竖屏' if want_portrait else '横屏'}的；"
                  f"当前窗口是{'竖屏' if self.orientation == 'portrait' else '横屏'}，"
                  f"想要那种排布请把窗口拖成竖的", file=sys.stderr, flush=True)
        self.wall.set_layout(layout_id)
        self.wall.relayout(force=True)
        self.sidebar.set_layout_name(self.wall.layout_id)
        # 记在**当前方向**名下：横屏选的布局不该被竖屏覆盖，反之亦然
        key = f"layout_{self.orientation or 'landscape'}"
        self.state.setdefault("ui", {})[key] = layout_id
        self.apply_quality_policy()
        self._refresh_meta()

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
            self._play_on(t, url, qn, profile, options, headers=resolver.headers))
        resolver.failed.connect(lambda rid, reason, t=tile: self._on_resolve_failed(t, reason))
        resolver.finished.connect(lambda t=tile: self._resolvers.pop(t, None))
        self._resolvers[tile] = resolver
        resolver.start()
        self.refresh_stats()          # 人数不用等下一轮轮询，立刻拉一次

    def _play_on(self, tile, url: str, quality: int = 0, profile: str = "web",
                 options: list | None = None, headers: dict | None = None) -> None:
        if options:
            tile.set_quality_options(options)
        if quality:
            tile.set_actual_quality(quality)
        player = self.players.get(tile)
        if player is None:
            player = TilePlayer(tile.video, self)
            player.stateChanged.connect(lambda state, t=tile: self._on_player_state(t, state))
            player.pictureActivity.connect(lambda t=tile: self._on_picture_activity(t))
            self.players[tile] = player
        player.freeze_watch = bool(self.settings.get("freeze_watch", True))
        player.set_volume(int(tile.volume))
        player.set_audio_channel(int(tile.audio_channel))
        player.set_muted(tile.muted)
        # 把这一路的取流结果记在格子上：插件（录像等）要拿它去拉同一路流
        room = tile.room or {}
        tile.stream_url = url
        tile.stream_profile = profile
        tile.stream_headers = dict(headers or TilePlayer.PROFILE_HEADERS.get(
            profile, TilePlayer.PROFILE_HEADERS["web"]))
        player.play(url, profile, tile.stream_headers)
        self.plugins.emit(
            plugin_api.EVENT_STREAM_RESOLVED,
            source=plugin_api.StreamSource(
                room_id=str(room.get("room_id") or ""),
                url=url,
                quality=int(quality or 0),
                channel=profile,
                headers=dict(tile.stream_headers),
                platform=str(room.get("platform") or "bilibili"),
                uname=str(room.get("uname") or ""),
                title=str(room.get("title") or ""),
            ),
            tile=tile,
        )

    def _on_resolve_failed(self, tile, reason: str) -> None:
        tile.set_status("连接失败")
        print(f"[取流失败] {tile.room.get('uname')}: {reason}")
        self.plugins.emit(plugin_api.EVENT_STREAM_FAILED, tile=tile, reason=reason,
                          room=dict(tile.room or {}))
        self.refresh_status()       # 取不到流时立刻确认是否已经下播
        if tile in self._freeze_refreshed:
            self._on_picture_frozen(tile)

    def _on_player_state(self, tile, state: str) -> None:
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
        if not self.settings.get("auto_reconnect", True):
            tile.set_status("断流（自动重连已关闭）")
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
        if resolver is not None and resolver.isRunning():
            resolver.terminate()
        self.plugins.emit(plugin_api.EVENT_TILE_STOPPED, tile=tile,
                          room=dict(tile.room or {}))

    def _offline_tile(self, tile) -> None:
        """这一路下播：停掉播放（画面变黑），格子继续留给它，等重新开播自动接上。"""
        timer = self._retry_timers.pop(tile, None)
        if timer is not None:
            timer.stop()
        self._retry_count.pop(tile, None)
        self._stop_tile(tile)
        tile.set_offline()
        print(f"[下播] {tile.room.get('uname')} 画面已清空，格子保留",
              file=sys.stderr, flush=True)

    def _tile_of(self, room_id: str):
        return next((tile for tile in self.wall.tiles
                     if str(tile.room.get("room_id") or "") == str(room_id)), None)

    def _prepare_room(self, room: dict) -> dict:
        """按全局设置给新上墙的直播间补默认静音 / 音量。"""
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
        to_start = []
        other = self._tile_of(room_id)
        if other is not None and other is not tile:
            # 已经在别的格子里：两边交换，避免同一个直播间出现两次
            previous = dict(tile.room) if tile.room.get("room_id") else None
            self._stop_tile(other)
            other.set_room(previous)
            if previous and previous.get("room_id"):
                to_start.append(other)
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
        """把来源格子里的直播间和目标格子互换（也包括拖到空格子上）。"""
        source = self._tile_of(source_room_id)
        if source is None or source is target_tile:
            return
        first, second = dict(source.room), dict(target_tile.room)
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

    def refresh_status(self) -> None:
        try:
            if self._poller is not None and self._poller.isRunning():
                return
        except RuntimeError:                 # 对象已被 Qt 回收
            self._poller = None
        room_ids = [str(room.get("room_id")) for room in self.sidebar.rooms()]
        if not room_ids:
            return
        poller = StatusPoller(room_ids, self)
        poller.updated.connect(self._on_status_updated)
        poller.finished.connect(self._on_poller_finished)
        self._poller = poller
        poller.start()

    def _on_poller_finished(self) -> None:
        poller = self._poller
        self._poller = None
        if poller is not None:
            poller.deleteLater()
        self.sidebar.set_refreshing(False)

    def refresh_follow(self) -> None:
        """侧栏的「刷新」：立刻拉一次直播状态，并把还没显示的头像补上。"""
        self.sidebar.set_refreshing(True)
        self.refresh_status()
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
            cover = info.get("cover_url") or ""
            if cover and cover != item.room.get("cover_url"):
                item.room["cover_url"] = cover      # 开播/下播后封面会变，缩略图跟着换
                covers[str(item.room.get("room_id"))] = cover
            if info["live"] and not was_live:
                # 刚开播：马上置位并重排，让「开播优先」先把卡片挪上去；
                # 动效等重排落地后再播，否则水滴会留在卡片原来的行上（两者错开）。
                if self.settings.get("live_alert", True):
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
        self.sidebar.resort()               # 「开播优先」要跟着开播状态重排
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
        tile = self._tile_of(str(room.get("room_id")))
        player = self.players.get(tile) if tile is not None else None
        if player is not None:
            player.set_volume(value)
        self._save_timer.start()       # 滑块停下 700ms 后保存每个格子的音量

    def _on_audio_changed(self, room: dict, value: int) -> None:
        tile = self._tile_of(str(room.get("room_id")))
        player = self.players.get(tile) if tile is not None else None
        if player is not None:
            player.set_audio_channel(value)
            # 播放中的这一路要等音频输出模块起来后再补一次，否则会被初始化冲掉
            player.reapply_audio_channel()
        self._save_timer.start()       # 声道属于格子，和音量一起记住

    def _on_quality_changed(self, room: dict, quality: int) -> None:
        # 注意：Qt 信号传过来的 dict 是副本，必须写回格子自己的字典
        tile = self._tile_of(str(room.get("room_id")))
        if tile is None:
            return
        tile.quality = quality
        tile.room["quality"] = quality
        if tile.room.get("live"):
            self.start_tile(tile)

    def _on_mute_changed(self, room: dict, muted: bool) -> None:
        tile = self._tile_of(str(room.get("room_id")))
        player = self.players.get(tile) if tile is not None else None
        if player is not None:
            player.set_muted(muted)
        self._save_timer.start()       # 静音也是格子状态，和音量一起记住

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

    def _on_fullscreen(self, room: dict) -> None:
        self.wall.focus_room(room)
        self.sidebar.set_layout_name(self.wall.layout_id)
        self.state.setdefault("ui", {})["layout"] = self.wall.layout_id
        self._refresh_meta()

    def _on_close_tile(self, room: dict) -> None:
        """关掉这一路，但留下空格子等新的直播间拖进来。"""
        tile = self._tile_of(str(room.get("room_id")))
        if tile is None:
            return
        self._stop_tile(tile)
        tile.set_room(None)
        self._refresh_meta()
        print(f"已关闭 {room.get('uname')}，格子已清空")

    def _wire_tile(self, tile) -> None:
        tile.qualityChanged.connect(self._on_quality_changed)
        tile.muteToggled.connect(self._on_mute_changed)
        tile.volumeChanged.connect(self._on_volume_changed)
        tile.audioChannelChanged.connect(self._on_audio_changed)
        tile.reloadRequested.connect(self._on_reload)
        tile.pauseToggled.connect(self._on_pause_toggled)
        tile.fullscreenRequested.connect(self._on_fullscreen)
        tile.closeRequested.connect(self._on_close_tile)
        tile.pluginMenuRequested.connect(lambda t=tile: self._fill_plugin_menu(t))

    def _fill_plugin_menu(self, tile) -> None:
        """右键菜单弹出前，把插件要加的项收进格子（插件异常不会影响菜单）。"""
        manager = getattr(self, "plugins", None)
        if manager is None:               # 插件还没装载（例如启动早期）
            tile.plugin_actions = []
            return
        collected = []
        for label, callback, name in manager.tile_actions(tile):
            collected.append((label, lambda cb=callback: manager.run_action(cb)))
        tile.plugin_actions = collected

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
        card_mode = bool(self.settings.get("sidebar_card_mode", True))
        if self.sidebar.card_mode != card_mode:
            self.hover_preview.stop()
            self.sidebar.set_card_mode(card_mode)
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
        widget = QApplication.widgetAt(QCursor.pos())
        while widget is not None:
            if isinstance(widget, Tile):
                return widget
            widget = widget.parentWidget()
        return None

    def keyPressEvent(self, event) -> None:
        pressed = QKeySequence(event.keyCombination()).toString()
        shortcuts = self.shortcuts
        if pressed and pressed == shortcuts.get("focus"):
            tile = self._tile_under_cursor()
            if tile is not None and tile.room.get("room_id"):
                self._previous_layout = self.wall.layout_id
                self._on_fullscreen(tile.room)
        elif pressed and pressed == shortcuts.get("solo"):
            self._toggle_solo_audio()
        elif pressed and pressed == shortcuts.get("restore") and self._previous_layout:
            self.wall.set_layout(self._previous_layout)
            self.sidebar.set_layout_name(self._previous_layout)
            self._previous_layout = None
            self._refresh_meta()
        else:
            super().keyPressEvent(event)

    def _toggle_solo_audio(self) -> None:
        """M/S：只让鼠标悬停的那一路有声，再按一次全部恢复静音。"""
        target = self._tile_under_cursor()
        for tile in self.wall.tiles:
            tile.set_muted(tile is not target)
        if target is not None:
            print(f"[快捷键] 只保留 {target.room.get('uname')} 的声音",
                  file=sys.stderr, flush=True)


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    try:                                    # 控制台可能是 GBK，避免房间名里的特殊字符导致崩溃
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass
    setup_file_log()
    app = QApplication(argv)
    app.setApplicationName("DD 监控室")
    app.setStyleSheet(theme.qss())
    for icon_path in (os.path.join(config_module.REPO, "assets", "favicon.ico"),
                      os.path.join(config_module.REPO, "favicon.ico")):
        if os.path.isfile(icon_path):        # 有图标文件就用，没有也不影响启动
            app.setWindowIcon(QIcon(icon_path))
            break

    state = config_module.load()
    sidebar, wall = config_module.build_rooms(state) if state else ([], [])
    print(f"关注房间 {len(sidebar)} 个，画面墙 {len(wall)} 个格子"
          + ("" if state else "（全新配置）"))

    window = MainWindow(sidebar, wall,
                        layout_id=(state.get("ui") or {}).get("layout", "auto"),
                        state=state)
    window.resize(1600, 900)
    window.showMaximized()
    code = app.exec()
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
