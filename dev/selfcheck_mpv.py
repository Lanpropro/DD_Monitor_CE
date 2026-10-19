"""libmpv 接口回归及真实原生多窗口/生命周期测试。"""
import argparse
import gc
import json
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
os.environ.setdefault("DDM_NO_SAVE", "1")

from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop, Qt, QTimer
from PySide6.QtWidgets import QApplication, QFrame, QGridLayout, QWidget

from ddm.audio_output import channel_filters, linear_volume
from ddm.player import HWDEC, TilePlayer, decode_media_options


def progress(player):
    fps = player._prop("container-fps", 30) or 30
    return SimpleNamespace(decoded_video=int(player._prop("estimated-frame-number", 0)),
        displayed_pictures=int(player._prop("time-pos", 0) * fps),
        decoded_audio=int(player._prop("audio-pts", 0) * 48000),
        lost_pictures=player._prop("frame-drop-count", 0))


def pump(app, seconds):
    loop = QEventLoop()
    QTimer.singleShot(max(1, round(seconds * 1000)), loop.quit)
    loop.exec()


def ready(app, player, timeout=12):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        pump(app, 0.03)
        if player._prop("time-pos", 0) > 0.1 and player._prop("vo-configured", False):
            player._check()
            assert player.state == "playing"
            return
    raise TimeoutError(f"no frame: {player.state}, {player.actual_decoder}")


def unit(app):
    widget = QWidget()
    first, other = TilePlayer(widget), TilePlayer(widget)
    headers = {"User-Agent": "test-agent", "Referer": "https://example.test/"}
    seen = []
    first.decoderFallback.connect(seen.append)
    first._prop = lambda name, default=None: default
    with patch.object(first, "_play_media") as play, patch.object(other, "_play_media"):
        first.stream_codec = other.stream_codec = "avc"
        first.play("https://example.test/live", "app", headers,
                   decode_media_options("d3d11va"))
        other.play("https://example.test/other", "app", headers,
                   decode_media_options("d3d11va"))
        assert not first._recover_decoder(), "网络断流不应切换解码器"
        first._decoder_error = True
        assert first._recover_decoder() and first.decode_mode == "none"
        assert not first._recover_decoder()
        assert seen == ["none"] and other.decode_mode == "d3d11va"
        assert play.call_args.args[:3] == ("https://example.test/live", "app", headers)
        first.play("https://example.test/other-cdn", "web", headers,
                   decode_media_options("d3d11va"))
        assert first.decode_mode == "none", "同编码 CDN 轮换保留失败记录"
        for mode in ("auto", "d3d11va-copy", "dxva2"):
            first.play("https://example.test/live", options=decode_media_options(mode))
            first._decoder_error = True
            assert first._recover_decoder() and first.decode_mode == "none"
            assert not first._recover_decoder(), "回退软件后不能循环重试硬解"
        first.stream_codec = "av1"
        first.play("https://example.test/av1", options=decode_media_options("d3d11va"))
        assert first.decode_mode == "d3d11va"
        first.paused = True
        assert not first._recover_decoder()
    core = Mock()
    first.player = core
    first._released = False
    first.set_volume(50)
    first.set_muted(True)
    first.set_audio_channel(3)
    assert abs(core.volume ** 3 / 100 ** 3 - 0.5) < 0.0001
    assert core.mute is True and core.af == ",".join(channel_filters(3))
    assert other.muted is False and other.audio_channel == 0
    first.release()
    first.release()
    core.terminate.assert_called_once()
    before = list(core.mock_calls)
    first.set_volume(10)
    first.set_muted(False)
    assert core.mock_calls == before, "释放后排队的音量更新不能访问播放内核"
    preview = TilePlayer(widget, silent=True)
    preview.set_muted(False)
    assert preview.muted and preview.decode_mode == "none"
    preview.bind()
    assert abs(preview._prop("demuxer-lavf-analyzeduration") - 0.1) < 0.001
    assert preview._prop("cache-pause") is True
    preview.release()
    normal = TilePlayer(widget)
    normal.bind()
    assert normal._prop("demuxer-lavf-analyzeduration") != 0.1
    assert normal._prop("cache-pause") is True, "普通观看应保留缓存暂停策略"
    normal.release()
    other.release()
    assert linear_volume(0) == 0 and linear_volume(100) == 100
    assert all(mode in HWDEC for mode in ("auto", "d3d11va", "d3d11va-copy", "dxva2", "none"))
    assert decode_media_options("d3d11va-copy") == ("hwdec=d3d11va-copy",)
    stalled = TilePlayer(widget)
    props = {"vo-configured": True, "demuxer-cache-state": {"cache-end": 1}}
    stalled._prop = lambda name, default=None: props.get(name, default)
    with patch.object(stalled, "_play_media"):
        stalled.play("https://example.test/live")
        stalled._media = "https://example.test/live"
        for step in range(8):
            props["demuxer-cache-state"] = {"cache-end": step + 1}
            assert not stalled._recover_decoder(), "缺少播放时间不能当作解码停帧"
        assert stalled._picture_signature() is None
        for step in range(8):
            props["time-pos"] = step + 1
            props["demuxer-cache-state"] = {"cache-end": step + 10}
            assert not stalled._recover_decoder(), "正常前进的直播不能触发解码降级"
        assert stalled._picture_signature() == (8, 8)
        for step in range(3):
            props["demuxer-cache-state"] = {"cache-end": step + 20}
            recovered = stalled._recover_decoder()
        assert recovered and stalled.decode_mode == "none"
    stalled.release()
    widget.close()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    print("mpv interface: PASS", flush=True)


