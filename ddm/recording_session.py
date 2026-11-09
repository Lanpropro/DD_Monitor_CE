"""Per-tile recording session state and completed segment bookkeeping."""
from __future__ import annotations
import subprocess
import time
import uuid
from concurrent.futures import Future
from pathlib import Path


class _Session:
    supports_replay = True

    def __init__(self, tile, settings: dict, recording: bool, folder: Path,
                 video_codec: str = ""):
        from . import recording as api
        self.tile = tile
        self.session_id = uuid.uuid4().hex
        self.created_at = time.time()
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
        self.extension = api.segment_extension_for(settings, self.video_codec)
        self.parts: list[Path] = []
        self.replay_parts: list[Path] = []
        self.process: subprocess.Popen | None = None
        self.active_pattern: Path | None = None
        self.url = ""
        self.chunk = 0
        self.stopping = False
        self.save_cache_on_stop = False
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
        self.resolver = None
        self.refreshing = False
        self.pruned_at = 0.0        # 上次裁分段的时间；纯缓存会话用（见 _prune_cache）
        self.segment_seconds = api.SEGMENT_SECONDS

    def recording_message(self, event, path=None):
        return {'start': f'{self.name} 开始录制',
                'resume': f'{self.name} 取到新流，继续录制',
                'saved': f'已保存录制：{path}'}[event]

    def parts_directory(self) -> Path:
        return self.folder / ".ddm-parts"

    def segment_options(self, pattern: Path) -> list[str]:
        from . import recording as api
        return api.segment_args(self.settings, pattern, self.video_codec,
                            encoder=self.encoder, segment_seconds=self.segment_seconds)

    def update_review(self) -> None:
        """Optional recording backend hook; only publish completed segments."""

    def save_recording(self, parts: list[Path]) -> Path | None:
        """Return a durable recording path when the backend already saved it."""
        return None

    def review_info(self) -> dict | None:
        return None

    def export_input(self, parts: list[Path], playlist: Path) -> list[str]:
        playlist.write_text("".join("file '" + str(p).replace("'", "'\\''") + "'\n"
                                    for p in parts), encoding="utf-8")
        return ["-f", "concat", "-safe", "0", "-i", str(playlist)]

    def snapshot_info(self, parts: list[Path]) -> dict:
        return {}

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
