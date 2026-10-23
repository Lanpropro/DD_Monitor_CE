"""Selectable continuous headroom, bounded catch-up and isolated preference persistence."""
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('DDM_NO_SAVE', '1')
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication, QWidget
from ddm import plugins
from dev.selfcheck_match_sync import FakeChat, FakeDecoder, jpeg
from plugins_user._match_sync import viewer as module
from plugins_user._match_sync.engine import LateBuffer, Match, SafetyBuffer


def controller_checks():
    for reserve in (2, 5, 8):
        control = LateBuffer(reserve)
        ahead, gap = 6.0, -1.2
        safety = SafetyBuffer()
        seen = False
        # Already matched/playing with 1.2s ahead: no missing content is required.
        for tick in range(800):
            now = tick * .5
            control.update(now, ahead, 60, {'side': gap, 'healthy': -20})
            seen |= control.building
            rate = min(.98, safety.rate(now, ahead, minimum=control.floor)) if control.building else safety.rate(now, ahead, minimum=control.floor)
            assert .98 <= rate <= 1.01
            added = (1 - rate) * .5
            ahead += added
            gap -= added
        assert seen and not control.building and not control.blocked
        assert -gap >= reserve - .11, (reserve, -gap)
        retained = control.floor
        assert safety.rate(401, ahead, minimum=retained) == 1, 'Do not consume acquired reserve'
        control.update(402, ahead, 60, {'side': gap + .2})
        control.update(404, ahead, 60, {'side': gap})
        assert not control.building, 'Brief jitter near target must not retrigger'
        control.update(430, ahead, 60, {'side': -.8})
        assert control.update(436, ahead, 60, {'side': -.8}), 'Replenish sustained reserve depletion'
        assert control.rooms == {'side'}
    control = LateBuffer(8)
    control.update(0, 6, 60, {'side': 1})
    control.update(5, 6, 60, {'side': 1})
    assert control.deadline > 400
    assert control.update(246, 10.8, 60, {'side': -3.8}), 'Extra reserve is not a slow-source timeout'
    control = LateBuffer(5)
    control.update(0, 6, 6.8, {'side': -1.5})
    control.update(5, 6, 6.8, {'side': -1.5})
    control.update(45, 6.8, 6.8, {'side': -2.3})
    assert control.limited == {'side'} and not control.blocked and not control.building
    for reserve in (2, 5, 8):
        control = LateBuffer(reserve)
        control.update(0, 6, 60, {'slow': 16, 'healthy': -20})
        control.update(6, 6, 60, {'slow': 16, 'healthy': -20})
        assert control.blocked == {'slow'} and not control.building
    print('PASS: 2/5/8s continuous reserve, refill without underrun, hysteresis, retention, capacity and catch-up deadlines')


def main():
    controller_checks()
    app = QApplication([])
    with tempfile.TemporaryDirectory() as directory, patch.object(module, 'Decoder', FakeDecoder), \
            patch.object(module, 'Chat', FakeChat), patch.object(module.AudioPump, 'start', lambda _: None):
        host = QWidget()
        host.settings = {}
        context = plugins.PluginContext(plugins.PluginManager(window=host, plugins_dir=directory), 'reserve')
        viewer = module.Viewer(context, {})
        try:
            assert viewer.reserve_seconds == 5
            viewer.add_room('1')
            viewer.add_room('2')
            viewer.toggle_running()
            viewer.render_timer.stop()
            viewer.match_timer.stop()
            before = (viewer.audio.correction, viewer.shifts(), [row.decoder for row in viewer.rows.values()])
            for value in (8, 2, 5):
                viewer.buffer_reserve.setCurrentIndex(viewer.buffer_reserve.findData(value))
                assert viewer.late_buffer.reserve_seconds == value
                viewer.save()
                assert context.setting('buffer_reserve', None) == value
                assert (viewer.audio.correction, viewer.shifts(), [row.decoder for row in viewer.rows.values()]) == before
            viewer.buffer_reserve.setCurrentIndex(viewer.buffer_reserve.findData(8))
            viewer.save()
            viewer.automatic.setChecked(False)
            assert viewer.late_buffer.reserve_seconds == 8
            viewer.automatic.setChecked(True)
            viewer.select_main('2')
            assert viewer.late_buffer.reserve_seconds == 8
            restored = module.Viewer(context, {})
            try:
                assert restored.reserve_seconds == 8 and restored.buffer_reserve.currentData() == 8
            finally:
                restored.close()
            # Real Viewer clock consumption: an already playing side with 1.2s
            # reserve reaches 5s, then 8s, without seeks/restarts or main stalls.
            viewer.select_main('1')
            viewer.buffer_reserve.setCurrentIndex(viewer.buffer_reserve.findData(5))
            now, clock = [120.0], [120.0]
            viewer.audio.clock = lambda: clock[0]
            viewer.stable_reference_shift = -6
            viewer.rendered_shifts.clear()
            viewer.alignment.lags.update({'1': 0, '2': 4.8})
            viewer.rematch_rooms.clear()
            image = jpeg()
            for row in viewer.rows.values():
                row.user_confirmed = row.match_confirmed = True
                row.user_confirmed_lag = viewer.alignment.lags[row.room_id]
                row.sync_state = '已同步'
                row.mix_gain = 1
                for tick in range(400):
                    row.decoder.history.append(100 + tick * .05, image)
                row.decoder.last_frame_received = now[0]
            correction = viewer.audio.correction
            with patch.object(module.time, 'monotonic', side_effect=lambda: now[0]):
                viewer.render()
                for tick in range(9000):
                    now[0] += .05
                    clock[0] += viewer.playback_rate * .05
                    if tick == 5000:
                        viewer.buffer_reserve.setCurrentIndex(viewer.buffer_reserve.findData(8))
                    for row in viewer.rows.values():
                        row.decoder.history.append(now[0], image)
                        row.decoder.last_frame_received = now[0]
                    viewer.render()
                    assert viewer.audio.correction == correction
                    assert viewer.shifts()['1'] == -6
                    assert viewer.rows['1'].sync_state == '已同步' and not viewer.canvas.waiting
                    side = viewer.rows['2']
                    if side.rematch_locally and not side.match_confirmed:
                        for _ in range(2):
                            viewer._matched(viewer.generation, {'2': Match(4.8, 1, 'verified', refined=True)})
                side_ahead = side.decoder.history.bounds()[1] - clock[0] - viewer.shifts()['2']
                assert side_ahead >= 7.8 and not viewer.late_buffer.building, side_ahead
                assert side.sync_state == '已同步'
        finally:
            viewer.close()
            host.close()
            app.processEvents()
    print('PASS: default/persisted choices, main/mode resets and live changes without seeking or restarting')


if __name__ == '__main__':
    main()
