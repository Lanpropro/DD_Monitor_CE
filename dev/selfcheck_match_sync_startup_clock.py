"""A never-started main can establish a playable clock after a long connection failure."""
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


def main():
    app = QApplication([])
    now = [120.0]
    with tempfile.TemporaryDirectory() as directory, patch.object(module, 'Decoder', FakeDecoder), \
            patch.object(module, 'Chat', FakeChat), patch.object(module.AudioPump, 'start', lambda _: None), \
            patch.object(module.time, 'monotonic', side_effect=lambda: now[0]):
        host = QWidget()
        host.settings = {}
        viewer = module.Viewer(plugins.PluginContext(plugins.PluginManager(window=host, plugins_dir=directory), 'startup_clock'), {})
        try:
            viewer.add_room('1')
            viewer.add_room('2')
            viewer.toggle_running()
            viewer.render_timer.stop()
            viewer.match_timer.stop()
            viewer.audio.clock = lambda: 120 + viewer.audio.correction
            viewer.locked_clock = 120
            viewer.sync_waiting = True
            viewer.select_main('2')
            row = viewer.rows['2']
            now[0] = 300
            image = jpeg()
            for stamp in range(240 * 20, 298 * 20):
                row.decoder.history.append(stamp / 20, image)
            row.decoder.last_frame_received = now[0]
            assert not row.was_isolated and viewer.stable_reference_shift is None
            viewer.render()
            position = viewer.audio.clock() + viewer.shifts()['2']
            assert row.decoder.history.bounds()[0] <= position <= row.decoder.history.bounds()[1]
            assert viewer.canvas.frame is not None and not viewer.canvas.waiting
            assert row.sync_state == '已同步' and viewer.stable_reference_shift is not None
            assert '前方可播放约 6.0 秒' in row.buffer_text and '超出范围' not in row.buffer_text
            # Subsequent playback keeps the established main basis and clock.
            correction, shift = viewer.audio.correction, viewer.shifts()['2']
            for tick in range(1, 41):
                now[0] += .05
                row.decoder.history.append(297.95 + tick * .05, image)
                row.decoder.last_frame_received = now[0]
                viewer.audio.clock = lambda tick=tick: 120 + viewer.audio.correction + tick * .05
                viewer.render()
                assert viewer.audio.correction == correction and viewer.shifts()['2'] == shift
            # A user-requested out-of-range manual offset must not be overridden,
            # and unreceived gaps cannot inflate the playable headroom display.
            viewer.automatic.setChecked(False)
            viewer.rows['2'].delay.setValue(180)
            viewer.offset_repositioning = False
            viewer.stable_reference_shift = None
            row.was_isolated = False
            before = viewer.audio.correction
            viewer.render()
            assert viewer.audio.correction == before
            assert viewer.canvas.waiting and '前方可播放约 0.0 秒' in row.buffer_text
            assert '超出范围' in row.buffer_text
            # Even automatic startup must await a fresh, sufficient reserve.
            viewer.alignment.automatic = True
            viewer.stable_reference_shift = None
            row.was_isolated = False
            with patch.object(row.decoder.history, 'bounds_at', return_value=(400, 402)):
                assert viewer._recover_clock(120, {'2': -6}) == 120
            row.decoder.last_frame_received = now[0] - 10
            with patch.object(row.decoder.history, 'bounds_at', return_value=(400, 460)):
                assert viewer._recover_clock(120, {'2': -6}) == 120
            assert viewer.audio.correction == before
        finally:
            viewer.close()
            host.close()
            app.processEvents()
    print('PASS: delayed first frames/main switch recover a stale clock; established/manual timelines stay fixed; headroom excludes unavailable gaps')


if __name__ == '__main__':
    main()
