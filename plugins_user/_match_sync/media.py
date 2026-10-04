"""FFmpeg frame/PCM capture and cancellable platform chat workers."""
from __future__ import annotations

import asyncio
import http.cookies
import socket
import subprocess
import threading
import time

from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtGui import QImage

from ddm import bili, danmaku, recording
from .engine import FPS, History, Sample


class Events(QObject):
    information = Signal(dict)
    state = Signal(str)
    message = Signal(dict)
    reset = Signal()


def fingerprint(jpeg: bytes, crop=(0.0, 0.0, 1.0, 1.0)) -> tuple[int, float]:
    image = QImage.fromData(jpeg)
    if image.isNull():
        return 0, 0
    x, y, width, height = crop
    image = image.copy(round(x * image.width()), round(y * image.height()),
                       max(1, round(width * image.width())),
                       max(1, round(height * image.height())))
    image = image.scaled(9, 9, Qt.IgnoreAspectRatio, Qt.SmoothTransformation).convertToFormat(QImage.Format_Grayscale8)
    pixels = bytes(image.constBits())
    stride = image.bytesPerLine()
    signature = 0
    texture = 0
    for row in range(8):
        for column in range(8):
            pixel = pixels[row * stride + column]
            right = pixels[row * stride + column + 1]
            below = pixels[(row + 1) * stride + column]
            signature = (signature << 1) | (pixel > right)
            signature = (signature << 1) | (pixel > below)
            texture += abs(pixel - right) + abs(pixel - below)
    return signature, texture / 128


def decode_command(executable: str, url: str, headers: dict, port: int, quality: int = 250) -> list[str]:
    width, height = (1920, 1080) if quality >= 400 else (1280, 720)
    return ([executable, "-nostdin", "-readrate", "1", "-threads", "2"]
            + recording.input_args(url, headers)
            + ["-map", "0:v:0", "-an", "-vf",
               f"setpts=PTS-STARTPTS,fps={FPS},scale=w='min({width},iw)':h='min({height},ih)':force_original_aspect_ratio=decrease:force_divisible_by=2",
               "-threads", "2", "-c:v", "mjpeg", "-q:v", "5",
               "-pix_fmt", "yuvj420p", "-f", "image2pipe", "-flush_packets", "1", "pipe:1",
               "-map", "0:a:0", "-vn", "-af",
               "asetpts=PTS-STARTPTS,aresample=async=1:first_pts=0",
               "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le",
               "-f", "s16le", f"tcp://127.0.0.1:{port}"])


class Decoder:
    def __init__(self, room_id: str, seed: dict | None = None, platform=None):
        self.room_id = room_id
        self.seed = seed or {}
        self.platform = platform
        self.source_url = ""
        self.source_headers = {}
        self.events = Events()
        self.history = History()
        self.crop = (0.0, 0.0, 1.0, 1.0)
        self.cancelled = threading.Event()
        self.process = None
        self.listener = None
        self.connection = None
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

    def stop(self) -> None:
        self.cancelled.set()
        with self.lock:
            process = self.process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass

    def _resolve(self, attempt: int) -> tuple[str, dict]:
        if attempt == 0 and self.seed.get("url"):
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
        url, _quality, _profile, headers = bili.play_url(
            self.room_id, self.seed.get("quality", 250), cancelled=self.cancelled.is_set, source_offset=attempt)
        self.source_url, self.source_headers = url, headers
        return url, headers

    def _run(self) -> None:
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
                    self.history = History()
                    self.events.reset.emit()
                self._capture(executable, url, headers)
            except bili.Cancelled:
                return
            except Exception:
                if not self.cancelled.is_set():
                    self.events.state.emit("连接或解码失败；稍后重试，可停止后重新开始")
            if self.cancelled.wait(min(10, 2 + attempt * 2)):
                break
            attempt += 1

    def _capture(self, executable: str, url: str, headers: dict) -> None:
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(0.2)
        self.listener = listener
        audio_thread = threading.Thread(target=self._read_audio, daemon=True)
        process = None
        try:
            process = subprocess.Popen(
                decode_command(executable, url, headers, listener.getsockname()[1], self.seed.get("quality", 250)),
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0,
                creationflags=recording._FFMPEG_FLAGS)
            recording._adopt_process(process)
            with self.lock:
                self.process = process
            if self.cancelled.is_set():
                process.terminate()
                return
            audio_thread.start()
            pending = bytearray()
            index = 0
            origin = None
            while not self.cancelled.is_set():
                block = process.stdout.read(65536)
                if not block:
                    break
                pending.extend(block)
                while True:
                    start = pending.find(b"\xff\xd8")
                    end = pending.find(b"\xff\xd9", max(0, start + 2))
                    if start < 0 or end < 0:
                        break
                    jpeg = bytes(pending[start:end + 2])
                    del pending[:end + 2]
                    if origin is None:
                        origin = time.monotonic()
                        self.events.state.emit("取流已连接")
                    timestamp = origin + index / FPS
                    sample = None
                    if index % (FPS // 2) == 0:
                        with self.lock:
                            crop = self.crop
                        signature, texture = fingerprint(jpeg, crop)
                        sample = Sample(timestamp, signature, texture)
                    self.history.append(timestamp, jpeg, sample)
                    index += 1
                if len(pending) > 4 * 1024 * 1024:
                    raise ValueError("Invalid JPEG stream")
            if not self.cancelled.is_set():
                self.events.state.emit("直播流已结束或中断，正在重连")
        finally:
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
            listener.close()
            self.listener = None
            connection = self.connection
            if connection is not None:
                try:
                    connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
            if audio_thread.is_alive():
                audio_thread.join(1)

    def _read_audio(self) -> None:
        listener = self.listener
        connection = None
        try:
            while not self.cancelled.is_set():
                try:
                    connection, _address = listener.accept()
                    break
                except socket.timeout:
                    if self.process is None or self.process.poll() is not None:
                        return
            if connection is None:
                return
            self.connection = connection
            connection.settimeout(0.2)
            pending = b""
            while not self.cancelled.is_set():
                try:
                    data = connection.recv(16384)
                except socket.timeout:
                    continue
                if not data:
                    return
                pending += data
                size = len(pending) // 4 * 4
                self.history.audio.append(pending[:size])
                pending = pending[size:]
        except OSError:
            pass
        finally:
            if connection is not None:
                connection.close()
            self.connection = None


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
        try:
            asyncio.run(self._main())
        except asyncio.CancelledError:
            pass
        except Exception:
            if not self.cancelled.is_set():
                self.events.state.emit("弹幕连接失败，可重新开始连接")

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
