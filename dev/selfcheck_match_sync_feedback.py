"""Bounded picture waits, honest status labels and delay lock continuity."""
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
from dev.selfcheck_match_sync import FakeDecoder, FakeChat, jpeg
from plugins_user._match_sync import viewer as module
from plugins_user._match_sync.engine import Match


def main():
    app = QApplication([])
    now = [120.0]
    with tempfile.TemporaryDirectory() as root, patch.object(module, 'Decoder', FakeDecoder), \
            patch.object(module, 'Chat', FakeChat), patch.object(module.AudioPump, 'start', lambda _: None), \
            patch.object(module.time, 'monotonic', side_effect=lambda: now[0]):
        host = QWidget()
        host.settings = {}
        context = plugins.PluginContext(plugins.PluginManager(window=host, plugins_dir=root), 'feedback_check')
        viewer = module.Viewer(context, {})
        try:
            for key in ('1', '2'):
                viewer.add_room(key, {'alias': key})
            viewer.toggle_running()
            viewer.render_timer.stop()
            viewer.match_timer.stop()
            image = jpeg()
            for row in viewer.rows.values():
                for stamp in range(80 * 60, 122 * 60):
                    row.decoder.history.append(stamp / 60, image)
                row.decoder.last_frame_received = now[0]
            viewer.alignment.lags['2'] = .4
            viewer.rows['2'].match_confirmed = True
            viewer.render()
            viewer.show_comparison('2')
            # A one-tick picture decoder miss must not flash a buffer indicator.
            main_row = viewer.rows['1']
            with patch.object(main_row.decoder, 'picture_at', return_value=None, create=True):
                initial = viewer.canvas.frame_key
                now[0] += .05
                viewer.render()
                assert viewer.canvas.frame_key == initial and not viewer.canvas.waiting
                assert '播放正常' in viewer.comparison_panel.cards['1'][3].text()
                now[0] += .11
                viewer.render()
                assert viewer.canvas.waiting, 'Sustained lag must remain visible'
            viewer.render()
            assert not viewer.canvas.waiting
            canvas = viewer.canvas
            assert canvas.playback_waiting(main_row.decoder, now[0] - 3, canvas.frame, shared_wait=True)
            assert canvas.playback_waiting(main_row.decoder, 200, None), 'Missing source content gets no grace'
            # Even a fixed target cannot retain a missing picture indefinitely.
            canvas.missing_since = None
            target = canvas.frame_key
            assert not canvas.playback_waiting(main_row.decoder, target, None)
            now[0] += .16
            assert canvas.playback_waiting(main_row.decoder, target, None)
            canvas.playback_waiting(main_row.decoder, target, canvas.frame)
            # Lock preserves the exact rendered offsets despite saved manual trims.
            for key, value in (('1', .4), ('2', .7)):
                viewer.rows[key].delay.blockSignals(True)
                viewer.rows[key].delay.setValue(value)
                viewer.rows[key].previous_delay = value
                viewer.rows[key].delay.blockSignals(False)
            before = viewer.shifts()
            clock = viewer.audio.clock()
            viewer.lock_delay.click()
            assert not viewer.automatic.isChecked() and viewer.alignment.manual_locked
            assert viewer.lock_delay.text() == '解锁延时'
            assert all(abs(viewer.shifts()[key] - value) < 1e-9 for key, value in before.items())
            assert viewer.audio.clock() == clock and viewer.compare.isChecked()
            assert not viewer.offset_repositioning
            epoch = viewer.generation
            viewer._matched(epoch, {'2': Match(12, 1, 'late result', refined=True)})
            assert all(abs(viewer.shifts()[key] - value) < 1e-9 for key, value in before.items()), 'Locked delays reject pending automatic results'
            with patch.object(module.threading, 'Thread') as worker:
                viewer.analyse()
                worker.assert_not_called()
            assert '已同步' not in viewer.rows['2'].status.text()
            assert '延时已锁定' in viewer.rows['2'].status.text()
            viewer.lock_delay.click()
            assert viewer.automatic.isChecked() and not viewer.alignment.manual_locked
            assert viewer.compare.isChecked(), 'Unlock should retain the comparison'
            viewer.automatic.setChecked(False)
            viewer.rows['2'].sync_state = '已同步'
            viewer.rows['2'].refresh_status()
            assert '自动对齐已关闭' in viewer.rows['2'].status.text()
            assert viewer.rows['2'].playback_status() == '按当前偏移播放'
            viewer.alignment.lags.clear()
            viewer.render()
            viewer.comparison_panel.render(viewer.audio.clock(), viewer.shifts())
            assert '与主画面偏移相同' in viewer.comparison_panel.cards['2'][3].text()
            assert '自动对齐已关闭' in viewer.notice.text()
            assert '历史缓存约' in viewer.rows['2'].status.text()
            # The new control follows comparison in the heading, without moving the entry button.
            viewer.show()
            app.processEvents()
            assert viewer.lock_delay.x() > viewer.compare.x()
        finally:
            viewer.close()
            host.close()
            app.processEvents()
    print('PASS: transient versus sustained buffering, mode-specific labels, exact delay lock and unlock, stale-result rejection')


if __name__ == '__main__':
    main()
