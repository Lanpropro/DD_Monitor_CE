"""Recording/replay policy and tile state; the host owns sessions and shutdown."""
import time
from . import bili
from .recording_session import BackgroundRecordingSource
from .streamer_defaults import QUALITY_LABELS, quality_tiers, source_quality_option


class CaptureControl:
    def __init__(self, host):
        self.host = host
        self.waiting_for_cache = set()

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
        auto_recording = getattr(host, 'auto_recording', None)
        if auto_recording is not None:
            auto_recording.settings_changed()
            host.sidebar.items_control.set_auto_record_rooms(auto_recording.configured_rooms())
        if not enabled:
            pending = list(host._pending_capture)
            host._pending_capture.clear()
            for tile in pending:
                host._restore_capture_quality(tile)
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
        return bool(host.settings.get("recording_replay_enabled", True)) and host.recorder.supports_replay

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
            if tile in host.recorder.sessions or tile in host._pending_capture:
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
        if not host.recorder.directory_setting:
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
            host.recorder.stop(tile, save_cache=True)

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
        auto_recording = getattr(host, 'auto_recording', None)
        if recording and auto_recording and auto_recording.source_for(str(tile.room.get('room_id'))):
            host._record_notice("该主播正在后台录制，可在录制中心停止", tile.room)
            return
        if recording and not host._recording_enabled():
            host._record_notice("录制功能已在「设置 → 录制」里关闭", tile.room)
            return
        if tile in host._pending_capture:
            return
        if not str(host.settings.get("recording_dir") or "").strip():
            if not host.open_settings("recording"):
                return
            if not host.recorder.directory_setting:
                host._record_notice("请先选择录制保存目录", tile.room)
                return
        height = tile.room.get('_streamer_recording_height') if recording else None
        choice = tile.room.get('_streamer_recording_choice') if recording else None
        custom_quality = height is not None or choice is not None
        if not custom_quality and not host.settings.get("recording_lock_quality", True):
            host.recorder.start(tile, recording=recording)
            return
        session = host.recorder.sessions.get(tile)
        if session is not None and (not custom_quality or session.recording or session.stopping):
            host.recorder.start(tile, recording=recording)
            return
        if not tile.room.get("live") or not tile.isVisible():
            host.recorder.start(tile, recording=recording)
            return
        room_id = str(tile.room.get("room_id") or "")
        target = 10000
        if choice is not None:
            target = choice['qn']
            if target == 10000 and choice['label'] in ('最高', '最高可用'):
                tiers = quality_tiers(room_id, tile.quality_options, 0, allow_lower=False)
                target = tiers[0] if tiers else target
        elif height is not None:
            tiers = quality_tiers(room_id, tile.quality_options, height, allow_lower=False)
            if not tiers:
                host._record_notice(f"直播源未提供 {QUALITY_LABELS[height]}，录制未开始", tile.room)
                return
            target = tiers[0]
        host._capture_quality[tile] = (room_id, int(tile.quality))
        host._pending_capture[tile] = recording
        tile.quality_button.setEnabled(False)
        already_resolved = tile.actual_quality == target and bool(tile.stream_url)
        if tile.quality != target:
            blocked = tile.blockSignals(True)
            try:
                tile.set_quality(target)
                if already_resolved:
                    tile.set_actual_quality(target)
            finally:
                tile.blockSignals(blocked)
            tile.room["quality"] = target
        tile.quality_locked = True
        if session is not None and not (already_resolved and session.url == tile.stream_url):
            # A replay cache may still be writing the previous source.
            self.waiting_for_cache.add(tile)
            host.recorder.stop(tile)
        elif already_resolved:
            host._finish_pending_capture(tile)
        else:
            host.start_tile(tile)

    def finish_pending_capture(self, tile) -> None:
        host = self.host
        if tile in self.waiting_for_cache:
            return
        recording = host._pending_capture.pop(tile)
        if tile.actual_quality != tile.quality:
            height = tile.room.get('_streamer_recording_height') if recording else None
            choice = tile.room.get('_streamer_recording_choice') if recording else None
            label = f" {choice['label']}" if choice else (
                f" {QUALITY_LABELS[height]}" if height is not None else "原画")
            host._record_notice(f"直播源未提供{label}，录制未开始", tile.room)
            host._restore_capture_quality(tile)
        elif not host.recorder.start(tile, recording=recording):
            host._restore_capture_quality(tile)

    def restore_capture_quality(self, tile) -> None:
        host = self.host
        self.waiting_for_cache.discard(tile)
        previous = host._capture_quality.pop(tile, None)
        if previous is None:
            return
        tile.quality_locked = False
        tile.quality_button.setEnabled(source_quality_option(tile.quality_options) is None)
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
        if isinstance(tile, BackgroundRecordingSource):
            return
        host = self.host
        session = host.recorder.sessions.get(tile)
        if tile in host._preset_retired_tiles and session is None:
            host._preset_retired_tiles.remove(tile)
            host._capture_quality.pop(tile, None)
            self.waiting_for_cache.discard(tile)
            host.wall._drop_tile(tile)
            return
        if session is None and tile in self.waiting_for_cache:
            self.waiting_for_cache.remove(tile)
            saved = host._capture_quality.get(tile)
            if (not host._closing and tile in host._pending_capture and saved
                    and str(tile.room.get('room_id') or '') == saved[0]):
                if tile.actual_quality == tile.quality and tile.stream_url:
                    host._finish_pending_capture(tile)
                else:
                    host.start_tile(tile)
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

    def refresh_recording_source(self, session, *, resolver_type) -> None:
        host = self.host
        StreamResolver = resolver_type
        tile = session.tile
        if isinstance(tile, BackgroundRecordingSource):
            host.auto_recording.resolve_source(session)
            return
        platform = host.plugins.platform_for(session.room_id)
        if host._closing or tile not in host.wall.tiles or (':' in session.room_id and platform is None):
            host.recorder.source_failed(session, '直播间已关闭或平台不可用')
            return
        resolver = StreamResolver(session.room_id, int(tile.actual_quality or tile.quality or 250),
                                  host, platform=platform,
                                  codec=session.video_codec or host._codec_settings(tile)['bili_codec'])
        session.resolver = resolver

        def current():
            return (not host._closing and host.recorder.sessions.get(tile) is session
                    and not session.stopping and session.resolver is resolver
                    and tile in host.wall.tiles
                    and str(tile.room.get('room_id') or '') == session.room_id)

        def resolved(_rid, url, quality, profile, _options):
            if current():
                if ((tile.room.keys() & {'_streamer_recording_height', '_streamer_recording_choice'})
                        and tile in host._capture_quality
                        and quality != tile.quality):
                    host.recorder.source_failed(session, '直播源未提供锁定的录制画质')
                    return
                codec = resolver.source_codec if platform is not None else bili.codec_from_profile(profile)
                host.recorder.source_resolved(session, url, dict(resolver.headers), codec)

        def failed(_rid, reason):
            if current():
                host.recorder.source_failed(session, reason)

        resolver.resolved.connect(resolved)
        resolver.failed.connect(failed)
        resolver.finished.connect(lambda: host._resolvers_running.discard(resolver))
        resolver.finished.connect(resolver.deleteLater)
        host._resolvers_running.add(resolver)
        resolver.start()
