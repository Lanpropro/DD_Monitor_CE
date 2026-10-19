"""重编码编码器探测与选择：回退、GOP 差异、容器修正。"""
import os
import sys
import tempfile
import threading
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import encoders as encoder_module
from ddm.config import DEFAULT_SETTINGS
from ddm.encoders import (
    AUTO_ORDER,
    HARDWARE_ENCODERS,
    SOFTWARE_ENCODER,
    gop_args,
    probe,
    resolve_encoder,
    resolve_encoder_async,
    segment_extension,
    segment_format,
)
from ddm.recording import ffmpeg_path, segment_args


def main():
    ffmpeg = ffmpeg_path(DEFAULT_SETTINGS)
    assert ffmpeg, "本机需有 FFmpeg 才能完成编码器自检"

    with patch.dict(encoder_module._probe_cache, {}, clear=True), \
            patch.object(encoder_module, "_probe_one", side_effect=[False, True]) as check:
        assert resolve_encoder("auto", "test-ffmpeg")[2] == "qsv"
        assert [call.args[1] for call in check.call_args_list] == ["h264_nvenc", "h264_qsv"]
        assert resolve_encoder("auto", "test-ffmpeg")[2] == "qsv" and check.call_count == 2
    with patch.dict(encoder_module._probe_cache, {}, clear=True), \
            patch.object(encoder_module, "_probe_one", return_value=True) as check:
        assert resolve_encoder("amf", "test-ffmpeg")[2] == "amf" and check.call_count == 1
    with tempfile.TemporaryDirectory() as temp, patch.object(encoder_module, "_probe_one", return_value=True) as check:
        executable = Path(temp) / "ffmpeg"
        executable.write_bytes(b"old")
        resolve_encoder("nvenc", str(executable))
        executable.write_bytes(b"updated-binary")
        resolve_encoder("nvenc", str(executable))
        assert check.call_count == 2, "同一路径的 FFmpeg 更新后不能继续使用旧探测结果"

    started, release = threading.Event(), threading.Event()
    def slow_probe(*_args):
        started.set()
        assert release.wait(5)
        return SOFTWARE_ENCODER, ["-preset", "veryfast"], "cpu"
    with patch.object(encoder_module, "resolve_encoder", side_effect=slow_probe):
        future = resolve_encoder_async("auto", ffmpeg)
        try:
            assert started.wait(2) and not future.done(), "探测必须在后台执行"
        finally:
            release.set()
        assert future.result(timeout=2)[2] == "cpu"

    assert probe("") == {family: False for family in HARDWARE_ENCODERS}, \
        "没有 FFmpeg 路径时应全判为不可用，而不是抛异常"

    # 显式选 CPU 永远不探测硬件；探测不到位也必须回退，不能返回空。
    assert resolve_encoder("cpu", ffmpeg) == (SOFTWARE_ENCODER, ["-preset", "veryfast"], "cpu")
    assert resolve_encoder("cpu", "")[0] == SOFTWARE_ENCODER
    usable = probe(ffmpeg)
    unusable = [family for family, ok in usable.items() if not ok]
    if unusable:
        for family in unusable:
            encoder, _args, name = resolve_encoder(family, ffmpeg)
            assert (encoder, name) == (SOFTWARE_ENCODER, "cpu"), \
                f"{family} 不可用时必须回退 libx264，实际 {encoder}"
    else:
        # 本机三个硬件方案都可用时只能打桩，验证「探测失败即回退」这条。
        with patch("ddm.encoders.probe",
                   return_value=dict.fromkeys(HARDWARE_ENCODERS, False)):
            for family in AUTO_ORDER:
                assert resolve_encoder(family, ffmpeg)[0] == SOFTWARE_ENCODER

    encoders = {encoder for encoder, _args in HARDWARE_ENCODERS.values()} | {SOFTWARE_ENCODER}
    assert resolve_encoder("auto", ffmpeg)[0] in encoders
    for preference in ("auto", *AUTO_ORDER):
        encoder, extra, name = resolve_encoder(preference, ffmpeg)
        assert encoder in encoders and name in ("cpu", *HARDWARE_ENCODERS)
        assert not extra or extra[0].startswith("-"), extra
        if name != "cpu":
            assert usable[name], f"{preference} 选了探测不通过的 {name}"

    # 分段要求每段自带关键帧；-sc_threshold 只有 x264 认，硬件方案各有写法。
    cpu = gop_args("cpu", 30, 10)
    nvenc = gop_args("nvenc", 30, 10)
    qsv = gop_args("qsv", 30, 10)
    assert cpu == ["-g", "300", "-sc_threshold", "0"]
    assert nvenc == ["-g", "300", "-no-scenecut", "1"]
    assert qsv == gop_args("amf", 30, 10) == ["-g", "300"]
    assert len({tuple(cpu), tuple(nvenc), tuple(qsv)}) == 3
    assert gop_args("nvenc", 0, 0) == ["-g", "1", "-no-scenecut", "1"], "非法帧率不能算出 -g 0"

    assert segment_extension("mov", "av1") == "mp4", "MOV 装不下 AV1，FFmpeg 会直接拒绝"
    assert segment_extension("ts", "av1") == "mp4", \
        "mpegts 会把 AV1 塞成读不出的 bin_data（退出码还 0），必须换容器"
    assert segment_extension("mov", "hevc") == "mov"
    assert segment_extension("ts", "hevc") == "ts"
    assert segment_extension("mkv", "av1") == "mkv"
    assert segment_extension("mp4", "av1") == "mp4"
    assert segment_extension("mov", "") == "mov", "认不出的编码要原样返回，老路径不变"
    assert segment_extension("ts", "") == "ts"
    assert segment_format("mov") == "mov" and segment_format("mkv") == "matroska"
    assert segment_format("ts") == "mpegts" and segment_format("mp4") == "mp4"

    # 重编码命令：编码器/附加参数/GOP 按选中的方案走，容器跟着扩展名；硬件
    # 方案下命令里不能再出现只有 x264 认的 -sc_threshold。
    cpu_args = segment_args(dict(DEFAULT_SETTINGS, recording_codec="h264",
                                 recording_encoder="cpu"), Path("x_%05d.mp4"))
    assert cpu_args[cpu_args.index("-c:v") + 1] == SOFTWARE_ENCODER
    assert "veryfast" in cpu_args and "-sc_threshold" in cpu_args
    assert cpu_args[cpu_args.index("-pix_fmt") + 1] == "yuv420p"
    auto_args = segment_args(dict(DEFAULT_SETTINGS, recording_codec="h264"),
                             Path("x_%05d.mp4"))
    chosen = auto_args[auto_args.index("-c:v") + 1]
    assert chosen in encoders
    if chosen != SOFTWARE_ENCODER:
        assert "-sc_threshold" not in auto_args, "硬件编码器不认 -sc_threshold"
    assert auto_args[auto_args.index("-segment_format") + 1] == "mp4"
    assert auto_args[-1] == "x_%05d.mp4"
    mov_args = segment_args({"recording_format": "mov"}, Path("x_%05d.mov"))
    assert mov_args[mov_args.index("-segment_format") + 1] == "mov"
    av1_args = segment_args({"recording_format": "mov"}, Path("x_%05d.mp4"), "av1")
    assert av1_args[av1_args.index("-segment_format") + 1] == "mp4", \
        "AV1 源选 MOV 时要换成 MP4 容器"
    av1_ts_args = segment_args({"recording_format": "ts"}, Path("x_%05d.mp4"), "av1")
    assert av1_ts_args[av1_ts_args.index("-segment_format") + 1] == "mp4", \
        "AV1 源选 TS 时要换成 MP4 容器，否则录出读不出画面的假 TS"
    for fmt, muxer in (("mov", "mov"), ("ts", "mpegts")):
        args = segment_args({"recording_format": fmt, "recording_codec": "h264",
                             "recording_encoder": "cpu"}, Path(f"x_%05d.{fmt}"), "av1")
        assert args[args.index("-segment_format") + 1] == muxer
    print("编码器探测回退、GOP 分族与 AV1 容器修正：通过")
    print(f"本机 auto 解析为 {chosen}")


if __name__ == "__main__":
    main()
