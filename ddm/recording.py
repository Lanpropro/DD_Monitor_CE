"""每格独立的 FFmpeg 录制和即时回放；不接管 VLC 播放器。"""
from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from . import config

SEGMENT_SECONDS = 10
CHECK_MS = 2000

#: FFmpeg 子进程的创建标志（Windows）。
#:   CREATE_NO_WINDOW          —— 别弹控制台窗口
#:   BELOW_NORMAL_PRIORITY_CLASS —— **把录制的优先级压到「低于正常」**：
#:        录制是后台活，用户在打游戏时它不该跟游戏抢 CPU。压一级之后 Windows 会
#:        优先满足前台进程，录制慢一点无所谓（-c copy 下本身几乎不吃 CPU，
#:        真正会抢的是磁盘 IO 和网络，优先级能让调度偏向游戏）。
_FFMPEG_FLAGS = 0
if os.name == "nt":                                    # pragma: no cover - 平台分支
    _FFMPEG_FLAGS = subprocess.CREATE_NO_WINDOW | 0x00004000


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
    if headers:
        # 取流器传来的 app/web 请求头必须原样使用，不自行补 Referer。
        args += ["-headers", "".join(f"{key}: {value}\r\n"
                                       for key, value in headers.items())]
    return args + ["-i", url]


def segment_args(settings: dict, pattern: Path) -> list[str]:
    args = ["-map", "0:v:0", "-map", "0:a?", "-sn", "-dn"]
    if settings.get("recording_codec", "copy") == "h264":
        fps = max(1, int(settings.get("recording_fps", 30)))
        bitrate = max(500, int(settings.get("recording_bitrate", 6000)))
        args += ["-c:v", "libx264", "-preset", "veryfast", "-b:v", f"{bitrate}k",
                 "-r", str(fps), "-g", str(fps * SEGMENT_SECONDS),
                 "-sc_threshold", "0", "-c:a", "aac", "-b:a", "160k"]
    else:
        args += ["-c", "copy"]
    fmt = {"mkv": "matroska", "mov": "mov", "ts": "mpegts"}.get(
        settings.get("recording_format"), "mp4")
    return args + ["-f", "segment", "-segment_time", str(SEGMENT_SECONDS),
                   "-reset_timestamps", "1", "-segment_format", fmt, str(pattern)]


