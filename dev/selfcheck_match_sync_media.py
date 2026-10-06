"""Actual local FFmpeg pipelines and cancelled chat; never contacts real rooms."""
import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
os.environ.setdefault("DDM_NO_SAVE", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication  # noqa: E402
from ddm import plugins, recording  # noqa: E402
from plugins_user._match_sync import media  # noqa: E402
from plugins_user._match_sync.engine import RATE, match_scenes  # noqa: E402


def generate(executable, target):
    command = [executable, "-hide_banner", "-loglevel", "error", "-nostdin",
               "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30",
               "-f", "lavfi", "-i", r"aevalsrc=if(lt(t\,2.5)\,0\,0.3*sin(2*PI*440*t)):s=48000",
               "-t", "12", "-c:v", "libx264", "-preset", "ultrafast", "-g", "30",
               "-c:a", "pcm_s16le", str(target)]
    subprocess.run(command, check=True, capture_output=True, timeout=25,
                   creationflags=recording._FFMPEG_FLAGS)


def media_checks(app):
    executable = recording.ffmpeg_path()
    assert executable, "FFmpeg is required for media integration checks"
    with tempfile.TemporaryDirectory(prefix="ddm_match_media_") as root:
        source = Path(root) / "original.mkv"
        shifted = Path(root) / "shifted.mkv"
        generate(executable, source)
        subprocess.run([executable, "-hide_banner", "-loglevel", "error", "-nostdin",
                        "-ss", "2", "-i", str(source), "-t", "10", "-c", "copy", str(shifted)],
                       check=True, capture_output=True, timeout=15,
                       creationflags=recording._FFMPEG_FLAGS)
        a = media.Decoder("1", {"url": str(source), "headers": {}})
        platform = plugins.Platform()
        platform.kind = "local_test"
        platform.room_info = lambda _rid: plugins.RoomInfo("local_test:2", uname="本地平台")
        platform.play_url = lambda _rid, _quality: (str(shifted), 10000, "local", {})
        b = media.Decoder("local_test:2", {"quality": 10000}, platform)
        states = []
        a.events.state.connect(states.append)
        b.events.state.connect(states.append)
        with patch.object(media.bili, "play_url", side_effect=AssertionError("Network forbidden")) as network:
            try:
                a.start()
                b.start()
                deadline = time.monotonic() + 12
                while time.monotonic() < deadline:
                    app.processEvents()
                    if len(a.history.snapshots()) >= 14 and len(b.history.snapshots()) >= 14:
                        break
                    time.sleep(0.03)
                sa, sb = a.history.snapshots(), b.history.snapshots()
                assert len(sa) >= 14 and len(sb) >= 14, (len(sa), len(sb), states)
                assert a.history.audio.end > RATE * 5 and b.history.audio.end > RATE * 5
                assert a.process.poll() is None and b.process.poll() is None
                assert all(time.monotonic() - decoder.last_frame_received < 1 for decoder in (a, b))
                match = match_scenes(sa, sb)
                expected = b.history.origin - a.history.origin - 2
                assert match.lag is not None and abs(match.lag - expected) < 0.55, (match, expected)
                assert a.history.frame_at(sa[-1].time - 2) is not None
                pcm = a.history.pcm_at(a.history.origin + 2, 480)
                assert len(pcm) == 1920 and not any(pcm), "The two-second video frame must still precede the audio marker"
                assert any(a.history.pcm_at(a.history.origin + 2.6, 480))
                assert not any(b.history.pcm_at(b.history.origin + 0.4, 480))
                assert any(b.history.pcm_at(b.history.origin + 0.6, 480)), "The shifted feed's audio marker must shift by the same two seconds"
                assert abs((sa[-1].time - sa[0].time) - 6.5) < 0.01
                print(f"PASS: two actual original-video/PCM pipelines; expected lag {expected:.3f}s, matched {match.lag:.3f}s")
            finally:
                processes = (a.process, b.process)
                a.stop()
                b.stop()
                for decoder in (a, b):
                    decoder.thread.join(4)
                    assert not decoder.thread.is_alive(), "Decoder must stop without blocking the GUI"
                for process in processes:
                    if process is not None:
                        assert process.poll() is not None, "No orphan FFmpeg"
            assert not network.called
        # Immediate close also stops a child created concurrently with stop().
        c = media.Decoder("3", {"url": str(source)})
        with patch.object(media.bili, "room_info", side_effect=AssertionError("Network forbidden")):
            c.start()
            c.stop()
            c.thread.join(4)
            assert not c.thread.is_alive()
            assert c.process is None
    print("PASS: retained playback, PCM data, paced frame times, immediate stop and child cleanup")


def stalled_stream_checks(app):
    executable = recording.ffmpeg_path()
    command = media.decode_command(executable, "http://127.0.0.1/stream", {"Referer": "test"}, 12345)
    before_input = command[:command.index("-i")]
    assert before_input[before_input.index("-rw_timeout") + 1] == "6000000"
    assert before_input[-4:-2] == ["-reconnect", "0"]
    assert "Referer: test\r\n" in before_input
    released = threading.Event()
    requested = threading.Event()

    class StalledStream(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "video/x-flv")
            self.end_headers()
            self.wfile.flush()
            requested.set()
            released.wait(8)

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), StalledStream)
    server.daemon_threads = True
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()
    try:
        with tempfile.TemporaryDirectory(prefix="ddm_match_stall_") as root:
            source = Path(root) / "recovered.mkv"
            generate(executable, source)
            decoder = media.Decoder("42", {"url": f"http://127.0.0.1:{server.server_port}/stall"})
            states, resets = [], []
            decoder.events.state.connect(states.append)
            decoder.events.reset.connect(lambda: resets.append(True))
            with patch.object(media, "FRAME_TIMEOUT", .8), \
                    patch.object(media.bili, "room_info", return_value=None), \
                    patch.object(media.bili, "play_url", return_value=(str(source), 250, "local", {})) as fresh:
                try:
                    decoder.start()
                    started = time.monotonic()
                    deadline = started + 3.5
                    while time.monotonic() < deadline and not decoder.history.latest():
                        app.processEvents()
                        time.sleep(.02)
                    app.processEvents()
                    assert requested.is_set()
                    assert decoder.history.latest(), (states, "Stalled input must time out and resolve a fresh stream")
                    assert time.monotonic() - started < 3.5, "First retry must not add a two-second backoff"
                    assert any("超时" in state for state in states), states
                    assert resets and fresh.call_count == 1
                    assert fresh.call_args.kwargs["source_offset"] == 1
                    recovered = decoder.process
                    count = len(decoder.history.frames)
                    deadline = time.monotonic() + 1.2
                    while time.monotonic() < deadline:
                        app.processEvents()
                        time.sleep(.02)
                    assert decoder.process is recovered and recovered.poll() is None
                    assert len(decoder.history.frames) > count and fresh.call_count == 1
                finally:
                    process = decoder.process
                    decoder.stop()
                    decoder.thread.join(4)
                    assert not decoder.thread.is_alive()
                    assert process is None or process.poll() is not None
            # Closing during an initial blocked read also leaves no process or watchdog.
            pending = media.Decoder("43", {"url": f"http://127.0.0.1:{server.server_port}/stall"})
            pending.start()
            deadline = time.monotonic() + 2
            while pending.process is None and time.monotonic() < deadline:
                time.sleep(.01)
            pending.stop()
            pending.thread.join(4)
            assert not pending.thread.is_alive() and pending.process is None
            assert not any(t.name.startswith("match-sync-watchdog-") for t in threading.enumerate())
    finally:
        released.set()
        server.shutdown()
        server.server_close()
        serving.join(2)
    print("PASS: stalled HTTP input times out, rotates source, resumes real frames, and stops cleanly")


