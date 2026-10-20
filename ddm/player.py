"""每个画面独立的 libmpv 播放、音频与故障恢复。"""
import os
import sys
import time
from pathlib import Path
from typing import ClassVar

from PySide6.QtCore import QObject, QTimer, Signal

from .audio_output import channel_filters, linear_volume
from .auto_quality import AutoQuality
from .bili import APP_UA, UA, is_hls_profile
from .config import DECODE_HWDEC as HWDEC
from .config import DECODE_MODES as DECODE_MODES  # noqa: PLC0414

_runtime = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
_dll_directory = None
if sys.platform == "win32" and (_runtime / "libmpv-2.dll").is_file():
    os.environ["PATH"] = str(_runtime) + os.pathsep + os.environ.get("PATH", "")
    _dll_directory = os.add_dll_directory(str(_runtime))

import mpv

HW_DECODE_OFF_OPTION = "hwdec=no"
EMBEDDED_OPTIONS = {"config": False, "load_scripts": False, "osc": False, "ytdl": False,
    "load_stats_overlay": False, "load_console": False, "load_osd_console": False,
    "load_auto_profiles": False, "load_select": False, "load_positioning": False,
    "load_commands": False, "load_context_menu": False}

# 静音预览缩短流信息探测，缓存策略仍沿用普通播放器。
PREVIEW_STARTUP_OPTIONS = {"demuxer_lavf_analyzeduration": 0.1}


def decode_media_options(mode: str) -> tuple[str, ...]:
    return () if mode not in HWDEC or mode == "auto" else (f"hwdec={HWDEC[mode]}",)


