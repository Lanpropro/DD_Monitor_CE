"""Room placement and tile swaps; the host owns playback, recording and UI services."""
import sys


class RoomPlacement:
    def __init__(self, host):
        self.host = host

    def drop_room(self, tile, room_id: str) -> None:
        host = self.host
        room = host._room_dict(room_id)
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
            print(f"{room.get('uname')} ↔ 第 {host.wall.tiles.index(tile) + 1} 个格子",
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
        to_start.append(tile)
        restarted = host.apply_quality_policy()
        for candidate in to_start:
            if candidate not in restarted:
                host.start_tile(candidate)
        host._refresh_meta()
        print(f"{room.get('uname')} → 第 {host.wall.tiles.index(tile) + 1} 个格子")

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
            tile.sync_audio_ui()            # 值换位了，音量条控件要跟着重画
            tile.raise_overlays()
        host.wall.relayout(force=True)         # 换完位置重新摆一遍
        for tile in (source, target):
            tile.raise_overlays()
        host._refresh_meta()
        print("两个格子的画面已秒切（格子互换位置，媒体没有中断）",
              file=sys.stderr, flush=True)
        return True