class _Session:
    def __init__(self, tile, settings: dict, recording: bool, folder: Path):
        self.tile = tile
        self.settings = dict(settings)
        self.recording = recording
        self.folder = folder
        self.name = str(tile.room.get("uname") or "直播")
        self.room_id = str(tile.room.get("room_id") or "")
        self.extension = (settings.get("recording_format") if settings.get("recording_format")
                          in ("mkv", "mov", "ts") else "mp4")
        self.parts: list[Path] = []
        self.process: subprocess.Popen | None = None
        self.active_pattern: Path | None = None
        self.url = ""
        self.chunk = 0
        self.stopping = False
        self.next_url = ""
        self.next_headers: dict = {}
        self.warned = False
        self.retry_count = 0
        self.retry_at = 0.0
        self.started_at = 0.0

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
    changed = Signal(object)

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.sessions: dict[object, _Session] = {}
        self.exports: list[tuple[subprocess.Popen, Path, list[Path], bool]] = []
        self._delete_after_exports: set[Path] = set()
        self.timer = QTimer(self)
        self.timer.setInterval(CHECK_MS)
        self.timer.timeout.connect(self._poll)
        self.timer.start()

    def _say(self, message: str) -> None:
        print(f"[录制] {message}", file=sys.stderr, flush=True)
        self.notice.emit(message)

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
        if not tile.room.get("live") or not tile.room.get("room_id") or not tile.isVisible():
            self._say("只能录制正在显示的直播格子")
            return False
        if tile in self.sessions:
            if self.sessions[tile].stopping:
                self._say("上一段正在结束，请稍后再开始")
                return False
            if recording:
                self.sessions[tile].recording = True
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
            session = _Session(tile, self.settings, recording, folder)
            self.sessions[tile] = session
            self._launch(session, tile.stream_url, dict(tile.stream_headers or {}))
            self.changed.emit(tile)
            self._say(f"{session.name} {'开始录制' if recording else '开启即时回放缓存'}")
            return True
        except (OSError, ValueError) as error:
            self.sessions.pop(tile, None)
            self._say(f"录制启动失败：{error}")
            return False

    def _launch(self, session: _Session, url: str, headers: dict) -> None:
        session.chunk += 1
        parts_dir = session.folder / ".ddm-parts"
        parts_dir.mkdir(parents=True, exist_ok=True)
        # 同一时刻不同格子/重启均不会共用文件名；文件名不含房间号。
        nonce = f"{time.time_ns()}_{session.chunk}"
        pattern = parts_dir / f"{safe_name(session.name)}_{nonce}_%05d.{session.extension}"
        command = [ffmpeg_path(session.settings), "-y"] + input_args(url, headers)
        command += segment_args(session.settings, pattern)
        log_path = parts_dir / f"{safe_name(session.name)}_{nonce}.log"
        with log_path.open("wb") as log:
            session.process = subprocess.Popen(command, stdin=subprocess.PIPE,
                                               stdout=subprocess.DEVNULL, stderr=log,
                                               creationflags=_FFMPEG_FLAGS)
        session.active_pattern = pattern
        session.url = url
        session.retry_at = 0.0
        session.started_at = time.monotonic()

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

    def _finalize(self, session: _Session) -> None:
        self.sessions.pop(session.tile, None)
        self.changed.emit(session.tile)
        if session.recording:
            parts = session.finished_parts()
            # 用户要求：手动结束录制时，顺手把「最近 N 分钟」的即时回放也存一份。
            # 两份导出用同一批分段 —— _cleanup_parts() 会把「仍在导出队列里」的分段
            # 排除在删除之外，所以先启动的那份不会被后完成的那份删掉源文件。
            self._export_replay(session, parts)
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
        elif session.process is None:
            try:
                self._launch(session, tile.stream_url, dict(tile.stream_headers or {}))
                self._say(f"{session.name} 取到新流，继续录制")
            except OSError as error:
                self._say(f"{session.name} 续录失败：{error}")
                self.stop(tile)
        elif tile.stream_url != session.url:
            session.next_url = tile.stream_url
            session.next_headers = dict(tile.stream_headers or {})
            self._end_process(session)

    def _poll(self) -> None:
        for tile, session in list(self.sessions.items()):
            process = session.process
            if process is None:
                if session.retry_at and time.monotonic() >= session.retry_at:
                    try:
                        self._launch(session, tile.stream_url,
                                     dict(tile.stream_headers or {}))
                        self._say(f"{session.name} 重新连接录制流")
                    except OSError as error:
                        self._say(f"{session.name} 续录失败：{error}")
                        self.stop(tile)
                continue
            if process.poll() is None:
                if time.monotonic() - session.started_at > 30:
                    session.retry_count = 0
                if not session.stopping:
                    self._check_space(session)
                continue
            exit_code = process.returncode
            session.close_chunk()
            if session.stopping:
                self._finalize(session)
            elif session.next_url:
                url = session.next_url or session.url
                headers = session.next_headers or dict(tile.stream_headers or {})
                session.next_url = ""
                session.next_headers = {}
                try:
                    self._launch(session, url, headers)
                except OSError as error:
                    self._say(f"{session.name} 续录失败：{error}")
                    self.stop(tile)
            elif exit_code:
                self._say(f"{session.name} 的 FFmpeg 意外退出（{exit_code}）；详见 .ddm-parts 日志")
                if not self._free_enough(session.folder):
                    self._stop_for_space(session)
                else:
                    session.retry_count += 1
                    session.retry_at = time.monotonic() + min(60, 2 ** session.retry_count)
                    self._say(f"{session.name} 等待 {int(session.retry_at - time.monotonic()) + 1} 秒续录")
            else:
                self.stop(tile)
            if not session.recording and not session.stopping:
                self._prune_cache(session)
        for export in list(self.exports):
            process, result, parts, full = export
            if process.poll() is None:
                continue
            self.exports.remove(export)
            if process.returncode == 0 and result.exists():
                self._say(f"已保存{'录制' if full else '即时回放'}：{result}")
                result.with_suffix(".concat.txt").unlink(missing_ok=True)
                if full:
                    self._delete_after_exports.update(parts)
            else:
                self._say(f"导出失败；原始分段仍保留在 .ddm-parts：{result.parent}")
                self._delete_after_exports.difference_update(parts)
        self._cleanup_parts()

    def _cleanup_parts(self) -> None:
        protected = {part for _process, _result, parts, _full in self.exports
                     for part in parts}
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
        self._say(f"{session.name} 磁盘空间不足，录制已停止；已写入分段保留待恢复")
        self.stop(session.tile)

    def _prune_cache(self, session: _Session) -> None:
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

    def save_replay(self, tile) -> bool:
        session = self.sessions.get(tile)
        if session is None:
            self._say("请先开启录制或即时回放缓存")
            return False
        count = math.ceil(max(1, int(session.settings.get("recording_replay_minutes", 3)))
                          * 60 / SEGMENT_SECONDS)
        parts = session.finished_parts()[-count:]
        if not parts:
            self._say("缓存还没有完成一个分段，请稍后再保存")
            return False
        return self._export(session, parts, full=False)

    def _export(self, session: _Session, parts: list[Path], *, full: bool) -> bool:
        if not parts:
            self._say(f"{session.name} 没有可导出的录制分段")
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
            self.exports.append((process, result, parts, full))
            self._say(f"正在导出{'录制' if full else '即时回放'}：{result}")
            return True
        except OSError as error:
            self._say(f"导出失败：{error}；原始分段保留")
            return False

    def shutdown(self) -> None:
        self.timer.stop()
        for session in self.sessions.values():
            self._end_process(session)
        for session in self.sessions.values():
            if session.process:
                try:
                    session.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._say(f"{session.name} 收尾超时；原始分段保留")
                    session.process.terminate()
                    try:
                        session.process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        session.process.kill()
                        session.process.wait()
                session.close_chunk()
                if session.recording:
                    self._export(session, session.finished_parts(), full=True)
                else:
                    self._discard_cache(session)
        self.sessions.clear()
        # 导出进程不能在应用退出后悬空；最多等 10 秒，失败时保留原始分段。
        for process, _result, _parts, _full in self.exports:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
        self._poll()
