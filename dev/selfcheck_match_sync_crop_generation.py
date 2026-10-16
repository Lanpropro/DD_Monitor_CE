"""Changing ROI cannot publish an already-computing feature from the old region."""
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from dataclasses import replace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('DDM_NO_SAVE', '1')
from PySide6.QtWidgets import QApplication
from ddm import recording
from dev.selfcheck_match_sync_video import fixture
from plugins_user._match_sync import media


def main():
    app = QApplication([])
    entered, release = threading.Event(), threading.Event()
    armed = [True]
    original = media.frame_sample
    crops = ((0, 0, 1, 1), (.1, .1, .8, .8), (.2, .1, .7, .8))

    def delayed(frame, timestamp, crop, size):
        sample = replace(original(frame, timestamp, crop, size), signature=crops.index(tuple(crop)))
        if armed[0]:
            armed[0] = False
            entered.set()
            assert release.wait(5), 'Test did not release feature computation'
        return sample

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as root:
        source = Path(root) / 'scene.mkv'
        fixture(recording.ffmpeg_path(), source, '320x180', 60, 6)
        decoder = media.Decoder('test', {'url': str(source)})
        try:
            with patch.object(media, 'frame_sample', side_effect=delayed):
                decoder.start()
                for generation, crop in enumerate(crops[1:], 1):
                    assert entered.wait(5), 'No in-flight sample to race with set_crop'
                    decoder.set_crop(crop)
                    release.set()
                    deadline = time.monotonic() + 3
                    while time.monotonic() < deadline:
                        app.processEvents()
                        with decoder.history.lock:
                            details = list(decoder.history.details)
                            coarse = list(decoder.history.samples)
                        if len(details) >= 12 and coarse:
                            break
                        time.sleep(.01)
                    assert details and coarse
                    assert {sample.signature for sample in details + coarse} == {generation}, 'Old ROI sample republished after clear'
                    assert all(len(sample.feature) == 6144 for sample in details + coarse)
                    assert decoder.history.received_frames >= 12
                    if generation == 1:
                        entered.clear()
                        release.clear()
                        armed[0] = True
        finally:
            release.set()
            decoder.stop()
            if decoder.thread is not None:
                decoder.thread.join(5)
                assert not decoder.thread.is_alive()
            app.processEvents()
    print('PASS: real decoder discards in-flight full-frame→ROI and ROI→ROI samples; detailed/coarse features stay in one generation and video reception continues')


if __name__ == '__main__':
    main()
