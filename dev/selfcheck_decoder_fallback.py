"""解码恢复：有限回退、格子隔离、保留媒体选项，以及网络失败不触发切换。"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock, patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
os.environ.setdefault("DDM_NO_SAVE", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PYTHON_VLC_LIB_PATH", str(REPO / "libvlc.dll"))

from PySide6.QtWidgets import QApplication, QWidget

from ddm.player import PlayerPool, TilePlayer, vlc

ERROR = cast(Any, vlc.State).Error
PLAYING = cast(Any, vlc.State).Playing


def check_real_playback(app):
    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg
    with tempfile.TemporaryDirectory(prefix="ddm-decode-check-") as temp:
        source = Path(temp) / "source.mp4"
        subprocess.run([ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i",
                        "testsrc2=s=160x96:r=10", "-t", "2", "-c:v", "libx264", str(source)],
                       check=True, capture_output=True)
        instance = vlc.Instance("--intf=dummy", "--vout=dummy", "--no-audio", "--quiet")
        assert instance is not None
        widget = QWidget()
        with patch.object(PlayerPool, "instance", return_value=instance):
            player = TilePlayer(widget)
        try:
            stats = SimpleNamespace(demux_read_bytes=1024, decoded_video=0, displayed_pictures=0)
            with patch.object(player, "_media_stats", return_value=stats):
                with patch.object(player, "_play_media"):
                    player.play(str(source), options=(":no-audio", ":avcodec-hw=d3d11va"))
                    assert player._recover_decoder(ERROR)
                assert player._recover_decoder(ERROR) and player.decode_mode == "none"
            end = time.monotonic() + 6
            decoded = 0
            while time.monotonic() < end and decoded == 0:
                app.processEvents()
                actual = player._media_stats()
                decoded = int(actual.decoded_video) if actual else 0
                time.sleep(.02)
            assert decoded > 0, "切到 CPU 后必须真正解出画面"
        finally:
            player.release()
            instance.release()


def main():
    app = QApplication.instance() or QApplication([])
    widgets = [QWidget(), QWidget()]
    player, other = [TilePlayer(widget) for widget in widgets]
    stats = SimpleNamespace(demux_read_bytes=1024, decoded_video=0, displayed_pictures=0)
    player.stream_codec = "avc"
    seen = []
    player.decoderFallback.connect(seen.append)
    try:
        with patch.object(player, "_play_media") as play, \
                patch.object(player, "_media_stats", return_value=stats), \
                patch.object(player.player, "video_get_track_count", return_value=2), \
                patch.object(other, "_play_media"):
            options = (":no-audio", ":avcodec-hw=d3d11va")
            headers = {"User-Agent": "test-agent", "Referer": "https://example.test"}
            player.play("https://example.test/live", "app", headers, options)
            other.play("https://example.test/other", "app", headers, options)
            assert player._recover_decoder(ERROR) and player.decode_mode == "dxva2"
            assert play.call_args.args == ("https://example.test/live", "app", headers,
                                          (":no-audio", ":avcodec-hw=dxva2"))
            assert other.decode_mode == "d3d11va", "一个格子的失败不能改变另一个格子"
            assert player._recover_decoder(ERROR) and player.decode_mode == "none"
            assert not player._recover_decoder(ERROR)
            assert seen == ["dxva2", "none"], "每种方式只尝试一次，最后落到 CPU"
            player.play("https://example.test/new-cdn", "web", headers, options)
            assert player.decode_mode == "none", "重取 CDN 不能重新启用已经失败的硬解"
            assert play.call_args.args[-1] == (":no-audio", ":avcodec-hw=none")

            player.stream_codec = "av1"
            player.play("https://example.test/new-codec", "app", headers, options)
            assert player.decode_mode == "d3d11va", "编码改变后应重新建立回退序列"
            player.play("https://example.test/live", options=(":avcodec-hw=none",))
            assert not player._recover_decoder(ERROR), "指定 CPU 后不应切回硬件"

            player.play("https://example.test/live")
            stats.demux_read_bytes = 0
            assert not player._recover_decoder(ERROR), "没有媒体数据时应重连网络"
            player._relay = Mock()
            player._relay.needs_restart.return_value = True
            stats.demux_read_bytes = 1024
            assert not player._recover_decoder(ERROR), "转封装退出时应重取流"
            player._relay = None

            player._decode_snapshot = None
            for count in (1024, 2048, 3072, 4096):
                stats.demux_read_bytes = count
                recovered = player._recover_decoder(PLAYING)
            assert recovered and player.decode_mode == "d3d11va", "持续进数据但没有画面应切换解码器"
            player._decode_snapshot = None
            player._decode_stall_ticks = 0
            for _ in range(5):
                assert not player._recover_decoder(PLAYING)
            assert player.decode_mode == "d3d11va", "媒体数据不增长时不能把网络卡顿当解码失败"
            with patch.object(player.player, "video_get_track_count", return_value=0):
                stats.demux_read_bytes += 1024
                assert not player._recover_decoder(PLAYING), "纯音频媒体不能触发视频解码回退"

            with patch.object(player.video_widget, "isVisible", return_value=True), \
                    patch.object(player.video_widget, "isMinimized", return_value=False):
                player._decode_snapshot = None
                for count in range(5):
                    stats.demux_read_bytes += 1024
                    stats.decoded_video = count
                    recovered = player._recover_decoder(PLAYING)
                    if recovered:
                        break
                assert recovered and player.decode_mode == "dxva2", "有解码计数却始终黑屏也应尝试恢复"

            player.play("https://example.test/live", options=(":avcodec-hw=d3d11va",))

            player._decode_snapshot = (4096, 10, 10)
            stats.demux_read_bytes, stats.decoded_video, stats.displayed_pictures = 8192, 10, 10
            assert player._recover_decoder(PLAYING, frozen=True)
            assert player.decode_mode == "dxva2"
            player._decode_snapshot = (8192, 10, 10)
            stats.demux_read_bytes, stats.decoded_video, stats.displayed_pictures = 16384, 20, 20
            assert not player._recover_decoder(PLAYING), "正常出帧不能切换解码器"
            player.paused = True
            with patch.object(player, "_recover_decoder") as recover:
                player._check()
                assert not recover.called, "暂停时不能启动解码恢复"
            player.paused = False
        player.stop()
        assert player._play_request is None and player._decode_key is None
    finally:
        player.release()
        other.release()
        app.processEvents()
    check_real_playback(app)
    print("解码器有限回退、网络区分、媒体选项与格子隔离：通过")


if __name__ == "__main__":
    main()
