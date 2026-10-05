"""Local multi-room comparison, fair overlay admission and live-clock recovery."""
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
from ddm import plugins, theme
from dev.selfcheck_match_sync import FakeChat, FakeDecoder, FakeDevice, FakeSink, jpeg
from plugins_user._match_sync import viewer as module


def main():
    app = QApplication([])
    app.setStyleSheet(theme.qss())
    with tempfile.TemporaryDirectory() as root, \
            patch.object(module, "Chat", FakeChat), patch.object(module, "Decoder", FakeDecoder), \
            patch.object(module.AudioPump, "start", lambda _self: None):
        host = QWidget()
        host.settings = {"video_danmaku_size": 16, "video_danmaku_scale": False}
        manager = plugins.PluginManager(window=host, plugins_dir=root)
        viewer = module.Viewer(plugins.PluginContext(manager, "playback_check"), {})
        viewer.resize(1600, 1000)
        viewer.show()
        try:
            for key in ("1", "2", "3", "4", "5", "6"):
                viewer.add_room(key, {"alias": "主播" + key})
            viewer.toggle_running()
            viewer.render_timer.stop()
            viewer.match_timer.stop()
            viewer.audio.clock = lambda: 100
            image = jpeg()
            for row in viewer.rows.values():
                for stamp in range(80, 101):
                    row.decoder.history.append(stamp, image)
            viewer.rows["5"].delay.setValue(.5)
            app.processEvents()
            panel = viewer.comparison_panel
            assert panel.shown_rooms == ("1", "5"), panel.shown_rooms
            assert panel.target.isVisible()
            assert sum(card[0].isVisible() for card in panel.cards.values()) == 2
            assert panel.cards["1"][0].x() < panel.cards["5"][0].x()
            (REPO / "work").mkdir(exist_ok=True)
            panel.grab().save(str(REPO / "work/match-sync-six-room-comparison.png"))
            panel.target.setCurrentIndex(panel.target.findData("6"))
            assert panel.shown_rooms == ("1", "6")
            decoders = [row.decoder for row in viewer.rows.values()]
            panel.close_button.click()
            app.processEvents()
            assert panel.isHidden() and not viewer.compare.isChecked()
            assert viewer.rows["5"].delay.value() == .5 and viewer.running
            assert [row.decoder for row in viewer.rows.values()] == decoders
            print("PASS: six rooms keep two readable comparison pictures, choose room, collapse without losing offsets")

            viewer.picture.danmaku_button.setChecked(True)
            accepted = []
            slots = [1]
            def admit(event):
                if not slots[0]:
                    return False
                slots[0] -= 1
                accepted.append(event["source_room"])
                return True
            with patch.object(viewer.video_danmaku, "add_event", side_effect=admit):
                viewer.rows["2"].pending.extend((97, {"text": "先到弹幕"}) for _ in range(50))
                viewer.render()
                assert accepted == ["2"]
                viewer.rows["1"].pending.append((97, {"text": "玩机器首次弹幕"}))
                viewer.render()  # Full lane: preserve one fresh message, rather than lose the source.
                assert "1" in viewer.overlay_pending
                for key in ("2", "3", "4", "5", "6"):
                    viewer.rows[key].pending.append((97, {"text": "其他来源"}))
                for _ in range(6):
                    slots[0] = 1
                    viewer.render()
                assert accepted[1:] == ["3", "4", "5", "6", "1", "2"], accepted
                assert not viewer.overlay_pending
                viewer.rows["1"].pending.append((80, {"text": "旧弹幕"}))
                viewer.render()
                assert not viewer.overlay_pending
            assert [row.decoder for row in viewer.rows.values()] == decoders
            print("PASS: late source reaches first enabled overlay, round-robin lanes, bounded fresh messages, no decoder restart")

            for key in list(viewer.rows)[2:]:
                viewer.remove_room(key)
            viewer.rows["1"].delay.setValue(0)
            viewer.rows["2"].delay.setValue(-4)
            viewer.automatic.setChecked(False)
            viewer.automatic.setChecked(True)  # Exercise the unlocked recovery policy separately.
            del viewer.audio.clock
            with patch.object(module.time, "monotonic", return_value=120):
                for key, row in viewer.rows.items():
                    row.decoder.last_frame_received = 120
                    row.decoder.history.frames.clear()
                    for stamp in range(80, 111 if key == "1" else 109):
                        row.decoder.history.append(stamp, image)
                shifts = viewer.shifts()
                assert shifts["2"] - shifts["1"] == 4
                viewer.render()
                assert not viewer.canvas.image.isNull() and not viewer.picture._buffering, "Live video must recover when the clock outruns decoded frames"
                clock = viewer.audio.clock()
                assert all(row.decoder.history.frame_at(clock + shifts[key]) is not None
                           for key, row in viewer.rows.items())
                assert clock < 120 and viewer.audio.correction < 0
                assert viewer.shifts() == shifts, "Clock recovery must preserve manual relative offsets"
                viewer.audio.sink = FakeSink()
                viewer.audio.device = FakeDevice(viewer.audio.sink)
                viewer.audio.anchor = 120
                with patch.object(viewer.rows["1"].decoder.history, "pcm_at", return_value=bytes(1920)) as main_pcm, \
                        patch.object(viewer.rows["2"].decoder.history, "pcm_at", return_value=bytes(1920)) as other_pcm:
                    viewer.audio.fill()
                    assert abs(main_pcm.call_args.args[0] - clock - shifts["1"]) < 1e-7
                    assert abs(other_pcm.call_args.args[0] - clock - shifts["2"]) < 1e-7
                viewer.audio.stop()
                viewer.rows["2"].pending.append((106, {"text": "recovered chat"}))
                viewer.render()
                assert viewer.panel._blocks[-1]["text"] == "recovered chat"
                correction = viewer.audio.correction
                for row in viewer.rows.values():
                    row.decoder.last_frame_received = 100
                assert viewer._recover_clock(140, shifts) == 140
                assert viewer.audio.correction == correction, "Disconnected rooms must not repeatedly rewind playback"
                viewer.rows["1"].decoder.last_frame_received = 120
                viewer.rows["1"].delay.setValue(60)
                clock = viewer.audio.clock()
                assert viewer._recover_clock(clock, viewer.shifts()) == clock
            assert viewer.rows["1"].decoder is decoders[0]
            print("PASS: healthy delayed decoders recover video/audio/chat clock, preserve offsets, ignore stale inputs and retain oversized-delay wait")
            with patch.object(module.time, "monotonic", return_value=200):
                viewer.audio.correction = 0
                for row in viewer.rows.values():
                    row.delay.setValue(0)
                    row.decoder.last_frame_received = 200
                    row.decoder.history.frames.clear()
                    for stamp in (200, 200.25, 200.5):
                        row.decoder.history.append(stamp, image)
                viewer.render()
                assert not viewer.picture._buffering, "Startup should use the first quarter second of shared history"
                assert abs(viewer.audio.clock() - 202.1) < 1e-6
                for row in viewer.rows.values():
                    for stamp in (201, 202, 203, 204):
                        row.decoder.history.append(stamp, image)
                viewer.rows["2"].delay.setValue(-3)
                shifts = viewer.shifts()
                viewer.render()
                assert not viewer.picture._buffering and shifts["2"] - shifts["1"] == 3
                assert all(row.decoder.history.frame_at(viewer.audio.clock() + shifts[key]) is not None
                           for key, row in viewer.rows.items()), "Offset changes should seek shared available history"
                key = viewer.canvas.frame_key
                viewer.rows["2"].delay.setValue(-60)
                correction = viewer.audio.correction
                viewer.render()
                assert viewer.picture._buffering and not viewer.canvas.image.isNull()
                assert viewer.canvas.frame_key == key and viewer.audio.correction == correction
                assert viewer.comparison_panel.cards["1"][2].waiting
                assert not viewer.comparison_panel.cards["1"][2].image.isNull()
                with patch.object(viewer.picture, "set_buffering", wraps=viewer.picture.set_buffering) as buffering:
                    viewer.render()
                    viewer.render()
                    assert not buffering.called, "Retained frame must not restart the spinner every render"
            print("PASS: quarter-second startup, shared cache seek on offset change, last frame retained when history cannot overlap")

            with patch.object(module.time, "monotonic", return_value=240):
                viewer.audio.correction = 0
                for row in viewer.rows.values():
                    row.delay.setValue(0)
                    row.pending.clear()
                    row.decoder.last_frame_received = 240
                    row.decoder.history.frames.clear()
                    for stamp in range(200, 211):
                        row.decoder.history.append(stamp, image)
                viewer.locked_clock = None
                viewer.sync_waiting = False
                viewer.audio.correction = 0
                viewer.render()
                row = viewer.rows["2"]
                row.chat.events.message.emit({"text": "斗鱼时间轴弹幕"})
                assert row.pending[0][0] == 210, "Receipt must follow decoder time rather than drifted wall time"
                viewer._reset(row, row.decoder)
                assert row.pending, "Video reconnect must preserve independent chat messages"
            with patch.object(module.time, "monotonic", return_value=240.5):
                for row in viewer.rows.values():
                    row.decoder.history.append(210.5, image)
                    row.decoder.last_frame_received = 240.5
                viewer.render()
                assert viewer.panel._blocks[-1]["text"] == "斗鱼时间轴弹幕"
            assert [row.decoder for row in viewer.rows.values()] == decoders[:2]
            print("PASS: thirty-second decoder drift does not hide chat, pending messages survive video reset")
        finally:
            viewer.close()
            host.close()
            app.processEvents()


if __name__ == "__main__":
    main()
