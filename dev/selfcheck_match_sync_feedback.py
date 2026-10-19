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
                assert '显示帧准备较慢' in viewer.notice.text()
                assert '连接' not in viewer.notice.text(), 'Cached video must not be reported as a connection failure'
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
            viewer.alignment.lags['2'] = .437
            viewer.rendered_shifts.clear()
            viewer.render()
            assert viewer.rows['1'].delay.value() == 0
            assert viewer.rows['2'].delay.value() == -.44, 'Automatic relative delay must reach the input'
            automatic_shifts = viewer.shifts()
            viewer.automatic.setChecked(False)
            assert viewer.compare.isChecked() and viewer.alignment.manual_locked
            assert all(abs(viewer.shifts()[key] - value) < 1e-9 for key, value in automatic_shifts.items()), 'Turning auto off must preserve exact offsets'
            viewer._matched(viewer.generation, {'2': Match(15, 1, 'pending correction', refined=True)})
            assert abs(viewer.shifts()['2'] - automatic_shifts['2']) < 1e-9
            viewer.rows['2'].delay.setValue(-.34)
            assert not viewer.automatic.isChecked() and viewer.compare.isChecked()
            assert abs(viewer.shifts()['1'] - automatic_shifts['1']) < 1e-9
            assert abs(viewer.shifts()['2'] - automatic_shifts['2'] + .1) < 1e-9, 'The first manual edit must not apply the old automatic lag twice'
            viewer.automatic.setChecked(True)
            assert viewer.compare.isChecked() and not viewer.alignment.manual_locked
            assert all(row.delay.value() == 0 for row in viewer.rows.values())
            assert viewer.alignment.lags == {'1': 0}
            viewer.alignment.lags['2'] = .4
            viewer.rows['2'].match_confirmed = True
            viewer.render()
            # Turning auto off preserves exact rendered offsets despite saved manual trims.
            for key, value in (('1', .4), ('2', .7)):
                viewer.rows[key].delay.blockSignals(True)
                viewer.rows[key].delay.setValue(value)
                viewer.rows[key].previous_delay = value
                viewer.rows[key].delay.blockSignals(False)
            before = viewer.shifts()
            clock = viewer.audio.clock()
            viewer.automatic.setChecked(False)
            assert not viewer.automatic.isChecked() and viewer.alignment.manual_locked
            assert all(abs(viewer.shifts()[key] - value) < 1e-9 for key, value in before.items())
            assert viewer.audio.clock() == clock and viewer.compare.isChecked()
            assert not viewer.offset_repositioning
            epoch = viewer.generation
            viewer._matched(epoch, {'2': Match(12, 1, 'late result', refined=True)})
            assert all(abs(viewer.shifts()[key] - value) < 1e-9 for key, value in before.items()), 'Manual offsets reject pending automatic results'
            with patch.object(module.threading, 'Thread') as worker:
                viewer.analyse()
                worker.assert_not_called()
            assert '已同步' not in viewer.rows['2'].status.text()
            assert '手动偏移' in viewer.rows['2'].status.text()
            viewer.rows['2'].sync_state = '已同步'
            viewer.rows['2'].refresh_status()
            assert '自动对齐已关闭' in viewer.rows['2'].status.detail
            assert viewer.rows['2'].playback_status() == '按当前偏移播放'
            viewer.alignment.lags.clear()
            viewer.render()
            viewer.comparison_panel.render(viewer.audio.clock(), viewer.shifts())
            assert '设置偏移' in viewer.comparison_panel.cards['2'][3].text()
            assert '自动对齐已关闭' in viewer.notice.text()
            assert '历史缓存约' in viewer.rows['2'].status.detail
            # Only automatic alignment and comparison remain in the heading.
            viewer.show()
            app.processEvents()
            assert not hasattr(viewer, 'lock_delay')
            assert not any(widget.text() in ('锁定延时', '解锁延时')
                           for widget in viewer.findChildren(module.QCheckBox))
        finally:
            viewer.close()
            host.close()
            app.processEvents()
    print('PASS: transient versus sustained buffering, mode-specific labels, removed delay lock, preserved manual offsets, stale-result rejection')


if __name__ == '__main__':
    main()
