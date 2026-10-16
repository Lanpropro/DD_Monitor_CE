"""Continuous common playback can absorb bounded lateness; impossible feeds name themselves."""
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
from plugins_user._match_sync.engine import LateBuffer, Match, SafetyBuffer


def controller_checks():
    control = LateBuffer()
    assert not control.update(0, 6, 60, {'slow': 1})
    assert not control.update(4.9, 6, 60, {'slow': 1})
    assert control.update(5, 6, 60, {'slow': 1}) and control.floor == 7.5
    assert not control.update(80, 7.45, 60, {'slow': -.45})
    retained = control.floor
    control.update(90, 7.45, 60, {})
    assert control.floor == retained and SafetyBuffer().rate(90, retained, minimum=retained) == 1
    control = LateBuffer()
    control.update(0, 6, 60, {'slow': 1})
    control.update(5, 6, 60, {'slow': 1})
    control.update(10, 6.1, 6.5, {'slow': .9})
    assert not control.building and control.blocked == {'slow'} and control.floor <= 6.5
    control = LateBuffer()
    control.update(0, 6, 60, {'slow': 1, 'recoverable': .5})
    control.update(5, 6, 60, {'slow': 1, 'recoverable': .5})
    control.update(21, 6.3, 60, {'slow': 1.6, 'recoverable': .1})
    assert control.blocked == {'slow'} and control.building and control.rooms == {'recoverable'}
    for reason in ('too-late', 'capacity', 'growing', 'timeout'):
        control = LateBuffer()
        gap, capacity = (16, 60) if reason == 'too-late' else (1, 6.8 if reason == 'capacity' else 60)
        control.update(0, 6, capacity, {'slow': gap, 'healthy': -3})
        control.update(5, 6, capacity, {'slow': gap, 'healthy': -3})
        if reason == 'growing':
            control.update(21, 6.3, 60, {'slow': 1.6, 'healthy': -3})
        elif reason == 'timeout':
            control.update(126, 6.5, 60, {'slow': .5, 'healthy': -3})
        assert control.blocked == {'slow'} and not control.building, reason
        repeated_gap = 1.6 if reason == 'growing' else .5 if reason == 'timeout' else gap
        control.update(127, 6.5, capacity, {'slow': repeated_gap, 'healthy': -3})
        assert control.blocked == {'slow'} and not control.building, 'Failed attempts must not restart each frame'
        if reason == 'growing':
            assert control.update(127.5, 6.5, 60, {'slow': .4, 'healthy': -3})
        control.update(128, 6.5, 60, {'slow': -1, 'healthy': -3})
        assert not control.blocked
    print('PASS: persistent lateness, bounded headroom, growing/oversized deficits, capacity, deadline and retained reserve')


