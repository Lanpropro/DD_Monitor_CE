"""Compare two/three native streams while drawing, matching and mixing audio."""
import os
from pathlib import Path
import random
import statistics
import sys
import tempfile
import threading
import time
from array import array
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
os.environ.setdefault("DDM_NO_SAVE", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from ddm import recording
from dev.selfcheck_match_sync_video import fixture, ready
from dev.selfcheck_match_sync_refinement import samples
from plugins_user._match_sync import engine, media, video
from PySide6.QtGui import QImage
from plugins_user._match_sync.viewer import Canvas


def mixing_checks():
    rng = random.Random(761)
    for count in (0, 1, 2, 3, 6):
        for frames in (1, 240, 2048):
            inputs = [(array("h", [rng.randrange(-32768, 32768) for _ in range(frames * 2)]).tobytes(),
                       rng.choice((-1, 0, 1, 33, 50, 73, 100, 110))) for _ in range(count)]
            with patch.object(engine, "np", None):
                expected = engine.mix_pcm(inputs, frames)
            assert engine.mix_pcm(inputs, frames) == expected
    for pcm, volume in ((array("h", [1, -1, 3, -3]).tobytes(), 50),
                        (array("h", [32767, -32768] * 2).tobytes(), 100)):
        with patch.object(engine, "np", None):
            expected = engine.mix_pcm([(pcm, volume)] * 3, 2)
        assert engine.mix_pcm([(pcm, volume)] * 3, 2) == expected
    pcm = array("h", [12345, -23456] * 2048).tobytes()
    inputs = [(pcm, 73)] * 3
    elapsed = []
    for vectorized in (False, True):
        trials = []
        with patch.object(engine, "np", engine.np if vectorized else None):
            for _ in range(5):
                start = time.perf_counter()
                for _ in range(100):
                    engine.mix_pcm(inputs, 2048)
                trials.append((time.perf_counter() - start) / 100)
        elapsed.append(statistics.median(trials))
    print(f"MEASURE: three-stream mixing {elapsed[0]*1000:.3f} -> {elapsed[1]*1000:.3f} ms/fill")
    assert elapsed[1] < elapsed[0] / 2, "Batch mixing must reduce GUI work"
    print("PASS: byte-identical gain, headroom, clipping, rounding and mute behavior")


def image_checks():
    for width in (17, 1919, 2560):
        pixels = engine.np.random.default_rng(width).integers(0, 256, (27, width, 4), dtype=engine.np.uint8)
        frame = video.av.VideoFrame.from_ndarray(pixels, format="bgra")
        plane = frame.planes[0]
        expected = QImage(bytes(plane), width, 27, plane.line_size, QImage.Format_ARGB32).copy()
        actual = video.image_from_frame(frame)
        assert actual == expected, "Padded native rows must retain all pixels"
        plane.update(bytes(plane.buffer_size))
        assert actual == expected, "Retained pictures must own their memory"
    print("PASS: single-copy native images preserve padding, exact pixels and ownership")


def play(app, source, count):
    decoders = [media.Decoder(str(i), {"url": str(source)}) for i in range(count)]
    canvases = [Canvas(), Canvas()]
    stop = threading.Event()
    errors = []
    histories = [samples(i * 2.233, .027 * i, 2, count=1201) for i in range(count)]

    def analyse():
        try:
            while not stop.is_set():
                for i, history in enumerate(histories[1:], 1):
                    match = engine.refine_match(engine.Match(i * 2.233, .9, "tracking"), histories[0], history)
                    assert match.lag is not None
                stop.wait(.02)
        except Exception as error:
            errors.append(error)

    worker = None
    try:
        for canvas in canvases:
            canvas.resize(960, 540)
            canvas.show()
        for decoder in decoders:
            decoder.start()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and any(d.history.received_frames < 180 for d in decoders):
            app.processEvents()
            time.sleep(.005)
        assert all(d.history.received_frames >= 180 for d in decoders)
        for i, canvas in enumerate(canvases):
            canvas.set_frame(ready(decoders[i], decoders[i].history.origin + 1))
            canvas.presented = 0
        worker = threading.Thread(target=analyse, daemon=True)
        worker.start()
        start = time.monotonic()
        next_audio = 0
        while time.monotonic() - start < 1.5:
            elapsed = time.monotonic() - start
            for i, canvas in enumerate(canvases):
                canvas.show_at(decoders[i], decoders[i].history.origin + 1 + elapsed)
            if elapsed >= next_audio:
                pcm = [(d.history.pcm_at(d.history.origin + 1 + elapsed, 2048), 73) for d in decoders]
                assert len(engine.mix_pcm(pcm, 2048)) == 8192
                next_audio = elapsed + 2048 / engine.RATE
            app.processEvents()
            time.sleep(.003)
        result = min(canvas.presented / (time.monotonic() - start) for canvas in canvases)
        assert not errors, errors
        assert all(d.video_size == (2560, 1440) and abs(d.fps - 60) < .01 for d in decoders)
        assert all(d.diagnostics()["recent_received_fps"] >= 58 for d in decoders)
        print(f"MEASURE: {count} streams, two visible native pictures + matching + audio: {result:.1f} distinct fps")
        return result
    finally:
        stop.set()
        if worker is not None:
            worker.join(3)
            assert not worker.is_alive()
        for decoder in decoders:
            decoder.stop()
        for decoder in decoders:
            decoder.thread.join(4)
            assert not decoder.thread.is_alive()
        for canvas in canvases:
            canvas.close()


def main():
    mixing_checks()
    image_checks()
    app = QApplication([])
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as root:
        source = Path(root) / "1440p60.mkv"
        fixture(recording.ffmpeg_path(), source, "2560x1440", "60", 7)
        two = play(app, source, 2)
        three = play(app, source, 3)
        assert three >= 45 and three >= two * .8, (two, three)
    print("PASS: three-stream presentation stays responsive with native quality and source timing")


if __name__ == "__main__":
    main()
