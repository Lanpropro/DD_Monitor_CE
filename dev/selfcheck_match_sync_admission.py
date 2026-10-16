"""A late source previews real cached content; admission never delays the main."""
import os
from pathlib import Path
import sys
import tempfile
from collections import deque
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('DDM_NO_SAVE', '1')
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication, QWidget
from ddm import plugins
from dev.selfcheck_match_sync import FakeChat, FakeDecoder, jpeg
from plugins_user._match_sync import viewer as module
from plugins_user._match_sync.engine import Match, Sample


def main():
    app = QApplication([])
    now = [120.0]
    with tempfile.TemporaryDirectory() as directory, patch.object(module, 'Decoder', FakeDecoder), \
            patch.object(module, 'Chat', FakeChat), patch.object(module.AudioPump, 'start', lambda _: None), \
            patch.object(module.time, 'monotonic', side_effect=lambda: now[0]):
        host = QWidget()
        host.settings = {}
        viewer = module.Viewer(plugins.PluginContext(plugins.PluginManager(window=host, plugins_dir=directory), 'admission'), {})
        try:
            for key in ('1', '2', '3'):
                viewer.add_room(key, {'alias': key})
            viewer.toggle_running()
            viewer.render_timer.stop()
            viewer.match_timer.stop()
            image = jpeg()
            for key, row in viewer.rows.items():
                end = 116 if key == '2' else 123
                for stamp in range(80 * 20, end * 20 + 1):
                    row.decoder.history.append(stamp / 20, image)
                row.decoder.last_frame_received = now[0]
            viewer.stable_reference_shift = -6
            viewer.alignment.lags['3'] = 0
            viewer.rows['3'].match_confirmed = viewer.rows['3'].user_confirmed = True
            viewer.render()
            main_shift = viewer.shifts()['1']
            candidate = Match(11.2, 1, 'fine late candidate', refined=True)
            for _ in range(2):
                viewer._matched(viewer.generation, {'2': candidate})
            viewer.show_comparison('2')
            viewer.render()
            row = viewer.rows['2']
            canvas, state = viewer.comparison_panel.cards['2'][2:]
            assert row.awaiting_confirmation and row.mix_gain == 0
            assert row.join.text() == '确认当前偏移'
            assert '不改变主画面' in row.join.toolTip()
            assert canvas.preview_only and not canvas.waiting
            assert '独立预览' in state.text() and '尚未与主画面对齐' in state.text()
            assert viewer.shifts()['1'] == main_shift
            # Cached fallback preview is not the synchronized display and
            # must not produce a spurious tens-of-seconds playback error.
            for key in ('1', '2'):
                viewer.rows[key].decoder.history.details = [Sample(100, 0, 10, bytes(256))]
            deliveries = []
            viewer.results.matched.connect(lambda epoch, results: deliveries.append(results['2']))
            viewer.analysis_cursor = 0
            with patch.object(module, 'refine_match', return_value=candidate) as refine, \
                    patch.object(module.threading, 'Thread') as worker:
                worker.side_effect = lambda **kw: type('Inline', (), {'start': lambda self: kw['target']()})()
                viewer.analyse()
            assert deliveries and deliveries[-1].playback_error is None
            assert not any(call.args[0].reason == '播放进度复核' for call in refine.call_args_list)
            for key in ('1', '2'):
                viewer.rows[key].decoder.history.details = []
            previous = canvas.frame_key
            start = previous
            for tick in range(40):
                now[0] += .05
                for key, current in viewer.rows.items():
                    end = 116 if key == '2' else 123
                    current.decoder.history.append(end + (tick + 1) * .05, image)
                    current.decoder.last_frame_received = now[0]
                viewer.render()
                assert canvas.preview_only and not canvas.waiting and canvas.frame_key >= previous
                assert row.mix_gain == 0 and viewer.shifts()['1'] == main_shift
                previous = canvas.frame_key
            assert canvas.frame_key - start >= 1.8, 'Preview must advance even while the required synchronized target is unavailable'
            clock, fixed_shifts = viewer.audio.clock(), viewer.shifts()
            row.join.click()
            assert viewer.audio.clock() == clock and viewer.shifts() == fixed_shifts
            assert row.user_confirmed and not row.awaiting_confirmation and row.mix_gain == 0
            assert '副路晚到' in row.match_text and '2' not in viewer.admitted_rooms
            # A sustained late feed does not become playable by confirming it.
            for _ in range(5):
                assert viewer.admit_pending('2') is False
                assert viewer.shifts() == fixed_shifts and viewer.audio.clock() == clock
            # New content can cover the fixed target without changing either clock.
            for stamp in range(118 * 20, 136 * 20):
                row.decoder.history.append(stamp / 20, image)
            assert viewer.admit_pending('2')
            assert viewer.audio.clock() == clock and viewer.shifts() == fixed_shifts
            now[0] += .6
            viewer.render()
            assert not canvas.preview_only and not canvas.waiting
            assert row.match_confirmed and row.mix_gain == 1
            assert abs(row.actual_position - viewer.rows['1'].actual_position - 11.2) < .06
            # Later optional confirmation is a different action and must never
            # incur the initial safety-reserve delay again.
            main_shift = viewer.shifts()['1']
            for _ in range(2):
                viewer._matched(viewer.generation, {'2': Match(11.8, 1, 'new offset', refined=True, playback_error=.6)})
            viewer.render()
            assert row.join.text() == '确认当前偏移（可选）' and not canvas.preview_only and row.mix_gain == 1
            clock, shifts = viewer.audio.clock(), viewer.shifts()
            row.join.click()
            assert viewer.audio.clock() == clock and viewer.shifts() == shifts and viewer.shifts()['1'] == main_shift
            # Even a small valid headroom must not trigger reserve replenishment.
            target = clock + shifts['2']
            with patch.object(row.decoder.history, 'bounds_at', return_value=(target - 20, target + .1)):
                assert viewer.admit_pending('2')
                assert viewer.audio.clock() == clock and viewer.shifts() == shifts
            # An overall history span cannot make a timestamp gap playable.
            with patch.object(row.decoder.history, 'bounds_at', return_value=(target + 1, target + 2)):
                assert viewer.admit_pending('2') is False
                assert row.mix_gain == 0 and viewer.shifts() == shifts
            row.recheck_alignment = False
            viewer._queue_rematch(row)
            row.needs_epoch_samples = True
            for key in ('1', '2'):
                viewer.rows[key].decoder.history.details = [Sample(100, 0, 10, bytes(256)), Sample(103, 1, 10, bytes(256))]
            viewer.analysis_cursor = 0
            with patch.object(module, 'refine_match', return_value=candidate), \
                    patch.object(module.threading, 'Thread') as worker:
                worker.side_effect = lambda **kw: type('Inline', (), {'start': lambda self: kw['target']()})()
                viewer.analyse()
            assert deliveries[-1].lag is None and '4 秒' in deliveries[-1].reason and not row.match_confirmed
            for key in ('1', '2'):
                viewer.rows[key].decoder.history.details = []
            # A join cannot be made valid by delaying the main if the requested
            # secondary timestamp is already older than its earliest cached frame.
            saved_frames = row.decoder.history.frames
            target = viewer.audio.clock() + viewer.shifts()['2']
            row.decoder.history.frames = deque((target + 1 + n, image) for n in range(10))
            row.match_confirmed = True
            before = viewer.shifts()['1']
            assert viewer.admit_pending('2', automatic=True) is False
            assert not row.match_confirmed and not row.rematch_locally and '2' in viewer.rematch_rooms
            assert viewer.shifts()['1'] == before
            row.decoder.history.frames = saved_frames
            # An actual decoder epoch can move the offset beyond the ordinary
            # 15s guard, but cannot automatically rewind the healthy main.
            row.needs_epoch_samples = True
            main_before_epoch = viewer.shifts()['1']
            for _ in range(2):
                viewer._matched(viewer.generation, {'2': Match(26, 1, 'verified new epoch', refined=True)})
            assert viewer.alignment.lags['2'] == 26 and '2' not in viewer.independent_shifts
            assert viewer.shifts()['1'] == main_before_epoch
            viewer.alignment.lags['2'] = shifts['2'] - shifts['1']
            row.needs_epoch_samples = False
            row.match_confirmed = True
            # Reacquisition of a previously admitted source must retain strict
            # playback verification instead of substituting an independent preview.
            current_lag = viewer.alignment.lags['2']
            viewer.alignment.lags['2'] = 30
            viewer.rendered_shifts.clear()
            viewer.shift_reference = None
            viewer.render()
            assert not canvas.preview_only and row.mix_gain == 0
            viewer.alignment.lags['2'] = current_lag
            row.recheck_alignment = False
            viewer.rendered_shifts.clear()
            viewer.shift_reference = None
            canvas.preview_only = True
            canvas.preview_shift = -10
            viewer.select_main('2')
            viewer.render()
            assert not canvas.preview_only and canvas.preview_shift is None
            assert '独立预览' not in state.text()
        finally:
            viewer.close()
            host.close()
            app.processEvents()
    print('PASS: advancing cached preview before late admission, truthful unsynced labels, fixed main through late admission, cache recovery and optional confirmation without seeking')


if __name__ == '__main__':
    main()
