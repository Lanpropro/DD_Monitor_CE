"""每格独立的 FFmpeg 录制和即时回放；不接管 VLC 播放器。"""
from __future__ import annotations

import ctypes
import math
import os
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import Future
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal

from . import config
from .encoders import (
    gop_args,
    resolve_encoder,
    resolve_encoder_async,
    segment_extension,
    segment_format,
)

SEGMENT_SECONDS = 10
CHECK_MS = 2000

#: 纯缓存的会话多久裁一次分段。ffmpeg 每 SEGMENT_SECONDS 秒落一个文件，
#: 30 秒能攒下 3 个，来得及；再密就是白扫目录（`_prune_cache` 要 glob 整个
#: `.ddm-parts`，分段一多那一趟并不便宜）。
PRUNE_SECONDS = 30

#: FFmpeg 子进程的创建标志（Windows）。
#:   CREATE_NO_WINDOW          —— 别弹控制台窗口
#:   BELOW_NORMAL_PRIORITY_CLASS —— **把录制的优先级压到「低于正常」**：
#:        录制是后台活，用户在打游戏时它不该跟游戏抢 CPU。压一级之后 Windows 会
#:        优先满足前台进程，录制慢一点无所谓（-c copy 下本身几乎不吃 CPU，
#:        真正会抢的是磁盘 IO 和网络，优先级能让调度偏向游戏）。
#: 进程起来之后还会再调一次 `_adopt_process()`：把 CPU 和**磁盘 IO** 一起压到
#: 更低的后台模式，并挂进 Job Object 兜住孤儿进程。
_FFMPEG_FLAGS = 0
if os.name == "nt":                                    # pragma: no cover - 平台分支
    _FFMPEG_FLAGS = subprocess.CREATE_NO_WINDOW | 0x00004000

# --------------------------------------------------------------- Windows 后台化
#
# `BELOW_NORMAL_PRIORITY_CLASS` 只压 CPU；磁盘 IO 优先级还是「正常」，录制写盘
# 照样和前台程序平起平坐。`PROCESS_MODE_BACKGROUND_BEGIN`（后台模式）会把 CPU
# 和 IO 优先级一起降到最低，正是「别影响我打游戏」要的效果。
# 它不能和别的优先级类一起作为**创建标志**传给 CreateProcess，所以在进程起来
# 之后再单独设。

_PROCESS_MODE_BACKGROUND_BEGIN = 0x00100000
_PROCESS_SET_INFORMATION = 0x0200
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_TERMINATE = 0x0001
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9

_kernel32 = None
_job_handle = None
if os.name == "nt":                                    # pragma: no cover - 平台分支
    try:
        _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        # 64 位下句柄是 64 位；不声明 restype，ctypes 会按 int32 截断，句柄就废了。
        _kernel32.CreateJobObjectW.restype = ctypes.c_void_p
        _kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
        _kernel32.SetInformationJobObject.restype = ctypes.c_int
        _kernel32.SetInformationJobObject.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint32]
        _kernel32.OpenProcess.restype = ctypes.c_void_p
        _kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        _kernel32.AssignProcessToJobObject.restype = ctypes.c_int
        _kernel32.AssignProcessToJobObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        _kernel32.SetPriorityClass.restype = ctypes.c_int
        _kernel32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        _kernel32.CloseHandle.restype = ctypes.c_int
        _kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    except OSError:                                    # pragma: no cover
        _kernel32 = None


class _BasicLimitInformation(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", ctypes.c_uint32),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", ctypes.c_uint32),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", ctypes.c_uint32),
                ("SchedulingClass", ctypes.c_uint32)]


class _IoCounters(ctypes.Structure):
    _fields_ = [("ReadOperationCount", ctypes.c_uint64),
                ("WriteOperationCount", ctypes.c_uint64),
                ("OtherOperationCount", ctypes.c_uint64),
                ("ReadTransferCount", ctypes.c_uint64),
                ("WriteTransferCount", ctypes.c_uint64),
                ("OtherTransferCount", ctypes.c_uint64)]


