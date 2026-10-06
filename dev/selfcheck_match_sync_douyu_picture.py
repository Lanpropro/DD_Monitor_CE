"""Douyu picture fidelity, 60 Hz playback and shared timestamps; local media only."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
os.environ["DDM_NO_SAVE"] = "1"
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QWidget
from ddm import plugins, recording
from dev.selfcheck_match_sync import FakeChat
from plugins_user._match_sync import media, viewer as module


def picture_checks(app):
    executable = recording.ffmpeg_path()
    assert executable, "FFmpeg is required"
    platform = plugins.Platform()
    platform.kind = "douyu"
    platform.room_info = lambda rid: plugins.RoomInfo(rid, uname="Local Douyu")
    platform.room_quality_options = lambda rid: [{"qn": 10000, "desc": "1080P60"}]
    with tempfile.TemporaryDirectory(prefix="ddm_douyu_picture_") as root:
        source = Path(root) / "1080p60.mkv"
        subprocess.run([executable, "-hide_banner", "-loglevel", "error", "-nostdin",
            "-f", "lavfi", "-i", "testsrc2=size=1920x1080:rate=60",
            "-f", "lavfi", "-i", r"aevalsrc=if(lt(t\,2)\,0\,0.3*sin(2*PI*440*t)):s=48000",
            "-t", "5", "-c:v", "libx264", "-threads", "2", "-preset", "ultrafast",
            "-c:a", "pcm_s16le", str(source)], check=True, capture_output=True, timeout=30,
            creationflags=recording._FFMPEG_FLAGS)
        platform.play_url = lambda rid, quality: (str(source), 10000, "local", {})
        # A platform quality ID is not a Bilibili resolution threshold.
        decoder = media.Decoder("douyu:42", {"quality": 80}, platform)
        with patch.object(media.bili, "play_url", side_effect=AssertionError("Network forbidden")):
            try:
                decoder.start()
                deadline = time.monotonic() + 10
                while time.monotonic() < deadline:
                    app.processEvents()
                    with decoder.history.lock:
                        frames = list(decoder.history.frames)
                    if frames and frames[-1][0] - frames[0][0] >= 3:
                        break
                    time.sleep(.01)
                assert frames, "No decoded local frames"
                image = QImage.fromData(frames[-1][1])
                assert (image.width(), image.height()) == (1920, 1080), "Douyu source was downscaled"
                duration = frames[-1][0] - frames[0][0]
                fps = (len(frames) - 1) / duration
                assert abs(fps - 60) < .01, f"60 fps source reduced to {fps:.1f} fps"
                assert len({jpeg for _, jpeg in frames[:120]}) == 120, "Motion frames duplicated or discarded"
                assert abs(decoder.history.snapshots()[1].time - decoder.history.snapshots()[0].time - .5) < .001
                assert not any(decoder.history.pcm_at(decoder.history.origin + 1.8, 480))
                assert any(decoder.history.pcm_at(decoder.history.origin + 2.2, 480))
                assert time.monotonic() - decoder.last_frame_received < .5, "Decode pipeline fell behind"
                assert duration >= 3 and time.monotonic() - decoder.history.origin < 4.5
                print("PASS: native 1080P60 motion frames, real-time capture, 2 Hz fingerprints and PCM share media time")
            finally:
                process = decoder.process
                decoder.stop()
                decoder.thread.join(4)
                assert not decoder.thread.is_alive()
                assert process is None or process.poll() is not None, "Orphan FFmpeg"


def viewer_checks(app):
    platform = plugins.Platform()
    platform.kind = "douyu"
    with tempfile.TemporaryDirectory() as root, \
            patch.object(media.Decoder, "start", lambda self: None), \
            patch.object(module, "Chat", FakeChat), patch.object(module, "PlatformChat", FakeChat), \
            patch.object(module.AudioPump, "start", lambda self: None):
        host = QWidget()
        host.settings = {}
        manager = plugins.PluginManager(window=host, plugins_dir=root)
        with patch.object(manager, "platform_for", side_effect=lambda rid: platform if rid.startswith("douyu:") else None):
            viewer = module.Viewer(plugins.PluginContext(manager, "picture_check"), {})
            try:
                viewer.add_room("1")
                viewer.add_room("douyu:42")
                viewer.toggle_running()
                viewer.rows["douyu:42"].delay.setValue(-1)
                shifts = viewer.shifts()
                viewer.main.setCurrentIndex(viewer.main.findData("douyu:42"))
                assert viewer.render_timer.interval() <= 16, "Douyu main picture still limited to 30 Hz"
                viewer.main.setCurrentIndex(viewer.main.findData("1"))
                assert viewer.render_timer.interval() == 33
                assert viewer.shifts() == shifts and viewer.alignment.manual_locked
                print("PASS: main picture switches between 60/30 Hz without restarting decoders or changing locked offsets")
            finally:
                viewer.close()
                host.close()
                app.processEvents()


if __name__ == "__main__":
    app = QApplication([])
    picture_checks(app)
    viewer_checks(app)
