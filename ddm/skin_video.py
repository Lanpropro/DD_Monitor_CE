"""Disposable low-resolution background copies; never modify source assets."""
import hashlib
import os
from pathlib import Path
import subprocess
import uuid

from PySide6.QtCore import QThread, Signal

from . import config
from .recording import _adopt_process, ffmpeg_path


def proxy_path(source):
    source = Path(source).resolve()
    stat = source.stat()
    identity = f'1080p15-v1\0{source}\0{stat.st_size}\0{stat.st_mtime_ns}'
    key = hashlib.sha256(identity.encode('utf-8')).hexdigest()
    return Path(config.REPO) / 'cache' / 'skin-video' / (key + '.mp4')


def prepare_video(source, cancelled=lambda: False):
    source = Path(source).resolve()
    target = proxy_path(source)
    if cancelled():
        return None
    if target.is_file() and target.stat().st_size > 0:
        return str(target)
    executable = ffmpeg_path()
    if not executable:
        raise ValueError('找不到 FFmpeg，暂用原视频背景')
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(target.stem + '-' + uuid.uuid4().hex + '.partial.mp4')
    command = [executable, '-nostdin', '-hide_banner', '-loglevel', 'error',
               '-threads', '2', '-filter_threads', '1', '-i', str(source),
               '-map', '0:v:0', '-an', '-sn', '-dn', '-vf',
               "fps=15,scale=w='min(1920,iw)':h='min(1080,ih)':"
               'force_original_aspect_ratio=decrease:force_divisible_by=2',
               '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '24',
               '-threads', '2', '-pix_fmt', 'yuv420p', '-movflags', '+faststart',
               '-n', str(partial)]
    flags = (subprocess.CREATE_NO_WINDOW | subprocess.BELOW_NORMAL_PRIORITY_CLASS
             if os.name == 'nt' else 0)
    process = None
    try:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.PIPE, creationflags=flags)
        _adopt_process(process)
        while True:
            if cancelled():
                process.kill()
                process.communicate()
                return None
            try:
                _output, error = process.communicate(timeout=0.1)
                break
            except subprocess.TimeoutExpired:
                continue
        if process.returncode != 0 or not partial.is_file() or partial.stat().st_size == 0:
            detail = error.decode('utf-8', errors='replace').strip()[-300:]
            raise ValueError('背景副本生成失败，暂用原视频：' + detail)
        if cancelled():
            return None
        if proxy_path(source) != target:
            raise ValueError('背景文件在转换期间发生变化，请重新选择')
        os.replace(partial, target)
        return str(target)
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.communicate()
        partial.unlink(missing_ok=True)


class VideoProxy(QThread):
    ready = Signal(str)
    failed = Signal(str)

    def __init__(self, source, parent=None):
        super().__init__(parent)
        self.source = source

    def run(self):
        try:
            path = prepare_video(self.source, self.isInterruptionRequested)
            if path is not None and not self.isInterruptionRequested():
                self.ready.emit(path)
        except (OSError, ValueError) as error:
            if not self.isInterruptionRequested():
                self.failed.emit(str(error))
