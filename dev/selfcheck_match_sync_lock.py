"""Manual alignment survives single-source stalls and reconnects; no live streams."""
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
os.environ["DDM_NO_SAVE"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget
from ddm import plugins
from dev.selfcheck_match_sync import FakeChat, FakeDecoder, FakeDevice, FakeSink, jpeg
from plugins_user._match_sync import viewer as module
from plugins_user._match_sync.engine import History, Match


def main():
    app = QApplication([])
    now = [120.0]
    with tempfile.TemporaryDirectory() as root, \
            patch.object(module, "Decoder", FakeDecoder), patch.object(module, "Chat", FakeChat), \
            patch.object(module.AudioPump, "start", lambda _self: None), \
            patch.object(module.time, "monotonic", side_effect=lambda: now[0]):
        host = QWidget()
        host.settings = {}
        manager = plugins.PluginManager(window=host, plugins_dir=root)
        viewer = module.Viewer(plugins.PluginContext(manager, "lock_check"), {})
        try:
            viewer.add_room("1", {"alias": "主画面"})
            viewer.add_room("2", {"alias": "二路"})
            viewer.toggle_running()
            viewer.render_timer.stop()
            viewer.match_timer.stop()
            image = jpeg()
            for row in viewer.rows.values():
                row.decoder.last_frame_received = now[0]
                for stamp in range(80, 121):
                    row.decoder.history.append(stamp, image)
            viewer.alignment.accept("2", Match(5, 1, "confirmed"))
            assert viewer.alignment.accept("2", Match(5, 1, "confirmed"))
            viewer.render()
            secondary = viewer.rows["2"]
            secondary.delay.setValue(-1)
            viewer.compare.setChecked(False)
            baseline = dict(viewer.alignment.lags)
            shifts = viewer.shifts()
            assert shifts == {"1": -8, "2": -2}
            assert viewer.alignment.manual_locked and not viewer.automatic.isChecked()
            assert "已锁定" in secondary.match_text
            for _ in range(4):
                viewer._matched(viewer.generation, {"2": Match(20, 1, "must not overwrite")})
                assert not viewer.alignment.accept("2", Match(20, 1, "must not overwrite"))
            assert viewer.shifts() == shifts and viewer.alignment.lags == baseline
            print("PASS: manual edit freezes existing auto baseline, closes comparison safely, rejects automatic overwrites")

            for stalled in ("1", "2"):
                viewer.locked_clock = None
                viewer.sync_waiting = False
                viewer.audio.correction = 0
                now[0] = 120
                for row in viewer.rows.values():
                    row.decoder.history = History()
                    row.decoder.last_frame_received = now[0]
                    for stamp in range(80, 121):
                        row.decoder.history.append(stamp, image)
                viewer.render()
                clocks = []
                for stamp in range(121, 135):
                    now[0] = stamp
                    for key, row in viewer.rows.items():
                        if key != stalled:
                            row.decoder.history.append(stamp, image)
                            row.decoder.last_frame_received = stamp
                    viewer.render()
                    if viewer.sync_waiting:
                        clocks.append(viewer.audio.clock())
                assert len(clocks) >= 3 and max(clocks) - min(clocks) < 1e-7, clocks
                assert viewer.picture._buffering and not viewer.canvas.image.isNull()
                assert viewer.shifts() == shifts and secondary.delay.value() == -1
                for row in viewer.rows.values():
                    assert row.decoder.history.frame_at(clocks[-1] + shifts[row.room_id]) is not None
                viewer.audio.sink = FakeSink()
                viewer.audio.device = FakeDevice(viewer.audio.sink)
                with patch.object(secondary.decoder.history, "pcm_at") as pcm:
                    viewer.audio.fill()
                    assert viewer.audio.device.data and not any(viewer.audio.device.data)
                    assert not pcm.called, "Waiting must silence audio rather than loop a frozen PCM interval"
                viewer.audio.stop()
                worker = viewer.rows[stalled].decoder
                worker.history = History()
                viewer._reset(viewer.rows[stalled], worker)
                viewer.render()
                assert viewer.sync_waiting and viewer.alignment.lags == baseline
                now[0] = 140
                for key, row in viewer.rows.items():
                    for stamp in range(136, 141):
                        row.decoder.history.append(stamp, image)
                    row.decoder.last_frame_received = now[0]
                viewer.render()
                for stamp in range(141, 148):
                    now[0] = stamp
                    for row in viewer.rows.values():
                        row.decoder.history.append(stamp, image)
                        row.decoder.last_frame_received = stamp
                    viewer.render()
                assert not viewer.sync_waiting and not viewer.picture._buffering
                assert viewer.shifts() == shifts and viewer.alignment.lags == baseline
                assert all(row.decoder.history.frame_at(viewer.audio.clock() + shifts[key]) is not None
                           for key, row in viewer.rows.items())
                print(f"PASS: source {stalled} stalls over three seconds, pair waits silently, reset preserves alignment, common cache resumes")

            previous = secondary.decoder
            viewer.select_main("2")
            assert viewer.shifts() == shifts
            viewer.picture.set_quality(80)
            assert previous.stopped and secondary.decoder is not previous
            assert viewer.shifts() == shifts and viewer.alignment.manual_locked
            viewer.stop()
            viewer.toggle_running()
            viewer.render_timer.stop()
            viewer.match_timer.stop()
            assert viewer.shifts() == shifts and viewer.alignment.manual_locked
            viewer.add_room("3", {"alias": "第三路"})
            now[0] = 180
            for row in viewer.rows.values():
                row.decoder.last_frame_received = now[0]
                for stamp in range(150, 181):
                    row.decoder.history.append(stamp, image)
            viewer.render()
            assert viewer.shifts()["2"] - viewer.shifts()["1"] == 6
            for stamp in range(181, 190):
                now[0] = stamp
                for key, row in viewer.rows.items():
                    if key != "3":
                        row.decoder.history.append(stamp, image)
                        row.decoder.last_frame_received = stamp
                viewer.render()
            assert viewer.sync_waiting
            viewer.rows["3"].paused = True
            viewer.render()
            assert not viewer.sync_waiting, "A room explicitly paused by the user must not block the remaining rooms"
            print("PASS: third source joins locked pair, its stall holds all rooms, explicit pause releases the remaining pair")
            viewer.automatic.setChecked(True)
            assert not viewer.alignment.manual_locked and not viewer.sync_waiting
            viewer.compare.setChecked(False)
            for _ in range(2):
                viewer._matched(viewer.generation, {"1": Match(-3, 1, "explicitly unlocked")})
            assert viewer.alignment.lags["1"] == -3
            print("PASS: main/quality/restart preserve lock, explicit automatic checkbox releases lock and accepts new matching")
        finally:
            viewer.close()
            host.close()
            app.processEvents()


if __name__ == "__main__":
    main()
