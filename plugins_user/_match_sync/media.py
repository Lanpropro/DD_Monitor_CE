"""FFmpeg frame/PCM capture and cancellable platform chat workers."""
from __future__ import annotations

import asyncio
import http.cookies
import subprocess
import threading
import time

from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtGui import QImage

from ddm import bili, danmaku, recording
from ddm.auto_quality import AUTO_QUALITY
from .engine import FPS, Sample, SIGNATURE_BITS, np
from .video import av, VideoHistory, PictureReader, StreamInput

FRAME_TIMEOUT = 8.0


class Events(QObject):
    information = Signal(dict)
    state = Signal(str)
    message = Signal(dict)
    reset = Signal()


def fingerprint(jpeg: bytes, crop=(0.0, 0.0, 1.0, 1.0)) -> tuple[int, float]:
    image = jpeg if isinstance(jpeg, QImage) else QImage.fromData(jpeg)
    if image.isNull():
        return 0, 0
    x, y, width, height = crop
    image = image.copy(round(x * image.width()), round(y * image.height()),
                       max(1, round(width * image.width())),
                       max(1, round(height * image.height())))
    image = image.scaled(17, 17, Qt.IgnoreAspectRatio, Qt.SmoothTransformation).convertToFormat(QImage.Format_Grayscale8)
    pixels = bytes(image.constBits())
    stride = image.bytesPerLine()
    signature = 0
    texture = 0
    for row in range(16):
        for column in range(16):
            pixel = pixels[row * stride + column]
            right = pixels[row * stride + column + 1]
            below = pixels[(row + 1) * stride + column]
            signature = (signature << 1) | (pixel > right)
            signature = (signature << 1) | (pixel > below)
            texture += abs(pixel - right) + abs(pixel - below)
    return signature, texture / SIGNATURE_BITS


def scene_feature(image, crop):
    x, y, width, height = crop
    image = image.copy(round(x * image.width()), round(y * image.height()),
                       max(1, round(width * image.width())), max(1, round(height * image.height())))
    image = image.scaled(16, 16, Qt.IgnoreAspectRatio, Qt.SmoothTransformation).convertToFormat(QImage.Format_Grayscale8)
    pixels = np.frombuffer(image.constBits(), dtype=np.uint8).reshape(16, image.bytesPerLine())[:, :16]
    centre, scale = pixels.mean(), max(8, pixels.std())
    return np.clip(np.rint(128 + (pixels.astype(np.float32) - centre) * 48 / scale), 0, 255).astype(np.uint8).tobytes()


def decode_command(executable: str, url: str, headers: dict, port: int, quality: int = 250,
                   *, hls_retry=False, platform_kind="") -> list[str]:
    inputs = recording.input_args(url, headers)
    if url.lower().startswith(("http://", "https://")):
        # Let the outer retry resolve a fresh address instead of looping on a broken CDN.
        inputs = inputs[:-2] + ["-reconnect", "0", "-rw_timeout",
                               "30000000" if hls_retry else "6000000"] + inputs[-2:]
        if hls_retry:
            inputs = inputs[:-2] + ["-http_persistent", "0", "-http_multiple", "1",
                                   "-seg_max_retry", "3"] + inputs[-2:]
    # Only local fixtures/files need pacing. Throttling real live inputs loses
    # packets when the server delivers a burst (especially Douyu's FLV).
    pacing = [] if url.lower().startswith(("http://", "https://", "rtmp://", "rtmps://")) else ["-readrate", "1"]
    return ([executable, "-nostdin"] + pacing + ["-copyts", "-start_at_zero", "-threads", "2"]
            + inputs
            + ["-map", "0:v:0", "-map", "0:a:0", "-c:v", "copy", "-af",
               "aresample=async=1",
               "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le",
               "-avoid_negative_ts", "make_zero", "-f", "nut", "-flush_packets", "1", "pipe:1"])


