"""VLC 播放封装：共享一个 libvlc 实例，每个格子一个 media_player。"""
import ctypes
import sys
import threading

import vlc
from PySide6.QtCore import QObject, QTimer, Signal

from .audio_output import StereoOutput, vlc_channel_for

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
REFERRER = "https://live.bilibili.com/"
APP_UA = ("Mozilla/5.0 BiliDroid/6.25.0 (bbcallen@gmail.com) os/android model/MuMu "
          "mobi_app/android build/6250300 channel/bili innerVer/6250300 osVer/6.0.1 network/2")

#: 硬件解码开关（设置里可关）：关掉时给每个 media 加这一条，改用软解。
HW_DECODE_OFF_OPTION = ":avcodec-hw=none"


class PlayerPool:
    """整个程序共用一个 libvlc 实例（比每格一个实例省内存）。

    关注列表的悬停预览另用一个**结构性静音**的实例，见 ``preview_instance()``。
    """

    _instance: vlc.Instance | None = None
    _preview: vlc.Instance | None = None
    _lock = threading.Lock()

    @classmethod
    def instance(cls) -> vlc.Instance:
        with cls._lock:                     # 预热线程和主线程可能同时进来
            if cls._instance is None:
                cls._instance = vlc.Instance(
                    "--no-video-title-show", "--quiet",
                    "--no-snapshot-preview", "--avcodec-hw=any")
                _silence_libvlc(cls._instance)
            return cls._instance

    @classmethod
    def preview_instance(cls) -> vlc.Instance:
        """悬停预览专用的 libvlc 实例：**让预览不可能出声**。

        预览在代码里本来就是 muted=True / volume=0，媒体上还带了 ``:no-audio``，
        但用户那边（Windows 26200 + NVIDIA 616.64，音频模块 mmdevice）仍然听得到
        声音。与其继续猜「哪一步没生效」，不如另开一个实例，从根上堵死：

            --aout=adummy      音频输出走 dummy 模块，解出来的声音直接丢掉
            --no-audio         连音频输出都不建
            --avcodec-hw=none  也不抢显卡解码器（预览才两百来像素宽，软解足够）

        顺带把预览和画面墙那一路彻底隔离：一边出问题不会牵连另一边。
        """
        with cls._lock:
            if cls._preview is None:
                cls._preview = vlc.Instance(
                    "--no-video-title-show", "--quiet", "--no-snapshot-preview",
                    "--aout=adummy", "--no-audio", "--avcodec-hw=none")
                _silence_libvlc(cls._preview)
            return cls._preview

    @classmethod
    def warm_up_async(cls, preview: bool = True) -> threading.Thread:
        """后台先把 libvlc 建出来，别等第一次播放才建。

        用户机器上的看门狗日志显示 ``libvlc_new()`` 在主线程里卡了 4.5 秒
        （第一次运行要扫 200 多个 VLC 插件，加上杀软扫刚解压的包），
        那一下整个界面就冻住了。放到后台线程建，启动时就把这段时间错开。

        ``preview``：悬停预览的实例只在设置里开了「悬停预览」时才建，省一点内存。
        """
        def build() -> None:
            cls.instance()
            if preview:
                cls.preview_instance()

        thread = threading.Thread(target=build, name="ddm-vlc-warmup", daemon=True)
        thread.start()
        return thread


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

    @staticmethod
    def warm_up_vlc(preview: bool = True):
        """启动时在后台把 libvlc 建好（见 PlayerPool.warm_up_async）。"""
        return PlayerPool.warm_up_async(preview=preview)

    @staticmethod
    def vlc_version() -> str:
        try:
            version = vlc.libvlc_get_version()
        except Exception:  # noqa: BLE001
            return "?"
        if isinstance(version, bytes):
            return version.decode("utf-8", "replace")
        return str(version)

    def __init__(self, video_widget, parent=None, silent: bool = False):
        super().__init__(parent)
        self.video_widget = video_widget
        self.url = ""
        #: 预览用：结构性静音（自己的 libvlc 实例 + dummy 音频输出），见 PlayerPool
        self.silent = bool(silent)
        self.muted = self.silent
        self.volume = 0 if self.silent else 42
        self.audio_channel = 0
        self.paused = False
        self.state = "idle"
        self._instance = (PlayerPool.preview_instance() if self.silent
                          else PlayerPool.instance())
        self.player = self._instance.media_player_new()
        self._audio_output = StereoOutput()
        self._audio_callbacks_enabled = False
        self._audio_play_cb = None
        self._audio_pause_cb = None
        self._audio_resume_cb = None
        self._audio_flush_cb = None
        self._audio_drain_cb = None
        self.player.video_set_mouse_input(False)
        self.player.video_set_key_input(False)
        self.player.audio_set_volume(self.volume)
        self.player.audio_set_mute(True)
        self._bound = False
        self._bound_hwnd = 0
        #: 这一段流的取流结果（「秒切」时跟着播放器一起搬到别的格子）
        self.stream_url = ""
        self.stream_profile = "web"
        self.stream_headers: dict = {}
        self.actual_quality = 0
        self._stall_ticks = 0
        self._last_time = None
        self._last_picture = None
        self._frozen_ticks = 0
        self.freeze_watch = True          # 画面卡死检测（可在全局设置里关掉）
        self._media = None                # 当前媒体：画面卡死检测要读它的解码计数
        self._released = False
        self._audio_ready = False         # aout 起来之后补过静音/音量没有
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

    def play(self, url: str, profile: str = "web", headers: dict | None = None,
             options=None) -> None:
        """开始播放。

        ``options`` 是额外的 media 选项（例如预览用的 ``:no-audio``）：留在这里
        而不是写死在播放器上，是因为同一路流在画面墙和预览里要的配置不一样。
        """
        if not self._bound:
            self.bind()
        self.paused = False               # 换流后从"播放中"重新开始
        self.url = url
        self._audio_ready = False         # 新的 aout 还没建，起来之后再补静音/音量
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
        for option in options or ():
            media.add_option(str(option))
        self._media = media
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
        self._media = None              # 画面卡死检测别再碰这个媒体
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
    @property
    def uses_pcm_routing(self) -> bool:
        return self._audio_callbacks_enabled

    def needs_audio_restart(self, channel: int) -> bool:
        """Switching between native VLC output and PCM routing needs a new player."""
        routed = int(channel) in (3, 4)
        return routed != self._audio_callbacks_enabled

    def _enable_pcm_routing(self) -> None:
        """Install callbacks before playback; default audio keeps VLC's native output."""
        if self._audio_callbacks_enabled:
            return
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
        self._audio_callbacks_enabled = True

    def set_muted(self, muted: bool) -> None:
        self.muted = muted
        self.player.audio_set_mute(muted)
        self._audio_output.set_enabled(self.uses_pcm_routing and not muted)

    def set_volume(self, volume: int) -> None:
        self.volume = volume
        self.player.audio_set_volume(volume)
        self._audio_output.set_volume(volume)

    def set_audio_channel(self, channel: int) -> None:
        """声道模式：3/4 将完整声音混为单声道后只送左/右输出。

        VLC 3 的“左/右”模式只是挑选片源中的一条轨道，并会以居中的
        单声道输出。这里让 VLC 保持立体声，再在解码回调中完成真正的
        左右定位；其他 VLC 原生模式仍交给 VLC。
        """
        self.audio_channel = int(channel)
        if self.audio_channel in (3, 4) and not self.uses_pcm_routing:
            self._enable_pcm_routing()
        self._audio_output.set_channel(self.audio_channel)
        self.player.audio_set_channel(vlc_channel_for(self.audio_channel))

    def reapply_audio_channel(self) -> None:
        """播放起来之后再补一次声道设置（音频输出模块初始化会重置它）。"""
        channel = vlc_channel_for(self.audio_channel)
        if channel:
            self.player.audio_set_channel(channel)

    def _ensure_audio_settings(self) -> None:
        """音频输出模块起来之后，补一次静音 / 音量。

        VLC 的 aout 是**真正开始播放时**才建的：在那之前设的静音、音量会被
        这次初始化冲掉。关注列表的悬停预览复用一个播放器反复 stop / play，
        第二次起 VLC 那边的音量就弹回构造时的 42（Python 这边明明记着 0），
        用户听到的就是「预览会出声」。用音轨数判断 aout 起来没有，每次播放只补一次。

        预览（``silent``）再补一刀：直接把音频轨关掉，并且把实际状态写进日志 ——
        用户那边「预览还有声音」一直没能复现，日志里留下这一行才好对齐。
        """
        if self._audio_ready:
            return
        try:
            if self.player.audio_get_track_count() <= 0:
                return                      # aout 还没起来
        except Exception:  # noqa: BLE001
            return
        self._audio_ready = True
        try:
            if self.silent:
                self.player.audio_set_track(-1)      # 干脆不要音频轨
            self.player.audio_set_mute(True if self.silent else self.muted)
            self.player.audio_set_volume(self.volume)
        except Exception:  # noqa: BLE001
            pass
        self._audio_output.set_volume(self.volume)
        self._audio_output.set_enabled(self.uses_pcm_routing and not self.muted)
        if self.silent:
            self._log_audio_state()

    def _log_audio_state(self) -> None:
        """预览的音频自检：把 VLC 侧真实读数写进日志（-1 = 没有音频输出）。"""
        try:
            print(f"[预览音频] mute={self.player.audio_get_mute()}"
                  f" volume={self.player.audio_get_volume()}"
                  f" 音轨数={self.player.audio_get_track_count()}"
                  f" 当前轨={self.player.audio_get_track()}",
                  file=sys.stderr, flush=True)
        except Exception:  # noqa: BLE001
            pass

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
        """抓一个「画面有没有在动」的指纹。

        VLC 有时状态还是 Playing、时钟也在走，画面其实已经不动了，只靠时间判断
        不出来，所以要另看一个信号。

        以前是 `video_take_snapshot` 写一张 PNG 再比文件内容 —— 那是重活，而且
        **用户机器上正好崩在它里面**：看门狗日志显示主线程卡在 _picture_signature
        7.1 秒，同时一次 access violation（把「硬件解码」关掉改用软解也照样崩）。
        现在改成读 VLC 自己的解码计数：画面不动时 decoded_video /
        displayed_pictures 就不再涨（实测暂停后两者定格），效果一样，
        但不用截图、不用写临时文件，也就没有那个崩溃面。
        """
        media = self._media
        if media is None:
            return None
        stats = vlc.MediaStats()
        try:
            if vlc.libvlc_media_get_stats(media, ctypes.byref(stats)) != 1:
                return None
        except Exception:  # noqa: BLE001
            return None
        return (int(stats.decoded_video), int(stats.displayed_pictures))

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
        self._ensure_audio_settings()       # aout 起来了就把静音/音量补回去
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
