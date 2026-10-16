"""Explicit timer ROI matching with real rendered digits and independent sample clocks."""
import math
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter
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


def scoreboard_samples(lag=0, paused=False):
    result = []
    for i in range(360):
        stamp = i * .05
        image = QImage(760, 180, QImage.Format_RGB32)
        image.fill(QColor('#625346'))
        painter = QPainter(image)
        painter.fillRect(60, 18, 540, 80, QColor('#172c43'))
        painter.fillRect(60, 18, 160, 80, QColor('#344fa0'))
        painter.fillRect(440, 18, 160, 80, QColor('#92364c'))
        font = QFont('Consolas')
        font.setPixelSize(45)
        painter.setFont(font)
        painter.setPen(Qt.white)
        painter.drawText(QRect(120, 18, 90, 80), Qt.AlignCenter, '7')
        painter.drawText(QRect(440, 18, 90, 80), Qt.AlignCenter, '1')
        clock = QImage.fromData(clock_jpeg(95 if paused else 112 - math.floor(stamp - lag)))
        painter.drawImage(QRect(285, 30, 70, 29), clock)
        font.setPixelSize(12)
        painter.setFont(font)
        painter.drawText(QRect(275, 64, 100, 22), Qt.AlignCenter, 'ROUND 9')
        painter.end()
        gray = image.convertToFormat(QImage.Format_Grayscale8)
        plane = np.frombuffer(gray.constBits(), dtype=np.uint8).reshape(180, gray.bytesPerLine())[:, :760].copy()
        frame = av.VideoFrame.from_ndarray(plane, format='gray')
        result.append(frame_sample(frame, stamp, (0, 0, .999, .999), (640, 360)))
    return result


def main():
    app = QApplication([])
    assert QFontDatabase.addApplicationFont('C:/Windows/Fonts/consola.ttf') >= 0
    board_reference, board_other = scoreboard_samples(), scoreboard_samples(2.36)
    board_coarse = match_scenes(board_reference[::4], board_other[::4], focused=True)
    board_fine = refine_match(board_coarse, board_reference, board_other, focused=True)
    assert board_fine.lag is not None and abs(board_fine.lag - 2.36) <= .06, (board_coarse, board_fine)
    print('PASS: a small changing timer inside a largely static scoreboard aligns without discarding its digit evidence')
    frozen_board = scoreboard_samples(paused=True)
    assert match_scenes(frozen_board[::4], frozen_board[::4], focused=True).lag is None
    assert refine_match(Match(0, 1, 'paused scoreboard'), frozen_board, frozen_board, focused=True).lag is None
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
