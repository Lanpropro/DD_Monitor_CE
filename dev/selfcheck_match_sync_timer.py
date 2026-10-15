"""Explicit timer ROI matching with real rendered digits and independent sample clocks."""
import math
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtGui import QFontDatabase, QImage
from PySide6.QtWidgets import QApplication, QWidget
from ddm import plugins
from dev.selfcheck_match_sync import FakeDecoder, FakeChat
from dev.selfcheck_match_sync_offsets import clock_jpeg
from plugins_user._match_sync.engine import Match, Sample, match_scenes, refine_match
from plugins_user._match_sync.media import av, fingerprint, frame_sample, scene_feature
from plugins_user._match_sync.engine import np
from plugins_user._match_sync import viewer as module


def samples(lag=0, scale=1, paused=False, repeated=False):
    result = []
    for i in range(360):
        stamp = i * .05
        reading = 90 if paused else 112 - math.floor(stamp - lag)
        if repeated:
            reading = 90 + reading % 2
        image = QImage.fromData(clock_jpeg(reading, scale))
        result.append(Sample(stamp, *fingerprint(image), scene_feature(image, (0, 0, 1, 1))))
    return result


def main():
    app = QApplication([])
    assert QFontDatabase.addApplicationFont('C:/Windows/Fonts/consola.ttf') >= 0
    native = []
    for width, height, lag in ((3840, 2160, 0), (1920, 1080, 4.537)):
        sequence = []
        for i in range(300):
            stamp = i * .05
            clock = QImage.fromData(clock_jpeg(112 - math.floor(stamp - lag))).scaled(90, 36).convertToFormat(QImage.Format_Grayscale8)
            plane = np.full((height, width), 40, dtype=np.uint8)
            plane[10:46, 10:100] = np.frombuffer(clock.constBits(), dtype=np.uint8).reshape(36, clock.bytesPerLine())[:, :90]
            frame = av.VideoFrame.from_ndarray(plane, format='gray')
            sequence.append(frame_sample(frame, stamp, (10 / width, 10 / height, 90 / width, 36 / height), (640, 360)))
        native.append(sequence)
    coarse = match_scenes(native[0][::4], native[1][::4], focused=True)
    fine = refine_match(coarse, *native, focused=True)
    assert fine.lag is not None and abs(fine.lag - 4.537) <= .06, (coarse, fine)
    print('PASS: a 90x36 timer cropped from native 4K/1080p frames retains timing detail')
    reference = samples()
    for lag in (4.537, -2.163):
        other = samples(lag, 2)
        coarse = match_scenes(reference[::4], other[::4], focused=True)
        fine = refine_match(coarse, reference, other, focused=True)
        assert fine.refined and fine.lag is not None and abs(fine.lag - lag) <= .06 and fine.confidence >= .65, (coarse, fine)
        print(f'PASS: timer ROI lag {lag:.3f}s -> {fine.lag:.3f}s')
    still = samples(paused=True)
    assert refine_match(Match(0, 1, 'test'), still, still, focused=True).lag is None
    repeat = samples(repeated=True)
    assert refine_match(match_scenes(repeat[::4], repeat[::4]), repeat, repeat, focused=True).lag is None
    with tempfile.TemporaryDirectory() as root, patch.object(module, 'Decoder', FakeDecoder), \
            patch.object(module, 'Chat', FakeChat), patch.object(module.AudioPump, 'start', lambda _: None):
        host = QWidget()
        host.settings = {}
        ctx = plugins.PluginContext(plugins.PluginManager(window=host, plugins_dir=root), 'timer_check')
        viewer = module.Viewer(ctx, {})
        try:
            for key in ('1', '2'):
                viewer.add_room(key, {'alias': key, 'crop': [.1, .1, .8, .8]})
            viewer.toggle_running()
            viewer.render_timer.stop()
            viewer.match_timer.stop()
            viewer.audio.clock = lambda: 17.9
            for key, detail in (('1', reference), ('2', samples(4.537, 2))):
                row = viewer.rows[key]
                for sample in detail:
                    row.decoder.history.append(sample.time, clock_jpeg(90), sample)
                row.decoder.history.details = detail
                row.decoder.last_frame_received = module.time.monotonic()
            viewer.render()
            # A timer still gathering enough changing digits must not fall back
            # after the old ten-second deadline or three early uncertain results.
            row = viewer.rows['2']
            with patch.object(module.time, 'monotonic', return_value=row.alignment_started + 12):
                for _ in range(3):
                    viewer._matched(viewer.generation, {'2': Match(None, 0, '精校正时间差不明确')})
            assert '2' not in viewer.independent_shifts
            with patch.object(module.threading, 'Thread') as worker:
                worker.side_effect = lambda **kwargs: type('Inline', (), {'start': lambda self: kwargs['target']()})()
                viewer.analyse()
                viewer.analyse()
            assert row.match_confirmed and abs(viewer.alignment.lags['2'] - 4.537) <= .06, (row.match_text, viewer.alignment.lags, viewer.canvas.waiting)
            assert not viewer.rows['1'].paused
            print('PASS: viewer confirms focused timer lag; early ambiguity preserves playback and continues gathering')
        finally:
            viewer.close()
            host.close()
    app.quit()


if __name__ == '__main__':
    main()
