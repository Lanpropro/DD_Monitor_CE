"""Room placement and tile swaps; the host owns playback, recording and UI services."""
import sys
import time
import webbrowser
from urllib.parse import urlsplit


class RoomPlacement:
    def __init__(self, host):
        self.host = host
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
        host = self.host
        room_id = str(room.get("room_id") or "")
        if room_id.isascii() and room_id.isdecimal():
            return f"https://live.bilibili.com/{room_id}"
        kind, separator, raw_id = room_id.partition(":")
        platform = host.plugins.platforms.get(kind) if separator and raw_id else None
        if platform is None:
            return ""
        try:
            url = platform.room_url(room_id)
            parts = urlsplit(url)
            return url if parts.scheme in ("http", "https") and parts.netloc else ""
        except Exception:  # noqa: BLE001
            return ""

    def open_room_browser(self, url: str) -> None:
        from PySide6.QtWidgets import QMessageBox
        host = self.host
        try:
            opened = webbrowser.open(url)
        except OSError:
            opened = False
        if not opened:
            QMessageBox.warning(host, "观看直播", "无法打开默认浏览器，请检查系统浏览器设置。")

    def normalize_room_input(self, text: str) -> str | None:
        from PySide6.QtWidgets import QDialog
        host = self.host
        from .room_input import bili_room_id, extract_room_input, is_bili_short_url
        text = extract_room_input(text)
        platform = host.plugins.platform_for(text)
        if platform is not None:
            profile = getattr(platform, "profile_sec_uid", None)
            sec_uid = profile(text) if callable(profile) else ""
            if sec_uid:
                from .profile_room import ProfileRoomDialog
                dialog = ProfileRoomDialog(platform, sec_uid, host)
                result = dialog.exec()
                room_id = dialog.room_id
                dialog.deleteLater()
                if result != QDialog.Accepted:
                    raise ValueError("主页读取已取消，可重新粘贴主页链接重试")
                return room_id
            return platform.normalize(text)
        if room_id := bili_room_id(text):
            return room_id
        if is_bili_short_url(text):
            return text  # Expand the short link in InfoResolver's background thread.
        # 未装载的平台输入不能被旧的数字提取误当作 B 站房间。
        if ":" in text and urlsplit(text).hostname != "live.bilibili.com":
            raise ValueError("未识别平台，请启用对应的平台插件并重启")
        return None                    # B 站仍使用原有房间号解析

    def sync_platform_rooms(self) -> None:
        from . import config as config_module
        host = self.host
        host.hover_preview.cancel()
        active = {kind for kind, owner in host.plugins._platform_owner.items()
                  if owner not in host.plugins._removed and
                  (host.plugins.enabled is None or owner in host.plugins.enabled)}
        saved = config_module.sync_platform_rooms(host.current_state(), active)
        host.state["suspended_platform_rooms"] = saved["suspended_platform_rooms"]
        rooms, wall = config_module.build_rooms(saved)
        followed = {room["room_id"] for room in rooms}
        for room in host.sidebar.rooms():
            if room["room_id"] not in followed:
                host.sidebar.remove_room(room)
        for room in rooms:
            if not any(item["room_id"] == room["room_id"] for item in host.sidebar.rooms()):
                host.sidebar.add_room(room)
        for key in ("import_order", "custom_order"):
            getattr(host.sidebar, "set_" + key)(saved[key])
        host.sidebar.apply_pins(saved["pinned"])
        host.sidebar.set_folders(saved.get("follow_folders") or [])
        for index, room in enumerate(wall):
            if index >= len(host.wall.tiles):
                host.wall.add_room(room)
                continue
            tile = host.wall.tiles[index]
            if str(tile.room.get("room_id") or "") == str(room.get("room_id") or ""):
                continue
            if tile is host._fullscreen_tile:
                host._exit_fullscreen()
            host.recorder.stop(tile)
            host._pending_capture.pop(tile, None)
            host._stop_tile(tile)
            tile.set_volume(room["volume"])
            tile.set_audio_channel(room["audio_channel"])
            tile.set_muted(room["muted"])
            tile.set_room(room)
        host._refresh_meta()

    def tick_watch_history(self):
        host = self.host
        now = time.monotonic()
        elapsed = now - host._watch_history_last_tick
        host._watch_history_last_tick = now
        history = host.sidebar.watch_history
        if host._closing or not history.enabled:
            return
        present = {str(tile.room.get("room_id")) for tile in host.wall.tiles
                   if tile.room.get("room_id")}
        active = set()
        if host.isVisible() and not host.isMinimized():
            for tile in host.wall.visible_tiles():
                player = host.players.get(tile)
                if (tile.isVisible() and not tile.paused and player is not None
                        and player.state == "playing" and not player.paused):
                    active.add(str(tile.room.get("room_id")))
        if history.sample(present, active, elapsed):
            host._save_timer.start()

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
        from . import bili
        host = self.host
        room_id = str(room_id)
        for room in host.sidebar.rooms():
            if str(room.get("room_id")) == room_id:
                return room
        return bili.room_info(room_id) if room_id.isdigit() else None

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
        host = self.host
        AddRoomDialog = dialog_type
        dialog = AddRoomDialog(host, room_id_resolver=host._normalize_room_input,
                               folders=host.sidebar.folder_state(),
                               folder_creator=host.sidebar.create_folder)
        hints = [hint for p in host.plugins.platforms.values()
                 if (hint := getattr(p, "room_input_hint", ""))]
        if hints:
            dialog.hint.setText("支持 B 站房间号；" + "；".join(hints))
        if dialog.exec() != AddRoomDialog.Accepted:
            return
        host._add_room_id(dialog.room_id, folder_id=dialog.folder_id)

    def add_room_id(self, room_id: str, *, folder_id: str = "", resolver_type) -> None:
        from PySide6.QtWidgets import QMessageBox
        host = self.host
        InfoResolver = resolver_type
        from .room_input import is_bili_short_url
        short_link = is_bili_short_url(room_id)
        if any(str(room.get("room_id")) == room_id for room in host.sidebar.rooms()):
            print(f"房间 {room_id} 已在关注列表里")
            return
        platform = host.plugins.platform_for(room_id)
        if ":" in room_id and not short_link:
            if platform is None:
                QMessageBox.warning(host, "添加直播间", "请启用对应的平台插件并重启")
                return
            resolver = InfoResolver(room_id, host, platform=platform)
            resolver.resolved.connect(lambda room: host._on_room_added(room, folder_id=folder_id)
                                      if not host._closing else None)
            resolver.failed.connect(lambda _rid, r=resolver: host._on_platform_room_failed(
                r, platform, room_id, folder_id=folder_id))
            resolver.finished.connect(lambda r=resolver: host._platform_info_running.discard(r))
            resolver.finished.connect(resolver.deleteLater)
            host._platform_info_running.add(resolver)
            resolver.start()
            return
        print(f"正在查询房间 {room_id} ...")
        resolver = InfoResolver(room_id, host)
        resolver.resolved.connect(lambda room: host._on_room_added(room, folder_id=folder_id))
        if short_link:
            resolver.failed.connect(lambda _rid: QMessageBox.warning(
                host, "添加直播间", "分享链接解析失败，请确认是直播间链接并检查网络后重试")
                if not host._closing else None)
        else:
            resolver.failed.connect(lambda rid: print(f"房间 {rid} 查询失败"))
        resolver.finished.connect(lambda r=resolver: host._platform_info_running.discard(r))
        resolver.finished.connect(resolver.deleteLater)
        host._platform_info_running.add(resolver)
        resolver.start()

    def on_platform_room_failed(self, resolver, platform, room_id, *, folder_id=""):
        from PySide6.QtWidgets import QDialog, QMessageBox
        host = self.host
        if host._closing:
            return
        if (getattr(resolver, "browser_verification", False) is True
                and platform.kind == "douyin" and getattr(platform, "room_browser_init_script", "")):
            from .profile_room import ProfileRoomDialog
            dialog = ProfileRoomDialog(platform, "", host, room_id=room_id)
            result = dialog.exec()
            canonical = dialog.room_id
            dialog.deleteLater()
            if result == QDialog.Accepted and canonical and not host._closing:
                host._add_room_id(canonical, folder_id=folder_id)
            return
        QMessageBox.warning(host, "添加直播间", "平台房间获取失败\n\n" + (
            getattr(resolver, "error_message", "") or "请检查房间链接或稍后重试"))

    def on_room_added(self, room: dict, *, folder_id: str = "", max_tiles) -> None:
        host = self.host
        MAX_TILES = max_tiles
        if host._closing:
            return
        if host.sidebar.add_room(room):
            if folder_id:
                host.sidebar.move_to_folder([str(room.get("room_id"))], folder_id)
            host.load_avatars_for([room])       # 新加的房间立刻显示头像
            from .online_ui import show_result
            show_result(host, "已添加 " + str(room.get("uname") or room.get("room_id")), rooms=[room])
        status = "直播中" if room.get("live") else "未开播"
        print(f"已添加 {room.get('uname')}（{status}）")
        if len(host.wall.tiles) < MAX_TILES:
            host.add_to_wall(room)
        host._refresh_meta()
        host._save_timer.start()

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
        empty = next((tile for tile in candidates if not tile.room.get("room_id")), None)
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
        from . import plugins as plugin_api
        host = self.host
        if host.hover_preview._room_id() == str(room.get("room_id")):
            host.hover_preview.cancel()
        tile = host._tile_of(str(room.get("room_id")))
        if tile is not None:
            host.plugins.emit(plugin_api.EVENT_TILE_REMOVED, tile=tile,
                              room=dict(tile.room or {}))
            host._pending_capture.pop(tile, None)
            host.recorder.stop(tile)
            host._stop_tile(tile)
            host.wall.remove_room(tile.room)
            if tile not in host.recorder.sessions:
                host._restore_capture_quality(tile)
        host.sidebar.remove_room(room)
        host._refresh_meta()
        print(f"已移除 {room.get('uname')}")

    def remove_rooms(self, rooms: list) -> None:
        host = self.host
        for room in rooms:
            host.remove_room(room)
        print(f"多选删除完成，共 {len(rooms)} 个")