def platform_checks(app):
    from PySide6.QtCore import QObject
    from ddm.live_danmaku import LiveDanmakuClient
    from plugins_user.domestic_live.plugin import HuyaPlatform, DouyuPlatform, DouyinPlatform
    parent = QObject()
    for platform in (HuyaPlatform(), DouyuPlatform(), DouyinPlatform()):
        room_id = platform.kind + ":42"
        metadata, received, states = [], [], []
        decoder = media.Decoder(room_id, {"url": "http://127.0.0.1:9/cached", "quality": 10000,
                                        "title": "缓存直播间标题"}, platform)
        decoder.events.information.connect(metadata.append)
        with patch.object(media.bili, "room_info", side_effect=AssertionError("Bilibili lookup forbidden")), \
                patch.object(media.bili, "play_url", side_effect=AssertionError("Bilibili stream forbidden")), \
                patch.object(platform, "room_info", return_value=plugins.RoomInfo(room_id, uname="跨平台主播")) as info, \
                patch.object(platform, "play_url", return_value=("http://127.0.0.1:9/fresh", 10000, "web", {"Referer": "platform"})) as play:
            if platform.kind == "douyu":
                assert decoder._resolve(0) == ("http://127.0.0.1:9/fresh", {"Referer": "platform"})
                play.assert_called_once_with(room_id, 10000)
                assert info.called, "Douyu must resolve a fresh consumer address, not reuse cached playback"
            else:
                assert decoder._resolve(0) == ("http://127.0.0.1:9/cached", {})
                assert metadata[-1]["title"] == "缓存直播间标题"
                assert not info.called and not play.called
            assert decoder._resolve(1) == ("http://127.0.0.1:9/fresh", {"Referer": "platform"})
            assert play.call_args.args == (room_id, 10000)
            calls = play.call_count
            assert metadata[-1]["actual_quality"] == 10000 and metadata[-1]["quality_options"]
            decoder.stop()
            try:
                decoder._resolve(2)
            except media.bili.Cancelled:
                pass
            else:
                raise AssertionError("Cancelled platform lookup must not resolve a stream")
            assert play.call_count == calls

        async def local_chat(client):
            client._loop = asyncio.get_running_loop()
            client._task = asyncio.current_task()
            client.status.emit("已连接")
            client.message.emit({"uname": "跨平台观众", "text": "离线消息"})
            await asyncio.Event().wait()

        with patch.object(LiveDanmakuClient, "_main", local_chat):
            chat = media.PlatformChat(room_id, platform, parent)
            client = chat.client
            chat.events.message.connect(received.append)
            chat.events.state.connect(states.append)
            chat.start()
            deadline = time.monotonic() + 2
            while not received and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(.01)
            assert received == [{"uname": "跨平台观众", "text": "离线消息"}] and states == ["已连接"]
            chat.stop()
            assert not client.isRunning(), "Platform QThread must finish before parent cleanup"
            app.processEvents()

    unsupported = plugins.Platform()
    chat = media.PlatformChat("unsupported:1", unsupported, parent)
    states = []
    chat.events.state.connect(states.append)
    chat.start()
    assert states and "暂不支持弹幕" in states[0]
    chat.stop()
    app.processEvents()
    with patch.object(unsupported, "danmaku_client", side_effect=ImportError("Missing optional backend")):
        chat = media.PlatformChat("unsupported:1", unsupported, parent)
        states = []
        chat.events.state.connect(states.append)
        chat.start()
        assert states and "请更新" in states[0]
        chat.stop()
        app.processEvents()
    print("PASS: platform cached/fresh streams, header and quality metadata, cancellation, real QThread chat forwarding and cleanup")


