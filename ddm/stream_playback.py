"""Stream requests and playback coordination; state and Qt children belong to the window."""
import sys

from PySide6.QtCore import QTimer

from . import bili
from . import plugins as plugin_api
from .auto_quality import AUTO_QUALITY, OVERSEAS_PLATFORMS
from .tile_widgets import Tile


class StreamPlayback:
    def __init__(self, host):
        self.host = host

    def start_startup_tiles(self) -> None:
        host = self.host
        if host._closing:
            return
        host.apply_quality_policy(restart=False)
        pending = list(host.wall.tiles)
        def start_next():
            if host._closing:
                return
            while pending:
                tile = pending.pop(0)
                if (tile in host.wall.tiles and tile not in host.players
                        and tile not in host._resolvers):
                    host.start_tile(tile)
                    break
            if pending:
                QTimer.singleShot(0, host, start_next)
        QTimer.singleShot(0, host, start_next)

    def start_all(self) -> None:
        # 启动阶段先静默写好主次画质，再统一启动；否则 set_quality 的信号会
        # 先取一次流，下面的循环又取一次，同一格两个 resolver 会互相抢播放器。
        host = self.host
        host.apply_quality_policy(restart=False)
        for tile in host.wall.tiles:
            host.start_tile(tile)

    def apply_quality_policy(self, *, restart: bool = True) -> list:
        """有主次布局时：主画面自动用原画，其余用 720P。"""
        host = self.host
        changed = []
        if not host.settings.get("auto_quality", True):
            return changed
        main = host.wall.main_index()
        if main is None:
            return changed
        for index, tile in enumerate(host.wall.tiles):
            if not tile.room.get("room_id"):
                continue
            if not str(tile.room["room_id"]).isdigit():
                continue                  # 原画/720P 策略仅适用于 B 站，插件沿用本平台手选档位
            if tile in host._capture_quality:
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
                    host.start_tile(tile)
        return changed

    def start_tile(self, tile, *, stream_quality: int | None = None, resolver_type) -> None:
        host = self.host
        StreamResolver = resolver_type
        if getattr(host, "_tray", None) is not None and host._tray.hold_playback(tile):
            return
        if host._match_sync_holds(tile):
            host._match_sync_saved.setdefault(tile, (str(tile.room.get("room_id") or ""), tile.paused))
            return
        if host._closing:
            return                    # 关窗途中别再起取流/播放器
        room = tile.room or {}
        room_id = str(room.get("room_id") or "")
        if not room_id:
            return
        tile.codec_reconnect_pending = False
        platform = host.plugins.platform_for(room_id)
        if platform is not None and platform.kind in OVERSEAS_PLATFORMS and tile.quality == 250:
            tile.quality = tile.room["quality"] = AUTO_QUALITY
        if ":" in room_id and platform is None:
            tile.set_status("请启用对应的平台插件并重启")
            return
        if not room.get("live") and (platform is None or room.get("live_known", True)):
            host._offline_tile(tile)
            tile.set_status("未开播")
            return
        host.playback_recovery.cancel_retry(tile)
        previous = host._resolvers.get(tile)
        if previous is not None:
            previous.cancel()
        player = host.players.get(tile)
        if player is not None:
            player.freeze_watch = bool(host.settings.get("freeze_watch", True))
        codec = host._codec_settings(tile)["bili_codec"]
        retained_codec = player.stream_codec if player is not None and tile.stream_url else ""
        strict_codec = platform is None and retained_codec in bili.CODEC_PARAM and codec != retained_codec
        if strict_codec:
            names = {"avc": "H.264", "hevc": "HEVC", "av1": "AV1"}
            tile.codec_probe_note = f"正在探测 {names[codec]}；当前继续使用 {names[retained_codec]}。"
            if player is not None and player.paused and not tile.paused:
                player.set_paused(False)
        else:
            tile.codec_probe_note = ""
            tile.set_paused(False)        # 重新取流就恢复播放状态
            tile.set_status("连接中…")
        # 以格子上的画质为准（信号带过来的字典是副本，不能当数据源）
        quality = int(tile.quality or room.get("quality", 250))
        source_offset = host._stream_attempts.get(tile, 0)
        host._stream_attempts[tile] = source_offset + 1
        if room_id.startswith("huya:"):
            print(f"[平台诊断] 阶段=source_request 房间={room_id} 画质={quality} 尝试={source_offset + 1}",
                  file=sys.stderr, flush=True)
        resolver = StreamResolver(room_id, quality if stream_quality is None else stream_quality,
                                  host, source_offset=source_offset,
                                  platform=platform,
                                  codec=codec, strict_codec=strict_codec)

        def current():
            return (not host._closing and tile in host.wall.tiles
                    and str(tile.room.get("room_id") or "") == room_id
                    and host._resolvers.get(tile) is resolver and not resolver.is_cancelled()
                    and host._codec_settings(tile)["bili_codec"] == codec)

        def resolved(_rid, url, qn, profile, options):
            if not current() or int(tile.quality) != quality:
                return
            host._resolvers.pop(tile, None)
            if tile.paused:
                tile.codec_reconnect_pending = True
                return
            if strict_codec:
                if bili.codec_from_profile(profile) != codec:
                    host._keep_tile_codec(tile, codec, retained_codec, unavailable=True)
                    return
                tile.codec_probe_note = ""
            elif platform is not None:
                tile.codec_probe_note = getattr(resolver, "codec_probe_note", "")
            elif getattr(resolver, "original_quality_note", ""):
                tile.codec_probe_note = f"{resolver.original_quality_note}；已使用默认 H.264。"
                tile.codec_overrides["bili_codec"] = "avc"
                dialog = host._codec_dialogs.get(tile)
                if dialog is not None:
                    dialog.controls.set_values(tile.codec_overrides)
                host._save_timer.start()
            host._play_on(tile, url, qn, profile, options, headers=resolver.headers,
                          room_id=room_id, requested_quality=quality,
                          source_codec=(getattr(resolver, "source_codec", "")
                                        if platform is not None else None))

        def failed(_rid, reason):
            if not current() or int(tile.quality) != quality:
                return
            host._resolvers.pop(tile, None)
            tile.set_quality_options(getattr(resolver, "failure_quality_options", []))
            if strict_codec:
                host._keep_tile_codec(tile, codec, retained_codec,
                                      unavailable=resolver.codec_unavailable,
                                      quality_note=getattr(resolver, "original_quality_note", ""))
            else:
                tile.codec_probe_note = f"取流失败：{reason}"
                host._on_resolve_failed(tile, reason, requested_quality=quality,
                                        login_required=resolver.login_required)

        resolver.resolved.connect(resolved)
        resolver.failed.connect(failed)
        resolver.finished.connect(lambda t=tile, r=resolver: host._on_resolver_finished(t, r))
        resolver.finished.connect(resolver.deleteLater)
        host._resolvers_running.add(resolver)
        host._resolvers[tile] = resolver
        resolver.start()
        host._stats_refresh_timer.start()  # 取流优先，多路同时开播时合并人数查询

    def resolver_finished(self, tile, resolver) -> None:
        host = self.host
        if host._resolvers.get(tile) is resolver:
            host._resolvers.pop(tile, None)
        host._resolvers_running.discard(resolver)

    def play_on(self, tile, url: str, quality: int = 0, profile: str = "web",
                 options: list | None = None, headers: dict | None = None,
                 room_id: str = "", requested_quality: int = 0,
                 source_codec: str | None = None, *, player_type) -> None:
        host = self.host
        TilePlayer = player_type
        if host._closing:
            # 关窗后迟到的取流回调：播放器已经 release，碰它就是野指针
            return
        if host._match_sync_holds(tile):
            return
        if getattr(host, "_tray", None) is not None and host._tray.hold_playback(tile):
            return
        if room_id and str(tile.room.get("room_id") or "") != str(room_id):
            return                    # 迟到的取流结果（格子已经换台/被换走了）
        if requested_quality and int(tile.quality) != requested_quality:
            return                    # 画质已切换，旧请求不能覆盖新流
        if ":" in str(tile.room.get("room_id") or ""):
            tile.set_live(True)
        if options:
            discover_highest = (not tile.quality_options and host._fullscreen_tile is tile
                                and requested_quality == 10000)
            tile.set_quality_options(options)
            if discover_highest and host._upgrade_fullscreen_quality(tile):
                return  # 首次档位迟到：直接取最高档，不先播放旧的较低档。
            if quality and requested_quality != AUTO_QUALITY and ":" in str(tile.room.get("room_id") or ""):
                tile.quality = quality
                tile.room["quality"] = quality
        if quality:
            tile.set_actual_quality(quality)
            if (requested_quality != AUTO_QUALITY and ":" in str(tile.room.get("room_id") or "") and requested_quality != quality
                    and any(int(option["qn"]) == requested_quality for option in options or [])):
                tile.quality_button.setToolTip(
                    f"请求 {tile._quality_name(requested_quality)}，平台实际返回 {tile._quality_name(quality)}")
        player = host.players.get(tile)
        if player is None:
            player = TilePlayer(tile.video, host)
            # 连接里不锁死格子：秒切之后播放器会挂到别的格子上，回调现查
            player.stateChanged.connect(
                lambda state, p=player:
                host._on_player_state(host._tile_of_player(p), state))
            player.pictureActivity.connect(
                lambda p=player: host._on_picture_activity(host._tile_of_player(p)))
            player.autoQualityRequested.connect(lambda qn, p=player: host._on_auto_quality(p, qn))
            player.decoderFallback.connect(lambda mode, p=player: host._on_decoder_fallback(p, mode))
            host.players[tile] = player
        player.freeze_watch = bool(host.settings.get("freeze_watch", True))
        player.set_volume_normalization(bool(host.settings.get("volume_normalization", False)), host.settings.get('volume_normalization_curve'))
        player.set_volume(int(tile.volume))
        player.set_audio_channel(int(tile.audio_channel))
        player.set_muted(tile.muted or bool(getattr(host, "_match_sync_active", False)))
        # 把这一路的取流结果记在格子和播放器上：插件（录像等）要拿它去拉同一路流；
        # 播放器上那份是给「秒切」用的 —— 画面搬走时取流结果跟着一起走。
        room = tile.room or {}
        stream_codec = (source_codec if source_codec is not None else
                        bili.codec_from_profile(profile) if host._is_bili_tile(tile) else "")
        tile.stream_url = url
        tile.stream_profile = profile
        tile.stream_codec = stream_codec
        tile.stream_headers = dict(headers or TilePlayer.PROFILE_HEADERS.get(
            profile, TilePlayer.PROFILE_HEADERS["web"]))
        player.stream_url = tile.stream_url
        player.stream_profile = profile
        player.stream_codec = stream_codec
        player.stream_headers = dict(tile.stream_headers)
        player.diagnostic_room = str(room.get("room_id") or "")
        player.actual_quality = int(quality or 0)
        player.configure_auto_quality(str(room.get("room_id") or ""),
            options if tile.quality == AUTO_QUALITY and profile in OVERSEAS_PLATFORMS else [])
        try:
            player.play(url, profile, tile.stream_headers,
                        options=host.media_options(tile))
        except (RuntimeError, OSError) as error:
            tile.set_buffering(False)
            tile.set_status(str(error))
            tile.codec_probe_note = f"播放失败：{error}"
            return
        host.recorder.on_resolved(tile)
        if tile in host._pending_capture:
            host._finish_pending_capture(tile)
        host._emit_stream_resolved(tile, quality)
        if getattr(host, "_tray", None) is not None and host._tray.hold_playback(tile):
            host._stop_tile(tile)
            return
        resume = getattr(host, "_match_sync_resume_pause", {}).pop(tile, None)
        if resume == str(tile.room.get("room_id") or ""):
            tile.set_paused(True)
            player.set_paused(True)
        # 直播起来了：即时回放该开的就在这里开，不用用户手动点
        host._sync_replay_scope()

    def auto_quality(self, player, quality: int) -> None:
        host = self.host
        tile = host._tile_of_player(player)
        if (host._closing or tile is None or tile.quality != AUTO_QUALITY or tile.paused
                or tile in host._resolvers or tile in host._capture_quality
                or not tile.room.get("live") or player.auto_quality is None
                or str(tile.room.get("room_id")) != player.auto_quality.room_id):
            return
        host.start_tile(tile, stream_quality=quality)

    def emit_stream_resolved(self, tile, quality: int = 0) -> None:
        """把「这一格现在播的是哪路流」告诉插件（录像等要靠它拉同一路流）。"""
        host = self.host
        room = tile.room or {}
        host.plugins.emit(
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

    def resolve_failed(self, tile, reason: str, requested_quality: int = 0,
                           *, login_required=False) -> None:
        host = self.host
        if host._closing:
            return                    # 关窗后迟到的取流失败：别再拉轮询线程
        if requested_quality and int(tile.quality) != requested_quality:
            return
        if not tile.room.get("live") and tile.room.get("live_known", True):
            host._offline_tile(tile)
            tile.set_status("未开播")
            return
        if tile in host._pending_capture:
            host._pending_capture.pop(tile)
            host._record_notice(f"原画取流失败，录制未开始：{reason}", tile.room)
            host._restore_capture_quality(tile)
            if not login_required:
                return
        if login_required:
            tile.set_buffering(False)
            tile.set_status(reason)
            kind = str(tile.room.get("room_id") or "").partition(":")[0]
            account = host._accounts.get(kind)
            already_warned = bool(account and account.get("_login_expired"))
            if account is not None:
                account["_login_expired"] = True
            host._render_account(load_avatar=False)
            if not already_warned:
                host._show_notice(reason, kind="warning")
            return
        tile.set_buffering(False)
        tile.set_status("连接失败")
        print(f"[取流失败] {tile.room.get('uname')}: {reason}")
        host.plugins.emit(plugin_api.EVENT_STREAM_FAILED, tile=tile, reason=reason,
                          room=dict(tile.room or {}))
        host.refresh_status()       # 取不到流时立刻确认是否已经下播
        if tile in host._freeze_refreshed:
            host._on_picture_frozen(tile)
        elif tile.room.get("room_id") and tile.room.get("live") and not tile.paused:
            host._schedule_retry(tile)

    def check_audio_output_device(self) -> None:
        host = self.host
        if host._closing:
            return
        device_id = bytes(host._audio_devices.defaultAudioOutput().id())
        if device_id == host._default_audio_output_id:
            return
        try:
            for player in host.players.values():
                player.refresh_audio_device()
        except Exception as exc:  # noqa: BLE001 - device notifications must not stop Qt
            print(f"[音频输出] 刷新设备失败：{exc}", file=sys.stderr, flush=True)
            return
        host._default_audio_output_id = device_id

    def on_player_state(self, tile, state: str) -> None:
        host = self.host
        if tile is None:
            return                        # 播放器已经不在任何格子上（刚被停掉）
        if not tile.room.get("room_id"):
            return
        if state == "playing":
            host.playback_recovery.cancel_retry(tile)
            tile.set_video_active(True)
            tile.set_buffering(False)
            tile.set_status("")
            tile.start_elapsed_timer()
            host.playback_recovery.reset_retry_after_playing(tile)
            player = host.players.get(tile)
            if player is not None:
                # 声道要在音频输出模块起来之后再设一次，否则会被初始化冲掉
                player.reapply_audio_channel()
            host.plugins.emit(plugin_api.EVENT_TILE_PLAYING, tile=tile,
                              room=dict(tile.room or {}))
        elif state == "connecting":
            tile.set_video_active(False)
            tile.set_status("连接中…")
        elif state == "buffering":
            tile.set_buffering(True)         # 卡顿时也显示缓冲动画
        elif state == "frozen":
            player = host.players.get(tile)
            if str(tile.room.get("room_id", "")).startswith("douyu:") and player is not None:
                host.plugins.emit(plugin_api.EVENT_STREAM_FAILED, tile=tile, room=dict(tile.room),
                    source_url=player.stream_url, reason="STALL")
            host._on_picture_frozen(tile)
        elif state == "error":
            host._clear_freeze_recovery(tile)
            tile.set_video_active(False)
            tile.stop_elapsed_timer()
            player = host.players.get(tile)
            if str(tile.room.get("room_id", "")).startswith(("huya:", "douyu:")) and player is not None:
                host.plugins.emit(plugin_api.EVENT_STREAM_FAILED, tile=tile, room=dict(tile.room),
                    source_url=player.stream_url, reason=player.source_failure or "STALL")
            host.refresh_status()           # 断流可能来自下播，立即向接口确认
            host._schedule_retry(tile)
        else:
            tile.set_video_active(False)
            tile.stop_elapsed_timer()
        tile.raise_overlays()

    def stop_tile(self, tile) -> None:
        host = self.host
        dialog = host._codec_dialogs.get(tile)
        if dialog is not None:
            dialog.close()
        host._replay_suppressed.pop(tile, None)
        host.playback_recovery.clear_tile(tile)
        host._stream_attempts.pop(tile, None)
        player = host.players.pop(tile, None)
        if player is not None:
            player.release()
        resolver = host._resolvers.pop(tile, None)
        if resolver is not None:
            # 只作废、不强杀：terminate() 会带走线程本地存储和锁，主线程可能
            # 整个卡死（窗口不动也不退出，用户看到的就是「直接崩了」）
            resolver.cancel()
        host.plugins.emit(plugin_api.EVENT_TILE_STOPPED, tile=tile,
                          room=dict(tile.room or {}))

    def match_sync_holds(self, tile):
        host = self.host
        if not getattr(host, "_match_sync_active", False):
            return False
        return tile not in host.recorder.sessions and tile not in host._pending_capture

    def set_match_sync_playback(self, active):
        """Release hidden watching sessions, preserving independent recordings."""
        host = self.host
        if bool(active) == getattr(host, "_match_sync_active", False):
            return
        host._match_sync_active = bool(active)
        if active:
            host._match_sync_saved = {}
            host._match_sync_resume_pause = {}
            for tile in set(host.players) | set(host._resolvers) | set(host._retry_timers):
                if host._match_sync_holds(tile):
                    host._match_sync_saved[tile] = (str(tile.room.get("room_id") or ""), tile.paused)
                    host._stop_tile(tile)
        else:
            saved, host._match_sync_saved = getattr(host, "_match_sync_saved", {}), {}
            if host._closing:
                return
            for tile, (room_id, paused) in saved.items():
                if (tile.isVisible() and room_id == str(tile.room.get("room_id") or "")
                        and tile.room.get("live")):
                    if paused:
                        host._match_sync_resume_pause[tile] = room_id
                    host.start_tile(tile)

    def sync_tile_playback(self, *, start_visible: bool = False) -> None:
        """只让**看得见**的格子播放。

        布局从 9 格换成 6 格时，多出来的格子以前只是 ``setVisible(False)``：播放器
        一步没停，还在解码、**还在出声**（用户报「没显示出来的格子也在响」）。这里
        把当前布局放不下的停掉；已选择的可见房间按需起播，新增位置保持空白。
        """
        host = self.host
        if getattr(host, "_tray", None) is not None and host._tray.playback_suspended:
            return
        if not getattr(host, "plugins", None):
            start_visible = False       # 构造期间插件还没装好，不能在这里起流
        for tile in host.wall.tiles:
            if getattr(host, "_match_sync_active", False):
                continue
            player = host.players.get(tile)
            if tile.isVisible():
                if start_visible and player is None and tile.room.get("live"):
                    host.start_tile(tile)
            else:
                host._pending_capture.pop(tile, None)
                host.recorder.stop(tile)
                if tile not in host.recorder.sessions:
                    host._restore_capture_quality(tile)
                if (player is None and tile not in host._resolvers
                        and tile not in host._retry_timers
                        and tile not in host._freeze_retry_timers):
                    continue
                print(f"[布局] {tile.room.get('uname')} 当前布局放不下，先停播",
                      file=sys.stderr, flush=True)
                host._stop_tile(tile)

    def offline_tile(self, tile) -> None:
        """这一路下播：停掉播放（画面变黑），格子继续留给它，等重新开播自动接上。"""
        host = self.host
        host.playback_recovery.cancel_retry(tile, reset_attempts=True)
        host._pending_capture.pop(tile, None)
        host.recorder.stop(tile)
        host._stop_tile(tile)
        tile.set_offline()
        if tile not in host.recorder.sessions:
            host._restore_capture_quality(tile)
        print(f"[下播] {tile.room.get('uname')} 画面已清空，格子保留",
              file=sys.stderr, flush=True)

    def tile_of(self, room_id: str):
        host = self.host
        return next((tile for tile in host.wall.tiles
                     if str(tile.room.get("room_id") or "") == str(room_id)), None)

    def sender_tile(self):
        """发信号的那个格子；不是格子发的（定时器之类）返回 None。

        定位操作对象**别用 room_id 反查**：同一个直播间占了两个格子时（配置里
        存重了、或同一张卡片被拖上两次），反查只命中列表里第一个 —— 于是「静音
        这一格」把另一格的播放器静音了，这一格反倒还在出声，而标志是画在自己
        身上的、照样亮着。用户报的「开这格静音，旁边那格声音不对」就是这个。
        这些信号都是直接连接的，sender() 可靠；反查只留作兜底。
        """
        host = self.host
        sender = host.sender()
        return sender if isinstance(sender, Tile) else None

    def tile_of_player(self, player):
        """播放器现在挂在哪个格子上（格子换位置之后连接不用重接，靠这个现查）。"""
        host = self.host
        for tile, candidate in host.players.items():
            if candidate is player:
                return tile
        return None

    def on_tile_clicked(self, room: dict) -> None:
        # 信号带过来的字典是副本，用房间号比较（不能比较对象身份）
        host = self.host
        room_id = str(room.get("room_id") or "")
        host.sidebar.watch_history.select(room_id)
        for tile in host.wall.tiles:
            tile.set_focused(bool(room_id) and str(tile.room.get("room_id") or "") == room_id)
        host.sidebar.select_room(room)

    def on_volume_changed(self, room: dict, value: int) -> None:
        host = self.host
        tile = host._sender_tile() or host._tile_of(str(room.get("room_id")))
        player = host.players.get(tile) if tile is not None else None
        if player is not None:
            player.set_volume(value)
        host._save_timer.start()       # 滑块停下 700ms 后保存每个格子的音量

    def on_audio_changed(self, room: dict, value: int) -> None:
        host = self.host
        tile = host._sender_tile() or host._tile_of(str(room.get("room_id")))
        player = host.players.get(tile) if tile is not None else None
        if player is not None:
            player.set_audio_channel(value)
            # 播放中的这一路要等音频输出模块起来后再补一次，否则会被初始化冲掉
            player.reapply_audio_channel()
        host._save_timer.start()       # 声道属于格子，和音量一起记住

    def on_quality_changed(self, room: dict, quality: int) -> None:
        # 注意：Qt 信号传过来的 dict 是副本，必须写回格子自己的字典
        host = self.host
        tile = host._sender_tile() or host._tile_of(str(room.get("room_id")))
        if tile is None:
            return
        if tile in host._capture_quality and quality != 10000:
            blocked = tile.blockSignals(True)
            try:
                tile.set_quality(10000)
            finally:
                tile.blockSignals(blocked)
            return
        tile.quality = quality
        tile.room["quality"] = quality
        host._save_timer.start()
        if tile.room.get("live"):
            player = host.players.get(tile)
            if (player is not None and player.stream_profile in OVERSEAS_PLATFORMS
                    and player._media is not None and player.state in ("playing", "buffering")
                    and any(int(item["qn"]) == player.actual_quality
                            for item in tile.quality_options)
                    and quality in (AUTO_QUALITY, player.actual_quality)):
                # 自动是画质策略；沿用正在播放的档位，避免点击时停掉原生解码器。
                # 锁定当前档也只需关掉策略。其他手选档位仍走正常换流流程。
                previous = host._resolvers.pop(tile, None)
                if previous is not None:
                    previous.cancel()
                player.configure_auto_quality(str(tile.room["room_id"]),
                    tile.quality_options if quality == AUTO_QUALITY else [])
                tile.set_actual_quality(player.actual_quality)
                return
            host.start_tile(tile)

    def on_mute_changed(self, room: dict, muted: bool) -> None:
        host = self.host
        tile = host._sender_tile() or host._tile_of(str(room.get("room_id")))
        player = host.players.get(tile) if tile is not None else None
        if player is not None:
            player.set_muted(muted)
        host._save_timer.start()       # 静音也是格子状态，和音量一起记住

    def audit_audio(self) -> None:
        """保持每格的独立音量、静音和声道。"""
        host = self.host
        for tile in host.wall.tiles:
            player = host.players.get(tile)
            if player is not None and tile.room.get("room_id"):
                player.sync_audio(int(tile.volume), bool(tile.muted), int(tile.audio_channel))

    def on_reload(self, room: dict) -> None:
        host = self.host
        tile = host._sender_tile() or host._tile_of(str(room.get("room_id")))
        if tile is not None:
            host._clear_freeze_recovery(tile)
            if host._is_bili_tile(tile) and tile.codec_probe_note:
                tile.codec_probe_note = ""
            host.start_tile(tile)

    def on_pause_toggled(self, room: dict) -> None:
        host = self.host
        tile = host._sender_tile() or host._tile_of(str(room.get("room_id")))
        if tile is None:
            return
        paused = not tile.paused
        tile.set_paused(paused)
        resolver = host._resolvers.get(tile)
        if paused and resolver is not None:
            host._resolvers.pop(tile, None)
            resolver.cancel()
            tile.codec_reconnect_pending = True
            tile.codec_probe_note = "探测已暂停；恢复播放时重新探测，当前流保持暂停。"
        if not paused and getattr(tile, "codec_reconnect_pending", False):
            host.start_tile(tile)
            return
        player = host.players.get(tile)
        if player is not None:
            player.set_paused(paused)
        print(f"[暂停] {tile.room.get('uname')} -> {'暂停' if paused else '继续'}",
              file=sys.stderr, flush=True)