class _ExtendedLimitInformation(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", _BasicLimitInformation),
                ("IoInfo", _IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t)]


def _ensure_job():
    """建一个「句柄一关就杀光里面进程」的 Job Object，并一直持有句柄。

    句柄**故意不关**：主进程无论怎么退出（正常关闭、崩溃、被任务管理器强杀），
    Windows 都会关掉这个句柄，内核随即杀掉 Job 里剩下的 ffmpeg。没有这层兜底时，
    主进程被强杀就会留下孤儿 ffmpeg 继续录 —— 用户实测过「软件已经关了，后台
    还在录，一路攒到 4.3 GB」。
    """
    global _job_handle
    if _job_handle is not None or _kernel32 is None:
        return _job_handle
    try:
        job = _kernel32.CreateJobObjectW(None, None)
        if not job:
            return None
        info = _ExtendedLimitInformation()
        info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        ok = _kernel32.SetInformationJobObject(
            ctypes.c_void_p(job), _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(info), ctypes.sizeof(info))
        if not ok:
            _kernel32.CloseHandle(ctypes.c_void_p(job))
            return None
        _job_handle = job
    except OSError:                                    # pragma: no cover
        return None
    return _job_handle


def _adopt_process(process: subprocess.Popen) -> None:
    """把刚起来的 ffmpeg 收进 Job，并把它的 CPU / IO 优先级压到「后台」。

    全是尽力而为：收不进 Job（例如本进程已经在一个不允许嵌套的 Job 里）不影响
    录制，只是少了退出时的兜底。
    """
    if _kernel32 is None:
        return
    access = _PROCESS_SET_INFORMATION | _PROCESS_SET_QUOTA | _PROCESS_TERMINATE
    raw = _kernel32.OpenProcess(access, False, process.pid)
    if not raw:
        return
    handle = ctypes.c_void_p(raw)
    try:
        _kernel32.SetPriorityClass(handle, _PROCESS_MODE_BACKGROUND_BEGIN)
        job = _ensure_job()
        if job:
            _kernel32.AssignProcessToJobObject(ctypes.c_void_p(job), handle)
    except OSError:                                    # pragma: no cover
        pass
    finally:
        _kernel32.CloseHandle(handle)


def ffmpeg_path(settings: dict | None = None) -> str:
    """发布包优先用自带的 FFmpeg；源码运行可从 PATH 找。"""
    name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    adjacent = Path(config.REPO) / name
    return str(adjacent) if adjacent.is_file() else (shutil.which(name) or "")


def safe_name(name: str) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    return value[:80] or "直播"


def output_path(folder: Path, name: str, extension: str) -> Path:
    base = (safe_name(name) + "_" + time.strftime("%Y-%m-%d_%H-%M-%S")
            + f"_{time.time_ns() % 1_000_000_000:09d}")
    result = folder / f"{base}.{extension}"
    index = 2
    while result.exists():
        result = folder / f"{base}_{index}.{extension}"
        index += 1
    return result


def input_args(url: str, headers: dict) -> list[str]:
    args = ["-hide_banner", "-loglevel", "warning"]
    if url.lower().startswith(("http://", "https://")):
        # 断流时先让 ffmpeg 自己接回去：URL 还有效的话能自愈，比整段重启便宜
        # —— 重启会新开一个分段文件，也会在「最近 N 分钟」里多一个接缝。
        # URL 过期（B 站流的 expires 到了）时重连也救不回来，那时仍走外层重取流。
        args += ["-reconnect", "1", "-reconnect_streamed", "1",
                 "-reconnect_delay_max", "5"]
    if headers:
        # 取流器传来的 app/web 请求头必须原样使用，不自行补 Referer。
        args += ["-headers", "".join(f"{key}: {value}\r\n"
                                       for key, value in headers.items())]
    return args + ["-i", url]


