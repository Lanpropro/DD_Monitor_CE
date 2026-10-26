"""Large offsets need temporal evidence; explicit retry remains after assistance UI removal."""
import os
from pathlib import Path
import sys
import tempfile
from dataclasses import replace
from collections import deque
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('DDM_NO_SAVE', '1')
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication, QWidget, QDialog
from PySide6.QtCore import QRectF
from ddm import plugins
from dev.selfcheck_match_sync import FakeChat, FakeDecoder, jpeg
from dev.selfcheck_match_sync_refinement import samples
from plugins_user._match_sync import viewer as module
from plugins_user._match_sync.engine import Match, assisted_match, History
from plugins_user._match_sync.video import VideoHistory


def main():
    app = QApplication([])
    for lag in (16.237, -16.237):
        result = assisted_match(lag + 2.4, samples(), samples(lag, .027, 2))
        assert result.refined and abs(result.lag - lag) < .06, result
    assert assisted_match(16, samples(), samples(-16)).lag is None
    still = [type(sample)(sample.time, sample.signature, sample.texture, bytes([128] * 256)) for sample in samples()]
    assert assisted_match(16, still, still).lag is None
    print('PASS: positive/negative 16s hints refine noisy dynamic scenes; wrong hints and static images are rejected')

    now = [120.0]
    with tempfile.TemporaryDirectory() as root, patch.object(module, 'Decoder', FakeDecoder), \
            patch.object(module, 'Chat', FakeChat), patch.object(module.AudioPump, 'start', lambda _: None), \
            patch.object(module.time, 'monotonic', side_effect=lambda: now[0]):
        host = QWidget()
        host.settings = {}
        viewer = module.Viewer(plugins.PluginContext(plugins.PluginManager(window=host, plugins_dir=root), 'assistance'), {})
        try:
            for key in ('1', '2', '3'):
                viewer.add_room(key, {'crop': [.1, .1, .5, .3]} if key == '2' else {})
            viewer.toggle_running()
            viewer.render_timer.stop()
            viewer.match_timer.stop()
            image = jpeg()
            for row in viewer.rows.values():
                for stamp in range(70 * 20, 170 * 20):
                    row.decoder.history.append(stamp / 20, image)
                row.decoder.last_frame_received = now[0]
            viewer.render()
            main_shift = viewer.shifts()['1']
            correction = viewer.audio.correction
            row = viewer.rows['2']
            assert row.crop == (.1, .1, .5, .3)
            assert row.decoder.crop == (0, 0, 1, 1), 'Saved preview crop must not restrict automatic samples'
            row.user_confirmed_lag = -20  # A previous viewing session is not a current human confirmation.
            candidate = Match(16, 1, 'verified scenes', refined=True, evidence_end=110)
            for _ in range(5):
                viewer._matched(viewer.generation, {'2': candidate})
            assert viewer.alignment.lags.get('2', 0) != 16, 'Repeated deliveries of the same instant are not independent observations'
            for _ in range(3):
                now[0] += 2
                viewer._matched(viewer.generation, {'2': candidate})
            assert viewer.alignment.lags.get('2', 0) != 16, 'A frozen evidence window cannot validate a large offset'
            for _ in range(4):
                now[0] += 2
                candidate = replace(candidate, evidence_end=candidate.evidence_end + 2)
                viewer._matched(viewer.generation, {'2': candidate})
            assert viewer.alignment.lags['2'] == 16
            assert viewer.shifts()['1'] == main_shift and viewer.audio.correction == correction
            row.user_confirmed = row.match_confirmed = True
            row.user_confirmed_lag = 16
            for _ in range(5):
                now[0] += 2
                viewer._matched(viewer.generation, {'2': Match(33, 1, 'suspicious jump', refined=True)})
            assert viewer.alignment.lags['2'] == 16 and '2' not in viewer.independent_shifts

            viewer.show_comparison('2')
            viewer.canvas.set_frame((115, image))
            viewer.comparison_panel.cards['2'][2].set_frame((121, image))
            assert not hasattr(viewer, 'assist_alignment')
            assert not viewer.comparison_panel.findChildren(module.QPushButton, 'MatchSyncAssist')
            before = (viewer.generation, viewer.analysis_serial, dict(viewer.alignment.lags),
                      viewer.shifts(), row.match_confirmed, row.user_confirmed, viewer.audio.correction)
            def select_timer(dialog):
                dialog.findChild(module.Canvas).crop = QRectF(.2, .1, .3, .2)
                return QDialog.Accepted
            with patch.object(QDialog, 'exec', select_timer), patch.object(row.decoder, 'set_crop') as sampling, \
                    patch.object(viewer, 'retry_alignment') as retry:
                viewer.choose_crop(row)
                sampling.assert_not_called()
                retry.assert_not_called()
            assert row.crop == (.2, .1, .3, .2)
            assert before == (viewer.generation, viewer.analysis_serial, dict(viewer.alignment.lags),
                              viewer.shifts(), row.match_confirmed, row.user_confirmed, viewer.audio.correction)
            assert viewer.comparison_panel.zoom.isChecked() and viewer.compare.isChecked()
            for key, detail in (('1', samples()), ('2', samples(16.237, .027, 2))):
                detail = [replace(sample, signature=sum((value >= 128) << bit for bit, value in enumerate(sample.feature)))
                          for sample in detail]
                history = viewer.rows[key].decoder.history
                history.origin = 100
                history.details = deque(detail)
                history.samples = deque(detail[::4])
            row.next_analysis = 0
            viewer.rows['3'].next_analysis = now[0] + 100
            collected = {}
            def inline(**kwargs):
                return SimpleNamespace(start=kwargs['target'])
            bridge = SimpleNamespace(completed=SimpleNamespace(emit=lambda serial, epoch, results: collected.update(results)))
            # An explicit retry uses the existing human-confirmed lag as a
            # first candidate, but must still escape a wrong old lag globally.
            for old_lag in (16.237, 30):
                row.user_confirmed = True
                row.needs_epoch_samples = False
                viewer.alignment.lags['2'] = old_lag
                viewer.rendered_shifts.clear()
                with patch.object(viewer, 'analyse'):
                    viewer.retry_alignment('2')
                assert row.rematch_locally
                with patch.object(viewer, 'results', bridge), patch.object(module.threading, 'Thread', side_effect=inline), \
                        patch.object(module, 'match_scenes', wraps=module.match_scenes) as search, \
                        patch.object(module, 'refine_match', wraps=module.refine_match) as refine:
                    viewer.analyse()
                assert collected['2'].refined and abs(collected['2'].lag - 16.237) < .06, (old_lag, viewer.alignment.lags, collected)
                assert search.called == (old_lag == 30)
                assert all(not call.kwargs.get('focused', False) for call in search.call_args_list + refine.call_args_list)
                assert row.decoder.crop == (0, 0, 1, 1)
            print('PASS: large verified lag accepted; established 16→33 jump held; removed assistance UI and explicit automatic retry preserve main clock')
        finally:
            viewer.close()
            host.close()
            app.processEvents()

    history = History()
    history.append(100, b'frame')
    history.append(160, b'frame')
    assert '早于' in module.cache_gap(history, 90)
    assert '尚未收到' in module.cache_gap(history, 170)
    history = VideoHistory()
    history.frames.extend([(100, b'a'), (110, b'b'), (120, b'c'), (130, b'd')])
    history.intervals.extend([[100, 110], [120, 130]])
    assert '缺口' in module.cache_gap(history, 115)
    assert module.cache_gap(history, 125) == ''
    print('PASS: expired history, future content and in-range outage gaps are distinguished')


if __name__ == '__main__':
    main()
