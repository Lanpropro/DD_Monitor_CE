"""Original compressed video, native PTS/pixels, asynchronous presentation and bounds."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque
from dataclasses import replace
from fractions import Fraction
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
os.environ["DDM_NO_SAVE"] = "1"
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication
from ddm import plugins, recording
from plugins_user._match_sync import media, video
from plugins_user._match_sync.viewer import Canvas


def ready(decoder, timestamp, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = decoder.picture_at(timestamp, exact=True)
        if result is not None:
            return result
        time.sleep(.005)
    raise AssertionError(("Picture not prepared", decoder.diagnostics(), timestamp, decoder.history.bounds()))


def fixture(executable, source, size, rate, seconds):
    subprocess.run([executable, "-hide_banner", "-loglevel", "error", "-nostdin",
        "-f", "lavfi", "-i", f"testsrc2=size={size}:rate={rate}",
        "-f", "lavfi", "-i", r"aevalsrc=if(lt(t\,1)\,0\,0.3*sin(2*PI*440*t)):s=48000",
        "-t", str(seconds), "-c:v", "libx264", "-threads", "2", "-preset", "ultrafast",
        "-g", "60", "-bf", "2", "-c:a", "pcm_s16le", str(source)],
        check=True, capture_output=True, timeout=40, creationflags=recording._FFMPEG_FLAGS)


def run(app):
    executable = recording.ffmpeg_path()
    assert executable and video.av is not None
    for address in ("https://live.test/feed.flv", "http://live.test/feed.m3u8", "rtmp://live.test/feed"):
        command = media.decode_command(executable, address, {}, 12345)
        assert "-readrate" not in command, "Live sources must consume bursts without forced throttling"
    assert "-readrate" in media.decode_command(executable, "fixture.mkv", {}, 12345)
    bounded = video.VideoHistory(seconds=1, byte_limit=6000)
    pending = video.VideoHistory()
    pending.pending_frames = deque((.1, .2))
    assert pending.bounds() is None, "Unanchored media must not move the shared clock into source PTS"
    pending.set_origin(100)
    assert pending.frames[0] == (100.1, .1)
    assert pending.origin == 100
    bounded.origin = 100
    bounded.codec = ("h264", b"")
    unanchored = video.VideoHistory(seconds=1, byte_limit=6000)
    for index in range(20):
        packet = video.av.Packet(b"x" * 1000)
        packet.pts = packet.dts = index
        packet.time_base = Fraction(1, 10)
        packet.is_keyframe = index % 4 == 0
        bounded.append_packet(packet)
        bounded.append(100 + index / 10, index / 10)
        unanchored.append_packet(packet)
        unanchored.append(index / 10, index / 10)
        assert len(unanchored.pending_frames) <= 6
        assert not unanchored.frames and not unanchored.snapshots()
        assert bounded.byte_size <= 6000
        assert not bounded.packets or bounded.packets[0].keyframe
        assert not bounded.frames or bounded.frames[0][1] >= bounded.packets[0].time
    assert bounded.frame_at(100) is None
    assert bounded.packet_range(None, 1.9)[2]
    print("PASS: compressed history stays bounded and retains only decodable complete GOPs")
    with tempfile.TemporaryDirectory(prefix="ddm_native_video_", ignore_cleanup_errors=True) as root:
        source = Path(root) / "1440p60.mkv"
        fixture(executable, source, "2560x1440", "60", 7)
        decoders = []
        canvas = Canvas()
        try:
            for kind in ("bilibili", "huya", "douyu"):
                platform = plugins.Platform()
                platform.kind = kind
                platform.room_info = lambda rid: plugins.RoomInfo(rid, uname="Local")
                platform.play_url = lambda rid, qn: (str(source), 80, "local", {})
                decoder = media.Decoder(kind + ":42", {"quality": 80}, platform)
                decoders.append(decoder)
                decoder.start()
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                app.processEvents()
                if all(d.history.received_frames >= 181 for d in decoders):
                    break
                time.sleep(.005)
            for decoder in decoders:
                with decoder.history.lock:
                    frames = list(decoder.history.frames)
                assert len(frames) >= 180, decoder.diagnostics()
                assert decoder.video_size == (2560, 1440)
                assert abs(decoder.fps - 60) < .01, decoder.diagnostics()
                assert abs((frames[119][0] - frames[0][0]) - 119 / 60) < .002
                assert time.monotonic() - frames[0][0] < 4.3, "Concurrent decoders fall behind"
                assert not any(decoder.history.pcm_at(decoder.history.origin + .8, 480))
                assert any(decoder.history.pcm_at(decoder.history.origin + 1.2, 480))
            print("PASS: Bilibili/Huya/Douyu retain 1440P60 and B-frame PTS with three concurrent real-time decoders")
            decoder = decoders[0]
            frame = list(decoder.history.frames)[90]
            shown = ready(decoder, frame[0])
            # Decode the source itself; playback must contain identical native pixels.
            with video.av.open(str(source)) as container:
                reference = next(f for i, f in enumerate(container.decode(video=0)) if i == 90)
                expected = video.image_from_frame(reference)
            assert shown[1] == expected, "Native pixels changed during caching/playback"
            with patch.object(media.QImage, "fromData", side_effect=AssertionError("JPEG decode on GUI thread")):
                canvas.set_frame(shown)
                assert canvas.image == expected and canvas.frame_key == frame[0]
            assert len(decoder.pictures.images) <= 8
            assert sum(image.sizeInBytes() for image in decoder.pictures.images.values()) <= 64 * 1024 * 1024
            # Backwards seek, forwards seek, and another decoder cannot reuse stale pictures.
            for index in (30, 130, 60):
                frame = list(decoder.history.frames)[index]
                assert ready(decoder, frame[0])[0] == frame[0]
            other = decoders[1]
            other_frame = list(other.history.frames)[90]
            changed = decoder.pictures.get(other.history, other_frame, exact=True)
            assert changed is None, "Another source inherited an old decoded image"
            deadline = time.monotonic() + 2
            while changed is None and time.monotonic() < deadline:
                time.sleep(.005)
                changed = decoder.pictures.get(other.history, other_frame, exact=True)
            assert changed is not None and changed[0] == other_frame[0]
            print("PASS: byte-identical decoded source pixels; backward/forward seek, bounded prefetch, no GUI JPEG decode")
            # Poll a moving playback timeline, measuring actual frame presentation.
            clock = decoder.history.origin + 1
            from dev.selfcheck_match_sync_refinement import samples
            from plugins_user._match_sync.engine import Alignment, Match, match_scenes, refine_match
            def long_history(lag=0, phase=0, noise=0):
                return [replace(s, signature=sum((value > 128) << i for i, value in enumerate(s.feature)))
                        for s in samples(lag, phase, noise, count=1201)]
            fine_reference, fine_other = long_history(), long_history(7.237, .027, 2)
            canvas.resize(960, 540)
            canvas.show()
            canvas.set_frame(ready(decoder, clock))
            canvas.presented = 0
            finish_analysis = threading.Event()
            analysis_errors, analysis_rounds = [], []

            def analyse():
                try:
                    while not finish_analysis.is_set():
                        started = time.perf_counter()
                        coarse = match_scenes(fine_reference[::4], fine_other[::4])
                        fine = refine_match(coarse, fine_reference, fine_other)
                        assert fine.lag is not None and abs(fine.lag - 7.237) < .06, fine
                        analysis_rounds.append(time.perf_counter() - started)
                except Exception as error:
                    analysis_errors.append(error)

            analysis = threading.Thread(target=analyse, daemon=True)
            analysis.start()
            start = time.monotonic()
            ticks = 0
            drift = Alignment()
            drift.lags["other"] = 0
            drift.candidates["other"] = (.15, 2)
            next_tracking = .25
            try:
                while time.monotonic() - start < 1:
                    elapsed = time.monotonic() - start
                    if elapsed >= next_tracking:
                        drift.accept("other", Match(.15, 1, "tracking", refined=True))
                        next_tracking += .25
                    canvas.show_at(decoder, clock + elapsed - drift.lags["other"])
                    app.processEvents()
                    ticks += 1
                    time.sleep(.004)
            finally:
                finish_analysis.set()
                analysis.join(3)
                assert not analysis.is_alive()
            assert not analysis_errors and analysis_rounds, analysis_errors
            print(f"MEASURE: full 60s coarse/fine matching completed {len(analysis_rounds)} rounds, longest {max(analysis_rounds):.3f}s")
            print(f"MEASURE: {canvas.presented} distinct pictures in 1s; {ticks} presentation polls; {decoder.diagnostics()}")
            assert canvas.presented >= 50, "Presentation falls behind during full analysis and repeated backward tracking"
        finally:
            for decoder in decoders:
                decoder.stop()
            for decoder in decoders:
                decoder.thread.join(4)
                assert not decoder.thread.is_alive()
                assert decoder.process is None
            assert not any(t.name == "match-sync-picture" and t.is_alive() for t in threading.enumerate())
            canvas.close()
        for rate in ("30", "60000/1001"):
            source = Path(root) / (rate.replace("/", "_") + ".mkv")
            fixture(executable, source, "320x180", rate, 4)
            decoder = media.Decoder("local", {"url": str(source)})
            try:
                decoder.start()
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline and decoder.history.received_frames < 50:
                    time.sleep(.005)
                frames = list(decoder.history.frames)
                expected_rate = 30 if rate == "30" else 60000 / 1001
                assert abs((frames[49][0] - frames[0][0]) - 49 / expected_rate) < .002
                assert abs(decoder.fps - expected_rate) < .1
            finally:
                decoder.stop()
                decoder.thread.join(4)
        print("PASS: 30 and 59.94 fps retain source timing without duplicated/dropped capture frames")


if __name__ == "__main__":
    run(QApplication([]))