def segment_extension_for(settings: dict, video_codec: str) -> str:
    """按实际输出编码选择能容纳它的格式。"""
    extension = str(settings.get("recording_format") or "mp4")
    if extension not in ("mkv", "mov", "ts"):
        extension = "mp4"
    output_codec = "avc" if settings.get("recording_codec", "copy") == "h264" else video_codec
    return segment_extension(extension, output_codec)


def segment_args(settings: dict, pattern: Path, video_codec: str = "", *,
                 encoder: tuple[str, list[str], str] | None = None) -> list[str]:
    args = ["-map", "0:v:0", "-map", "0:a?", "-sn", "-dn"]
    if settings.get("recording_codec", "copy") == "h264":
        name, extra, family = encoder if encoder is not None else resolve_encoder(
            settings.get("recording_encoder", "auto"), ffmpeg_path(settings))
        fps = max(1, int(settings.get("recording_fps", 30)))
        bitrate = max(500, int(settings.get("recording_bitrate", 6000)))
        # GOP 参数按编码器族生成：-sc_threshold 是 x264 独有的，塞给硬件编码器
        # 会让 FFmpeg 直接启动失败。
        args += ["-c:v", name, *extra, "-pix_fmt", "yuv420p", "-b:v", f"{bitrate}k",
                 "-r", str(fps), *gop_args(family, fps, SEGMENT_SECONDS),
                 "-c:a", "aac", "-b:a", "160k"]
    else:
        args += ["-c", "copy"]
    fmt = segment_format(segment_extension_for(settings, video_codec))
    return args + ["-f", "segment", "-segment_time", str(SEGMENT_SECONDS),
                   "-reset_timestamps", "1", "-segment_format", fmt, str(pattern)]


class _Session:
    def __init__(self, tile, settings: dict, recording: bool, folder: Path,
                 video_codec: str = ""):
        self.tile = tile
        self.room = dict(tile.room)
        self.settings = dict(settings)
        self.recording = recording
        self.folder = folder
        self.name = str(tile.room.get("uname") or "直播")
        self.room_id = str(tile.room.get("room_id") or "")
        #: 这一路流的视频编码（avc / hevc / av1），由 start() 从格子上取。分段容器
        #: 要靠它挑（AV1 装不进 MOV）；取不到就是空串，而 segment_extension 对认不出
        #: 的编码原样返回，所以老路径行为不变。
        self.video_codec = video_codec
        self.extension = segment_extension_for(settings, self.video_codec)
        self.parts: list[Path] = []
        self.replay_parts: list[Path] = []
        self.process: subprocess.Popen | None = None
        self.active_pattern: Path | None = None
        self.url = ""
        self.chunk = 0
        self.stopping = False
        self.next_url = ""
        self.next_headers: dict = {}
        self.next_video_codec: str | None = None
        self.encoder: tuple[str, list[str], str] | None = None
        self.encoder_future: Future | None = None
        self.log_path: Path | None = None
        self.warned = False
        self.retry_count = 0
        self.retry_at = 0.0
        self.started_at = 0.0
        self.output_started_at = 0.0
        self.rotating = False
        self.pruned_at = 0.0        # 上次裁分段的时间；纯缓存会话用（见 _prune_cache）

    def finished_parts(self) -> list[Path]:
        result = list(self.parts)
        if self.active_pattern is not None:
            current = sorted(self.active_pattern.parent.glob(
                self.active_pattern.name.replace("%05d", "*")))
            # 最后一个分段仍可能在写，不能交给 concat/回放。
            result.extend(current[:-1] if self.process and self.process.poll() is None
                          else current)
        return [path for path in result if path.exists() and path.stat().st_size > 0]

    def close_chunk(self) -> None:
        if self.active_pattern is not None:
            self.parts.extend(sorted(self.active_pattern.parent.glob(
                self.active_pattern.name.replace("%05d", "*"))))
            self.active_pattern = None
        self.process = None


