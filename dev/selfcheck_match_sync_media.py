"""Actual local FFmpeg pipelines and cancelled chat; never contacts real rooms."""
import asyncio
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
os.environ.setdefault("DDM_NO_SAVE", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication  # noqa: E402
from ddm import recording  # noqa: E402
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
        b = media.Decoder("2", {"url": str(shifted), "headers": {}})
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
                print(f"PASS: two actual JPEG/PCM pipelines; expected lag {expected:.3f}s, matched {match.lag:.3f}s")
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
    print("PASS: chat cancellation during lookup and active websocket cleanup without QThread destruction")


def main():
    app = QCoreApplication.instance() or QCoreApplication(sys.argv)
    media_checks(app)
    chat_checks()
    print("PASS: match-sync media selfcheck")


if __name__ == "__main__":
    main()
