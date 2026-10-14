"""FFmpeg 硬件编码器探测与选择。

录制重编码默认优先用显卡编码器（NVENC / QSV / AMF）：同样码率下画质不差，
CPU 占用却低一个数量级，不会和游戏抢核。但硬件编码要求显卡、驱动和这一份
FFmpeg 构建三者同时具备，缺一不可，所以这里**实测探测**而不是按平台猜 ——
探测方式就是真的起一个进程编一帧，只有退出码为 0 才算可用。

探测结果按 FFmpeg 可执行文件路径缓存：一次运行里每格录制都会问同一份结果，
不缓存就会反复起探测进程。
"""
from __future__ import annotations

import subprocess
import sys
import threading

#: 「编码方式」设置项：值 -> 界面文案。
ENCODER_CHOICES = (
    ("auto", "自动（优先显卡编码，不可用回退 CPU）"),
    ("cpu", "CPU（libx264，兼容性最好）"),
    ("nvenc", "NVIDIA NVENC"),
    ("qsv", "Intel Quick Sync"),
    ("amf", "AMD AMF"),
)

#: 硬件方案 -> (FFmpeg 编码器名, 推荐附加参数)。
HARDWARE_ENCODERS = {
    "nvenc": ("h264_nvenc", ["-preset", "p5", "-tune", "hq"]),
    "qsv": ("h264_qsv", ["-preset", "medium"]),
    "amf": ("h264_amf", ["-quality", "balanced"]),
}

#: 自动模式下的尝试顺序。NVENC 覆盖率最高，排在前面。
AUTO_ORDER = ("nvenc", "qsv", "amf")

#: 回退方案：libx264 是 FFmpeg 自带软件编码器，任何构建都有。
SOFTWARE_ENCODER = "libx264"
SOFTWARE_ARGS = ["-preset", "veryfast"]

#: 探测用的输入：一帧纯色足够让编码器完成初始化。
_PROBE_INPUT = ["-f", "lavfi", "-i", "color=c=black:s=256x144:r=30", "-t", "1"]

_probe_cache: dict[str, dict[str, bool]] = {}
_probe_lock = threading.Lock()


def _probe_one(executable: str, encoder: str) -> bool:
    """真起一次编码，退出码 0 才算这个编码器在这台机器上可用。"""
    command = [executable, "-hide_banner", "-loglevel", "error", *_PROBE_INPUT,
               "-c:v", encoder, "-an", "-f", "null", "-"]
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        result = subprocess.run(command, stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                timeout=20, creationflags=flags)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def probe(executable: str) -> dict[str, bool]:
    """探测这台机器可用的硬件编码器；结果按可执行文件路径缓存。"""
    if not executable:
        return {family: False for family in HARDWARE_ENCODERS}
    with _probe_lock:
        cached = _probe_cache.get(executable)
        if cached is None:
            cached = {family: _probe_one(executable, encoder)
                      for family, (encoder, _args) in HARDWARE_ENCODERS.items()}
            _probe_cache[executable] = cached
        return cached


def resolve_encoder(preference: str, executable: str) -> tuple[str, list[str], str]:
    """按设置挑一个真正能用的 H.264 编码器。

    返回 ``(编码器名, 附加参数, 族名)``。族名是 ``cpu`` 或硬件方案名，调用方
    要靠它决定 GOP 参数怎么写（见 ``gop_args``）。任何情况下都不会返回空 ——
    实在没有硬件编码器就用 libx264。
    """
    if preference == "cpu":
        return SOFTWARE_ENCODER, list(SOFTWARE_ARGS), "cpu"
    families = (preference,) if preference in HARDWARE_ENCODERS else AUTO_ORDER
    usable = probe(executable)
    for family in families:
        if usable.get(family):
            encoder, args = HARDWARE_ENCODERS[family]
            return encoder, list(args), family
    return SOFTWARE_ENCODER, list(SOFTWARE_ARGS), "cpu"


def gop_args(family: str, fps: int, segment_seconds: int) -> list[str]:
    """关键帧间隔参数。

    分段录制要求每个分段自带关键帧，所以固定 ``-g``。``-sc_threshold 0``
    （关掉场景切换插入关键帧）只对 x264 系列有意义，硬件编码器要用各自的
    开关：NVENC 是 ``-no-scenecut``，QSV / AMF 不传即可。
    """
    args = ["-g", str(max(1, fps) * max(1, segment_seconds))]
    if family == "cpu":
        return args + ["-sc_threshold", "0"]
    if family == "nvenc":
        return args + ["-no-scenecut", "1"]
    return args


#: 分段容器：录制设置里的扩展名 -> FFmpeg 的 ``-segment_format`` 值。
SEGMENT_FORMATS = {"mkv": "matroska", "mov": "mov", "ts": "mpegts", "mp4": "mp4"}

#: 装不进某些容器的视频编码 -> 那些容器的扩展名。
#: AV1 的 MOV 复用器在 FFmpeg 里是明确拒绝的（"av1 only supported in MP4 and
#: AVIF"），用户选 MOV 又录到 AV1 源时会直接启动失败，所以这里提前换容器。
INCOMPATIBLE_FORMATS = {"av1": ("mov",)}


def segment_extension(extension: str, video_codec: str) -> str:
    """挑一个装得下 ``video_codec`` 的分段扩展名。

    AV1 只能装进 MP4 / MKV / TS，所以「MOV + AV1」这一组换成 MP4；其余原样返回。
    """
    if extension in INCOMPATIBLE_FORMATS.get(video_codec, ()):
        return "mp4"
    return extension


def segment_format(extension: str) -> str:
    """扩展名 -> FFmpeg ``-segment_format`` 值；认不出的按 MP4 处理。"""
    return SEGMENT_FORMATS.get(extension, "mp4")
