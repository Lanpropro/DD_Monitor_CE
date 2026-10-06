"""Highest main stream, platform tier ordering and explicit quality overrides; offline."""
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DDM_NO_SAVE"] = "1"
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtWidgets import QApplication, QWidget
from ddm import plugins
from dev.selfcheck_match_sync import FakeChat, FakeDecoder
from plugins_user._match_sync import media, viewer as module


def main():
    app = QApplication([])
    metadata = []
    decoder = media.Decoder("1", {"quality": 80, "url": "cached-preview", "highest_quality": True})
    decoder.events.information.connect(metadata.append)
    with patch.object(media.bili, "room_quality_options", return_value=[
            {"qn": -1}, {"qn": 25000}, {"qn": 10000}]), \
            patch.object(media.bili, "room_info", return_value={"uname": "Highest main"}), \
            patch.object(media.bili, "play_url", return_value=("fresh", 250, "local", {})) as play:
        assert decoder._resolve(0) == ("fresh", {})
        assert play.call_args.args[1] == 25000, "Bilibili highest can exceed 10000"
        assert metadata[0]["requested_quality"] == 25000 and metadata[-1]["actual_quality"] == 250
        decoder.stop()
        with patch.object(media.bili, "room_quality_options", side_effect=AssertionError("Lookup after cancellation")):
            try:
                decoder._resolve(1)
            except media.bili.Cancelled:
                pass
            else:
                raise AssertionError("Cancelled highest request must stop")
    platform = plugins.Platform()
    platform.kind = "douyu"
    platform.room_quality_options = lambda rid: [{"qn": 10000}, {"qn": 2000004}]
    platform.room_info = lambda rid: plugins.RoomInfo(rid, uname="Douyu")
    with patch.object(platform, "play_url", return_value=("fresh", 10000, "local", {})) as play:
        media.Decoder("douyu:42", {"quality": 2000004, "highest_quality": True}, platform)._resolve(0)
        assert play.call_args.args[1] == 10000, "Highest tier follows platform order, not largest numeric ID"
    print("PASS: fresh highest request, Bilibili 2K tiers, Douyu tier order, actual fallback reporting and cancellation")

    with tempfile.TemporaryDirectory() as root, \
            patch.object(module, "Decoder", FakeDecoder), patch.object(module, "Chat", FakeChat), \
            patch.object(module.AudioPump, "start", lambda self: None):
        host = QWidget()
        host.settings = {}
        viewer = module.Viewer(plugins.PluginContext(plugins.PluginManager(window=host, plugins_dir=root), "main_quality"), {})
        try:
            viewer.add_room("1", {"quality": 80})
            viewer.add_room("2", {"quality": 250})
            viewer.toggle_running()
            assert viewer.rows["1"].quality == 10000 and viewer.rows["1"].decoder.seed["highest_quality"]
            assert viewer.rows["2"].quality == 250 and not viewer.rows["2"].decoder.seed["highest_quality"]
            original = viewer.rows["1"].decoder
            viewer.select_main("2")
            assert viewer.rows["2"].quality == 10000 and viewer.rows["1"].decoder is original
            options = [{"qn": 25000, "desc": "2K"}, {"qn": 10000, "desc": "原画"}]
            viewer._information(viewer.rows["2"], viewer.rows["2"].decoder,
                                {"requested_quality": 25000, "quality_options": options})
            assert viewer.picture.quality == 25000 and viewer.picture.quality_options == options
            viewer.picture.set_quality(250)
            assert viewer.rows["2"].quality == 250 and not viewer.rows["2"].decoder.seed["highest_quality"]
            viewer._information(viewer.rows["2"], viewer.rows["2"].decoder, {"title": "Updated title"})
            assert viewer.rows["2"].quality == 250, "Metadata refresh must preserve explicit user quality"
            viewer.select_main("1")
            assert viewer.rows["1"].decoder is original, "An existing highest-quality main must keep its decoder"
            viewer.select_main("2")
            assert viewer.rows["2"].quality == 10000 and viewer.rows["2"].decoder.seed["highest_quality"]
            print("PASS: initial/switch main defaults highest, other decoder stays intact, explicit lower quality is retained")
        finally:
            viewer.close()
            host.close()
            app.processEvents()


if __name__ == "__main__":
    main()
