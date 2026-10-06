"""Manual five-second advance, clock crops and previews; no live rooms or sound."""
import os
from pathlib import Path
import sys
from array import array
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
os.environ.setdefault("DDM_NO_SAVE", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QIODevice, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QImage, QPainter
from PySide6.QtWidgets import QApplication, QDialog, QWidget
from ddm import plugins
from dev.selfcheck_match_sync import FakeChat, FakeDecoder, FakeDevice, FakeSink
from plugins_user._match_sync.engine import Alignment, Match, RATE, Sample, match_scenes
from plugins_user._match_sync.media import fingerprint
from plugins_user._match_sync import viewer as module


def clock_jpeg(seconds, scale=1):
    image = QImage(120 * scale, 50 * scale, QImage.Format_RGB32)
    image.fill(QColor("#151515"))
    painter = QPainter(image)
    painter.setPen(QColor("white"))
    font = QFont("Consolas")
    font.setPixelSize(34 * scale)
    painter.setFont(font)
    painter.drawText(image.rect(), Qt.AlignCenter, f"{seconds // 60}:{seconds % 60:02}")
    painter.end()
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    assert image.save(buffer, "JPEG")
    return bytes(buffer.data())


def offset_checks():
    alignment = Alignment()
    alignment.select_reference("main")
    alignment.automatic = False
    shifts = alignment.shifts({"main": 0, "late": -4.5})
    assert shifts == {"main": -6.5, "late": -2}, shifts
    assert shifts["late"] - shifts["main"] == 4.5
    alignment.automatic = True
    alignment.lags["late"] = 5
    shifts = alignment.shifts({"main": 0, "late": -1})
    assert shifts == {"main": -8, "late": -2}, shifts
    before = alignment.shifts({"main": 7, "late": 7})
    alignment.select_reference("late")
    assert alignment.shifts({"main": 7, "late": 7}) == before, "Main selection must preserve delayed playback positions"
    alignment.automatic = False
    assert alignment.shifts({"main": 2, "late": 0}) == {"main": -4, "late": -2}
    print("PASS: negative manual offsets advance relatively without reading future media")


def clock_checks():
    font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "consola.ttf"
    assert QFontDatabase.addApplicationFont(str(font)) >= 0, "Clock fixture font unavailable"
    reference, other = [], []
    for i in range(56):
        seconds = 112 - i // 2
        reference.append(Sample(100 + i * .5, *fingerprint(clock_jpeg(seconds))))
        other.append(Sample(104.5 + i * .5, *fingerprint(clock_jpeg(seconds, 2))))
    match = match_scenes(reference, other)
    assert match.lag is not None and abs(match.lag - 4.5) < .51, match
    still = [Sample(100 + i * .5, *fingerprint(clock_jpeg(90))) for i in range(56)]
    assert match_scenes(still, still).lag is None, "A paused clock must not establish a lag"
    print("PASS: timer crops at different resolutions match 4.5s, paused clocks remain unconfirmed")


def preview_checks(app):
    host = QWidget()
    host.settings, host.players = {}, {}
    manager = plugins.PluginManager(window=host)
    context = plugins.PluginContext(manager, "match_sync_offset_test")
    with patch.object(module, "Decoder", FakeDecoder), patch.object(module, "Chat", FakeChat), \
            patch.object(module.AudioPump, "start", lambda self: None):
        viewer = module.Viewer(context, {})
        viewer.add_room("1", {"alias": "Machine", "volume": 100})
        viewer.add_room("2", {"alias": "CS-advent", "volume": 100})
        viewer.automatic.setChecked(False)
        viewer.toggle_running()
        viewer.render_timer.stop()
        viewer.match_timer.stop()
        viewer.audio.clock = lambda: 100
        main, late = viewer.rows.values()
        for i in range(44):
            for row, content in ((main, i), (late, i - 9)):
                image = clock_jpeg(112 - content // 2)
                row.decoder.history.append(80 + i * .5, image)
                row.decoder.history.audio.append(array("h", [1000 + content * 200] * RATE).tobytes())
        with patch.object(module.QDialog, "exec", side_effect=AssertionError("An unseen cache frame must not open selection")):
            viewer.choose_crop(main)
        assert viewer.canvas.frame is None
        viewer.show()
        app.processEvents()
        assert viewer.comparison_panel.isHidden() and not viewer.compare.isChecked()
        viewer.render()
        assert viewer.canvas.frame_key == 98
        late.delay.setValue(-4.5)
        app.processEvents()
        assert viewer.compare.isChecked() and viewer.comparison_panel.isVisible()
        cards = viewer.comparison_panel.cards
        assert set(cards) == {"1", "2"}
        assert cards["1"][2].frame_key == viewer.canvas.frame_key == 93.5
        assert cards["2"][2].frame_key == 98
        assert cards["1"][2].image == cards["2"][2].image, "Five-second-late content must now match"
        assert "4.5" in cards["2"][3].text()
        assert all(not card[2].waiting for card in cards.values())
        viewer.audio.sink = FakeSink()
        viewer.audio.device = FakeDevice(viewer.audio.sink)
        viewer.audio.anchor = 100
        viewer.audio.fill()
        assert set(array("h", viewer.audio.device.data)) == {6400}, "Mixed PCM must immediately use the adjusted shared timeline"
        late.pending.append((97, {"uname": "A", "text": "adjusted chat"}))
        viewer.render()
        assert viewer.panel._blocks[-1]["text"] == "adjusted chat"
        late.delay.setValue(0)
        viewer.render()
        assert cards["1"][2].image != cards["2"][2].image
        assert cards["1"][2].frame_key == cards["2"][2].frame_key == 98
        late.delay.setValue(5)
        assert cards["2"][2].frame_key == 93
        viewer.automatic.setChecked(True)
        assert not viewer.compare.isChecked() and all(row.delay.value() == 0 for row in viewer.rows.values())
        viewer._matched(viewer.generation, {"2": Match(4.5, 1, "ok")})
        assert "2" not in viewer.alignment.lags, "A single automatic result still needs confirmation"
        viewer.alignment.lags["2"] = 4.5
        viewer.show_comparison("2")
        def crop_dialog(dialog):
            selector = dialog.findChild(module.Canvas)
            assert selector.frame_key == cards["2"][2].frame_key
            assert selector.image == cards["2"][2].image, "Crop selection must freeze the visible comparison frame"
            selector.crop = QRectF(.2, .1, .3, .2)
            return QDialog.Accepted
        with patch.object(module.QDialog, "exec", crop_dialog), \
                patch.object(late.decoder.history, "latest", side_effect=AssertionError("Latest cache is not the displayed picture")):
            viewer.choose_crop(late)
        assert viewer.alignment.lags["2"] == 4.5, "Changing crop must preserve confirmed alignment"
        assert late.decoder.crop == late.crop == (.2, .1, .3, .2)
        viewer.render()
        assert cards["2"][2].zoom_crop and cards["2"][2].crop == QRectF(*late.crop)
        viewer.comparison_panel.zoom.setChecked(False)
        viewer.render()
        assert not cards["2"][2].zoom_crop
        displayed = viewer.canvas.frame
        main.paused = True
        viewer.audio.clock = lambda: 105
        viewer.render()
        def main_dialog(dialog):
            selector = dialog.findChild(module.Canvas)
            assert selector.frame == displayed, "Paused or retained video must use the exact displayed frame"
            assert selector.image == viewer.canvas.image
            return QDialog.Rejected
        with patch.object(module.QDialog, "exec", main_dialog), \
                patch.object(main.decoder.history, "latest", side_effect=AssertionError("Do not substitute newer live content")):
            viewer.choose_crop(main)
            main.paused = False
            viewer.audio.clock = lambda: 100
            main.delay.setValue(60)
            viewer.render()
            assert viewer.canvas.waiting and viewer.canvas.frame == displayed
            viewer.choose_crop(main)
        main.delay.setValue(0)
        viewer.compare.setChecked(False)
        expected = late.decoder.history.frame_at(100 + viewer.shifts()["2"])
        assert expected != late.decoder.history.latest()
        def hidden_dialog(dialog):
            assert dialog.findChild(module.Canvas).frame == expected, "Hidden rooms must use the shared playback position"
            return QDialog.Rejected
        with patch.object(module.QDialog, "exec", hidden_dialog):
            viewer.choose_crop(late)
        viewer.compare.setChecked(True)
        viewer.render()
        print("PASS: crop dialog freezes displayed main/comparison frames, retains pause/buffering snapshots, hidden rooms use playback time")
        decoder = main.decoder
        sizes = viewer.body_split.sizes()
        viewer.compare.setChecked(False)
        app.processEvents()
        assert viewer.comparison_panel.isHidden() and viewer.body_split.sizes()[0] > sizes[0]
        assert main.decoder is decoder and viewer.running
        main.increase.click()
        assert viewer.compare.isChecked()
        viewer.minimize_settings.click()
        assert viewer.comparison_panel.isHidden() and not viewer.compare.isChecked()
        viewer.restore_settings.click()
        viewer.compare.setChecked(True)
        viewer.remove_room("2")
        viewer.render()
        assert set(viewer.comparison_panel.cards) == {"1"}
        viewer.remove_room("1")
        assert viewer.canvas.frame is None, "Removing every room must release the retained snapshot"
        assert all(card[2].image.isNull() for card in viewer.comparison_panel.cards.values())
        viewer.close()
        host.close()
        app.processEvents()
    print("PASS: actual playback previews, 4.5s PCM/chat adjustment, crop zoom, frozen auto targets and cleanup")


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    offset_checks()
    clock_checks()
    preview_checks(app)
    print("PASS: offset regression checks")


if __name__ == "__main__":
    main()
