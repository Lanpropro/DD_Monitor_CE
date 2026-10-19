"""Verified secondary drift slews through continuous cache without seeking the main."""
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('DDM_NO_SAVE', '1')
from PySide6.QtWidgets import QApplication, QWidget
from ddm import plugins
from dev.selfcheck_match_sync import FakeChat, FakeDecoder, jpeg
from plugins_user._match_sync import viewer as module
from plugins_user._match_sync.video import VideoHistory


def main():
    app = QApplication([])
    now = [120.0]
    with tempfile.TemporaryDirectory() as root, patch.object(module, 'Decoder', FakeDecoder), \
            patch.object(module, 'Chat', FakeChat), patch.object(module.AudioPump, 'start', lambda _: None), \
            patch.object(module.time, 'monotonic', side_effect=lambda: now[0]):
        host = QWidget()
        host.settings = {}
        viewer = module.Viewer(plugins.PluginContext(plugins.PluginManager(window=host, plugins_dir=root), 'smoothing'), {})
        try:
            for key in ('1', '2', '3'):
                viewer.add_room(key)
            viewer.toggle_running()
            viewer.render_timer.stop()
            viewer.match_timer.stop()
            image = jpeg()
            row = viewer.rows['2']
            row.user_confirmed = row.match_confirmed = True
            row.sync_state = '已同步'
            row.alignment_started = 100
            viewer.rematch_rooms.clear()
            for stamp in range(100, 161):
                row.decoder.history.append(stamp, image)
            original = {'1': -6, '2': -6, '3': -6}
            for delta in (-.6, .6):
                now[0] = 120
                viewer.shift_reference = None
                viewer.shift_updated = None
                viewer._smooth_shifts(original)
                previous = dict(original)
                last_position = now[0] + previous['2']
                wanted = dict(original, **{'2': -6 + delta})
                for _ in range(1100):
                    now[0] += 1 / 60
                    actual = viewer._smooth_shifts(wanted)
                    assert actual['1'] == original['1'] and actual['3'] == original['3']
                    assert abs(actual['2'] - previous['2']) <= .04 / 60 + 1e-9
                    assert .96 - 1e-9 <= viewer.relative_rates['2'] <= 1.04 + 1e-9
                    assert now[0] + actual['2'] > last_position, 'Smoothing replayed or held a frame position'
                    last_position = now[0] + actual['2']
                    previous = actual
                assert abs(actual['2'] - wanted['2']) <= .1001
            # Startup, a new epoch, rematching or a large correction must not slowly replay obsolete content.
            for mode in ('initial', 'epoch', 'rematch', 'settling', 'isolated', 'large', 'cache-gap'):
                row.user_confirmed = mode != 'initial'
                row.sync_state = '暂时隔离' if mode == 'isolated' else '已同步'
                row.alignment_started = now[0] if mode == 'settling' else now[0] - 10
                row.needs_epoch_samples = mode == 'epoch'
                viewer.rematch_rooms = {'2'} if mode == 'rematch' else set()
                viewer.rendered_shifts = dict(original)
                viewer.shift_reference = '1'
                viewer.shift_updated = now[0] - .05
                wanted = dict(original, **{'2': -6 + (2 if mode == 'large' else .6)})
                if mode == 'cache-gap':
                    history = VideoHistory()
                    history.frames.extend([(110, b'a'), (150, b'b')])
                    position = viewer.audio.clock() - 6
                    history.intervals.extend([[110, position + .2], [position + .4, 150]])
                    row.decoder.history = history
                assert viewer._smooth_shifts(wanted) == wanted, mode
            print('PASS: ±600ms drift converges with at most 4% secondary speed change; main/peer stay fixed; startup, epoch, rematch, >800ms and cache gaps bypass smoothing')
        finally:
            viewer.close()
            host.close()
            app.processEvents()


if __name__ == '__main__':
    main()
