"""Enumerate three-room chat joins, toggles, removals and video overlay without network."""
import itertools
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
from dev.selfcheck_match_sync import FakeChat, FakeDecoder, jpeg
from plugins_user._match_sync import viewer as module


def check_sources(viewer, keys):
    viewer.panel.clear()
    viewer.picture.video_danmaku.clear()
    with patch.object(module.time, "monotonic", return_value=95):
        for key, row in viewer.rows.items():
            row.pending.clear()
            if row.chat is not None:
                row.chat.events.message.emit({"uname": "观众", "text": "消息" + key})
    viewer.render()
    assert {e["uname"] for e in viewer.panel._blocks} == {"【主播" + key + "】 观众" for key in keys}


def main():
    app = QApplication([])
    cases = 0
    with tempfile.TemporaryDirectory() as root, \
            patch.object(module, "Chat", FakeChat), patch.object(module, "Decoder", FakeDecoder), \
            patch.object(module.AudioPump, "start", lambda _self: None):
        for order in itertools.permutations(("1", "2", "3")):
            host = QWidget()
            host.settings = {"video_danmaku_size": 16, "video_danmaku_area": 100}
            manager = plugins.PluginManager(window=host, plugins_dir=root)
            viewer = module.Viewer(plugins.PluginContext(manager, "chat_check"), {})
            viewer.resize(1600, 1000)
            viewer.show()
            try:
                viewer.render_timer.stop()
                viewer.match_timer.stop()
                viewer.audio.clock = lambda: 100
                image = jpeg()
                joined = []
                for room_id in order:
                    viewer.add_room(room_id, {"alias": "主播" + room_id})
                    if not viewer.running:
                        viewer.toggle_running()
                        viewer.render_timer.stop()
                        viewer.match_timer.stop()
                    for stamp in range(90, 101):
                        viewer.rows[room_id].decoder.history.append(stamp, image)
                    # Chat permutations use already-highest feeds; quality reloads
                    # are covered separately and would replace this synthetic history.
                    viewer.rows[room_id].quality = 10000
                    viewer.rows[room_id].decoder.seed.update(quality=10000, highest_quality=True)
                    joined.append(room_id)
                    check_sources(viewer, joined)
                viewer.render_timer.stop()
                viewer.match_timer.stop()
                app.processEvents()
                viewer.render()
                decoders = {key: row.decoder for key, row in viewer.rows.items()}
                for main in order:
                    viewer.select_main(main)
                    for flags in itertools.product((False, True), repeat=3):
                        for key, enabled in zip(order, flags):
                            viewer.rows[key].show_chat.setChecked(enabled)
                        viewer.panel.clear()
                        viewer.picture.video_danmaku.clear()
                        viewer.picture.danmaku_button.setChecked(True)
                        with patch.object(module.time, "monotonic", return_value=95):
                            for key in order:
                                row = viewer.rows[key]
                                if row.chat is not None:
                                    row.chat.events.message.emit({"uname": "观众", "text": "消息" + key})
                        viewer.render()
                        expected = {"【主播" + key + "】 观众" for key, flag in zip(order, flags) if flag}
                        assert {e["uname"] for e in viewer.panel._blocks} == expected, (order, main, flags)
                        texts = {c.text for c in viewer.picture.video_danmaku.comments}
                        assert texts == {"【主播" + key + "】 消息" + key
                                         for key, flag in zip(order, flags) if flag}, (order, main, flags, texts)
                        assert viewer.running and not viewer.canvas.image.isNull()
                        assert all(viewer.rows[key].decoder is decoder for key, decoder in decoders.items())
                        cases += 1
                for row in viewer.rows.values():
                    row.show_chat.setChecked(True)
                    row.pending.clear()
                    row.pending.extend((95, {"uname": "burst", "text": "burst"}) for _ in range(210))
                viewer.panel.clear()
                viewer.render()
                counts = {key: sum(e["uname"].startswith("【主播" + key + "】")
                                   for e in viewer.panel._blocks) for key in order}
                assert set(counts.values()) == {66}, counts
                viewer.picture.danmaku_button.setChecked(False)
                check_sources(viewer, order)
                assert not viewer.picture.video_danmaku.comments
                viewer.picture.danmaku_button.setChecked(True)
                check_sources(viewer, order)
                assert len(viewer.picture.video_danmaku.comments) == 3
                for key in order:
                    row = viewer.rows[key]
                    previous = row.chat
                    row.show_chat.setChecked(False)
                    assert previous.stopped and row.chat is None
                    check_sources(viewer, [item for item in order if item != key])
                    row.show_chat.setChecked(True)
                    assert row.chat is not previous
                    viewer.panel.clear()
                    for item in viewer.rows.values():
                        item.pending.clear()
                    previous.events.message.emit({"uname": "old", "text": "obsolete"})
                    with patch.object(module.time, "monotonic", return_value=95):
                        row.chat.events.message.emit({"uname": "new", "text": "reconnected"})
                    viewer.render()
                    assert [e["text"] for e in viewer.panel._blocks] == ["reconnected"]
                    viewer.remove_room(key)
                    check_sources(viewer, [item for item in order if item != key])
                    viewer.add_room(key, {"alias": "主播" + key})
                    for stamp in range(90, 101):
                        viewer.rows[key].decoder.history.append(stamp, image)
                    check_sources(viewer, order)
                    assert len(viewer.panel._blocks) == 3, (order, key)
            finally:
                viewer.close()
                assert not viewer.picture.video_danmaku.comments
                host.close()
                app.processEvents()
    print(f"PASS: {cases} three-room join/main/toggle combinations, fair bursts, reconnect and remove/rejoin")
    print("PASS: all enabled rooms reach both chat list and labelled video overlay without restarting video")


if __name__ == "__main__":
    main()
