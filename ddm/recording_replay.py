"""Recording replay retention, segment leases and completed-file export; manager owns sessions and exports."""
import math
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from .recording_session import (_Session)


class RecordingReplay:
    def __init__(self, host):
        self.host = host

    def export_replay(self, session: _Session, parts: list[Path]) -> bool:
        """单独存一份「最近 N 分钟」（即时回放），完整录制照旧另外导出。"""
        host = self.host
        if not session.supports_replay or not parts:
            return False
        count = math.ceil(max(1, int(session.settings.get("recording_replay_minutes", 3)))
                          * 60 / session.segment_seconds)
        recent = parts[-count:]
        return host._export(session, recent, full=False)

    def pin_parts(self, parts: list[Path]) -> str:
        """Keep completed segments alive while a plugin prepares a local snapshot."""
        host = self.host
        token = uuid.uuid4().hex
        host._part_leases[token] = tuple(parts)
        return token

    def release_parts(self, token: str) -> None:
        host = self.host
        host._part_leases.pop(token, None)
        host._cleanup_parts()

    def protected_parts(self) -> set[Path]:
        host = self.host
        protected = {part for _process, _result, parts, _full in host.exports
                     for part in parts}
        protected.update(part for parts in host._part_leases.values() for part in parts)
        return protected

    def cleanup_parts(self) -> None:
        host = self.host
        protected = host._protected_parts()
        protected.update(part for session in host.sessions.values()
                         for part in session.replay_parts)
        for part in host._delete_after_exports - protected:
            part.unlink(missing_ok=True)
            host._delete_after_exports.discard(part)

    def prune_cache(self, session: _Session, *, prune_seconds) -> None:
        """把纯缓存会话的分段裁到「最近 N 分钟」。

        节流到每 PRUNE_SECONDS 秒一趟：`finished_parts()` 要 glob 整个
        `.ddm-parts` 目录，跟着 2 秒一轮的巡检每次都扫反而变成新的开销。
        被跳过的那些轮次不影响正确性 —— 会话结束时 `_finalize()` 要么
        `_discard_cache()` 全清、要么 `_export()` 按需取样，都不看目录里的存量。
        """
        host = self.host
        PRUNE_SECONDS = prune_seconds
        now = time.monotonic()
        if now - session.pruned_at < PRUNE_SECONDS:
            return
        session.pruned_at = now
        completed = session.finished_parts()
        keep = math.ceil(max(1, int(session.settings.get("recording_replay_minutes", 3)))
                         * 60 / session.segment_seconds) + 2
        protected = host._protected_parts()
        for part in completed[:-keep]:
            if part in protected:
                continue
            part.unlink(missing_ok=True)
            if part in session.parts:
                session.parts.remove(part)

    def discard_cache(self, session: _Session) -> None:
        host = self.host
        host._delete_after_exports.update(session.finished_parts())
        host._cleanup_parts()

    def prune_recording_replay(self, session: _Session) -> None:
        host = self.host
        keep = math.ceil(max(1, int(session.settings.get("recording_replay_minutes", 3)))
                         * 60 / session.segment_seconds) + 2
        session.replay_parts = session.replay_parts[-keep:]
        host._cleanup_parts()

    def save_replay(self, tile) -> bool:
        host = self.host
        if not host.supports_replay:
            host._say("当前为切片素材模式；请在录像页选择时间范围生成切片")
            return False
        if not bool(host.settings.get("recording_replay_enabled", True)):
            host._say("即时回放已在「设置 → 录制」里关闭")
            return False
        session = host.sessions.get(tile)
        if session is None:
            host._say("请先开启录制或即时回放缓存")
            return False
        if not session.supports_replay:
            host._say("这路录制为切片素材；请在录像页生成切片", session.room)
            return False
        count = math.ceil(max(1, int(session.settings.get("recording_replay_minutes", 3)))
                          * 60 / session.segment_seconds)
        parts = (session.replay_parts + session.finished_parts())[-count:]
        if not parts:
            host._say("缓存还没有完成一个分段，请稍后再保存")
            return False
        return host._export(session, parts, full=False)

    def export(self, session: _Session, parts: list[Path], *, full: bool, output_name, ffmpeg_binary, adopt_process, creation_flags) -> bool:
        host = self.host
        output_path = output_name
        ffmpeg_path = ffmpeg_binary
        _adopt_process = adopt_process
        _FFMPEG_FLAGS = creation_flags
        if not parts:
            host._say(f"{session.name} 没有可导出的录制分段", session.room)
            return False
        try:
            if full:
                saved = session.save_recording(parts)
                if saved is not None:
                    host._say(session.recording_message("saved", saved), session.room)
                    return True
            primary = session.folder  # 当前录制固定使用启动时选定的目录
            needed = sum(part.stat().st_size for part in parts)
            reserve = max(256, int(session.settings.get("recording_min_free_mb", 2048)))
            folder = primary if full else primary / "replays"
            folder.mkdir(parents=True, exist_ok=True)
            if shutil.disk_usage(folder).free < needed + reserve * 1024 * 1024:
                host._say("导出空间不足；原始分段保留，清理磁盘后可手动恢复")
                return False
            name = session.name
            if getattr(session, 'catalog_metadata', False):
                platform = str(session.room.get('platform') or ('bilibili' if session.room_id.isdigit() else session.room_id.partition(':')[0]) or '直播')
                name = '_'.join([session.name[:24], platform[:12], str(session.room.get('title') or '直播')[:24], session.room_id[:18]])
            result = output_path(folder, name + ("_回放" if not full else ""),
                                 session.extension)
            playlist = result.with_suffix(".concat.txt")
            command = [ffmpeg_path(session.settings), "-y", "-hide_banner", "-loglevel",
                       "warning", *session.export_input(parts, playlist), "-c", "copy"]
            if session.extension in ("mp4", "mov"):
                command += ["-movflags", "+faststart"]
            command += [str(result)]
            log = result.with_suffix(".ffmpeg.log")
            with log.open("wb") as handle:
                process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                           stdout=subprocess.DEVNULL, stderr=handle,
                                           creationflags=_FFMPEG_FLAGS)
            _adopt_process(process)         # 导出同样是后台活，别跟游戏抢盘
            host.exports.append((process, result, parts, full))
            host._export_rooms[result] = dict(session.room)
            if getattr(session, 'catalog_metadata', False):
                host._export_info[result] = {'room': dict(session.room), 'title': session.room.get('title') or session.name,
                    'created_at': session.created_at, 'kind': 'recording' if full else 'replay'}
            host._say(f"正在导出{'录制' if full else '即时回放'}：{result}", session.room)
            return True
        except OSError as error:
            host._say(f"导出失败：{error}；原始分段保留", session.room)
            return False
