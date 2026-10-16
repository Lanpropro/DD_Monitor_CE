"""Confirmed cached playback survives uncertainty; later offset reviews are optional."""
import os
from pathlib import Path
import sys
import tempfile
from array import array
from collections import deque
from dataclasses import replace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('DDM_NO_SAVE', '1')
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication, QWidget
from ddm import plugins
from dev.selfcheck_match_sync import FakeChat, FakeDecoder, FakeDevice, FakeSink, jpeg
from dev.selfcheck_match_sync_refinement import samples
from plugins_user._match_sync import viewer as module
from plugins_user._match_sync.engine import Match


def inline(**kwargs):
    return type('Inline', (), {'start': lambda self: kwargs['target']()})()


def main():
    app = QApplication([])
    now = [120.0]
    with tempfile.TemporaryDirectory() as directory, patch.object(module, 'Decoder', FakeDecoder), \
            patch.object(module, 'Chat', FakeChat), patch.object(module.AudioPump, 'start', lambda _: None), \
            patch.object(module.time, 'monotonic', side_effect=lambda: now[0]):
        host = QWidget()
        host.settings = {}
        viewer = module.Viewer(plugins.PluginContext(plugins.PluginManager(window=host, plugins_dir=directory), 'tracking'), {})
        try:
            for key in ('1', '2', '3'):
                viewer.add_room(key, {'alias': key})
            viewer.toggle_running()
            viewer.render_timer.stop()
            viewer.match_timer.stop()
            image = jpeg()
            for row in viewer.rows.values():
                for stamp in range(80 * 20, 133 * 20):
                    row.decoder.history.append(stamp / 20, image)
                row.decoder.last_frame_received = now[0]
            viewer.render()
            row, peer = viewer.rows['2'], viewer.rows['3']
            candidate = Match(.4, 1, 'initial', refined=True)
            for _ in range(2):
                viewer._matched(viewer.generation, {'2': candidate})
            viewer.render()
            assert row.awaiting_confirmation and row.mix_gain == 0
            row.join.click()
            now[0] += .6
            viewer.render()
            assert row.user_confirmed and row.match_confirmed and row.mix_gain == 1
            viewer.alignment.lags['3'] = .2
            peer.match_confirmed = peer.user_confirmed = True
            viewer.render()
            before = viewer.shifts()
            # This previously jumps to the live edge and mutes after three failures.
            for tick in range(100):
                now[0] += .5
                for current in viewer.rows.values():
                    current.decoder.history.append(now[0] + 12, image)
                    current.decoder.last_frame_received = now[0]
                failure = (Match(.9, .4, '低置信度候选', refined=True) if tick % 3 == 0 else
                           Match(None, 0, '粗匹配候选未通过精校正，保持已确认偏移' if tick % 2 else
                                 '精校正时间差不明确，保持已确认偏移'))
                viewer._matched(viewer.generation, {'2': failure})
                viewer.render()
                assert row.match_confirmed and row.mix_gain == 1, 'Uncertain matching must continue buffered playback'
                assert '2' not in viewer.independent_shifts and '2' not in viewer.rematch_rooms
                assert viewer.shifts() == before and peer.mix_gain == 1
            # An unrefined guess cannot replace an established fine offset.
            for _ in range(3):
                viewer._matched(viewer.generation, {'2': Match(2, 1, 'coarse only')})
            viewer.render()
            assert viewer.shifts() == before and row.mix_gain == 1
            drift = Match(1.0, 1, 'reliable drift', refined=True, playback_error=.6)
            viewer._matched(viewer.generation, {'2': drift})
            assert viewer.alignment.lags['2'] == .4, 'One new result is insufficient to move the cached timeline'
            viewer._matched(viewer.generation, {'2': drift})
            viewer.render()
            assert row.match_confirmed and row.mix_gain == 1 and not row.awaiting_confirmation
            assert row.review_alignment and not row.join.isHidden() and '可选' in row.join.text()
            corrected = viewer.shifts()
            assert corrected['1'] == before['1'] and corrected['3'] == before['3']
            # Leaving the optional review untouched does not start repeated rematches.
            for tick in range(60):
                now[0] += .5
                for current in viewer.rows.values():
                    current.decoder.history.append(now[0] + 12, image)
                viewer._matched(viewer.generation, {'2': Match(None, 0, '精校正尚未确认，保持已确认偏移')})
                viewer.render()
                assert viewer.shifts() == corrected and row.mix_gain == 1
                assert row.review_alignment and '2' not in viewer.rematch_rooms
            # Consume actual cached PCM while the optional review is still ignored.
            for current in viewer.rows.values():
                current.audible.setChecked(current is row)
            row.volume.setValue(100)
            target = viewer.audio.clock() + viewer.shifts()['2']
            pcm = array('h', [6400, -6400] * 1024).tobytes()
            row.decoder.history.audio.append_at(round((target - row.decoder.history.origin) * 48000), pcm)
            viewer.audio.sink = FakeSink()
            viewer.audio.device = FakeDevice(viewer.audio.sink)
            viewer.audio.anchor = now[0] - viewer.audio.correction
            viewer.audio.fill()
            assert set(array('h', viewer.audio.device.data)) == {6400, -6400}
            viewer.audio.stop()
            for current in viewer.rows.values():
                current.audible.setChecked(True)
            old_serial, old_epoch = viewer.analysis_serial, viewer.generation
            clock, shifts = viewer.audio.clock(), viewer.shifts()
            row.join.click()
            assert not row.review_alignment and row.user_confirmed_lag == shifts['2'] - shifts['1']
            assert viewer.audio.clock() == clock and viewer.shifts() == shifts
            viewer._analysis_finished(old_serial, old_epoch, {'2': Match(8, 1, 'stale', refined=True)})
            assert viewer.shifts() == shifts and not row.review_alignment
            for _ in range(2):
                viewer._matched(viewer.generation, {'2': Match(1.5, 1, 'second drift', refined=True, playback_error=.5)})
            viewer.render()
            assert row.review_alignment and not row.join.isHidden() and row.mix_gain == 1
            # Optional manual review retains sound, then returns to automatic tracking.
            row.join.click()
            row.delay.setValue(row.delay.value() + .1)
            viewer.render()
            assert not viewer.alignment.automatic and row.review_alignment and row.mix_gain == 1
            manual = viewer.shifts()
            row.join.click()
            assert viewer.alignment.automatic and not row.review_alignment and viewer.shifts() == manual
            # Real loss of target content still mutes; merely ignoring a review never does.
            viewer._update_sync_health(now[0], dict(viewer.shifts(), **{'2': 100}))
            assert row.mix_gain == 0 and row.recheck_alignment
            row.review_alignment = True
            row.recheck_alignment = False
            row.decoder.last_frame_received = now[0]
            row.decoder.history.frames = deque(frame for frame in row.decoder.history.frames if frame[0] <= now[0] + 2)
            viewer.alignment.lags['2'] = 15
            viewer.rendered_shifts.clear()
            viewer.shift_reference = None
            row.match_confirmed = True
            before_main = viewer.shifts()['1']
            viewer.render()
            assert row.join.text().startswith('延后'), (row.join.text(), row.sync_state, viewer.shifts())
            row.join.click()
            assert viewer.shifts()['1'] < before_main and not row.review_alignment
            # Prior human approval cannot bypass actual playback verification
            # after a decoder timebase reset and a fresh acquisition.
            viewer._queue_rematch(row)
            for _ in range(2):
                viewer._matched(viewer.generation, {'2': Match(2, 1, 'new epoch candidate', refined=True, playback_error=4)})
            viewer.render()
            assert not row.match_confirmed and row.mix_gain == 0
            print('PASS: 80s uncertain cached playback, two-result drift correction, optional repeated review, no-click continuity, exact confirmation and true underrun')
        finally:
            viewer.close()
            host.close()
            app.processEvents()

    # The newest ingested segment may differ while the delayed playback is aligned.
    now[0] = 120
    with tempfile.TemporaryDirectory() as directory, patch.object(module, 'Decoder', FakeDecoder), \
            patch.object(module, 'Chat', FakeChat), patch.object(module.AudioPump, 'start', lambda _: None), \
            patch.object(module.time, 'monotonic', side_effect=lambda: now[0]):
        host = QWidget()
        host.settings = {}
        viewer = module.Viewer(plugins.PluginContext(plugins.PluginManager(window=host, plugins_dir=directory), 'shown_tracking'), {})
        try:
            for key in ('1', '2'):
                viewer.add_room(key, {'alias': key})
            viewer.toggle_running()
            viewer.render_timer.stop()
            viewer.match_timer.stop()
            for key, detail in (('1', samples(count=601)), ('2', samples(.4, count=601))):
                history = viewer.rows[key].decoder.history
                history.origin = 100
                history.frames.extend((stamp / 20, image) for stamp in range(80 * 20, 133 * 20))
                if key == '2':
                    detail = [replace(sample, feature=bytes((i * 37 + n * 19) % 256 for i in range(256)))
                              if sample.time > 118 else sample for n, sample in enumerate(detail)]
                history.details = deque(detail)
                history.samples = deque(detail[::10])
                viewer.rows[key].decoder.last_frame_received = now[0]
            row = viewer.rows['2']
            row.match_confirmed = row.user_confirmed = True
            viewer.alignment.lags['2'] = .4
            viewer.stable_reference_shift = -6
            viewer.rematch_rooms.clear()
            viewer.render()
            deliveries = []
            viewer.results.matched.connect(lambda epoch, results: deliveries.append(results['2']))
            with patch.object(module.threading, 'Thread', side_effect=inline):
                viewer.analyse()
            assert deliveries and deliveries[0].refined and abs(deliveries[0].lag - .4) < .06, deliveries
            assert row.match_confirmed and '2' not in viewer.independent_shifts
            print('PASS: tracking verifies delayed playback instead of unrelated newer live-edge scenes')
        finally:
            viewer.close()
            host.close()
            app.processEvents()


if __name__ == '__main__':
    main()
