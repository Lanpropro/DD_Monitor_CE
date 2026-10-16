"""Admission, isolation, jitter buffering, audio clock and comparison tracking."""
import os
from pathlib import Path
import sys
import tempfile
from array import array
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("DDM_NO_SAVE", "1")
from PySide6.QtWidgets import QApplication, QWidget
from ddm import plugins
from dev.selfcheck_match_sync import FakeChat, FakeDecoder, FakeDevice, FakeSink, jpeg
from plugins_user._match_sync import viewer as module
from plugins_user._match_sync.engine import Match, SafetyBuffer, resample_pcm
from plugins_user._match_sync.engine import Sample, refine_match
from dev.selfcheck_match_sync_refinement import samples
from plugins_user._match_sync.video import PictureReader


def main():
    buffer = SafetyBuffer()
    assert buffer.target == 6
    for i in range(40):
        buffer.observe("main", 1 + i * 3.1, 60)
        buffer.rate(1 + i * 3.1, 3)
    assert buffer.target == 8 and buffer.rate(125, 2) == .98
    for i in range(300):
        buffer.observe("main", 126 + i / 60, 60)
        buffer.rate(126 + i / 60, 3)
    assert 2 <= buffer.target < 8
    assert len(resample_pcm(array("h", [1000, -1000] * 485).tobytes(), 480)) == 1920
    corner = []
    for sample in samples():
        feature = bytearray([128] * 256)
        for y in range(8):
            feature[y * 16:y * 16 + 8] = sample.feature[y * 16:y * 16 + 8]
        corner.append(Sample(sample.time, sample.signature, sample.texture, bytes(feature)))
    assert refine_match(Match(0, 1, "corner animation"), corner, corner).lag is None
    reader = PictureReader()
    reader.thread = Mock()
    reader.target = (10.2, 10.2)
    reader.history = object()
    reader.images[10.1] = module.QImage(20, 20, module.QImage.Format_RGB32)
    assert reader.get(reader.history, (10.1, 10.1), exact=True)[0] == 10.1
    assert reader.target == (10.2, 10.2) and not reader.wake.is_set()
    reader.configure(128 * 1024 * 1024, 30)
    assert reader.fps == 30 and reader.max_frames == 24
    reader.stop()

    app = QApplication([])
    now = [120.0]
    with tempfile.TemporaryDirectory() as root, patch.object(module, "Decoder", FakeDecoder), \
            patch.object(module, "Chat", FakeChat), patch.object(module.AudioPump, "start", lambda _self: None), \
            patch.object(module.time, "monotonic", side_effect=lambda: now[0]):
        host = QWidget()
        host.settings = {}
        context = plugins.PluginContext(plugins.PluginManager(window=host, plugins_dir=root), "control_check")
        viewer = module.Viewer(context, {})
        viewer.alignment.buffer_seconds = 3  # Exercise this legacy admission fixture on its fixed timeline.
        try:
            for key in ("1", "2", "3"):
                viewer.add_room(key, {"alias": key})
            viewer.toggle_running()
            viewer.render_timer.stop()
            viewer.match_timer.stop()
            viewer.alignment.lags["2"] = 0
            viewer.rows["2"].match_confirmed = True
            image = jpeg()
            for row in viewer.rows.values():
                for stamp in range(80, 121):
                    row.decoder.history.append(stamp, image)
                row.decoder.last_frame_received = now[0]
            assert viewer.alignment.buffer_seconds == 3
            viewer.render()
            assert viewer.rows["2"].sync_state == "已同步"
            assert viewer.rows["3"].sync_state == "等待对齐" and viewer.rows["3"].mix_gain == 0
            for _ in range(3):
                viewer._matched(viewer.generation, {"2": Match(None, 0, "比赛区域变化不足")})
            assert viewer.rows["2"].match_confirmed, "A static scene must preserve established synchronization"
            for _ in range(3):
                viewer._matched(viewer.generation, {"2": Match(None, 0, "三路时间差不一致")})
            assert not viewer.rows["2"].match_confirmed
            viewer.rows["2"].match_confirmed = True
            viewer.rows["2"].match_failures = 0
            viewer.independent_shifts.pop("2", None)
            viewer.alignment.lags["2"] = 0
            original = viewer.canvas.frame_key
            viewer.alignment.lags["3"] = 8
            viewer.rows["3"].match_confirmed = True
            for stamp in range(121, 127):
                now[0] = stamp
                viewer.rows["1"].decoder.history.append(stamp, image)
                viewer.rows["1"].decoder.last_frame_received = stamp
                viewer.render()
            assert viewer.canvas.frame_key > original and not viewer.sync_waiting
            assert viewer.rows["2"].sync_state == "暂时隔离" and viewer.rows["2"].mix_gain == 0
            assert viewer.rows["3"].mix_gain == 0, "Late third stream must not shift the established main"
            for step in (0, .25, .55, .8):
                now[0] = 127 + step
                if step:
                    viewer.rows["2"].match_confirmed = True  # Reconfirmation precedes the recovery/fade fixture.
                for key in ("1", "2"):
                    row = viewer.rows[key]
                    row.decoder.history.append(now[0], image)
                    row.decoder.last_frame_received = now[0]
                viewer.rows["3"].decoder.history.append(now[0], image)
                viewer.rows["3"].decoder.last_frame_received = now[0]
                viewer.render()
                if step < .5:
                    assert viewer.rows["2"].mix_gain == 0
            assert viewer.rows["2"].sync_state == "已同步" and viewer.rows["2"].mix_gain == 1
            assert viewer.rows["3"].join.isHidden(), "Late feed cannot offer an action that delays the main"
            before_manual = viewer.canvas.frame_key
            viewer.rows["2"].delay.setValue(.1)
            assert viewer.canvas.frame_key == before_manual and viewer.rows["3"].mix_gain == 0
            viewer.automatic.setChecked(True)
            viewer.alignment.lags.update({"2": 0, "3": 8})
            viewer.rows["2"].match_confirmed = viewer.rows["3"].match_confirmed = True
            viewer.stable_reference_shift = -3
            viewer.render()
            before_join = viewer.shifts()
            assert viewer.admit_pending("3") is False
            assert viewer.rows["3"].mix_gain == 0
            assert viewer.shifts() == before_join
            viewer.admitted_rooms.clear()
            viewer._smooth_shifts({"1": -3, "2": -3, "3": -3})
            now[0] += .05
            controlled = viewer._smooth_shifts({"1": -3, "2": -2.85, "3": -3})
            assert 0 < controlled["2"] + 3 <= .00101 and abs(viewer.relative_rates["2"] - 1.02) < 1e-6
            viewer.relative_rates.clear()
            viewer.show_comparison("2")
            deliveries = []
            viewer.results.matched.connect(lambda epoch, results: deliveries.append(tuple(results)))
            with patch.object(module, "match_scenes", return_value=Match(0, 1, "test")), \
                    patch.object(module, "refine_match", return_value=Match(0, 1, "test", refined=True)), \
                    patch.object(module.threading, "Thread") as thread:
                thread.side_effect = lambda **kwargs: type("Inline", (), {"start": lambda self: kwargs["target"]()})()
                for _ in range(4):
                    # Coarse-only fixtures must respect the tracking retry delay.
                    now[0] += 2
                    viewer.analyse()
                assert thread.call_count == 4, "Viewing comparison must keep automatic analysis active"
                assert deliveries == [("2",), ("3",), ("2",), ("3",)]
            sink = FakeSink()
            sink.processedUSecs = lambda: 10000
            viewer.audio.sink = sink
            viewer.audio.device = FakeDevice(sink)
            viewer.audio.anchor = 100
            viewer.audio.correction = 0
            viewer.playback_rate = 1.01
            for row in viewer.rows.values():
                row.decoder.history.pcm_at = lambda timestamp, frames: array("h", [1000, -1000] * frames).tobytes()
            viewer.audio.fill()
            assert len(viewer.audio.device.data) == 1920
            assert abs(viewer.audio.clock() - (100 + 485 / 48000)) < 1e-8
            viewer.audio.stop()
        finally:
            viewer.close()
            host.close()
            app.processEvents()
    print("PASS: bounded adaptive buffer, cached microseek, late admission, independent isolation/recovery/fade, comparison tracking, speed-aware audio clock")


if __name__ == "__main__":
    main()
