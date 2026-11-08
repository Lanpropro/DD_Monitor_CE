"""Per-tile codec preferences and UI; the window owns dialogs, requests and players."""
import sys

from PySide6.QtCore import Qt

from . import config as config_module
from . import player as player_module


class CodecControl:
    def __init__(self, host):
        self.host = host

    def decoder_fallback(self, player, mode: str) -> None:
        host = self.host
        tile = host._tile_of_player(player)
        if tile is None:
            return
        label = config_module.DECODE_LABELS.get(mode, mode)
        tile.set_status(f"解码异常，正在尝试{label}…")
        print(f"[播放] {tile.room.get('uname')} 解码异常，切换至{label}",
              file=sys.stderr, flush=True)

    def media_options(self, tile=None) -> tuple[str, ...]:
        """按设置给每一路画面墙媒体选择 播放器 解码方式。"""
        host = self.host
        return player_module.decode_media_options(host._codec_settings(tile)["decode_mode"])

    def codec_settings(self, tile=None) -> dict:
        host = self.host
        return config_module.codec_settings(host.settings,
            getattr(tile, "codec_overrides", None))

    def is_bili_tile(self, tile) -> bool:
        host = self.host
        room_id = str(tile.room.get("room_id") or "")
        return room_id.isdigit() and host.plugins.platform_for(room_id) is None

    def restart_codec_tile(self, tile) -> None:
        host = self.host
        tile.codec_reconnect_pending = True
        resolver = host._resolvers.pop(tile, None)
        if resolver is not None:
            resolver.cancel()
        if (not tile.room.get("room_id") or not tile.room.get("live")
                or tile.paused or tile.isHidden()):
            return
        host.start_tile(tile)

    def tile_codecs_changed(self, tile, before: dict) -> bool:
        host = self.host
        after = host._codec_settings(tile)
        return (before.get("decode_mode") != after["decode_mode"]
                or before.get("bili_codec") != after["bili_codec"])

    def set_tile_codecs(self, tile, values: dict) -> None:
        host = self.host
        if host._closing or tile not in host.wall.tiles:
            return
        before = host._codec_settings(tile)
        tile.codec_overrides = config_module.codec_overrides(values)
        if host._tile_codecs_changed(tile, before):
            host._restart_codec_tile(tile)
        host._save_timer.start()

    def keep_tile_codec(self, tile, requested: str, retained: str, *, unavailable: bool,
                         quality_note: str = "") -> None:
        host = self.host
        names = {"avc": "H.264", "hevc": "HEVC", "av1": "AV1"}
        reason = "直播源未提供" if unavailable else "未能验证直播源格式"
        detail = quality_note or f"{reason} {names[requested]}"
        tile.codec_probe_note = f"{detail}，未切换；继续使用 {names[retained]}。"
        tile.codec_overrides["bili_codec"] = retained
        dialog = host._codec_dialogs.get(tile)
        if dialog is not None:
            dialog.controls.set_values(tile.codec_overrides)
        host._save_timer.start()
        player = host.players.get(tile)
        if (player is not None and player._decode_key is not None
                and player._decode_key[1] != host._codec_settings(tile)["decode_mode"]):
            try:
                player.play(player.stream_url, player.stream_profile, player.stream_headers,
                            options=host.media_options(tile))
            except (RuntimeError, OSError):
                tile.codec_probe_note += " 新的本机解码方式未能应用。"

    def codec_status(self, tile) -> str:
        host = self.host
        if host._closing or tile not in host.wall.tiles:
            return "该窗口已关闭。"
        requested = host._codec_settings(tile)
        names = {"avc": "H.264", "hevc": "HEVC", "av1": "AV1"}
        if tile in host._resolvers and not getattr(host._resolvers[tile], "strict_codec", False):
            return "正在连接，等待新流；当前选择将在连接成功后生效。"
        player = host.players.get(tile)
        if player is None or not tile.room.get("room_id"):
            return (getattr(tile, "codec_probe_note", "")
                    or "当前没有播放中的流；设置将在下次播放时生效。")
        if getattr(tile, "codec_reconnect_pending", False):
            return "新设置已保存，将在恢复播放或下次连接时生效。"
        codec = names.get(player.actual_codec, "未知（平台未提供编码信息）")
        if (host._is_bili_tile(tile) and player.stream_codec
                and player.stream_codec != requested["bili_codec"]):
            codec += f"（首选 {names[requested['bili_codec']]}，当前未切换）"
        mode = player.decode_mode
        labels = {value: label for label, value in player_module.DECODE_MODES}
        actual = player.actual_decoder
        decoder = "软件解码（CPU）" if actual == "no" else actual
        decoder = f"{labels.get(mode, mode)}；实际：{decoder}"
        if mode != requested["decode_mode"] or actual == "no" and mode != "none":
            decoder += "（故障回退）"
        note = getattr(tile, "codec_probe_note", "")
        params = player._prop("video-params") or {}
        resolution = (f"\n实际分辨率：{params['w']}×{params['h']}"
                      if isinstance(params, dict) and params.get("w") and params.get("h") else "")
        return f"实际直播源：{codec}\n当前解码方式：{decoder}" + resolution + (f"\n{note}" if note else "") + (
            "\n已暂停；新设置将在恢复播放时生效。" if tile.paused else "")

    def open_tile_codecs(self, tile, *, dialog_type) -> None:
        host = self.host
        CodecSettingsDialog = dialog_type
        if host._closing or tile not in host.wall.tiles:
            return
        existing = host._codec_dialogs.get(tile)
        if existing is not None:
            existing.show()
            existing.raise_()
            existing.activateWindow()
            return
        dialog = CodecSettingsDialog(tile.codec_overrides, host,
            defaults=config_module.codec_settings(host.settings),
            bili_enabled=host._is_bili_tile(tile), status=lambda: host._codec_status(tile))
        dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        dialog.controls.changed.connect(lambda values: host._set_tile_codecs(tile, values))
        dialog.finished.connect(lambda _result: host._codec_dialogs.pop(tile, None))
        host._codec_dialogs[tile] = dialog
        dialog.show()

    def stream_info_snapshot(self, tile):
        host = self.host
        if host._closing or tile not in host.wall.tiles or not tile.room.get('room_id'):
            return None
        player = host.players.get(tile)
        info = player.stream_info() if player is not None else {'state': 'idle'}
        info['room'] = f"{tile.room.get('uname') or '直播间'} · {tile.room['room_id']}"
        return info

    def open_tile_stream_info(self, tile):
        host = self.host
        if host._stream_info_snapshot(tile) is None:
            return
        existing = host._stream_info_dialogs.get(tile)
        if existing is not None:
            existing.set_presentation_owner(tile.window())
            existing.refresh()
            existing.show()
            existing.raise_()
            existing.activateWindow()
            return
        from .stream_info import StreamInfoDialog
        dialog = StreamInfoDialog(lambda: host._stream_info_snapshot(tile), host)
        dialog.finished.connect(lambda _result: host._stream_info_dialogs.pop(tile, None))
        host._stream_info_dialogs[tile] = dialog
        dialog.set_presentation_owner(tile.window())
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