class Decoder:
    def __init__(self, room_id: str, seed: dict | None = None, platform=None):
        self.room_id = room_id
        self.seed = seed or {}
        self.platform = platform
        self.fps = 60 if platform is not None and platform.kind == "douyu" else FPS
        self.source_url = ""
        self.source_headers = {}
        self.events = Events()
        self.history = VideoHistory()
        self.pictures = PictureReader()
        self.video_size = (0, 0)
        self.last_frame_received = 0.0
        self.crop = (0.0, 0.0, 1.0, 1.0)
        self.cancelled = threading.Event()
        self.process = None
        self.thread = None
        self.lock = threading.RLock()

    def start(self) -> None:
        self.thread = threading.Thread(target=self._run,
                                       name=f"match-sync-video-{self.room_id}", daemon=True)
        self.thread.start()

    def set_crop(self, crop) -> None:
        with self.lock:
            self.crop = tuple(crop)
        with self.history.lock:
            self.history.samples.clear()
            self.history.details.clear()

    def stop(self) -> None:
        self.cancelled.set()
        self.pictures.stop()
        with self.lock:
            process = self.process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass

    def picture_at(self, timestamp, exact=False):
        frame = self.history.frame_at(timestamp)
        return self.pictures.get(self.history, frame, exact=exact) if frame is not None and not self.cancelled.is_set() else None

    def diagnostics(self):
        with self.history.lock:
            bounds = self.history.bounds()
            stamps = [item[0] for item in self.history.frames]
            gaps = sorted((b - a for a, b in zip(stamps, stamps[1:])), reverse=True)
            recent = [stamp for stamp in stamps if stamps and stamp >= stamps[-1] - 3]
            return {"size": self.video_size, "fps": self.fps,
                    "codec": self.history.codec[0] if self.history.codec else "",
                    "received_packets": self.history.sequence,
                    "received_frames": self.history.received_frames,
                    "largest_frame_gaps": gaps[:3],
                    "recent_received_fps": ((len(recent) - 1) / (recent[-1] - recent[0])) if len(recent) > 1 else 0,
                    "packet_bytes": self.history.byte_size,
                    "buffer_seconds": bounds[1] - bounds[0] if bounds else 0,
                    "picture_decode_ms": self.pictures.decode_ms,
                    "rgb_frames": self.pictures.decoded}

    def _resolve(self, attempt: int) -> tuple[str, dict]:
        if self.cancelled.is_set():
            raise bili.Cancelled()
        if self.seed.get("highest_quality"):
            # The host lists tiers from highest to lowest; IDs are platform-specific.
            options = (self.platform.room_quality_options(self.room_id) if self.platform is not None
                       else bili.room_quality_options(self.room_id))
            if self.cancelled.is_set():
                raise bili.Cancelled()
            self.seed["quality"] = next((int(item["qn"]) for item in options if int(item["qn"]) != AUTO_QUALITY), 10000)
            self.seed.pop("url", None)
            self.events.information.emit({"requested_quality": self.seed["quality"], "quality_options": options})
        # Douyu signed addresses may allow only one consumer; do not reuse the wall's URL.
        reuse_seed = self.platform is None or self.platform.kind != "douyu"
        if attempt == 0 and self.seed.get("url") and reuse_seed:
            self.source_url = self.seed["url"]
            self.source_headers = dict(self.seed.get("headers") or {})
            self.events.information.emit({"uname": self.seed.get("uname") or "未命名主播",
                                          "title": self.seed.get("title") or ""})
            return self.seed["url"], dict(self.seed.get("headers") or {})
        if self.platform is not None:
            info = self.platform.room_info(self.room_id)
            if self.cancelled.is_set():
                raise bili.Cancelled()
            if info:
                self.events.information.emit(info.as_dict())
            result = self.platform.play_url(self.room_id, self.seed.get("quality", 10000))
            if self.cancelled.is_set():
                raise bili.Cancelled()
            url, quality, _channel = result[:3]
            headers = dict(result[3]) if len(result) > 3 else {}
            self.events.information.emit({"actual_quality": quality,
                "quality_options": self.platform.room_quality_options(self.room_id)})
            self.source_url, self.source_headers = url, headers
            return url, headers
        info = bili.room_info(self.room_id)
        if self.cancelled.is_set():
            raise bili.Cancelled()
        if info:
            self.events.information.emit(info)
        url, quality, _profile, headers = bili.play_url(
            self.room_id, self.seed.get("quality", 250), cancelled=self.cancelled.is_set, source_offset=attempt)
        self.events.information.emit({"actual_quality": quality})
        self.source_url, self.source_headers = url, headers
        return url, headers

    def _run(self) -> None:
        if av is None:
            self.events.state.emit("缺少二路视频解码组件 PyAV；请安装新版完整程序或更新 requirements.txt 中的依赖")
            return
        if np is None:
            self.events.state.emit("缺少二路图像比较组件 NumPy；请更新 requirements.txt 中的依赖")
            return
        executable = recording.ffmpeg_path()
        if not executable:
            self.events.state.emit("找不到 FFmpeg：请使用完整发布包，或将 FFmpeg 放入 PATH")
            return
        attempt = 0
        while not self.cancelled.is_set():
            self.events.state.emit("正在取流…" if attempt == 0 else "正在重新连接…")
            try:
                url, headers = self._resolve(attempt)
                if self.cancelled.is_set():
                    return
                if attempt:
                    self.history = VideoHistory()
                    self.events.reset.emit()
                self._capture(executable, url, headers)
            except bili.Cancelled:
                return
            except Exception:
                if not self.cancelled.is_set():
                    self.events.state.emit("连接或解码失败；稍后重试，可停止后重新开始")
            if self.cancelled.wait(min(5, .5 + attempt * .5)):
                break
            attempt += 1

    def _capture(self, executable: str, url: str, headers: dict) -> None:
        process = None
        hls_proxy = None
        finished = threading.Event()
        timed_out = threading.Event()
        last_frame = [time.monotonic()]

        def watch_frames():
            while not finished.wait(.2):
                if self.cancelled.is_set() or process.poll() is not None:
                    return
                refresh = getattr(hls_proxy, "refresh_required", None)
                if (refresh is not None and refresh.is_set() or
                        time.monotonic() - last_frame[0] > FRAME_TIMEOUT):
                    timed_out.set()
                    try:
                        process.terminate()
                    except OSError:
                        pass
                    return

        watchdog = threading.Thread(target=watch_frames,
                                    name=f"match-sync-watchdog-{self.room_id}", daemon=True)
        try:
            if self.platform is not None and self.platform.kind in ("twitch", "youtube"):
                from ddm.global_danmaku import request_proxy
                from ddm.hls_proxy import HlsProxy
                hls_proxy = HlsProxy(url, headers, request_proxy(url))
                url, headers = hls_proxy.url, {}
            process = subprocess.Popen(
                decode_command(executable, url, headers, 0, self.seed.get("quality", 250),
                               hls_retry=hls_proxy is not None,
                               platform_kind=self.platform.kind if self.platform is not None else ""),
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0,
                creationflags=recording._FFMPEG_FLAGS & ~0x00004000)
            recording._adopt_process(process)
            # Playback retains the host's orphan-process job, at normal priority.
            kernel = getattr(recording, "_kernel32", None)
            if kernel is not None:
                handle = kernel.OpenProcess(recording._PROCESS_SET_INFORMATION, False, process.pid)
                if handle:
                    try:
                        kernel.SetPriorityClass(handle, 0x00000020)
                    finally:
                        kernel.CloseHandle(handle)
            with self.lock:
                self.process = process
            if self.cancelled.is_set():
                process.terminate()
                return
            watchdog.start()
            next_sample = 0.0
            next_detail = 0.0
            with av.open(StreamInput(process.stdout), "r", format="nut",
                         options={"probesize": "65536", "analyzeduration": "100000"}) as container:
                stream = container.streams.video[0]
                stream.codec_context.thread_count = 2
                stream.codec_context.thread_type = "SLICE"
                self.history.codec = (stream.codec_context.name, stream.codec_context.extradata)
                rate = stream.average_rate or stream.base_rate or stream.codec_context.framerate
                if rate:
                    self.fps = float(rate)
                for packet in container.demux():
                    if self.cancelled.is_set():
                        break
                    if packet.stream.type == "audio":
                        for frame in packet.decode():
                            if frame.pts is None:
                                continue
                            pts = float(frame.pts * frame.time_base)
                            if self.history.origin is None:
                                # Ignore an old cached video keyframe when anchoring live time.
                                self.history.set_origin(time.monotonic() - pts)
                                self.events.state.emit("取流已连接")
                            pcm = bytes(frame.planes[0])[:frame.samples * 4]
                            self.history.audio.append_at(round(pts * 48000), pcm)
                        continue
                    if packet.size:
                        self.history.append_packet(packet)
                    for frame in packet.decode():
                        if frame.pts is None:
                            continue
                        pts = float(frame.pts * frame.time_base)
                        if abs(pts) > 1e9:
                            continue  # An invalid/missing source timestamp cannot establish time.
                        timestamp = (self.history.origin or 0) + pts
                        self.video_size = (frame.width, frame.height)
                        sample = None
                        if pts + .0001 >= next_detail:
                            while next_detail <= pts + .0001:
                                next_detail += .05
                            with self.lock:
                                crop = self.crop
                            gray = frame.reformat(width=min(640, frame.width), height=min(360, frame.height), format="gray")
                            plane = gray.planes[0]
                            image = QImage(bytes(plane), gray.width, gray.height, plane.line_size, QImage.Format_Grayscale8)
                            signature, texture = fingerprint(image, crop)
                            detail = Sample(timestamp, signature, texture, scene_feature(image, crop))
                            with self.history.lock:
                                self.history.details.append(detail)
                                while self.history.details and timestamp - self.history.details[0].time > self.history.seconds:
                                    self.history.details.popleft()
                            if pts + .0001 >= next_sample:
                                next_sample = pts + .5
                                sample = detail
                        self.history.append(timestamp, pts, sample)
                        last_frame[0] = time.monotonic()
                        self.last_frame_received = last_frame[0]
            if not self.cancelled.is_set():
                refresh = getattr(hls_proxy, "refresh_required", None)
                self.events.state.emit("播放地址已失效，正在重新取流" if refresh is not None and refresh.is_set()
                                       else "画面接收超时，正在重新取流" if timed_out.is_set()
                                       else "直播流已结束或中断，正在重连")
        except Exception:
            if timed_out.is_set() and not self.cancelled.is_set():
                self.events.state.emit("画面接收超时，正在重新取流")
            elif not self.cancelled.is_set():
                raise
        finally:
            finished.set()
            if watchdog.is_alive():
                watchdog.join(1)
            with self.lock:
                self.process = None
            if process is not None:
                if process.poll() is None:
                    process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                process.stdout.close()
            if hls_proxy is not None:
                hls_proxy.stop()


