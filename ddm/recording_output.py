"""FFmpeg input/output arguments, file naming and container selection."""
from __future__ import annotations
import os
import re
import shutil
import time
from pathlib import Path
from . import config
from .encoders import gop_args, resolve_encoder, segment_extension, segment_format


SEGMENT_SECONDS = 10


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
                 encoder: tuple[str, list[str], str] | None = None,
                 segment_seconds: int = SEGMENT_SECONDS) -> list[str]:
    args = ["-map", "0:v:0", "-map", "0:a?", "-sn", "-dn"]
    if settings.get("recording_codec", "copy") == "h264":
        name, extra, family = encoder if encoder is not None else resolve_encoder(
            settings.get("recording_encoder", "auto"), ffmpeg_path(settings))
        fps = max(1, int(settings.get("recording_fps", 30)))
        bitrate = max(500, int(settings.get("recording_bitrate", 6000)))
        # GOP 参数按编码器族生成：-sc_threshold 是 x264 独有的，塞给硬件编码器
        # 会让 FFmpeg 直接启动失败。
        args += ["-c:v", name, *extra, "-pix_fmt", "yuv420p", "-b:v", f"{bitrate}k",
                 "-r", str(fps), *gop_args(family, fps, segment_seconds),
                 "-c:a", "aac", "-b:a", "160k"]
    else:
        args += ["-c", "copy"]
    fmt = segment_format(segment_extension_for(settings, video_codec))
    return args + ["-f", "segment", "-segment_time", str(segment_seconds),
                   "-reset_timestamps", "1", "-segment_format", fmt, str(pattern)]
