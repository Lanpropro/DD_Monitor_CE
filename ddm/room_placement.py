"""Room placement and tile swaps; the host owns playback, recording and UI services."""
import sys
from .room_catalog import RoomCatalog
from .room_navigation import RoomNavigation


class RoomPlacement:
    def __init__(self, host):
        self.host = host
        self.navigation = RoomNavigation(self.host)
        self.catalog = RoomCatalog(self.host)
        self.replacement = None

    def place_live_notice_rooms(self, rooms):
        from .wall_replacement import WallReplacement
        if self.replacement is None:
            self.replacement = WallReplacement(self)
        self.replacement.place(rooms)

    def drop_room(self, tile, room_id: str, *, room=None) -> None:
        host = self.host
        try:
            position = host.wall.tiles.index(tile) + 1
        except ValueError:
            return  # A queued drop may outlive a layout change that removed its target.
        room = room if room is not None else host._room_dict(room_id)
        if not room:
            print(f"拖入的直播间 {room_id} 查询失败")
            return
        host.sidebar.watch_history.select(str(room_id))
        host._prepare_room(room)
        other = host._tile_of(room_id)
        if other is tile:
            return
        if other is not None and other is not tile and host._hot_swap(other, tile):
            # 拖进来的这个直播间本来就在别的格子里：两边直接对调画面
            print(f"{room.get('uname')} ↔ 第 {position} 个格子",
                  file=sys.stderr, flush=True)
            return
        to_start = []
        if other is not None and other is not tile:
            # 已经在别的格子里：两边交换，避免同一个直播间出现两次
            room = dict(other.room)  # 包括该房间独立的弹幕开关，侧栏副本不带格子设置。
            previous = dict(tile.room) if tile.room.get("room_id") else None
            host.recorder.stop(other)
            host._stop_tile(other)
            other.set_room(previous)
            if previous and previous.get("room_id"):
                to_start.append(other)
        host.recorder.stop(tile)
        host._stop_tile(tile)
        tile.set_room(room)
        if other is not None:
            host.wall.pane_danmaku.swap_sources(other, tile)
        to_start.append(tile)
        restarted = host.apply_quality_policy()
        for candidate in to_start:
            if candidate not in restarted:
                host.start_tile(candidate)
        host._refresh_meta()
        print(f"{room.get('uname')} → 第 {position} 个格子")

    def swap_tiles(self, source_room_id: str, target_tile) -> None:
        """把来源格子里的直播间和目标格子互换（也包括拖到空格子上）。

        两边都在播的时候走**秒切**：播放器和它绑定的原生窗口都还在，只是换个
        格子挂上去 —— 不重新取流、不重新缓冲，画面直接对调。有一边没有播放器
        （空格子、取流还没回来）或者要换音频输出路径时，退回「停掉再各自起」。
        """
        host = self.host
        source = host._tile_of(source_room_id)
        if source is None or source is target_tile:
            return
        if host._hot_swap(source, target_tile):
            return
        first, second = dict(source.room), dict(target_tile.room)
        host.recorder.stop(source)
        host.recorder.stop(target_tile)
        host._stop_tile(source)
        host._stop_tile(target_tile)
        source.set_room(second if second.get("room_id") else None)
        target_tile.set_room(first if first.get("room_id") else None)
        host.wall.pane_danmaku.swap_sources(source, target_tile)
        restarted = host.apply_quality_policy()
        for tile in (source, target_tile):
            if tile.room.get("room_id") and tile not in restarted:
                host.start_tile(tile)
        host._refresh_meta()
        print("两个格子的直播间已互换")

    def hot_swap(self, source, target) -> bool:
        """两个格子互换：**把两个格子本身换个位置**，播放器一个都不动。

        为什么不搬播放器：实测（work/probe_sethwnd.py、work/repro_canvas_swap2.py）
        正在播的时候 `set_hwnd` 到别的窗口，画面不会乖乖跟过去 —— 旧窗口留着最后一帧、
        新窗口里只铺一小块；改用「关掉视频轨重建」能让画面动，但 播放器 会另外冒一个
        独立的播放窗（用户看到的「悬浮窗」，还会把另一格弄黑）。
        格子换位置就没这些事：画面、控制条、原生窗口一起搬，媒体一直在播，
        连 set_hwnd 都不用碰。
        """
        host = self.host
        source_player = host.players.get(source)
        target_player = host.players.get(target)
        source_live = bool(source.room.get("room_id") and source.room.get("live"))
        target_live = bool(target.room.get("room_id") and target.room.get("live"))
        if not source_live and not target_live:
            return False
        if (source_live and source_player is None) or (target_live and target_player is None):
            return False                       # 取流还没回来，没有画面可换
        tiles = host.wall.tiles
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
        source.video_danmaku_overrides, target.video_danmaku_overrides = \
            target.video_danmaku_overrides, source.video_danmaku_overrides
        for tile in (source, target):
            tile.room["volume"] = tile.volume
            tile.room["muted"] = tile.muted
            tile.room["audio_channel"] = tile.audio_channel
            player = host.players.get(tile)
            if player is None:
                continue
            player.set_volume(int(tile.volume))
            player.set_muted(tile.muted)
            player.set_audio_channel(int(tile.audio_channel))
            player.reapply_audio_channel()
        # Disabling paint alone still lets child HWNDs move with stale pixels
        # while the composer is reparented. Apply each bar's layout only once.
        bars = [(tile.bottom, tile.bottom.updatesEnabled(), tile.bottom.layout().isEnabled())
                for tile in (source, target)]
        for bar, _updates, _layout in bars:
            bar.setUpdatesEnabled(False)
            bar.layout().setEnabled(False)
        try:
            host.wall.relayout(force=True)         # 换完位置重新摆一遍
            for tile in (source, target):
                if host.players.get(tile) is not None:
                    tile.sync_audio_ui()
                tile.raise_overlays()
        finally:
            for bar, updates, layout in bars:
                bar.layout().setEnabled(layout)
                if layout:
                    bar.layout().activate()
                bar.setUpdatesEnabled(updates)
        for tile in (source, target):
            tile.apply_video_danmaku_settings()
            tile._refresh_moved_overlays()
        host._refresh_meta()
        print("两个格子的画面已秒切（格子互换位置，媒体没有中断）",
              file=sys.stderr, flush=True)
        return True

    def room_browser_url(self, room: dict) -> str:
        return self.navigation.room_browser_url(room)

    def open_room_browser(self, url: str) -> None:
        return self.navigation.open_room_browser(url)

    def normalize_room_input(self, text: str) -> str | None:
        return self.navigation.normalize_room_input(text)

    def sync_platform_rooms(self) -> None:
        return self.catalog.sync_platform_rooms()

    def tick_watch_history(self):
        from .watch_history_sampling import tick_watch_history
        return tick_watch_history(self.host)

    def prepare_room(self, room: dict) -> dict:
        """给新建格子补初始声音；已有格子的静音和音量由 Tile 保留。"""
        from . import config as config_module
        from .auto_quality import AUTO_QUALITY, OVERSEAS_PLATFORMS
        host = self.host
        if "muted" not in room:
            room["muted"] = bool(host.settings.get("default_muted", True))
        if "volume" not in room:
            room["volume"] = int(host.settings.get(
                "default_volume", config_module.DEFAULT_VOLUME))
        room.setdefault("quality", AUTO_QUALITY
            if str(room.get("room_id", "")).partition(":")[0] in OVERSEAS_PLATFORMS else 250)
        return room

    def room_dict(self, room_id: str) -> dict | None:
        return self.catalog.room_dict(room_id)

    def clear_tile_room(self, tile: "Tile") -> None:
        host = self.host
        host._pending_capture.pop(tile, None)
        host.recorder.stop(tile)
        host._stop_tile(tile)
        tile.set_room(None)
        if tile not in host.recorder.sessions:
            host._restore_capture_quality(tile)

    def on_close_tile(self, room: dict) -> None:
        """关掉这一路，但留下空格子等新的直播间拖进来。"""
        host = self.host
        tile = host._sender_tile() or host._tile_of(str(room.get("room_id")))
        if tile is None:
            return
        host._clear_tile_room(tile)
        host._refresh_meta()
        print(f"已关闭 {room.get('uname')}，格子已清空")

    def open_add_room(self, *, dialog_type) -> None:
        return self.catalog.open_add_room(dialog_type=dialog_type)

    def add_room_id(self, room_id: str, *, folder_id: str = "", resolver_type) -> None:
        return self.catalog.add_room_id(room_id, folder_id=folder_id, resolver_type=resolver_type)

    def on_platform_room_failed(self, resolver, platform, room_id, *, folder_id=""):
        return self.catalog.on_platform_room_failed(resolver, platform, room_id, folder_id=folder_id)

    def on_room_added(self, room: dict, *, folder_id: str = "", max_tiles) -> None:
        return self.catalog.on_room_added(room, folder_id=folder_id, max_tiles=max_tiles)

    def add_to_wall(self, room: dict, *, empty_only=False, max_tiles) -> None:
        from . import plugins as plugin_api
        host = self.host
        MAX_TILES = max_tiles
        host._prepare_room(room)
        room_id = str(room.get("room_id"))
        host.sidebar.watch_history.select(room_id)
        if host._tile_of(room_id) is not None:
            print(f"{room.get('uname')} 已经在画面墙上")
            return
        candidates = host.wall.visible_tiles() if empty_only else host.wall.tiles
        panes = host.wall.pane_danmaku
        chat_cells = panes.bindings()
        chat_tiles = {tile for cell, tile in panes.cell_tiles().items() if cell in chat_cells}
        empty = next((tile for tile in candidates
                      if tile not in chat_tiles and not tile.room.get("room_id")), None)
        if empty is not None:                      # 优先填空位
            host.recorder.stop(empty)
            host._stop_tile(empty)
            empty.set_room(room)
            host._wire_tile(empty)
            host.start_tile(empty)
            host.plugins.emit(plugin_api.EVENT_TILE_ADDED, tile=empty,
                              room=dict(empty.room or {}))
            host._refresh_meta()
            return
        if empty_only:
            return
        if len(host.wall.tiles) >= MAX_TILES:
            print(f"画面墙已满（{MAX_TILES} 路）")
            return
        tile = host.wall.add_room(room)
        host._wire_tile(tile)
        host.start_tile(tile)
        host.plugins.emit(plugin_api.EVENT_TILE_ADDED, tile=tile,
                          room=dict(tile.room or {}))
        host._refresh_meta()

    def remove_room(self, room: dict) -> None:
        return self.catalog.remove_room(room)

    def remove_rooms(self, rooms: list) -> None:
        return self.catalog.remove_rooms(rooms)
