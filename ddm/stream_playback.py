"""Stream requests and playback coordination; state and Qt children belong to the window."""
import sys

from PySide6.QtCore import QTimer

from . import bili
from . import plugins as plugin_api
from .auto_quality import AUTO_QUALITY, OVERSEAS_PLATFORMS


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
