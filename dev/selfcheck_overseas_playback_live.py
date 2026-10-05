"""显式指定海外房间的只读验收；静音、无配置保存、不记录签名地址。"""
import argparse
import logging
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
os.environ["DDM_NO_SAVE"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "windows" if sys.platform == "win32" else "offscreen")
os.environ.setdefault("PYTHON_VLC_LIB_PATH", str(REPO / "libvlc.dll"))
logging.disable(logging.CRITICAL)
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402
import vlc  # noqa: E402
from ddm.global_danmaku import request_proxy  # noqa: E402
from ddm import hls_proxy  # noqa: E402
from ddm.auto_quality import AUTO_QUALITY  # noqa: E402
from ddm.player import TilePlayer  # noqa: E402
from plugins_user.global_live.plugin import TwitchPlatform, YouTubePlatform  # noqa: E402
from plugins_user._match_sync.media import Decoder  # noqa: E402


def wait(app, predicate, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(.03)
    raise AssertionError("Playback check timed out")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("room")
    parser.add_argument("--seconds", type=int, default=20)
    parser.add_argument("--match-only", action="store_true")
    parser.add_argument("--quality", choices=("auto", "highest"), default="auto")
    args = parser.parse_args()
    quality = AUTO_QUALITY if args.quality == "auto" else 10000
    platform = TwitchPlatform() if args.room.startswith("twitch:") else YouTubePlatform()
    rid = platform.normalize(args.room)
    assert platform.room_info(rid).live, "The supplied room is offline"
    print("Proxy configured:", bool(request_proxy(platform.origin)), flush=True)
    app = QApplication([])
    video = QWidget()
    video.setWindowTitle("海外播放检查（静音）")
    video.resize(640, 360)
    video.show()
    tile = TilePlayer(video, silent=True)
    states = []
    tile.stateChanged.connect(states.append)

    def frames():
        stats = vlc.MediaStats()
        if tile._media is not None:
            tile._media.get_stats(stats)
        return stats.decoded_video

    try:
        if not args.match_only:
            url, qn, profile, headers = platform.play_url(rid, quality)
            tile.play(url, profile, headers, options=(":avcodec-hw=none",))
            started = time.monotonic()
            wait(app, lambda: frames() >= 30, 40)
            first = time.monotonic() - started
            previous, state_index = frames(), len(states)
            deadline = time.monotonic() + args.seconds
            wait(app, lambda: time.monotonic() >= deadline, args.seconds + 1)
            assert frames() > previous + args.seconds * 5, "Decoded frames must continue advancing"
            assert "error" not in states[state_index:] and "frozen" not in states[state_index:], states[state_index:]
            speed, samples = tile._relay._hls_proxy.network_speed()
            assert speed > 0 and samples > 0
            print(f"PASS: real {profile} VLC decoding, quality={qn}, first frames={first:.2f}s, "
                  f"continued={args.seconds}s, decoded={frames()}, samples={samples}, effective={speed / 1e6:.2f}Mbps", flush=True)
    finally:
        relay = tile._relay
        tile.release()
        video.close()
        if relay is not None:
            assert not relay._thread.is_alive() and not relay._hls_proxy._thread.is_alive()
    # 独立解析，二路不能依赖格子仍然持有的临时地址或消费会话。
    decoder = Decoder(rid, {"quality": quality}, platform)
    states, resets = [], []
    relays = []
    original_proxy = hls_proxy.HlsProxy
    def capture_proxy(*args):
        relay = original_proxy(*args)
        relays.append(relay)
        return relay
    patcher = patch.object(hls_proxy, "HlsProxy", side_effect=capture_proxy)
    patcher.start()
    decoder.events.state.connect(states.append)
    decoder.events.reset.connect(lambda: resets.append(True))
    try:
        started = time.monotonic()
        decoder.start()
        wait(app, lambda: len(decoder.history.frames) >= 10 and decoder.history.audio.end > 48000, 40)
        first = time.monotonic() - started
        previous = decoder.history.latest()[0]
        print(f"TRACE: match first frames={first:.2f}s, reconnects={len(resets)}", flush=True)
        deadline = time.monotonic() + args.seconds
        wait(app, lambda: time.monotonic() >= deadline, args.seconds + 1)
        speed, samples = relays[-1].network_speed()
        print(f"TRACE: match progress={decoder.history.latest()[0] - previous:.2f}s, reconnects={len(resets)}, "
              f"effective={speed / 1e6:.2f}Mbps, samples={samples}, states={states}", flush=True)
        assert decoder.history.latest()[0] > previous + args.seconds * .7, "Match playback fell behind"
        assert not resets and decoder.process is not None and decoder.process.poll() is None, (states, resets)
        print(f"PASS: real {platform.kind} match-sync JPEG/PCM, first frames={first:.2f}s, "
              f"continued={args.seconds}s, reconnects={len(resets)}", flush=True)
    finally:
        decoder.stop()
        decoder.thread.join(5)
        patcher.stop()
        assert not decoder.thread.is_alive() and decoder.process is None


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Streamlink 的异常链可能带完整签名 URL，只输出异常类型。
        if isinstance(error, AssertionError):
            print("FAIL: assertion:", str(error), flush=True)
        causes = []
        while error is not None:
            causes.append(type(error).__name__)
            error = error.__cause__
        print("FAIL: playback check:", " -> ".join(causes), flush=True)
        sys.exit(1)
