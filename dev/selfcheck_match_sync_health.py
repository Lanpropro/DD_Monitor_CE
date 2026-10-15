"""Buffered receive bursts and short presentation misses must not mute healthy feeds."""
import os
from pathlib import Path
import sys
import tempfile
from array import array
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('DDM_NO_SAVE', '1')
from PySide6.QtWidgets import QApplication, QWidget
from ddm import plugins
from dev.selfcheck_match_sync import FakeDecoder, FakeChat, FakeSink, FakeDevice, jpeg
from plugins_user._match_sync import viewer as module


def main():
    app = QApplication([])
    now = [120.0]
    with tempfile.TemporaryDirectory() as directory, patch.object(module, 'Decoder', FakeDecoder), \
            patch.object(module, 'Chat', FakeChat), patch.object(module.AudioPump, 'start', lambda _: None), \
            patch.object(module.time, 'monotonic', side_effect=lambda: now[0]):
        host = QWidget()
        host.settings = {}
        viewer = module.Viewer(plugins.PluginContext(plugins.PluginManager(window=host, plugins_dir=directory), 'health_check'), {})
        try:
            for key in ('1', '2'):
                viewer.add_room(key, {'alias': key})
            viewer.toggle_running()
            viewer.render_timer.stop()
            viewer.match_timer.stop()
            image = jpeg()
            for row in viewer.rows.values():
                for stamp in range(100 * 60, 116 * 60 + 1):
                    row.decoder.history.append(stamp / 60, image)
                row.decoder.last_frame_received = 116
                row.match_confirmed = True
                row.sync_state, row.mix_gain = '已同步', 1.0
                row.actual_position = 114
            viewer.alignment.lags['2'] = 0
            viewer.rematch_rooms.clear()
            shifts = {'1': -6, '2': -6}
            viewer._update_sync_health(120, shifts)
            assert all(row.sync_state == '已同步' and row.mix_gain == 1 for row in viewer.rows.values()), \
                'A receive gap is not an underrun while two seconds of decoded content remain'
            assert not viewer.rows['2'].recheck_alignment
            # Exercise the visible frame check with a native-style decoder.
            main_row = viewer.rows['1']
            main_row.decoder.picture_at = lambda *args: None
            for tick in range(100):
                now[0] = 120 + tick * .02
                for row in viewer.rows.values():
                    row.decoder.history.append(now[0], image)
                    row.decoder.last_frame_received = now[0]
                target = now[0] - 6
                main_row.actual_position = target - (.25 if tick % 20 < 5 else 0)
                viewer._update_sync_health(now[0], shifts)
                assert main_row.sync_state == '已同步' and main_row.mix_gain == 1, 'A short picture-cache miss must not repeatedly quarantine and mute the main'
            # Persistent loss of display frames still gets a real isolation state.
            for tick in range(40):
                now[0] += .02
                main_row.actual_position = now[0] - 7
                viewer._update_sync_health(now[0], shifts)
            assert main_row.mix_gain == 0 and main_row.sync_state != '已同步'
            viewer.audio.sink = FakeSink()
            viewer.audio.device = FakeDevice(viewer.audio.sink)
            viewer.audio.anchor = now[0]
            viewer.audio.clock_segments.clear()
            peer = viewer.rows['2']
            assert peer.sync_state == '已同步' and not viewer.sync_waiting
            with patch.object(main_row.decoder.history, 'pcm_at', side_effect=AssertionError('Isolated main audio must stay muted')), \
                    patch.object(peer.decoder.history, 'pcm_at', side_effect=lambda stamp, frames: array('h', [1000, 1000] * frames).tobytes()):
                viewer.audio.fill()
            assert any(viewer.audio.device.data), 'Main presentation isolation must not globally mute a healthy secondary'
        finally:
            viewer.close()
            host.close()
    print('PASS: buffered burst arrivals and transient picture misses preserve main audio; sustained loss still isolates')


if __name__ == '__main__':
    main()
