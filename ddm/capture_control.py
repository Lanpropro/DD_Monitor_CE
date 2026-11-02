"""Recording/replay policy and tile state; the host owns sessions and shutdown."""
import time


class CaptureControl:
    def __init__(self, host):
        self.host = host

    def replay_scope(self) -> str:
        """即时回放的适用范围：``recorded``（只跟录制走）或 ``all``（所有格子）。"""
        host = self.host
        scope = str(host.settings.get("recording_replay_scope", "recorded") or "")
        return scope if scope in ("recorded", "all") else "recorded"

    def recording_enabled(self) -> bool:
        """录制功能总开关。关掉时不起新录制，已经在录的正常收尾。"""
        host = self.host
        return bool(host.settings.get("recording_enabled", True))

    def sync_recording_switch(self) -> None:
        """按录制总开关收起「● 录制」按钮，并停掉正在录制的会话。

        停的是**正常收尾**（走 recorder.stop()，已录到的分段照样导出成文件），
        不是丢弃 —— 关开关的意图是「不想再录了」，不是「把刚才录的删掉」。
        """
        host = self.host
        enabled = host._recording_enabled()
        if not enabled:
            host._pending_capture.clear()       # 还在等原画的那几格也别等了
        for tile in host.wall.tiles:
            setter = getattr(tile, "set_recording_available", None)
            if setter is not None:
                setter(enabled)
            if enabled:
                continue
            session = host.recorder.sessions.get(tile)
            if session is not None and session.recording:
                host.recorder.stop(tile)

    def replay_enabled(self) -> bool:
        """即时回放总开关；关掉时既不开缓存，也不提供「保存最近 N 分钟」。"""
        host = self.host
        return bool(host.settings.get("recording_replay_enabled", True))

    def replay_max_tiles(self) -> int:
        """``all`` 时最多给几格开缓存；<= 0 表示不限制。"""
        host = self.host
        try:
            return int(host.settings.get("recording_replay_max_tiles", 3))
        except (TypeError, ValueError):
            return 3

    def drop_pure_caches(self, *, preserve_manual: bool = False) -> None:
        """停掉所有「纯缓存」会话；录制中的留着 —— 它本来就在写分段。"""
        host = self.host
        for tile in host.wall.tiles:
            session = host.recorder.sessions.get(tile)
            if (session is not None and not session.recording and
                    not (preserve_manual and getattr(session, "manual_replay", False))):
                host.recorder.stop(tile)

    def sync_replay_scope(self) -> None:
        """按「即时回放总开关 + 范围」自动开 / 关各格的缓存。

        ``recorded``：手动开启，录制时自动提供回放。保留手动缓存，停止自动缓存。
        ``all``：所有播放中的格子都开一份缓存，随时都能「保存最近 N 分钟」，
        但**最多开 ``recording_replay_max_tiles`` 格** —— 每开一格都是再拉一路
        同样的流（带宽翻倍）加一个 ffmpeg 进程（约 155 MB 内存）。用户实测过
        8 格全开：16 路同时下载、1.2 GB 常驻内存，打网游时延迟直接抖起来。

        注意这里**直接调 recorder.start()**、不走 ``_start_capture()`` —— 后者会为了
        录制把画质锁到原画，而「所有格子都锁原画」会把带宽吃光。
        """
        host = self.host
        if not host._replay_enabled():
            # 总开关关闭时，所有纯缓存都停止；完整录制继续。
            host._drop_pure_caches()
            return
        if host._replay_scope() != "all":
            host._drop_pure_caches(preserve_manual=True)
            return
        if not bool(str(host.settings.get("recording_dir") or "").strip()):
            return                                  # 没配保存目录，缓存没地方写
        limit = host._replay_max_tiles()
        # 额度按「已经在缓存的格子」现数（用户手动录制的那些不占额度）。
        # 每轮重数一遍，所以某个格子的缓存停掉之后，额度会自动让给后面的格子。
        cached = sum(1 for session in host.recorder.sessions.values()
                     if not session.recording)
        for tile in host.wall.tiles:
            if tile in host.recorder.sessions:
                continue                            # 已经有会话（录制或缓存）
            if host._replay_suppressed.get(tile) == str(tile.room.get("room_id") or ""):
                continue
            if limit > 0 and cached >= limit:
                break                               # 额度用完，剩下的格子先不缓存
            if not tile.isVisible() or not tile.room.get("live"):
                continue
            if not tile.room.get("room_id") or not tile.stream_url:
                continue                            # 还没取到流，等下一轮
            if host.recorder.start(tile, recording=False):
                cached += 1

    def start_replay(self, tile) -> None:
        host = self.host
        if not host._replay_enabled():
            return
        if not str(host.settings.get("recording_dir") or "").strip():
            if not host.open_settings("recording") or host._closing or not host._replay_enabled():
                return
        host._replay_suppressed.pop(tile, None)
        if host.recorder.start(tile, recording=False):
            host.recorder.sessions[tile].manual_replay = True

    def stop_replay(self, tile) -> None:
        host = self.host
        session = host.recorder.sessions.get(tile)
        if session is not None and not session.recording:
            host._replay_suppressed[tile] = str(tile.room.get("room_id") or "")
            host.recorder.stop(tile)

    def toggle_recording(self, tile) -> None:
        host = self.host
        if tile in host._pending_capture:
            host._pending_capture.pop(tile)
            host._restore_capture_quality(tile)
            return
        session = host.recorder.sessions.get(tile)
        if session and session.recording:
            host.recorder.stop(tile)
        else:
            host._start_capture(tile, recording=True)

    def start_capture(self, tile, *, recording: bool) -> None:
        host = self.host
        if recording and not host._recording_enabled():
            host._record_notice("录制功能已在「设置 → 录制」里关闭", tile.room)
            return
        if tile in host._pending_capture:
            return
        if not str(host.settings.get("recording_dir") or "").strip():
            if not host.open_settings("recording"):
                return
            if not str(host.settings.get("recording_dir") or "").strip():
                host._record_notice("请先选择录制保存目录", tile.room)
                return
        if not host.settings.get("recording_lock_quality", True):
            host.recorder.start(tile, recording=recording)
            return
        if tile in host.recorder.sessions:
            host.recorder.start(tile, recording=recording)
            return
        if not tile.room.get("live") or not tile.isVisible():
            host.recorder.start(tile, recording=recording)
            return
        host._capture_quality[tile] = (str(tile.room.get("room_id") or ""), int(tile.quality))
        host._pending_capture[tile] = recording
        tile.quality_button.setEnabled(False)
        tile.quality_locked = True
        if tile.quality == 10000 and tile.actual_quality == 10000 and tile.stream_url:
            host._finish_pending_capture(tile)
            return
        if tile.quality != 10000:
            blocked = tile.blockSignals(True)
            try:
                tile.set_quality(10000)
            finally:
                tile.blockSignals(blocked)
            tile.room["quality"] = 10000
        host.start_tile(tile)

    def finish_pending_capture(self, tile) -> None:
        host = self.host
        recording = host._pending_capture.pop(tile)
        if tile.actual_quality != 10000:
            host._record_notice("直播源未提供原画，录制未开始", tile.room)
            host._restore_capture_quality(tile)
        elif not host.recorder.start(tile, recording=recording):
            host._restore_capture_quality(tile)

    def restore_capture_quality(self, tile) -> None:
        host = self.host
        previous = host._capture_quality.pop(tile, None)
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
            if tile.room.get("live") and tile.isVisible() and not host._closing:
                host.start_tile(tile)

    def record_state_changed(self, tile) -> None:
        host = self.host
        session = host.recorder.sessions.get(tile)
        if tile in host._preset_retired_tiles and session is None:
            host._preset_retired_tiles.remove(tile)
            host._capture_quality.pop(tile, None)
            host.wall._drop_tile(tile)
            return
        if session is None and tile not in host._pending_capture:
            host._restore_capture_quality(tile)
        recording = bool(session and session.recording and not session.stopping)
        state = "record" if recording else (
            "cache" if session and not session.stopping else "")
        tile.set_recording_state(state)
        if recording:
            # 记下开录时刻，交给 _tick_record_clock() 每秒刷「● REC 00:12:34」
            host._recording_since[tile] = float(
                getattr(session, "started_at", 0.0) or time.monotonic())
        else:
            host._recording_since.pop(tile, None)
            tile.set_recording_elapsed("")
        host._tick_record_clock()

    def tick_record_clock(self) -> None:
        """刷新每格的录制时长（REC 旁边那个）。"""
        host = self.host
        now = time.monotonic()
        for tile in host.wall.tiles:
            started = host._recording_since.get(tile)
            if started is None:
                continue
            seconds = max(0, int(now - started))
            hours, rest = divmod(seconds, 3600)
            minutes, secs = divmod(rest, 60)
            tile.set_recording_elapsed(
                f"{hours:d}:{minutes:02d}:{secs:02d}" if hours
                else f"{minutes:02d}:{secs:02d}")
