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
    QApplication, QHBoxLayout, QLabel, QMainWindow, QVBoxLayout, QWidget,
)

from . import bili
from . import config as config_module
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
from .widgets import Sidebar, Tile, WallGrid

MAX_TILES = 16
POLL_INTERVAL_MS = 60_000        # 关注列表状态轮询：1 分钟
RETRY_BASE_SECONDS = 5           # 断流后的重连间隔（指数退避）
RETRY_MAX_SECONDS = 60
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
        self._previous_layout: str | None = None
        self._danmaku: DanmakuClient | None = None      # 弹幕格当前连的那一路
        self._danmaku_room = ""
        self.shortcuts = dict(DEFAULT_SHORTCUTS)
        self.settings = dict(config_module.DEFAULT_SETTINGS)
        self.settings.update(self.state.get("settings") or {})

        root = QWidget()
        root.setObjectName("Root")
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.sidebar = Sidebar(rooms)
        layout.addWidget(self.sidebar)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(0)
        self.wall = WallGrid(wall_rooms if wall_rooms is not None else rooms, layout_id)
        self.empty_hint = QLabel(EMPTY_HINT)
        self.empty_hint.setObjectName("EmptyHint")
        self.empty_hint.setAlignment(Qt.AlignCenter)
        right_layout.addWidget(self.wall, 1)
        right_layout.addWidget(self.empty_hint, 1)
        layout.addWidget(right, 1)
        self.setCentralWidget(root)

        # 信号接线
        self.sidebar.roomSelected.connect(self.wall.tileClicked.emit)
        self.sidebar.addRoomClicked.connect(self.open_add_room)
        self.sidebar.importFollowsClicked.connect(self.open_import_follows)
        self.sidebar.addToWallRequested.connect(self.add_to_wall)
        self.sidebar.removeRequested.connect(self.remove_room)
        self.sidebar.deleteRequested.connect(self.remove_rooms)
        self.sidebar.logoutRequested.connect(self.logout)
        self.sidebar.pinChanged.connect(self._on_pin_changed)
        self.sidebar.refreshRequested.connect(self.refresh_follow)
        self.sidebar.settingsRequested.connect(self.open_settings)
        self.sidebar.layoutChosen.connect(self._on_layout_changed)
        self.sidebar.set_layout_name(self.wall.layout_id)
        self.wall.tileClicked.connect(self._on_tile_clicked)
        self.wall.roomDropped.connect(self._on_room_dropped)
        self.wall.tileSwapped.connect(self._on_tile_swapped)
        for tile in self.wall.tiles:
            self._wire_tile(tile)

        bili.set_sessdata(self.state.get("sessdata", ""))
        self._restore_ui()
        self._refresh_meta()

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
        self.sidebar.apply_pins(self.state.get("pinned") or [])
        self.shortcuts = dict(DEFAULT_SHORTCUTS)
        self.shortcuts.update((self.state.get("ui") or {}).get("shortcuts") or {})

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
                    "volume": int(tile.room.get("volume", config_module.DEFAULT_VOLUME)),
                    "quality": int(tile.quality),
                    "audio_channel": int(tile.audio_channel),
                }
                for tile in self.wall.tiles
            ],
            "ui": {
                "sidebar_collapsed": self.sidebar.collapsed,
                "layout": self.wall.layout_id,
                "shortcuts": dict(self.shortcuts),
            },
            "pinned": list(self.sidebar.pinned),
            "settings": dict(self.settings),
            "geometry": str(self.saveGeometry().toBase64(), "ASCII"),
        }

    def closeEvent(self, event) -> None:
        config_module.save(self.current_state())
        self.stop_danmaku()
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
        self.wall.set_layout(layout_id)
        self.sidebar.set_layout_name(self.wall.layout_id)
        self.state.setdefault("ui", {})["layout"] = layout_id
        self.apply_quality_policy()
        self._refresh_meta()

    def _on_pin_changed(self, pinned: list) -> None:
        self.state["pinned"] = list(pinned)
        config_module.save(self.current_state())

    # ---- 播放 ----
    def start_all(self) -> None:
        self.apply_quality_policy()
        for tile in self.wall.tiles:
            self.start_tile(tile)

    def apply_quality_policy(self) -> None:
        """有主次布局时：主画面自动用原画，其余用 720P。"""
        if not self.settings.get("auto_quality", True):
            return
        main = self.wall.main_index()
        if main is None:
            return
        for index, tile in enumerate(self.wall.tiles):
            if not tile.room.get("room_id"):
                continue
            target = 10000 if index == main else 250
            if tile.quality != target:
                print(f"[画质策略] {tile.room.get('uname')} -> "
                      f"{'原画' if target == 10000 else '720P'}", file=sys.stderr, flush=True)
                tile.set_quality(target)

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
            self._play_on(t, url, qn, profile, options))
        resolver.failed.connect(lambda rid, reason, t=tile: self._on_resolve_failed(t, reason))
        resolver.finished.connect(lambda t=tile: self._resolvers.pop(t, None))
        self._resolvers[tile] = resolver
        resolver.start()
        self.refresh_stats()          # 人数不用等下一轮轮询，立刻拉一次

    def _play_on(self, tile, url: str, quality: int = 0, profile: str = "web",
                 options: list | None = None) -> None:
        if options:
            tile.set_quality_options(options)
        if quality:
            tile.set_actual_quality(quality)
        player = self.players.get(tile)
        if player is None:
            player = TilePlayer(tile.video, self)
            player.stateChanged.connect(lambda state, t=tile: self._on_player_state(t, state))
            self.players[tile] = player
        player.freeze_watch = bool(self.settings.get("freeze_watch", True))
        player.set_volume(int(tile.volume))
        player.set_audio_channel(int(tile.audio_channel))
        player.set_muted(tile.muted)
        player.play(url, profile)

    def _on_resolve_failed(self, tile, reason: str) -> None:
        tile.set_status("连接失败")
        print(f"[取流失败] {tile.room.get('uname')}: {reason}")

    def _on_player_state(self, tile, state: str) -> None:
        if not tile.room.get("room_id"):
            return
        if state == "playing":
            tile.set_video_active(True)
            tile.set_buffering(False)
            tile.set_status("")
            tile.start_elapsed_timer()
            self._retry_count.pop(tile, None)
        elif state == "connecting":
            tile.set_video_active(False)
            tile.set_status("连接中…")
        elif state == "buffering":
            tile.set_buffering(True)         # 卡顿时也显示缓冲动画
        elif state == "frozen":
            # 时钟还在走但画面完全没变化：只提示，不重连（静止画面可能误报）
            tile.set_status("画面已停止更新…")
        elif state == "error":
            tile.set_video_active(False)
            tile.stop_elapsed_timer()
            self._schedule_retry(tile)
        else:
            tile.set_video_active(False)
            tile.stop_elapsed_timer()
        tile.raise_overlays()

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
        player = self.players.pop(tile, None)
        if player is not None:
            player.release()
        resolver = self._resolvers.pop(tile, None)
        if resolver is not None and resolver.isRunning():
            resolver.terminate()

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
        other = self._tile_of(room_id)
        if other is not None and other is not tile:
            # 已经在别的格子里：两边交换，避免同一个直播间出现两次
            previous = dict(tile.room) if tile.room.get("room_id") else None
            self._stop_tile(other)
            other.set_room(previous)
            if previous and previous.get("room_id"):
                self.start_tile(other)
        self._stop_tile(tile)
        tile.set_room(room)
        self.start_tile(tile)
        self._refresh_meta()
        print(f"{room.get('uname')} → 第 {self.wall.tiles.index(tile) + 1} 个格子")
        self.apply_quality_policy()

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
        for tile in (source, target_tile):
            if tile.room.get("room_id"):
                self.start_tile(tile)
        self._refresh_meta()
        self.apply_quality_policy()
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
        faces: dict[str, str] = {}
        for tile in self.wall.tiles:
            info = status.get(str(tile.room.get("room_id") or ""))
            if not info:
                continue
            was_live = bool(tile.room.get("live"))
            tile.set_live(info["live"], info["viewers"])
            if was_live and not info["live"]:
                self._offline_tile(tile)          # 刚下播：黑屏但保留这一格
            elif not was_live and info["live"]:
                print(f"[开播] {tile.room.get('uname')} 自动开始播放",
                      file=sys.stderr, flush=True)
                self.start_tile(tile)             # 重新开播：自动接上
                self.refresh_stats()              # 刚开播：马上补一次在线人数
        for item in self.sidebar._items:            # noqa: SLF001
            info = status.get(str(item.room.get("room_id")))
            if not info:
                continue
            if info["title"]:
                item.room["title"] = info["title"]
            item.set_live(info["live"])
            face = info.get("face")
            if face and face != item.room.get("face"):
                item.room["face"] = face
                faces[str(item.room.get("room_id"))] = face
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

    def _on_audio_changed(self, room: dict, value: int) -> None:
        tile = self._tile_of(str(room.get("room_id")))
        player = self.players.get(tile) if tile is not None else None
        if player is not None:
            player.set_audio_channel(value)

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

    def _on_reload(self, room: dict) -> None:
        tile = self._tile_of(str(room.get("room_id")))
        if tile is not None:
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
            self._refresh_meta()
            self.refresh_stats()               # 新加的一路马上拉在线人数，不用等下一轮
            return
        if len(self.wall.tiles) >= MAX_TILES:
            print(f"画面墙已满（{MAX_TILES} 路）")
            return
        tile = self.wall.add_room(room)
        self._wire_tile(tile)
        self.start_tile(tile)
        self._refresh_meta()
        self.refresh_stats()

    def remove_room(self, room: dict) -> None:
        tile = self._tile_of(str(room.get("room_id")))
        if tile is not None:
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
        """把关注列表里的主播头像换成真实头像。"""
        items = {str(room.get("room_id")): room.get("face")
                 for room in self.sidebar.rooms() if room.get("face")}
        loader = self._start_avatar_loader(items, self._on_room_avatar)
        self._room_avatar_loader = loader

    def load_avatars_for(self, rooms: list) -> None:
        """刚加进来的房间立刻取头像，不用等下一轮状态刷新。"""
        items = {str(room.get("room_id")): room.get("face")
                 for room in rooms if room.get("face")}
        self._start_avatar_loader(items, self._on_room_avatar)

    def _start_avatar_loader(self, items: dict, slot):
        """统一的头像下载：线程都留个引用，关窗时好等它们收尾。"""
        if not items:
            return None
        loader = AvatarLoader(items, self)
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
                item.avatar.set_pixmap_image(pixmap)
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
        client = DanmakuClient(room_id, self)
        client.message.connect(self._on_danmaku_message)
        client.status.connect(self._on_danmaku_status)
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

    def _on_danmaku_message(self, kind: str, uname: str, text: str) -> None:
        self.wall.danmaku.add_event(kind, uname, text)

    def _on_danmaku_status(self, text: str) -> None:
        self.wall.danmaku.set_status(text)

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