class RecordingManager(QObject):
    """所有操作在 Qt 主线程发起；FFmpeg 子进程各自独立，轮询不阻塞界面。"""

    notice = Signal(str)
    noticeWithRoom = Signal(str, dict)
    changed = Signal(object)

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.sessions: dict[Any, _Session] = {}
        self.exports: list[tuple[subprocess.Popen, Path, list[Path], bool]] = []
        self._export_rooms: dict[Path, dict] = {}
        self._delete_after_exports: set[Path] = set()
        self.timer = QTimer(self)
        self.timer.setInterval(CHECK_MS)
        self.timer.timeout.connect(self._poll)
        self.timer.start()

    def _say(self, message: str, room=None) -> None:
        print(f"[录制] {message}", file=sys.stderr, flush=True)
        self.notice.emit(message)
        self.noticeWithRoom.emit(message, dict(room or {}))

    def _directory(self) -> Path:
        text = str(self.settings.get("recording_dir") or "").strip()
        if not text:
            raise ValueError("请先在「设置 → 录制」选择保存目录")
        folder = Path(text).expanduser().resolve()
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def _free_enough(self, folder: Path) -> bool:
        return shutil.disk_usage(folder).free >= max(
            256, int(self.settings.get("recording_min_free_mb", 2048))) * 1024 * 1024

    def start(self, tile, *, recording: bool) -> bool:
        if recording and not bool(self.settings.get("recording_enabled", True)):
            self._say("录制功能已在「设置 → 录制」里关闭")
            return False
        if not tile.room.get("live") or not tile.room.get("room_id") or not tile.isVisible():
            self._say("只能录制正在显示的直播格子")
            return False
        if tile in self.sessions:
            if self.sessions[tile].stopping:
                self._say("上一段正在结束，请稍后再开始")
                return False
            session = self.sessions[tile]
            if recording and not session.recording:
                session.recording = True
                session.output_started_at = time.monotonic()
                self.changed.emit(tile)
            return True
        if not str(self.settings.get("recording_dir") or "").strip():
            self._say("请先在「设置 → 录制」选择保存目录")
            return False
        executable = ffmpeg_path(self.settings)
        if not executable:
            self._say("找不到 FFmpeg；请检查发布包中的 ffmpeg.exe")
            return False
        if not getattr(tile, "stream_url", ""):
            self._say("这一格仍在连接中，请等画面出现后重试")
            return False
        try:
            folder = self._directory()
            if not self._free_enough(folder):
                self._say("录制未开始：保存目录所在磁盘剩余空间不足")
                return False
            # 取不到 stream_codec 的老格子（或插件造的假格子）按空串处理：
            # segment_extension 认不出编码就原样返回，行为跟改动前一致。
            session = _Session(tile, self.settings, recording, folder,
                               str(getattr(tile, "stream_codec", "") or ""))
            self.sessions[tile] = session
            self._launch(session, tile.stream_url, dict(tile.stream_headers or {}))
            self.changed.emit(tile)
            self._say(f"{session.name} {'开始录制' if recording else '开启即时回放缓存'}", session.room)
            return True
        except (OSError, ValueError) as error:
            self.sessions.pop(tile, None)
            self._say(f"录制启动失败：{error}")
            return False

    def _launch(self, session: _Session, url: str, headers: dict) -> None:
        if session.settings.get("recording_codec", "copy") == "h264" and session.encoder is None:
            if session.encoder_future is None:
                session.encoder_future = resolve_encoder_async(
                    session.settings.get("recording_encoder", "auto"), ffmpeg_path(session.settings))
            if not session.encoder_future.done():
                return
            session.encoder = session.encoder_future.result()
            session.encoder_future = None
        session.chunk += 1
        parts_dir = session.folder / ".ddm-parts"
        parts_dir.mkdir(parents=True, exist_ok=True)
        # 同一时刻不同格子/重启均不会共用文件名；文件名不含房间号。
        nonce = f"{time.time_ns()}_{session.chunk}"
        pattern = parts_dir / f"{safe_name(session.name)}_{nonce}_%05d.{session.extension}"
        command = [ffmpeg_path(session.settings), "-y"] + input_args(url, headers)
        command += segment_args(session.settings, pattern, session.video_codec,
                                encoder=session.encoder)
        log_path = parts_dir / f"{safe_name(session.name)}_{nonce}.log"
        session.log_path = log_path
        with log_path.open("wb") as log:
            session.process = subprocess.Popen(command, stdin=subprocess.PIPE,
                                               stdout=subprocess.DEVNULL, stderr=log,
                                               creationflags=_FFMPEG_FLAGS)
        _adopt_process(session.process)
        session.active_pattern = pattern
        session.url = url
        session.retry_at = 0.0
        session.started_at = time.monotonic()
        if session.recording and not session.output_started_at:
            session.output_started_at = session.started_at

    @staticmethod
    def _end_process(session: _Session) -> None:
        process = session.process
        if process and process.poll() is None and process.stdin:
            try:
                process.stdin.write(b"q\n")
                process.stdin.flush()
            except OSError:
                pass

    def stop(self, tile) -> None:
        session = self.sessions.get(tile)
        if session is None or session.stopping:
            return
        session.stopping = True
        self._end_process(session)
        self.changed.emit(tile)
        if session.process is None:
            self._finalize(session)

    def _finalize(self, session: _Session, *, save_replay: bool = True) -> None:
        self.sessions.pop(session.tile, None)
        self.changed.emit(session.tile)
        if session.recording:
            parts = session.finished_parts()
            # 用户要求：手动结束录制时，顺手把「最近 N 分钟」的即时回放也存一份。
            # 两份导出用同一批分段 —— _cleanup_parts() 会把「仍在导出队列里」的分段
            # 排除在删除之外，所以先启动的那份不会被后完成的那份删掉源文件。
            # 设置里关了即时回放总开关就不存那一份（完整录制照常导出）；
            # 这里读 manager 的 settings（与 app 同一个 dict），开关是实时的。
            if save_replay and bool(self.settings.get("recording_replay_enabled", True)):
                self._export_replay(session, session.replay_parts + parts)
            self._export(session, parts, full=True)
        else:
            self._discard_cache(session)

    def _export_replay(self, session: _Session, parts: list[Path]) -> None:
        """单独存一份「最近 N 分钟」（即时回放），完整录制照旧另外导出。"""
        if not parts:
            return
        count = math.ceil(max(1, int(session.settings.get("recording_replay_minutes", 3)))
                          * 60 / SEGMENT_SECONDS)
        recent = parts[-count:]
        if recent:
            self._export(session, recent, full=False)

    def on_resolved(self, tile) -> None:
        session = self.sessions.get(tile)
        if session is None or session.stopping:
            return
        if str(tile.room.get("room_id") or "") != session.room_id:
            self.stop(tile)
            return
        codec = str(getattr(tile, "stream_codec", "") or "")
        if session.process is None:
            try:
                self._change_codec(session, codec)
                self._launch(session, tile.stream_url, dict(tile.stream_headers or {}))
                self._say(f"{session.name} 取到新流，继续录制", session.room)
            except OSError as error:
                self._say(f"{session.name} 续录失败：{error}", session.room)
                self.stop(tile)
        elif session.next_url or tile.stream_url != session.url or codec != session.video_codec:
            session.next_url = tile.stream_url
            session.next_headers = dict(tile.stream_headers or {})
            session.next_video_codec = codec
            self._end_process(session)

    def _change_codec(self, session: _Session, codec: str) -> None:
        if codec == session.video_codec:
            return
        if session.settings.get("recording_codec", "copy") == "copy":
            parts = session.finished_parts()
            if session.recording and parts:
                self._export(session, parts, full=True)
                self._say(f"{session.name} 的直播编码已改变，后续录制保存为另一个文件", session.room)
            elif not session.recording:
                self._discard_cache(session)
            session.parts.clear()
            session.replay_parts.clear()
            session.output_started_at = 0.0
            self._cleanup_parts()
        session.video_codec = codec
        session.extension = segment_extension_for(session.settings, codec)

    def _fallback_encoder(self, session: _Session) -> bool:
        if session.encoder is None or session.encoder[2] == "cpu" or session.log_path is None:
            return False
        try:
            with session.log_path.open("rb") as log:
                log.seek(max(0, session.log_path.stat().st_size - 65536))
                detail = log.read().decode("utf-8", "replace").lower()
        except OSError:
            return False
        failures = ("error while opening encoder", "could not open encoder",
                    "openencodesessionex failed", "no capable devices found",
                    "unknown encoder", "device lost", "device removed")
        if not any(message in detail for message in failures):
            return False
        if "nothing was written into output file" in detail:
            prefix = session.log_path.stem + "_"
            session.parts = [path for path in session.parts
                             if path.parent != session.log_path.parent or not path.name.startswith(prefix)]
        session.encoder = resolve_encoder("cpu", ffmpeg_path(session.settings))
        self._say(f"{session.name} 硬件编码失败，改用 CPU 继续录制", session.room)
        return True

    def _poll(self) -> None:
        for tile, session in list(self.sessions.items()):
            process = session.process
            if process is None:
                if ((session.encoder_future is not None and session.encoder_future.done())
                        or session.retry_at and time.monotonic() >= session.retry_at):
                    try:
                        self._launch(session, tile.stream_url,
                                     dict(tile.stream_headers or {}))
                        self._say(f"{session.name} 重新连接录制流", session.room)
                    except OSError as error:
                        self._say(f"{session.name} 续录失败：{error}", session.room)
                        self.stop(tile)
                continue
            if process.poll() is None:
                now = time.monotonic()
                if now - session.started_at > 30:
                    session.retry_count = 0
                if not session.stopping:
                    self._check_space(session)
                    if not session.stopping and session.recording:
                        minutes = max(1, int(
                            session.settings.get("recording_segment_minutes", 60)))
                        if (not session.rotating and session.output_started_at and
                                now - session.output_started_at >= minutes * 60):
                            session.rotating = True
                            self._say(f"{session.name} 已录制 {minutes} 分钟，正在保存分段")
                            self._end_process(session)
                    elif not session.stopping:
                        # 纯缓存的会话要**边录边裁**。以前只在 ffmpeg 退出后才裁一次，
                        # 而直播一开几小时进程根本不退，分段就一路堆 —— 用户实测
                        # 单格堆到 223 段、整个目录 4.3 GB 才被发现。
                        self._prune_cache(session)
                continue
            exit_code = process.returncode
            session.close_chunk()
            if session.stopping:
                self._finalize(session)
            elif session.rotating:
                parts = list(session.parts)
                if parts:
                    self._export(session, parts, full=True)
                    if bool(self.settings.get("recording_replay_enabled", True)):
                        session.replay_parts.extend(parts)
                        self._prune_recording_replay(session)
                    else:
                        session.replay_parts.clear()
                session.parts.clear()
                session.rotating = False
                session.output_started_at = 0.0
                url = session.next_url or tile.stream_url or session.url
                headers = (session.next_headers if session.next_url
                           else dict(tile.stream_headers or {}))
                codec = session.next_video_codec
                session.next_url = ""
                session.next_headers = {}
                session.next_video_codec = None
                try:
                    if codec is not None:
                        self._change_codec(session, codec)
                    self._launch(session, url, headers)
                    self._say(f"{session.name} 分段已保存，继续录制")
                except OSError as error:
                    self._say(f"{session.name} 续录失败：{error}")
                    self.stop(tile)
            elif session.next_url:
                url = session.next_url or session.url
                headers = session.next_headers or dict(tile.stream_headers or {})
                codec = session.next_video_codec
                session.next_url = ""
                session.next_headers = {}
                session.next_video_codec = None
                try:
                    if codec is not None:
                        self._change_codec(session, codec)
                    self._launch(session, url, headers)
                except OSError as error:
                    self._say(f"{session.name} 续录失败：{error}", session.room)
                    self.stop(tile)
            elif exit_code:
                if self._fallback_encoder(session):
                    try:
                        self._launch(session, tile.stream_url, dict(tile.stream_headers or {}))
                    except OSError as error:
                        self._say(f"{session.name} CPU 续录失败：{error}", session.room)
                        self.stop(tile)
                    continue
                self._say(f"{session.name} 的 FFmpeg 意外退出（{exit_code}）；详见 .ddm-parts 日志", session.room)
                if not self._free_enough(session.folder):
                    self._stop_for_space(session)
                else:
                    session.retry_count += 1
                    session.retry_at = time.monotonic() + min(60, 2 ** session.retry_count)
                    self._say(f"{session.name} 等待 {int(session.retry_at - time.monotonic()) + 1} 秒续录", session.room)
            else:
                self.stop(tile)
            if not session.recording and not session.stopping:
                self._prune_cache(session)
        for export in list(self.exports):
            process, result, parts, full = export
            if process.poll() is None:
                continue
            self.exports.remove(export)
            room = self._export_rooms.pop(result, {})
            if process.returncode == 0 and result.exists():
                self._say(f"已保存{'录制' if full else '即时回放'}：{result}", room)
                result.with_suffix(".concat.txt").unlink(missing_ok=True)
                if full:
                    self._delete_after_exports.update(parts)
            else:
                self._say(f"导出失败；原始分段仍保留在 .ddm-parts：{result.parent}", room)
                self._delete_after_exports.difference_update(parts)
        self._cleanup_parts()

    def _cleanup_parts(self) -> None:
        protected = {part for _process, _result, parts, _full in self.exports
                     for part in parts}
        protected.update(part for session in self.sessions.values()
                         for part in session.replay_parts)
        for part in self._delete_after_exports - protected:
            part.unlink(missing_ok=True)
            self._delete_after_exports.discard(part)

    def _check_space(self, session: _Session) -> None:
        try:
            if not self._free_enough(session.folder):
                self._stop_for_space(session)
        except OSError as error:
            self._say(f"磁盘检查失败：{error}")

    def _stop_for_space(self, session: _Session) -> None:
        self._say(f"{session.name} 磁盘空间不足，录制已停止；已写入分段保留待恢复", session.room)
        self.stop(session.tile)

    def _prune_cache(self, session: _Session) -> None:
        """把纯缓存会话的分段裁到「最近 N 分钟」。

        节流到每 PRUNE_SECONDS 秒一趟：`finished_parts()` 要 glob 整个
        `.ddm-parts` 目录，跟着 2 秒一轮的巡检每次都扫反而变成新的开销。
        被跳过的那些轮次不影响正确性 —— 会话结束时 `_finalize()` 要么
        `_discard_cache()` 全清、要么 `_export()` 按需取样，都不看目录里的存量。
        """
        now = time.monotonic()
        if now - session.pruned_at < PRUNE_SECONDS:
            return
        session.pruned_at = now
        completed = session.finished_parts()
        keep = math.ceil(max(1, int(session.settings.get("recording_replay_minutes", 3)))
                         * 60 / SEGMENT_SECONDS) + 2
        protected = {part for _process, _result, parts, _full in self.exports
                     for part in parts}
        for part in completed[:-keep]:
            if part in protected:
                continue
            part.unlink(missing_ok=True)
            if part in session.parts:
                session.parts.remove(part)

    def _discard_cache(self, session: _Session) -> None:
        self._delete_after_exports.update(session.finished_parts())
        self._cleanup_parts()

    def _prune_recording_replay(self, session: _Session) -> None:
        keep = math.ceil(max(1, int(session.settings.get("recording_replay_minutes", 3)))
                         * 60 / SEGMENT_SECONDS) + 2
        session.replay_parts = session.replay_parts[-keep:]
        self._cleanup_parts()

    def save_replay(self, tile) -> bool:
        if not bool(self.settings.get("recording_replay_enabled", True)):
            self._say("即时回放已在「设置 → 录制」里关闭")
            return False
        session = self.sessions.get(tile)
        if session is None:
            self._say("请先开启录制或即时回放缓存")
            return False
        count = math.ceil(max(1, int(session.settings.get("recording_replay_minutes", 3)))
                          * 60 / SEGMENT_SECONDS)
        parts = (session.replay_parts + session.finished_parts())[-count:]
        if not parts:
            self._say("缓存还没有完成一个分段，请稍后再保存")
            return False
        return self._export(session, parts, full=False)

    def _export(self, session: _Session, parts: list[Path], *, full: bool) -> bool:
        if not parts:
            self._say(f"{session.name} 没有可导出的录制分段", session.room)
            return False
        try:
            primary = session.folder  # 当前录制固定使用启动时选定的目录
            needed = sum(part.stat().st_size for part in parts)
            reserve = max(256, int(session.settings.get("recording_min_free_mb", 2048)))
            folder = primary if full else primary / "replays"
            folder.mkdir(parents=True, exist_ok=True)
            if shutil.disk_usage(folder).free < needed + reserve * 1024 * 1024:
                self._say("导出空间不足；原始分段保留，清理磁盘后可手动恢复")
                return False
            result = output_path(folder, session.name + ("_回放" if not full else ""),
                                 session.extension)
            playlist = result.with_suffix(".concat.txt")
            playlist.write_text("".join("file '" + str(p).replace("'", "'\\''") + "'\n"
                                        for p in parts), encoding="utf-8")
            command = [ffmpeg_path(session.settings), "-y", "-hide_banner", "-loglevel",
                       "warning", "-f", "concat", "-safe", "0", "-i", str(playlist),
                       "-c", "copy"]
            if session.extension in ("mp4", "mov"):
                command += ["-movflags", "+faststart"]
            command += [str(result)]
            log = result.with_suffix(".ffmpeg.log")
            with log.open("wb") as handle:
                process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                           stdout=subprocess.DEVNULL, stderr=handle,
                                           creationflags=_FFMPEG_FLAGS)
            _adopt_process(process)         # 导出同样是后台活，别跟游戏抢盘
            self.exports.append((process, result, parts, full))
            self._export_rooms[result] = dict(session.room)
            self._say(f"正在导出{'录制' if full else '即时回放'}：{result}", session.room)
            return True
        except OSError as error:
            self._say(f"导出失败：{error}；原始分段保留", session.room)
            return False

    def shutdown(self) -> None:
        self.timer.stop()
        for session in self.sessions.values():
            self._end_process(session)
        for session in list(self.sessions.values()):
            if session.process:
                try:
                    session.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._say(f"{session.name} 收尾超时；原始分段保留", session.room)
                    session.process.terminate()
                    try:
                        session.process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        session.process.kill()
                        session.process.wait()
            session.close_chunk()
            # 退出只保存完整录制；等待重连时没有进程，也要收尾已有分段。
            # 用户主动发起的回放导出保留在 exports 中，下面照常等待完成。
            self._finalize(session, save_replay=False)
        self.sessions.clear()
        # 导出进程不能在应用退出后悬空；最多等 10 秒，失败时保留原始分段。
        for process, _result, _parts, _full in self.exports:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
        self._poll()
