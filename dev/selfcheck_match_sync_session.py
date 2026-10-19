"""Actual three-stream receive, automatic alignment and comparison admission."""
import faulthandler
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("DDM_NO_SAVE", "1")
from PySide6.QtWidgets import QApplication, QWidget
from ddm import plugins, recording
from dev.selfcheck_match_sync import FakeDecoder, FakeChat
from plugins_user._match_sync import media, viewer as module


def main():
    app = QApplication([])
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as root, \
            patch.object(module, "Decoder", FakeDecoder), patch.object(module, "Chat", FakeChat), \
            patch.object(module.AudioPump, "start", lambda _self: None):
        source = Path(root) / "scene.mkv"
        # Locally similar motion phases must not replace the exact timestamp
        # relationship when a cropped stream restarts from the beginning.
        subprocess.run([recording.ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-nostdin",
            "-f", "lavfi", "-i", "nullsrc=size=320x180:rate=60,geq=lum='128+40*sin(X*0.03+N*0.13)+40*sin(Y*0.04+N*0.061)+25*sin((X+Y)*0.02+N*0.027)':cb=128:cr=128",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
            "-t", "36", "-c:v", "libx264", "-threads", "2", "-preset", "ultrafast",
            "-c:a", "pcm_s16le", str(source)], check=True, capture_output=True, timeout=30,
            creationflags=recording._FFMPEG_FLAGS)
        host = QWidget()
        host.settings = {}
        context = plugins.PluginContext(plugins.PluginManager(window=host, plugins_dir=root), "session_check")
        viewer = module.Viewer(context, {})
        decoders = []
        try:
            viewer.show()
            for key in ("1", "2", "3"):
                viewer.add_room(key, {"alias": key})
            viewer.toggle_running()
            viewer.render_timer.stop()
            viewer.match_timer.stop()
            for key, row in viewer.rows.items():
                row.decoder.stop()
                row.decoder = media.Decoder(key, {"url": str(source)})
                decoders.append(row.decoder)
            begin = time.monotonic()
            decoders[0].start()
            started = 1
            next_match = 0
            matched_at = None
            while time.monotonic() - begin < 11:
                elapsed = time.monotonic() - begin
                if started < 3 and elapsed >= started * .8:
                    decoders[started].start()
                    started += 1
                viewer.render()
                if elapsed >= next_match:
                    viewer.analyse()
                    next_match = elapsed + .5
                app.processEvents()
                for key, pending in viewer.rows.items():
                    if pending.awaiting_confirmation and pending.match_confirmed:
                        assert pending.mix_gain == 0
                        viewer.admit_pending(key)
                if all(row.sync_state == "已同步" for row in viewer.rows.values()):
                    if matched_at is None:
                        matched_at = time.monotonic()
                        viewer.show_comparison("2")
                    if time.monotonic() - matched_at > 1:
                        break
                time.sleep(.005)
            assert matched_at is not None, {key: (row.sync_state, row.match_text) for key, row in viewer.rows.items()}
            for key in ("2", "3"):
                expected = viewer.rows[key].decoder.history.origin - decoders[0].history.origin
                assert abs(viewer.alignment.lags[key] - expected) <= .08, (key, expected, viewer.alignment.lags)
            actual = viewer.rows["2"].actual_position - viewer.rows["1"].actual_position
            expected = decoders[1].history.origin - decoders[0].history.origin
            assert abs(actual - expected) <= .1, (actual, expected)
            print(f"MEASURE: three real pipelines confirmed in {matched_at-begin:.2f}s; visible scene error {abs(actual-expected)*1000:.0f}ms")
            assert all(row.mix_gain == 1 for row in viewer.rows.values())
            assert viewer.compare.isChecked() and viewer.alignment.automatic
            # Recollect the larger focused features on all three feeds without
            # losing the human approvals or moving the healthy main timeline.
            main_shift = viewer.shifts()['1']
            for row in viewer.rows.values():
                row.crop = (.1, .1, .8, .8)
                row.decoder.set_crop(row.crop)
            viewer.retry_alignment('1')
            recrop_started = time.monotonic()
            while time.monotonic() - recrop_started < 8:
                viewer.render()
                viewer.analyse()
                app.processEvents()
                assert viewer.shifts()['1'] == main_shift and not viewer.sync_waiting
                assert not any(row.awaiting_confirmation for row in viewer.rows.values())
                if all(row.sync_state == '已同步' for row in viewer.rows.values()):
                    break
                time.sleep(.01)
            assert all(row.sync_state == '已同步' for row in viewer.rows.values()), [(r.match_text, r.sync_state) for r in viewer.rows.values()]
            print('PASS: three focused feature streams reacquire fairly without repeated approval or moving the main')
            # Resume one stream with a new PTS origin, reproducing a delayed rejoin.
            peer_lag = viewer.alignment.lags["3"]
            row = viewer.rows["2"]
            row.decoder.stop()
            row.decoder = media.Decoder("2", {"url": str(source)})
            row.decoder.set_crop(row.crop)
            decoders.append(row.decoder)
            viewer._reset(row, row.decoder)
            row.decoder.start()
            resumed = time.monotonic()
            next_match = resumed
            recovered_at = None
            checked_late = False
            main_shift = viewer.shifts()['1']
            # Cropping cleared the pre-crop features. The restarted file must
            # reach that retained scene interval for matching, but cannot catch
            # the healthy main by replaying old content at the same speed.
            while time.monotonic() - resumed < 18:
                viewer.render()
                if time.monotonic() >= next_match:
                    viewer.analyse()
                    next_match = time.monotonic() + .5
                app.processEvents()
                if row.match_confirmed and not checked_late:
                    assert viewer.shifts()['1'] == main_shift, 'An automatic late recovery must not rewind the main'
                    assert viewer.rows['1'].sync_state == '已同步' and row.mix_gain == 0
                    fixed_clock, fixed_shifts = viewer.audio.clock(), viewer.shifts()
                    assert viewer.admit_pending('2') is False
                    assert viewer.shifts() == fixed_shifts
                    assert viewer.audio.clock() >= fixed_clock
                    checked_late = True
                expected = (row.decoder.history.origin - decoders[0].history.origin
                            if row.decoder.history.origin is not None else None)
                actual = row.actual_position - viewer.rows["1"].actual_position if row.actual_position is not None else None
                if expected is not None and actual is not None and row.match_confirmed and row.sync_state == '已同步':
                    assert abs(actual - expected) <= .2, ('False recovery confirmation', actual, expected, row.match_text)
                if (expected is not None and actual is not None and row.match_confirmed
                        and row.sync_state == "已同步" and abs(actual-expected) <= .1):
                    if recovered_at is None:
                        recovered_at = time.monotonic()
                    if time.monotonic() - recovered_at >= .5:
                        break
                time.sleep(.005)
            # A restarted file advances at the same speed as the fixed main and
            # cannot catch up. Whether historical matching has reached its
            # intermediate "confirmed" state is not the playback requirement.
            # Verify the actual missing-content condition even when scene
            # ambiguity correctly keeps the source unconfirmed (also on v1.2.6).
            expected = row.decoder.history.origin - decoders[0].history.origin
            target = viewer.audio.clock() + viewer.shifts()['1'] + expected
            assert target > row.decoder.history.bounds()[1], 'The restarted fixture must actually be late'
            assert recovered_at is None, (row.match_text, row.sync_state)
            assert row.mix_gain == 0 and viewer.shifts()['1'] == main_shift
            assert abs(viewer.alignment.lags["3"] - peer_lag) <= .08
            assert not viewer.rows["1"].paused and not viewer.sync_waiting
            print("PASS: restarted source remains muted when its content cannot reach the fixed main; healthy streams continue")
        finally:
            viewer.close()
            for decoder in decoders:
                if decoder.thread is not None:
                    decoder.thread.join(4)
                    assert not decoder.thread.is_alive()
            host.close()
            app.processEvents()
    print("PASS: independent stream starts, actual frame alignment/admission, comparison tracking and cleanup")


if __name__ == "__main__":
    faulthandler.dump_traceback_later(50, exit=True)
    try:
        main()
    finally:
        faulthandler.cancel_dump_traceback_later()
