"""每格独立的 FFmpeg 录制和即时回放；不接管 VLC 播放器。"""
from __future__ import annotations

import ctypes
import math
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
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

from .recording_output import (SEGMENT_SECONDS, ffmpeg_path, safe_name, output_path, input_args, segment_extension_for, segment_args)
CHECK_MS = 2000

#: 纯缓存的会话多久裁一次分段。ffmpeg 每 SEGMENT_SECONDS 秒落一个文件，
#: 30 秒能攒下 3 个，来得及；再密就是白扫目录（`_prune_cache` 要 glob 整个
#: `.ddm-parts`，分段一多那一趟并不便宜）。
PRUNE_SECONDS = 30

from .recording_process import _FFMPEG_FLAGS, _adopt_process, _ensure_job


from .recording_session import (_Session)
from .recording_replay import RecordingReplay


# Supported session base for recording plugins; retain the historical import.
RecordingSession = _Session


class RecordingManager(QObject):
    """所有操作在 Qt 主线程发起；FFmpeg 子进程各自独立，轮询不阻塞界面。"""

    notice = Signal(str)
    noticeWithRoom = Signal(str, dict)
    changed = Signal(object)

    def __init__(self, settings: dict, parent=None, *, source_resolver=None):
        super().__init__(parent)
        self.replay_control = RecordingReplay(self)
        self.settings = settings
        self.source_resolver = source_resolver
        self.session_factory = RecordingSession
        self.backend_owner = None
        self.sessions: dict[Any, _Session] = {}
        self.exports: list[tuple[subprocess.Popen, Path, list[Path], bool]] = []
        self._export_rooms: dict[Path, dict] = {}
        self._export_info = {}
        self._delete_after_exports: set[Path] = set()
        self._part_leases: dict[str, tuple[Path, ...]] = {}
        self.timer = QTimer(self)
        self.timer.setInterval(CHECK_MS)
        self.timer.timeout.connect(self._poll)
        self.timer.start()

    @property
    def supports_replay(self):
        return getattr(self.session_factory, 'supports_replay', True)

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
        if not recording and not self.supports_replay:
            return False
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
                if session.process is not None:
                    self._say(f"{session.name} 开始录制", session.room)
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
            session = self.session_factory(tile, self.settings, recording, folder,
                                           str(getattr(tile, "stream_codec", "") or ""))
            session.catalog_metadata = self.backend_owner is not None
            self.sessions[tile] = session
            self._launch(session, tile.stream_url, dict(tile.stream_headers or {}))
            self.changed.emit(tile)
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
        parts_dir = session.parts_directory()
        parts_dir.mkdir(parents=True, exist_ok=True)
        # 同一时刻不同格子/重启均不会共用文件名；文件名不含房间号。
        nonce = f"{time.time_ns()}_{session.chunk}"
        pattern = parts_dir / f"{safe_name(session.name)}_{nonce}_%05d.{session.extension}"
        command = [ffmpeg_path(session.settings), "-y"] + input_args(url, headers)
        command += session.segment_options(pattern)
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
        if session.chunk == 1:
            self._say(session.recording_message("start") if session.recording else f"{session.name} 开启即时回放缓存", session.room)

    @staticmethod
    def _end_process(session: _Session) -> None:
        process = session.process
        if process and process.poll() is None and process.stdin:
            try:
                process.stdin.write(b"q\n")
                process.stdin.flush()
            except OSError:
                pass

    def stop(self, tile, *, save_cache: bool = False) -> None:
        session = self.sessions.get(tile)
        if session is None or session.stopping:
            return
        session.stopping = True
        session.save_cache_on_stop = bool(save_cache)
        self._cancel_source(session)
        self._end_process(session)
        self.changed.emit(tile)
        if session.process is None:
            self._finalize(session)

    @staticmethod
    def _cancel_source(session) -> None:
        if session.resolver is not None:
            session.resolver.cancel()
            session.resolver = None
        session.refreshing = False

    def _continue(self, session, url, headers) -> None:
        if self.source_resolver is not None and url.lower().startswith(('http://', 'https://')):
            if not session.refreshing:
                session.refreshing = True
                session.retry_at = 0.0
                self._say(f"{session.name} 正在重新获取录制地址", session.room)
                self.source_resolver(session)
        else:
            self._launch(session, url, headers)

    def source_resolved(self, session, url, headers, codec) -> None:
        if (self.sessions.get(session.tile) is not session or session.stopping
                or str(session.tile.room.get('room_id') or '') != session.room_id):
            return
        self._cancel_source(session)
        try:
            self._change_codec(session, codec)
            self._launch(session, url, headers)
            self._say(session.recording_message("resume"), session.room)
        except (OSError, ValueError) as error:
            self.source_failed(session, str(error))

    def source_failed(self, session, reason) -> None:
        if self.sessions.get(session.tile) is not session or session.stopping:
            return
        self._cancel_source(session)
        session.retry_count += 1
        session.retry_at = time.monotonic() + min(60, 2 ** min(6, session.retry_count))
        self._say(f"{session.name} 重新获取录制地址失败：{reason}；稍后重试", session.room)

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
            if save_replay and session.supports_replay and bool(self.settings.get("recording_replay_enabled", True)):
                self._export_replay(session, session.replay_parts + parts)
            self._export(session, parts, full=True)
        elif session.save_cache_on_stop:
            parts = session.finished_parts()
            if not parts:
                self._say(f"{session.name} 缓存中暂无可保存的视频片段", session.room)
            elif self._export_replay(session, parts):
                self._discard_cache(session)
        else:
            self._discard_cache(session)

    def _export_replay(self, session: _Session, parts: list[Path]) -> bool:
        """单独存一份「最近 N 分钟」（即时回放），完整录制照旧另外导出。"""
        return self.replay_control.export_replay(session, parts)

    def on_resolved(self, tile) -> None:
        session = self.sessions.get(tile)
        if session is None or session.stopping:
            return
        if str(tile.room.get("room_id") or "") != session.room_id:
            self.stop(tile)
            return
        codec = str(getattr(tile, "stream_codec", "") or "")
        if session.process is None:
            self._cancel_source(session)
            try:
                reconnecting = session.chunk > 0
                self._change_codec(session, codec)
                self._launch(session, tile.stream_url, dict(tile.stream_headers or {}))
                if reconnecting and session.process is not None:
                    self._say(session.recording_message("resume"), session.room)
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
            session.update_review()
            process = session.process
            if process is None:
                if ((session.encoder_future is not None and session.encoder_future.done())
                        or session.retry_at and time.monotonic() >= session.retry_at):
                    try:
                        reconnecting = session.chunk > 0
                        self._continue(session, tile.stream_url,
                                       dict(tile.stream_headers or {}))
                        if reconnecting and session.process is not None:
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
                            self._say(f"{session.name} 已录制 {minutes} 分钟，正在保存分段", session.room)
                            self._end_process(session)
                    elif not session.stopping:
                        # 纯缓存的会话要**边录边裁**。以前只在 ffmpeg 退出后才裁一次，
                        # 而直播一开几小时进程根本不退，分段就一路堆 —— 用户实测
                        # 单格堆到 223 段、整个目录 4.3 GB 才被发现。
                        self._prune_cache(session)
                continue
            exit_code = process.returncode
            session.close_chunk()
            session.update_review()
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
                    self._continue(session, url, headers)
                    self._say(f"{session.name} 分段已保存，{'正在获取新录制地址' if session.refreshing else '继续录制'}", session.room)
                except OSError as error:
                    self._say(f"{session.name} 续录失败：{error}", session.room)
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
            metadata = self._export_info.pop(result, None)
            if process.returncode == 0 and result.exists():
                if metadata is not None:
                    try:
                        from . import images
                        for key, source in [('cover_path', images.room_cover_path(str(room.get('room_id') or ''))),
                                            ('avatar_path', images.room_avatar_path(str(room.get('room_id') or '')))]:
                            if Path(source).is_file():
                                image = result.with_suffix('.' + key + '.png')
                                shutil.copy2(source, image)
                                metadata[key] = str(image)
                        result.with_suffix(result.suffix + '.recording.json').write_text(
                            json.dumps({**metadata, 'path': str(result), 'ended_at': time.time()}, ensure_ascii=False), encoding='utf-8')
                    except OSError as error:
                        self._say(f'录像已保存，但信息文件写入失败：{error}', room)
                self._say(f"已保存{'录制' if full else '即时回放'}：{result}", room)
                for suffix in (".concat.txt", ".ffmpeg.log"):
                    result.with_suffix(suffix).unlink(missing_ok=True)
                if full:
                    self._delete_after_exports.update(parts)
            else:
                self._say(f"导出{'录制' if full else '即时回放'}失败（原始分段保留）：{result}", room)
                self._delete_after_exports.difference_update(parts)
        self._cleanup_parts()

    def pin_parts(self, parts: list[Path]) -> str:
        """Keep completed segments alive while a plugin prepares a local snapshot."""
        return self.replay_control.pin_parts(parts)

    def release_parts(self, token: str) -> None:
        return self.replay_control.release_parts(token)

    def _protected_parts(self) -> set[Path]:
        return self.replay_control.protected_parts()

    def _cleanup_parts(self) -> None:
        return self.replay_control.cleanup_parts()

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
        return self.replay_control.prune_cache(session, prune_seconds=PRUNE_SECONDS)

    def _discard_cache(self, session: _Session) -> None:
        return self.replay_control.discard_cache(session)

    def _prune_recording_replay(self, session: _Session) -> None:
        return self.replay_control.prune_recording_replay(session)

    def save_replay(self, tile) -> bool:
        return self.replay_control.save_replay(tile)

    def _export(self, session: _Session, parts: list[Path], *, full: bool) -> bool:
        return self.replay_control.export(session, parts, full=full, output_name=output_path, ffmpeg_binary=ffmpeg_path, adopt_process=_adopt_process, creation_flags=_FFMPEG_FLAGS)

    def shutdown(self) -> None:
        self.timer.stop()
        for session in self.sessions.values():
            self._cancel_source(session)
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
            # 退出不自动保存回放；明确请求的缓存停止保存仍完成导出。
            # 等待重连时没有进程，也要收尾已有分段。
            self._finalize(session, save_replay=False)
        self.sessions.clear()
        # 导出进程不能在应用退出后悬空；最多等 10 秒，失败时保留原始分段。
        for process, _result, _parts, _full in self.exports:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass
        self._poll()