class TilePlayer(QObject):
    stateChanged = Signal(str)
    pictureActivity = Signal()
    autoQualityRequested = Signal(int)
    decoderFallback = Signal(str)

    PICTURE_POLL_MS = 1000
    FROZEN_TICKS = 2
    PROFILE_HEADERS: ClassVar = {
        "app": {"User-Agent": APP_UA},
        "web": {"User-Agent": UA, "Referer": "https://live.bilibili.com/"},
    }
    _version = "?"

    @classmethod
    def backend_version(cls) -> str:
        if cls._version == "?":
            core = mpv.MPV(vo="null", ao="null", **EMBEDDED_OPTIONS)
            try:
                cls._version = str(core.mpv_version)
            finally:
                core.terminate()
        return cls._version

    def __init__(self, video_widget, parent=None, silent: bool = False):
        super().__init__(parent)
        self.video_widget = video_widget
        self.silent = bool(silent)
        self.muted = self.silent
        self.volume = 0 if self.silent else 42
        self.audio_channel = 0
        self.paused = False
        self.state = "idle"
        self.url = ""
        self.stream_url = ""
        self.stream_profile = "web"
        self.stream_codec = ""
        self.stream_headers: dict = {}
        self.actual_quality = 0
        self.auto_quality = None
        self._auto_options = []
        self.freeze_watch = True
        self._released = False
        self._audio_ready = True
        self._bound = False
        self._bound_hwnd = 0
        self._media = None
        self._hls_proxy = None
        self.player = None
        self.decode_mode = "none" if self.silent else "auto"
        self._decode_key = None
        self._decode_tried: set[str] = set()
        self._play_request = None
        self._decoder_error = False
        self._decode_snapshot = None
        self._decode_stall_ticks = 0
        self._last_picture = None
        self._last_time = None
        self._frozen_ticks = 0
        self._stall_ticks = 0
        self._picture_limit = self.FROZEN_TICKS
        self._buffer_limit = 6
        self._watch = QTimer(self)
        self._watch.setInterval(1500)
        self._watch.timeout.connect(self._check)
        self._watch.timeout.connect(self._check_auto_quality)
        self._picture_watch = QTimer(self)
        self._picture_watch.setInterval(self.PICTURE_POLL_MS)
        self._picture_watch.timeout.connect(self._check_picture_tick)

    def _prop(self, name, default=None):
        if self.player is None or self._released:
            return default
        try:
            value = getattr(self.player, name.replace("-", "_"))
            return default if value is None else value
        except (AttributeError, RuntimeError, ValueError):
            return default

    def _set(self, name, value):
        if self.player is not None and not self._released:
            setattr(self.player, name.replace("-", "_"), value)

    def _log(self, level, prefix, message):
        if level in ("error", "fatal") and prefix.startswith(("vd", "ffmpeg/video")):
            self._decoder_error = True

    def bind(self) -> None:
        if self._released:
            return
        hwnd = int(self.video_widget.winId())
        if self.player is not None and hwnd != self._bound_hwnd:
            self._destroy_core()
        if self.player is None:
            self.player = mpv.MPV(
                wid=str(hwnd), vo="gpu", gpu_api="d3d11", gpu_context="d3d11",
                force_window="immediate", hwdec=HWDEC[self.decode_mode], vd_lavc_threads=2,
                ao="null" if self.silent else "wasapi", audio="no" if self.silent else "auto",
                audio_channels="stereo", volume=linear_volume(self.volume), mute=self.muted,
                **EMBEDDED_OPTIONS,
                **(PREVIEW_STARTUP_OPTIONS if self.silent else {}),
                input_default_bindings=False, input_vo_keyboard=False, input_cursor=False,
                input_builtin_dragging=False, idle=True, keep_open=True,
                # Close WASAPI on mpv's core thread, not during GUI-thread termination.
                gapless_audio=False,
                cache=True, demuxer_max_bytes="16MiB", demuxer_max_back_bytes=0,
                network_timeout=8, log_handler=self._log, loglevel="error",
            )
        self._bound_hwnd = hwnd
        self._bound = True

    def invalidate_binding(self) -> None:
        self._bound = False

    def play(self, url: str, profile: str = "web", headers: dict | None = None,
             options=None) -> None:
        if self._released:
            return
        options = tuple(str(option) for option in options or ())
        hwdec = next((item.split("=", 1)[1] for item in options if item.startswith("hwdec=")),
                      "auto")
        requested = next((mode for mode, value in HWDEC.items() if value == hwdec), "auto")
        key = (self.stream_codec or profile, requested)
        if key != self._decode_key:
            self._decode_key = key
            self.decode_mode = "none" if self.silent else requested
            self._decode_tried = {self.decode_mode}
        self._play_request = (url, profile, dict(headers or {}), options)
        self._play_media(url, profile, headers, options)

    def _play_media(self, url, profile, headers, options) -> None:
        self._stop_media()
        self.bind()
        self.url = url
        self.paused = False
        self._decoder_error = False
        self._decode_snapshot = None
        self._decode_stall_ticks = 0
        overseas = profile in ("twitch", "youtube")
        hls = is_hls_profile(profile) or profile in ("huya", "douyu", "douyin") or overseas
        self._picture_limit = 20 if overseas else 8 if hls else self.FROZEN_TICKS
        self._buffer_limit = 20 if overseas else 6
        default_profile = "app" if profile.startswith("app") else "web"
        request_headers = dict(headers) if headers else dict(self.PROFILE_HEADERS[default_profile])
        if not any(name.lower() == "user-agent" for name in request_headers):
            request_headers["User-Agent"] = UA
        playback_url = url
        if overseas:
            from .global_danmaku import request_proxy
            from .hls_proxy import HlsProxy
            self._hls_proxy = HlsProxy(url, request_headers, request_proxy(url))
            playback_url = self._hls_proxy.url
        self._set("http-header-fields", [f"{name}: {value}" for name, value in request_headers.items()
                                         if value and "\n" not in str(value) and "\r" not in str(value)])
        self._set("hwdec", HWDEC[self.decode_mode])
        self._set("pause", False)
        self._set("aid", "no" if self.silent or "audio=no" in options else "auto")
        self._ensure_audio_settings()
        self._media = playback_url
        self._start_pending_media()
        self._last_picture = self._last_time = None
        self._stall_ticks = self._frozen_ticks = 0
        self._set_state("connecting")
        self._watch.start()
        self._picture_watch.start()
        refresh_clip = getattr(self.video_widget, "refresh_clip", None)
        if callable(refresh_clip):
            refresh_clip()

    def _start_pending_media(self):
        if self.player is not None and self._media is not None and not self._released:
            self.player.command("loadfile", self._media, "replace")
            self._set("pause", self.paused)

    def _stop_media(self):
        if self.player is not None:
            self.player.command("stop")
        if self._hls_proxy is not None:
            self._hls_proxy.stop()
            self._hls_proxy = None
        self._media = None

    def stop(self) -> None:
        if self._released:
            return
        self._watch.stop()
        self._picture_watch.stop()
        self._stop_media()
        self.auto_quality = None
        self._auto_options = []
        self._last_picture = None
        self._frozen_ticks = 0
        self._play_request = self._decode_key = None
        self._decode_tried.clear()
        if self.silent:
            self._destroy_core()
        self._set_state("idle")

    def _destroy_core(self):
        if self.player is not None:
            self.player.force_window = False
            self.player.command("stop")
            self.player.terminate()
            self.player = None
        self._bound = False
        self._bound_hwnd = 0

    def release(self) -> None:
        if self._released:
            return
        self.stop()
        self._released = True
        self._destroy_core()
        self.deleteLater()

    def set_muted(self, muted: bool) -> None:
        self.muted = bool(muted) or self.silent
        self._set("mute", self.muted)

    def set_volume(self, volume: int) -> None:
        self.volume = max(0, min(100, int(volume)))
        self._set("volume", linear_volume(self.volume))

    def set_audio_channel(self, channel: int) -> None:
        self.audio_channel = int(channel)
        self._set("af", ",".join(channel_filters(self.audio_channel)))

    def reapply_audio_channel(self) -> None:
        self.set_audio_channel(self.audio_channel)

    def _ensure_audio_settings(self) -> None:
        self.set_muted(self.muted)
        self.set_volume(self.volume)
        self.reapply_audio_channel()

    def sync_audio(self, volume: int, muted: bool, channel: int) -> None:
        if self._released or self.silent:
            return
        if self.volume != volume or abs(self._prop("volume", linear_volume(volume)) - linear_volume(volume)) > 0.1:
            self.set_volume(volume)
        if self.muted != muted or self._prop("mute", muted) != muted:
            self.set_muted(muted)
        if self.audio_channel != channel:
            self.set_audio_channel(channel)

    def refresh_audio_device(self) -> None:
        if self.player is not None and not self.silent and not self._released:
            self.player.command("ao-reload")

    def set_paused(self, paused: bool) -> None:
        self.paused = bool(paused)
        self._set("pause", self.paused)
        if self.auto_quality is not None:
            self.auto_quality.stable_since = self.auto_quality.stalled_since = None
        self._last_picture = self._last_time = None
        self._stall_ticks = self._frozen_ticks = 0
        if self.paused:
            self._picture_watch.stop()
        elif self._media is not None:
            self._watch.start()
            self._picture_watch.start()

    @property
    def actual_decoder(self) -> str:
        return str(self._prop("hwdec-current", "等待首帧"))

    @property
    def actual_codec(self) -> str:
        codec = self._prop("video-format", "")
        return {"h264": "avc", "hevc": "hevc", "av1": "av1"}.get(codec, self.stream_codec)

    def configure_auto_quality(self, room_id, options):
        self._auto_options = list(options or [])
        if self.silent or not self._auto_options:
            self.auto_quality = None
        elif self.auto_quality is None or self.auto_quality.room_id != room_id:
            self.auto_quality = AutoQuality(room_id, time.monotonic())
        else:
            self.auto_quality.last_switch = time.monotonic()
            self.auto_quality.stable_since = self.auto_quality.stalled_since = None
            self.auto_quality.has_played = False

    def _check_auto_quality(self):
        if self.auto_quality is None or self.paused or self._hls_proxy is None:
            return
        quality = self.auto_quality.choose(self._auto_options, self.actual_quality,
            self._hls_proxy.network_speed(), "buffering" if self._frozen_ticks >= 4 else self.state,
            time.monotonic())
        if quality is not None:
            self.autoQualityRequested.emit(quality)

    def _picture_signature(self):
        if self._media is None or not self._prop("vo-configured", False):
            return None
        position = self._prop("time-pos")
        return None if position is None else (position, position)

    def _recover_decoder(self, *, frozen=False) -> bool:
        if (self.silent or self.paused or self._released or self._play_request is None
                or self.decode_mode == "none"):
            return False
        if self._hls_proxy is not None and self._hls_proxy.refresh_required.is_set():
            return False
        cache_end = (self._prop("demuxer-cache-state", {}) or {}).get("cache-end", 0) or 0
        pts = self._prop("time-pos")
        previous = self._decode_snapshot
        blocked = (pts is not None and previous is not None and previous[1] is not None
                   and cache_end > previous[0] and pts == previous[1]
                   and not self._prop("paused-for-cache", False))
        if not frozen:
            self._decode_snapshot = (cache_end, pts)
            self._decode_stall_ticks = self._decode_stall_ticks + 1 if blocked else 0
        if (self._prop("hwdec-current") == "no" and pts is not None and pts > 0 and not blocked
                and self._decode_stall_ticks == 0):
            self._decoder_error = False
        if not (self._decoder_error or self._decode_stall_ticks >= 3
                or frozen and blocked and self._decode_stall_ticks > 0):
            return False
        mode = "none"
        self.decode_mode = mode
        self._decode_tried.add(mode)
        url, profile, headers, options = self._play_request
        self._play_media(url, profile, headers, options)
        self.decoderFallback.emit(mode)
        return True

    def _check_picture(self, playing: bool) -> bool:
        if not (self.freeze_watch and playing):
            self._frozen_ticks = 0
            self._last_picture = None
            return False
        signature = self._picture_signature()
        if signature is None or signature[1] == 0:
            self._last_picture = None
            self._frozen_ticks = 0
            return False
        previous = self._last_picture
        self._frozen_ticks = self._frozen_ticks + 1 if signature == previous else 0
        self._last_picture = signature
        if previous is not None and signature != previous:
            self.pictureActivity.emit()
            if self.state == "frozen":
                self._set_state("playing")
        return self._frozen_ticks >= self._picture_limit

    def _check_picture_tick(self) -> None:
        if self._released or self._media is None:
            return
        if not self.video_widget.isVisible() or self.video_widget.window().isMinimized():
            self._check_picture(False)
            return
        playing = not self.paused and not self._prop("paused-for-cache", False)
        if self._check_picture(playing) and not self._recover_decoder(frozen=True):
            self._set_state("frozen")

    def _set_state(self, state: str) -> None:
        if state != self.state:
            self.state = state
            self.stateChanged.emit(state)

    def _check(self) -> None:
        if self.paused or self._released or self._media is None:
            return
        if self._hls_proxy is not None and self._hls_proxy.refresh_required.is_set():
            self._set_state("error")
            return
        if self._recover_decoder():
            return
        current = self._prop("time-pos")
        advanced = current is not None and (self._last_time is None or current > self._last_time)
        self._last_time = current
        ended = self._prop("eof-reached", False) or self._prop("idle-active", False)
        if advanced and not ended and self._prop("vo-configured", False):
            self._stall_ticks = 0
            if self.state != "frozen":
                self._set_state("playing")
            return
        self._stall_ticks += 2 if ended else 1
        if self._stall_ticks >= self._buffer_limit:
            self._set_state("error")
        elif self._stall_ticks >= 2:
            self._set_state("buffering")
