"""Visible resampling and cache-limited offset edits must not freeze the main."""
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DDM_NO_SAVE"] = "1"
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_SCALE_FACTOR"] = "2" if "--high-dpi" in sys.argv else "1"

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QWidget
from ddm import plugins
from dev.selfcheck_match_sync import FakeChat, FakeDecoder, jpeg
from plugins_user._match_sync import viewer as module


def main():
    app = QApplication([])
    canvas = module.Canvas()
    canvas.resize(640, 360)
    canvas.show()
    app.processEvents()
    ratio = canvas.devicePixelRatioF()
    width, height = round(1280 * ratio), round(720 * ratio)
    pixels = (b"\x00\x00\x00\xff\xff\xff\xff\xff" * (width // 2)) * height
    source = QImage(pixels, width, height, width * 4, QImage.Format_RGB32).copy()
    canvas.set_frame((100, source))
    app.processEvents()
    shown = canvas.grab().toImage()
    values = [shown.pixelColor(x, shown.height() // 2).red() for x in range(10, shown.width() - 10)]
    assert min(values) >= 120 and max(values) <= 136, (min(values), max(values), ratio)
    assert canvas.image == source, "Display resampling must preserve the retained native image"
    canvas.close()
    print(f"PASS: native fine-line image downsamples without aliasing at device scale {ratio:g}")

    now = [120.0]
    with tempfile.TemporaryDirectory() as root, \
            patch.object(module, "Decoder", FakeDecoder), patch.object(module, "Chat", FakeChat), \
            patch.object(module.AudioPump, "start", lambda _self: None), \
            patch.object(module.time, "monotonic", side_effect=lambda: now[0]):
        host = QWidget()
        host.settings = {}
        manager = plugins.PluginManager(window=host, plugins_dir=root)
        context = plugins.PluginContext(manager, "offset_continuity")
        with patch.object(context, "setting", side_effect=lambda key, default=None:
                          {"automatic": False, "rooms": [{"room_id": "1", "delay": 1.5}]}.get(key, default)):
            saved = module.Viewer(context, {}, {"room_id": "1"})
            assert saved.rows["1"].delay.value() == 1.5, "Manual preferences were cleared during construction"
            saved.close()
        viewer = module.Viewer(context, {})
        try:
            viewer.add_room("1", {"alias": "Main"})
            viewer.add_room("2", {"alias": "Other"})
            viewer.automatic.setChecked(False)
            viewer.toggle_running()
            viewer.render_timer.stop()
            viewer.match_timer.stop()
            viewer.audio.clock = lambda: now[0] + viewer.audio.correction
            image = jpeg()
            for row in viewer.rows.values():
                row.decoder.last_frame_received = now[0]
                for stamp in (118, 119, 120):
                    row.decoder.history.append(stamp, image)
            viewer.render()
            before = viewer.canvas.frame_key
            viewer.rows["2"].delay.setValue(-5)
            assert viewer.canvas.frame_key == before
            assert not viewer.rows["1"].paused and not viewer.sync_waiting
            assert viewer.offset_repositioning
            now[0] = 121
            for row in viewer.rows.values():
                row.decoder.history.append(121, image)
                row.decoder.last_frame_received = now[0]
            viewer.render()
            assert viewer.canvas.frame_key > before and not viewer.sync_waiting
            assert viewer.comparison_panel.cards["2"][2].waiting
            now[0] = 126
            for row in viewer.rows.values():
                for stamp in range(122, 127):
                    row.decoder.history.append(stamp, image)
                row.decoder.last_frame_received = now[0]
            viewer.render()
            assert not viewer.offset_repositioning and not viewer.sync_waiting
            assert all(row.decoder.history.frame_at(viewer.audio.clock() + viewer.shifts()[key])
                       for key, row in viewer.rows.items())
            viewer.automatic.setChecked(True)
            assert not viewer.compare.isChecked() and not viewer.alignment.manual_locked
            assert all(row.delay.value() == 0 for row in viewer.rows.values())
            assert viewer.shifts() == {"1": -2, "2": -2}
        finally:
            viewer.close()
            host.close()
            app.processEvents()
    print("PASS: cache-limited secondary edit keeps main advancing, common cache resumes, automatic clears manual trim/comparison")


if __name__ == "__main__":
    main()