def main():
    controller_checks()
    app = QApplication([])
    now, clock = [120.0], [120.0]
    with tempfile.TemporaryDirectory() as root, patch.object(module, 'Decoder', FakeDecoder), \
            patch.object(module, 'Chat', FakeChat), patch.object(module.AudioPump, 'start', lambda _: None), \
            patch.object(module.time, 'monotonic', side_effect=lambda: now[0]):
        host = QWidget()
        host.settings = {}
        viewer = module.Viewer(plugins.PluginContext(plugins.PluginManager(window=host, plugins_dir=root), 'late_buffer'), {})
        try:
            viewer.resize(2200, 900)
            viewer.show()
            for key, alias in (('1', 'Main'), ('2', 'Slow'), ('3', 'Healthy')):
                viewer.add_room(key, {'alias': alias})
            viewer.toggle_running()
            viewer.render_timer.stop()
            viewer.match_timer.stop()
            viewer.audio.clock = lambda: clock[0]
            viewer.stable_reference_shift = -6
            viewer.alignment.lags.update({'1': 0, '2': 6, '3': 0})
            viewer.rematch_rooms.clear()
            image = jpeg()
            for key, row in viewer.rows.items():
                row.user_confirmed = row.match_confirmed = True
                row.mix_gain = 1
                row.sync_state = '已同步'
                row.user_confirmed_lag = viewer.alignment.lags[key]
                for tick in range(400):
                    row.decoder.history.append(100 + tick * .05 - (1 if key == '2' else 0), image)
                row.decoder.last_frame_received = now[0]
            viewer.render()
            correction, reference_shift = viewer.audio.correction, viewer.shifts()['1']
            building_seen = False
            for _ in range(2200):
                elapsed = .05
                previous = clock[0]
                now[0] += elapsed
                clock[0] += viewer.playback_rate * elapsed
                assert .98 * elapsed - 1e-8 <= clock[0] - previous <= 1.01 * elapsed + 1e-8
                for key, row in viewer.rows.items():
                    row.decoder.history.append(now[0] - (1 if key == '2' else 0), image)
                    row.decoder.last_frame_received = now[0]
                viewer.render()
                building_seen |= viewer.late_buffer.building
                assert viewer.audio.correction == correction and viewer.shifts()['1'] == reference_shift
                assert viewer.rows['1'].sync_state == '已同步' and not viewer.canvas.waiting
                assert viewer.rows['3'].mix_gain == 1
                slow = viewer.rows['2']
                if slow.rematch_locally and not slow.match_confirmed:
                    for _attempt in range(2):
                        viewer._matched(viewer.generation, {'2': Match(6, 1, 'verified saved lag', refined=True)})
            assert building_seen and viewer.rows['2'].sync_state == '已同步'
            assert viewer.late_buffer.floor > 7 and not viewer.late_buffer.building
            assert not viewer.late_buffer.blocked and viewer.late_notice.isHidden()
            # A sixteen-second deficit must warn, without seeking or pausing the main.
            viewer.late_buffer = LateBuffer()
            viewer.alignment.lags['2'] = 22
            viewer.rendered_shifts.clear()
            slow.match_confirmed = slow.rematch_locally = False
            slow.needs_epoch_samples = True
            for offset in (0, 6):
                slow.decoder.last_frame_received = now[0] + offset
                viewer._update_late_buffer(now[0] + offset, clock[0], viewer.shifts(), 6, 59)
            assert not viewer.late_buffer.building and not viewer.late_buffer.blocked
            slow.rematch_locally = True
            for offset in (0, 6):
                slow.decoder.last_frame_received = now[0] + offset
                viewer._update_late_buffer(now[0] + offset, clock[0], viewer.shifts(), 6, 59)
            assert not viewer.late_buffer.building and not viewer.late_buffer.blocked
            slow.match_confirmed = True
            for offset in (0, 6):
                slow.decoder.last_frame_received = now[0] + offset - 4
                viewer._update_late_buffer(now[0] + offset, clock[0], viewer.shifts(), 6, 59)
            assert not viewer.late_buffer.building and not viewer.late_buffer.blocked
            slow.match_confirmed = slow.user_confirmed = True
            for _ in range(130):
                now[0] += .05
                clock[0] += .05
                for key, row in viewer.rows.items():
                    row.decoder.history.append(now[0] - (1 if key == '2' else 0), image)
                    row.decoder.last_frame_received = now[0]
                viewer.render()
            app.processEvents()
            assert 'Slow过慢，请更换主画面' == viewer.late_notice.text()
            assert not viewer.late_notice.isHidden() and not viewer.late_buffer.building
            assert viewer.late_notice.x() >= viewer.compare.geometry().right()
            assert viewer.audio.correction == correction and viewer.shifts()['1'] == reference_shift
            assert viewer.rows['1'].sync_state == '已同步' and not viewer.canvas.waiting
            viewer.automatic.setChecked(False)
            viewer.render()
            assert viewer.late_notice.isHidden() and viewer.late_buffer.floor == 0
            viewer.late_buffer.floor = 8
            viewer.late_notice.show()
            viewer.select_main('3')
            assert viewer.late_notice.isHidden() and viewer.late_buffer.floor == 0
            print('PASS: simulated 110s main/healthy playback stays continuous while a late source joins; impossible source warning is immediately right of comparison; manual mode clears policy')
        finally:
            viewer.close()
            host.close()
            app.processEvents()


if __name__ == '__main__':
    main()