def native(app, source, count, cycles, profile="web", headers=None, mode="auto", silent=False,
           soak_seconds=0):
    import psutil
    process = psutil.Process()
    window = QWidget()
    window.setWindowTitle("DDMonitor libmpv migration selfcheck")
    grid = QGridLayout(window)
    columns = max(1, round(count ** 0.5))
    frames, players = [], []
    records = []
    try:
        for index in range(count):
            frame = QFrame(window)
            frame.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
            frame.setMinimumSize(160, 90)
            grid.addWidget(frame, index // columns, index % columns)
            frames.append(frame)
            player = TilePlayer(frame, window, silent=silent)
            player.set_muted(True)
            players.append(player)
        window.resize(960, 600)
        window.show()
        started = time.perf_counter()
        for player in players:
            player.play(str(source), profile, headers, decode_media_options(mode))
        for player in players:
            ready(app, player)
        first_frame_ms = (time.perf_counter() - started) * 1000
        pump(app, 2)
        positions_before = [player._picture_signature() for player in players]
        drops_before = [player._prop("frame-drop-count", 0) for player in players]
        process.cpu_percent()
        pump(app, 4)
        result = {"windows": count, "first_frame_ms": first_frame_ms,
            "cpu_percent_normalized": process.cpu_percent() / (os.cpu_count() or 1),
            "rss_mib": process.memory_info().rss / 1024 ** 2,
            "decoders": [player.actual_decoder for player in players],
            "drops": [player._prop("frame-drop-count", 0) for player in players]}
        result["steady_drops_4s"] = [player._prop("frame-drop-count", 0) - before
                                     for player, before in zip(players, drops_before)]
        if soak_seconds:
            pump(app, soak_seconds)
            result["soak_seconds"] = soak_seconds
        for player, before in zip(players, positions_before):
            after = player._picture_signature()
            assert before is not None and after is not None and after[1] > before[1], \
                "真实播放位置必须持续前进"
            assert player.decode_mode == ("none" if silent else mode), "正常播放不能触发兜底"
        first = players[0]
        if silent:
            assert first._prop("aid") is False or first._prop("aid") == "no"
            assert first._prop("current-ao") != "wasapi"
        first.set_paused(True)
        position = first._prop("time-pos")
        pump(app, 0.5)
        assert abs(first._prop("time-pos") - position) < 0.1
        first.set_paused(False)
        first.set_volume(50)
        first.set_audio_channel(3)
        assert first._prop("af")[0]["name"] == "lavfi"
        first.set_audio_channel(0)
        if count > 1:
            assert abs(players[1]._prop("volume") - linear_volume(42)) < 0.01
            assert players[1]._prop("mute") is True and players[1]._prop("af") == []
        for _ in range(cycles):
            first.stop()
            first.play(str(source), profile, headers, decode_media_options(mode))
            ready(app, first)
            records.append({"handles": process.num_handles(),
                "rss_mib": process.memory_info().rss / 1024 ** 2})
        result["reload_resources"] = records
        result["pass"] = True
        return result
    finally:
        for player in players:
            player.release()
            player.deleteLater()
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        gc.collect()


def destroy_cycles(app, source, cycles):
    import psutil
    process = psutil.Process()
    records = []
    for _ in range(cycles):
        window = QWidget()
        window.resize(640, 360)
        window.show()
        player = TilePlayer(window, window)
        player.set_muted(True)
        player.play(str(source))
        ready(app, player)
        player.release()
        player.deleteLater()
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        del player, window
        gc.collect()
        pump(app, 0.1)
        records.append({"handles": process.num_handles(), "threads": process.num_threads(),
            "rss_mib": process.memory_info().rss / 1024 ** 2})
    return {"destroy_resources": records, "pass": True}


@contextmanager
def mta_lifetime():
    if sys.platform != "win32":
        yield
        return
    import ctypes
    ole = ctypes.WinDLL("ole32")
    ole.CoIncrementMTAUsage.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
    ole.CoIncrementMTAUsage.restype = ctypes.c_long
    ole.CoDecrementMTAUsage.argtypes = [ctypes.c_void_p]
    ole.CoDecrementMTAUsage.restype = ctypes.c_long
    cookie = ctypes.c_void_p()
    result = ole.CoIncrementMTAUsage(ctypes.byref(cookie))
    if result < 0:
        raise ctypes.WinError(result)
    try:
        yield
    finally:
        result = ole.CoDecrementMTAUsage(cookie)
        if result < 0:
            raise ctypes.WinError(result)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path)
    parser.add_argument("--input-file", type=Path)
    parser.add_argument("--mode", choices=list(HWDEC), default="auto")
    parser.add_argument("--silent", action="store_true")
    parser.add_argument("--windows", type=int, default=1)
    parser.add_argument("--cycles", type=int, default=0)
    parser.add_argument("--soak-seconds", type=int, default=0)
    parser.add_argument("--destroy-cycles", type=int, default=0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    # Keep MTA resources alive until Qt has released its WinRT factory cache.
    with mta_lifetime():
        app = QApplication([])
        app.setQuitOnLastWindowClosed(False)
        try:
            result = run(app, args)
        finally:
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            app.processEvents()
            gc.collect()
            app.shutdown()
    if result is not None:
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result), flush=True)


def run(app, args):
    unit(app)
    if args.source or args.input_file:
        if args.input_file:
            settings = json.loads(args.input_file.read_text(encoding="utf-8-sig"))
            source = settings["url"]
        else:
            assert args.source.is_file()
            source = args.source
            settings = {}
        result = (destroy_cycles(app, source, args.destroy_cycles) if args.destroy_cycles
                  else native(app, source, args.windows, args.cycles,
                              settings.get("profile", "web"), settings.get("headers"), args.mode,
                              args.silent, args.soak_seconds))
        return result


if __name__ == "__main__":
    main()
