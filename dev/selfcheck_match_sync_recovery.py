"""Persistent rematching, user admission, fair scheduling and retained stream epochs."""
import os
from pathlib import Path
import sys
import tempfile
from fractions import Fraction
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('DDM_NO_SAVE', '1')
from PySide6.QtWidgets import QApplication, QWidget
from ddm import plugins
from dev.selfcheck_match_sync import FakeDecoder, FakeChat, jpeg
from plugins_user._match_sync import viewer as module, video
from plugins_user._match_sync.engine import Match, Sample


def inline(**kwargs):
    return type('Inline', (), {'start': lambda self: kwargs['target']()})()


def main():
    app = QApplication([])
    now = [120.0]
    with tempfile.TemporaryDirectory() as root, patch.object(module, 'Decoder', FakeDecoder), \
            patch.object(module, 'Chat', FakeChat), patch.object(module.AudioPump, 'start', lambda _: None), \
            patch.object(module.time, 'monotonic', side_effect=lambda: now[0]):
        host = QWidget()
        host.settings = {}
        viewer = module.Viewer(plugins.PluginContext(plugins.PluginManager(window=host, plugins_dir=root), 'recovery_check'), {})
        try:
            for key in ('1', '2', '3'):
                viewer.add_room(key, {'alias': key})
            viewer.toggle_running()
            viewer.render_timer.stop()
            viewer.match_timer.stop()
            image = jpeg()
            for row in viewer.rows.values():
                for stamp in range(80 * 20, 123 * 20):
                    row.decoder.history.append(stamp / 20, image)
                row.decoder.last_frame_received = now[0]
            viewer.render()
            lag = Match(.4, 1, 'candidate', refined=True)
            viewer._matched(viewer.generation, {'2': lag})
            viewer._matched(viewer.generation, {'2': lag})
            viewer.render()
            row = viewer.rows['2']
            assert row.match_confirmed and row.awaiting_confirmation and row.mix_gain == 0
            assert row.join.text() == '确认对齐并加入' and not row.join.isHidden()
            row.delay.setValue(row.delay.value() + .1)
            assert not viewer.alignment.automatic and row.mix_gain == 0 and not row.join.isHidden()
            preview = viewer.shifts()
            main_shift = viewer.shifts()['1']
            row.join.click()
            now[0] += .6
            viewer.render()
            assert row.user_confirmed and not row.awaiting_confirmation and row.mix_gain == 1
            assert viewer.alignment.automatic and all(abs(viewer.shifts()[key] - value) < 1e-9 for key, value in preview.items())
            assert viewer.shifts()['1'] == main_shift

            # An uncertain feed remains discoverable after its old deadline.
            viewer._block_alignment('2', 'uncertain fixture')
            assert '2' in viewer.independent_shifts and row.mix_gain == 0
            now[0] += 30
            viewer.canvas.waiting = True  # RGB waiting must not block source analysis.
            deliveries = []
            viewer.results.matched.connect(lambda epoch, results: deliveries.append(tuple(results)))
            viewer.analysis_cursor = 0
            with patch.object(module.threading, 'Thread', side_effect=inline), \
                    patch.object(module, 'match_scenes', side_effect=RuntimeError('worker fixture')):
                viewer.analyse()
                assert not viewer.matching and 'RuntimeError' in row.match_text
            now[0] += 2
            with patch.object(module.threading, 'Thread', side_effect=inline), \
                    patch.object(module, 'match_scenes', return_value=lag):
                for _ in range(5):
                    viewer.analyse()
            assert ('2',) in deliveries and ('3',) in deliveries
            assert row.match_confirmed and '2' not in viewer.independent_shifts
            assert row.user_confirmed and not row.awaiting_confirmation, 'Recovery must reuse the human approval'
            assert viewer.admit_pending('2')
            position = viewer.audio.clock() + viewer.shifts()['2']
            assert row.decoder.history.bounds_at(position)[1] - position >= viewer.safety_buffer.target - .001, \
                'Explicit late admission must restore the safety reserve, not a 300ms underrun loop'

            # A new global result needs affirmative agreement with a healthy
            # third feed. An inconclusive peer check is not positive evidence.
            for item in viewer.rows.values():
                item.decoder.history.details = [Sample(100, 0, 10, bytes(256))]
            viewer.rows['3'].match_confirmed = True
            viewer.rows['3'].sync_state = '已同步'
            viewer._queue_rematch(row)
            viewer.analysis_cursor = 0
            with patch.object(module.threading, 'Thread', side_effect=inline), \
                    patch.object(module, 'match_scenes', return_value=lag), \
                    patch.object(module, 'refine_match', return_value=Match(None, 0, 'ambiguous peer')):
                viewer.analyse()
            assert not row.match_confirmed and '三路' in row.match_text
            for item in viewer.rows.values():
                item.decoder.history.details = []

            # A cancelled worker cannot clear or deliver into the replacement job.
            serial = viewer.analysis_serial
            viewer.retry_alignment('2')
            viewer.matching = True
            viewer._analysis_finished(serial, viewer.generation, {'2': lag})
            assert viewer.matching
            viewer.matching = False

            # Reconnection must drain an available old epoch before invalidating
            # approval, then retire it even when the clock waits at its last frame.
            main_row = viewer.rows['1']
            old = video.VideoHistory()
            old.set_origin(100)
            old.frames.extend((stamp / 20, stamp / 20 - 100) for stamp in range(2200, 2400))
            fresh = video.VideoHistory()
            fresh.set_origin(125)
            fresh.previous = old
            fresh.frames.extend((stamp / 20, stamp / 20 - 125) for stamp in range(2500, 2680))
            main_row.decoder.history = fresh
            viewer.audio.correction = 0
            viewer.stable_reference_shift = -6
            viewer.rendered_shifts.clear()
            viewer.shift_reference = None
            now[0] = 120
            main_row.decoder.last_frame_received = now[0]
            main_row.mix_gain = 1
            viewer._reset(main_row, main_row.decoder)
            assert main_row.reset_pending and main_row.mix_gain == 1
            with patch.object(main_row.decoder, 'picture_at', return_value=None, create=True):
                viewer.render()
                assert fresh.previous is old and main_row.reset_pending
                now[0] = old.bounds()[1] - viewer.shifts()['1'] - .05
                main_row.decoder.last_frame_received = now[0]
                viewer.render()
            assert fresh.previous is None and not main_row.reset_pending
            assert viewer.audio.clock() + viewer.shifts()['1'] >= fresh.bounds()[0]
        finally:
            viewer.close()

    previous = video.VideoHistory(byte_limit=6000)
    previous.set_origin(100)
    for index in range(20):
        packet = video.av.Packet(b'x' * 100)
        packet.pts = packet.dts = index
        packet.time_base = Fraction(1, 10)
        packet.is_keyframe = index % 4 == 0
        previous.append_packet(packet)
        previous.append(100 + index / 10, index / 10)
    pcm = b'\x01\x00\x02\x00' * 480
    previous.audio.append_at(48000, pcm)
    current = video.VideoHistory(byte_limit=6000)
    current.previous = previous
    current.set_origin(120)
    assert current.frame_at(101)[0] == 101 and current.bounds_at(101) == (100, 101.9)
    assert current.pcm_at(101, 480) == pcm
    overlapping = video.VideoHistory()
    overlapping.set_origin(101)
    overlapping.frames.extend(((101, 0), (102, 1)))
    overlapping.previous = previous
    assert overlapping.segment_at(101) is previous, 'Overlapping new PTS must not silently replace the playing epoch'
    assert current.frame_at(110) is None, 'A missing epoch must not repeat an old picture'
    for index in range(50):
        packet = video.av.Packet(b'x' * 100)
        packet.pts = packet.dts = index
        packet.time_base = Fraction(1, 10)
        packet.is_keyframe = index % 4 == 0
        current.append_packet(packet)
        current.append(120 + index / 10, index / 10)
        assert current.byte_size + previous.byte_size <= current.byte_limit
    current.append(127, 7)
    assert current.frame_at(126) is None, 'PTS holes must not count as playable reserve'
    assert current.bounds_at(127) == (127, 127)
    print('PASS: confirmation, recurring search, worker failure/cancellation, fair three-stream analysis, retained native history/PCM and bounded gaps')


if __name__ == '__main__':
    main()