class PlatformChat(QObject):
    """Keep the host platform's QThread alive until it finishes."""

    def __init__(self, room_id, platform, parent):
        super().__init__(parent)
        self.events = Events()
        self.stopped = False
        self.unavailable = "此平台暂不支持弹幕，直播画面与声音可正常播放"
        try:
            self.client = platform.danmaku_client(room_id, self)
        except (ImportError, AttributeError):
            self.client = None
            self.unavailable = "平台弹幕组件不可用，请更新支持多平台弹幕的主程序"
        if self.client is not None:
            self.client.status.connect(self.events.state.emit)
            self.client.message.connect(self.events.message.emit)
            self.client.finished.connect(self._finished)

    def _finished(self):
        client, self.client = self.client, None
        client.deleteLater()
        if self.stopped:
            self.deleteLater()

    def start(self):
        if self.client is None:
            self.events.state.emit(self.unavailable)
        else:
            self.client.start()

    def stop(self):
        self.stopped = True
        if self.client is not None:
            self.client.stop()
            if self.client.isRunning():
                self.client.wait(2000)
        else:
            self.deleteLater()


class Chat:
    """Reuse the host's Bilibili protocol in a plain Python thread, not a QThread."""

    def __init__(self, room_id: str):
        self.room_id = room_id
        self.events = Events()
        self.cancelled = threading.Event()
        self.loop = None
        self.task = None
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self._run,
                                       name=f"match-sync-chat-{self.room_id}", daemon=True)
        self.thread.start()

    def stop(self):
        self.cancelled.set()
        loop, task = self.loop, self.task
        if loop is not None and task is not None and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(task.cancel)
            except RuntimeError:
                pass

    def _run(self):
        if danmaku.blivedm is None:
            self.events.state.emit("弹幕组件不可用")
            return
        while not self.cancelled.is_set():
            try:
                asyncio.run(self._main())
            except asyncio.CancelledError:
                return
            except Exception:
                if not self.cancelled.is_set():
                    self.events.state.emit("弹幕连接失败，正在重试")
            if self.cancelled.wait(2):
                return

    async def _main(self):
        self.loop = asyncio.get_running_loop()
        self.task = asyncio.current_task()
        if self.cancelled.is_set():
            return
        cookies = http.cookies.SimpleCookie()
        if bili.SESSION_DATA:
            cookies["SESSDATA"] = bili.SESSION_DATA
            cookies["SESSDATA"]["domain"] = "bilibili.com"
        self.events.state.emit("弹幕连接中…")
        async with danmaku.aiohttp.ClientSession(
                timeout=danmaku.aiohttp.ClientTimeout(total=None, connect=15)) as session:
            session.cookie_jar.update_cookies(cookies)
            real_id, token, hosts = await asyncio.to_thread(bili.danmaku_conf, self.room_id)
            if self.cancelled.is_set():
                return
            if not hosts:
                self.events.state.emit("无法取得弹幕服务器")
                return
            client = danmaku._Client(real_id or int(self.room_id), session=session,
                                     hosts=hosts, token=token, on_status=self.events.state.emit)
            client.set_handler(danmaku._Handler(self.events.message.emit))
            client.start()
            try:
                await client.join()
            finally:
                await client.stop_and_close()