class Session:
    class Jar:
        def update_cookies(self, cookies):
            pass

    def __init__(self, **kwargs):
        self.cookie_jar = self.Jar()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class Client:
    instances = []

    def __init__(self, *args, **kwargs):
        self.closed = False
        self.instances.append(self)

    def set_handler(self, handler):
        pass

    def start(self):
        pass

    async def join(self):
        await asyncio.Event().wait()

    async def stop_and_close(self):
        self.closed = True


def chat_checks():
    # A pending lookup must not start a client after Stop was requested.
    def slow_conf(room_id):
        time.sleep(0.2)
        return 1, "fake", ["127.0.0.1"]
    with patch.object(media.bili, "danmaku_conf", side_effect=slow_conf), \
            patch.object(media.danmaku.aiohttp, "ClientSession", Session), \
            patch.object(media.danmaku, "_Client", Client):
        pending = media.Chat("1")
        pending.start()
        time.sleep(0.05)
        pending.stop()
        pending.thread.join(2)
        assert not pending.thread.is_alive() and not Client.instances
        active = media.Chat("1")
        active.start()
        deadline = time.monotonic() + 2
        while not Client.instances and time.monotonic() < deadline:
            time.sleep(0.01)
        assert Client.instances
        active.stop()
        active.thread.join(2)
        assert not active.thread.is_alive() and Client.instances[0].closed
    # A transient third-room lookup failure must not permanently end its chat worker.
    attempts = []
    received = []
    async def recover(self):
        attempts.append(True)
        if len(attempts) == 1:
            raise OSError("Temporary room lookup failure")
        self.loop = asyncio.get_running_loop()
        self.task = asyncio.current_task()
        self.events.message.emit({"text": "third room recovered"})
        await asyncio.Event().wait()
    with patch.object(media.Chat, "_main", recover):
        retrying = media.Chat("3")
        retrying.events.message.connect(received.append)
        retrying.start()
        try:
            deadline = time.monotonic() + 3
            while not received and time.monotonic() < deadline:
                QCoreApplication.instance().processEvents()
                time.sleep(.02)
            assert received == [{"text": "third room recovered"}] and len(attempts) == 2
        finally:
            retrying.stop()
            retrying.thread.join(2)
            assert not retrying.thread.is_alive()
    print("PASS: transient third-room chat failure retries and reconnects; cancellation leaves no worker")
    print("PASS: chat cancellation during lookup and active websocket cleanup without QThread destruction")


def main():
    app = QCoreApplication.instance() or QCoreApplication(sys.argv)
    media_checks(app)
    stalled_stream_checks(app)
    platform_checks(app)
    chat_checks()
    print("PASS: match-sync media selfcheck")


if __name__ == "__main__":
    main()
