"""VLC 播放封装：共享一个 libvlc 实例，每个格子一个 media_player。"""
import hashlib
import os
import tempfile

import vlc
from PySide6.QtCore import QObject, QTimer, Signal

from .audio_output import StereoOutput, vlc_channel_for

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
REFERRER = "https://live.bilibili.com/"
APP_UA = ("Mozilla/5.0 BiliDroid/6.25.0 (bbcallen@gmail.com) os/android model/MuMu "
          "mobi_app/android build/6250300 channel/bili innerVer/6250300 osVer/6.0.1 network/2")


class PlayerPool:
    """整个程序共用一个 libvlc 实例（比每格一个实例省内存）。"""

    _instance: vlc.Instance | None = None

    @classmethod
    def instance(cls) -> vlc.Instance:
        if cls._instance is None:
            cls._instance = vlc.Instance("--no-video-title-show", "--quiet",
                                         "--no-snapshot-preview", "--avcodec-hw=any")
            _silence_libvlc(cls._instance)
        return cls._instance


def _silence_libvlc(instance: vlc.Instance) -> None:
    """接管 libvlc 日志，别让解码器的告警往控制台刷屏。

    没人接日志时，libvlc 会把 ffmpeg 的告警（比如
    "co located POCs unavailable"）直接写到 stderr；接了就不写了。
    """
    def drop(_data, _level, _context):        # noqa: ANN001, ANN202
        return None

    try:
        instance.log_set(drop, None)
    except Exception:                         # noqa: BLE001
        pass


class TilePlayer(QObject):
    """一个格子的播放器：直连 http FLV，带 Referer / UA。"""

    stateChanged = Signal(str)   # idle / connecting / playing / error
    pictureActivity = Signal()   # 截图重新发生变化；用来取消画面静止后的重试

    PICTURE_POLL_MS = 1000
    FROZEN_TICKS = 2             # 连续 2 秒截图不变就认为画面停止更新

    #: 各取流通道该带的请求头。插件解析出来的流地址要自带对应的头，
    #: 否则 CDN 会 403（app 通道不能带 Referer，web 通道必须带）。
    PROFILE_HEADERS = {
        "app": {"User-Agent": APP_UA},
        "web": {"User-Agent": UA, "Referer": REFERRER},
    }

    def __init__(self, video_widget, parent=None):
        super().__init__(parent)
        self.video_widget = video_widget
        self.url = ""
        self.muted = False
        self.volume = 42
        self.audio_channel = 0
        self.paused = False
        self.state = "idle"
        self._instance = PlayerPool.instance()
        self.player = self._instance.media_player_new()
        self._audio_output = StereoOutput()
        callbacks = vlc.CallbackDecorators
        self._audio_play_cb = callbacks.AudioPlayCb(self._play_audio)
        self._audio_pause_cb = callbacks.AudioPauseCb(self._pause_audio)
        self._audio_resume_cb = callbacks.AudioResumeCb(self._resume_audio)
        self._audio_flush_cb = callbacks.AudioFlushCb(self._flush_audio)
        self._audio_drain_cb = callbacks.AudioDrainCb(self._drain_audio)
        self.player.audio_set_callbacks(
            self._audio_play_cb, self._audio_pause_cb, self._audio_resume_cb,
            self._audio_flush_cb, self._audio_drain_cb, None,
        )
        self.player.audio_set_format("S16N", 48_000, 2)
        self.player.video_set_mouse_input(False)
        self.player.video_set_key_input(False)
        self.player.audio_set_volume(self.volume)
        self.player.audio_set_mute(True)
        self._bound = False
        self._bound_hwnd = 0
        self._stall_ticks = 0
        self._last_time = None
        self._last_picture = None
        self._frozen_ticks = 0
        self.freeze_watch = True          # 画面卡死检测（可在全局设置里关掉）
        self._shot_path = os.path.join(tempfile.gettempdir(),
                                       f"ddm_shot_{id(self):x}.png")
        self._released = False
        self._watch = QTimer(self)
        self._watch.setInterval(1500)
        self._watch.timeout.connect(self._check)
        self._picture_watch = QTimer(self)
        self._picture_watch.setInterval(self.PICTURE_POLL_MS)
        self._picture_watch.timeout.connect(self._check_picture_tick)

    # ---- 生命周期 ----
    def bind(self) -> None:
        """把播放器绑定到格子的视频区域。"""
        hwnd = int(self.video_widget.winId())
        if self._bound and self._bound_hwnd == hwnd:
            return
        self.player.set_hwnd(hwnd)
        self._bound = True
        self._bound_hwnd = hwnd

    def invalidate_binding(self) -> None:
        """原生窗口重排前标记绑定失效；排布完成后只重新绑定一次。"""
        self._bound = False

    def play(self, url: str, profile: str = "web", headers: dict | None = None) -> None:
        if not self._bound:
            self.bind()
        self.paused = False               # 换流后从"播放中"重新开始
        self.url = url
        media = self._instance.media_new(url)
        # 插件解析出来的流可以自带请求头；没给就按通道用默认的
        request_headers = dict(headers) if headers else dict(
            self.PROFILE_HEADERS.get(profile, self.PROFILE_HEADERS["web"]))
        for name, value in request_headers.items():
            if not value:
                continue
            if name.lower() == "user-agent":
                media.add_option(f":http-user-agent={value}")
            elif name.lower() == "referer":
                media.add_option(f":http-referrer={value}")
            else:
                media.add_option(f":http-header={name}: {value}")
        if not any(name.lower() == "user-agent" for name in request_headers):
            # 后端一律要 UA，插件忘了给就补上通用的
            media.add_option(f":http-user-agent={UA}")
        media.add_option(":network-caching=800")
        self.player.set_media(media)
        self.player.play()
        self._stall_ticks = 0
        self._last_time = None
        self._last_picture = None
        self._frozen_ticks = 0
        self._set_state("connecting")
        self._watch.start()
        self._picture_watch.start()

    def stop(self) -> None:
        self._watch.stop()
        self._picture_watch.stop()
        self.player.stop()
        self._last_picture = None
        self._frozen_ticks = 0
        self._set_state("idle")

    def release(self) -> None:
        if self._released:              # 关窗流程可能被调用两次，重复释放会让 libvlc 崩
            return
        self._released = True
        self._watch.stop()
        self._picture_watch.stop()
        try:
            self.player.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.player.set_hwnd(0)     # 摘掉画面，格子不会留着最后一帧
        except Exception:  # noqa: BLE001
            pass
        self._bound = False
        self._bound_hwnd = 0
        try:
            self.player.release()
        except Exception:  # noqa: BLE001
            pass
        self._audio_output.close()

    # ---- 音频 ----
    def set_muted(self, muted: bool) -> None:
        self.muted = muted
        self.player.audio_set_mute(muted)
        self._audio_output.set_enabled(not muted)

    def set_volume(self, volume: int) -> None:
        self.volume = volume
        self.player.audio_set_volume(volume)

    def set_audio_channel(self, channel: int) -> None:
        """声道模式：3/4 将完整声音混为单声道后只送左/右输出。

        VLC 3 的“左/右”模式只是挑选片源中的一条轨道，并会以居中的
        单声道输出。这里让 VLC 保持立体声，再在解码回调中完成真正的
        左右定位；其他 VLC 原生模式仍交给 VLC。
        """
        self.audio_channel = int(channel)
        self._audio_output.set_channel(self.audio_channel)
        self.player.audio_set_channel(vlc_channel_for(self.audio_channel))

    def reapply_audio_channel(self) -> None:
        """播放起来之后再补一次声道设置（音频输出模块初始化会重置它）。"""
        channel = vlc_channel_for(self.audio_channel)
        if channel:
            self.player.audio_set_channel(channel)

    def _play_audio(self, _opaque, samples, count, _pts) -> None:
        self._audio_output.write(samples, count)

    def _pause_audio(self, _opaque, _pts) -> None:
        self._audio_output.pause()

    def _resume_audio(self, _opaque, _pts) -> None:
        self._audio_output.resume()

    def _flush_audio(self, _opaque, _pts) -> None:
        self._audio_output.flush()

    def _drain_audio(self, _opaque) -> None:
        self._audio_output.drain()

    def set_paused(self, paused: bool) -> None:
        """暂停 / 继续（不停取流，继续时直接接上）。"""
        self.paused = bool(paused)
        self.player.set_pause(1 if self.paused else 0)
        if self.paused:
            self._picture_watch.stop()
            self._last_picture = None
            self._frozen_ticks = 0
        else:
            self._last_time = None          # 继续后重新计时，避免被误判成卡顿
            self._stall_ticks = 0
            self._last_picture = None
            self._frozen_ticks = 0
            self._watch.start()
            self._picture_watch.start()

    # ---- 画面卡死检测 ----
    def _picture_signature(self):
        """抓一张小图当"指纹"，用来判断画面到底有没有在动。

        VLC 有时状态还是 Playing、时钟也在走，画面其实已经不动了，
        只靠时间判断不出来，所以再比一次画面内容。
        """
        try:
            if self.player.video_take_snapshot(0, self._shot_path, 160, 90) != 0:
                return None
            with open(self._shot_path, "rb") as handle:
                data = handle.read()
        except Exception:  # noqa: BLE001
            return None
        if not data:
            return None
        return (len(data), hashlib.md5(data).hexdigest())

    def _check_picture(self, playing: bool) -> bool:
        """画面是不是停了；返回 True 表示判定为卡住。"""
        if not (self.freeze_watch and playing):
            self._frozen_ticks = 0
            self._last_picture = None
            return False
        signature = self._picture_signature()
        if signature is None:
            return False
        previous = self._last_picture
        if signature == previous:
            self._frozen_ticks += 1
        else:
            self._frozen_ticks = 0
        self._last_picture = signature
        if previous is not None and signature != previous:
            self.pictureActivity.emit()
            if self.state == "frozen":
                self._set_state("playing")
        return self._frozen_ticks >= self.FROZEN_TICKS

    def _check_picture_tick(self) -> None:
        """独立于缓冲检测，每秒检查一次真实画面是否仍在变化。"""
        if self.paused:
            self._check_picture(False)
            return
        state = self.player.get_state()
        width, _ = self.player.video_get_size(0)
        if self._check_picture(state == vlc.State.Playing and bool(width)):
            self._set_state("frozen")

    # ---- 状态 ----
    def _set_state(self, state: str) -> None:
        if state == self.state:
            return
        self.state = state
        self.stateChanged.emit(state)

    def _check(self) -> None:
        if self.paused:
            return                          # 暂停时画面本来就不动，不能当成卡顿
        state = self.player.get_state()
        width, _ = self.player.video_get_size(0)
        current = self.player.get_time()
        advanced = self._last_time is not None and current > self._last_time
        self._last_time = current

        if state == vlc.State.Playing and width and (advanced or self._stall_ticks == 0):
            self._stall_ticks = 0
            if self.state != "frozen":
                self._set_state("playing")
            return
        if state in (vlc.State.Ended, vlc.State.Error, vlc.State.Stopped):
            self._stall_ticks += 2
        else:
            self._stall_ticks += 1
        if self._stall_ticks >= 6:      # 约 9 秒没有画面就判为失败
            self._watch.stop()
            self._set_state("error")
        elif self._stall_ticks >= 2:    # 卡住了：显示缓冲动画，等待恢复
            self._set_state("buffering")
