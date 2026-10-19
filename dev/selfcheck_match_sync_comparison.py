"""Exercise the actual comparison panel with four native streams."""
import os
import faulthandler
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
os.environ.setdefault("DDM_NO_SAVE", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication, QWidget
from ddm import plugins, recording, theme
from ddm.dialogs import SettingsDialog
from dev.selfcheck_match_sync import FakeChat, FakeDecoder
from dev.selfcheck_match_sync_video import fixture
from plugins_user._match_sync import media, viewer as module


class CountingImage(QImage):
    copies = 0

    def copy(self, *args):
        self.copies += 1
        return super().copy(*args)


def crop_check(app):
    image = CountingImage(640, 360, QImage.Format_RGB32)
    image.fill(QColor("red"))
    painter = QPainter(image)
    painter.fillRect(320, 180, 320, 180, QColor("blue"))
    painter.end()
    canvas = module.Canvas()
    canvas.resize(320, 180)
    canvas.set_frame((1, image))
    canvas.zoom_crop = True
    canvas.crop = QRectF(.5, .5, .5, .5)
    canvas.show()
    app.processEvents()
    rendered = canvas.grab().toImage()
    assert rendered.pixelColor(rendered.width() // 2, rendered.height() // 2).blue() == 255
    assert canvas.image.pixelColor(100, 100).red() == 255
    assert image.copies == 0, "Crop painting must not allocate a copied full-resolution image"
    assert canvas.image is image
    canvas.close()


def main():
    app = QApplication([])
    # Match real startup: install the global theme before building video widgets.
    theme.apply("dark")
    crop_check(app)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as root, \
            patch.object(module, "Decoder", FakeDecoder), patch.object(module, "Chat", FakeChat), \
            patch.object(module.AudioPump, "start", lambda _self: None):
        source = Path(root) / "1440p60.mkv"
        fixture(recording.ffmpeg_path(), source, "2560x1440", "60", 10)
        host = QWidget()
        host.settings = {}
        context = plugins.PluginContext(plugins.PluginManager(window=host, plugins_dir=root), "comparison_perf")
        viewer = module.Viewer(context, {})
        viewer.alignment.buffer_seconds = 3  # The rendering benchmark starts at source PTS 3.
        decoders = []
        try:
            viewer.resize(1280, 900)
            viewer.show()
            for key in ("1", "2", "3", "4"):
                viewer.add_room(key, {"alias": key})
            viewer.toggle_running()
            viewer.render_timer.stop()
            viewer.match_timer.stop()
            for key, row in viewer.rows.items():
                row.decoder.stop()
                row.decoder = media.Decoder(key, {"url": str(source)})
                decoders.append(row.decoder)
                row.decoder.start()
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline and any(d.history.received_frames < 180 for d in decoders):
                app.processEvents()
                time.sleep(.005)
            assert all(d.history.received_frames >= 180 for d in decoders)
            start = time.monotonic()
            viewer.audio.clock = lambda: decoders[0].history.origin + 3 + time.monotonic() - start

            def warmup(canvases):
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline and any(c.frame is None for c in canvases):
                    viewer.render()
                    app.processEvents()
                    time.sleep(.005)
                assert all(c.frame is not None for c in canvases)

            def measure():
                viewer.canvas.presented = 0
                begin = time.monotonic()
                waits = ticks = 0
                while time.monotonic() - begin < 1.2:
                    viewer.render()
                    waits += viewer.canvas.waiting
                    ticks += 1
                    app.processEvents()
                    time.sleep(.004)
                assert waits / ticks <= .05, ("Repeated main buffering after warmup", waits, ticks)
                print(f"MEASURE: main buffer indications {waits}/{ticks} polls")
                return viewer.canvas.presented / (time.monotonic() - begin)

            warmup([viewer.canvas])
            closed = measure()
            viewer.show_comparison("2")
            app.processEvents()
            main_card = viewer.comparison_panel.cards["1"][2]
            warmup([card[2] for card in viewer.comparison_panel.cards.values()])
            assert main_card.image == viewer.canvas.image
            with patch.object(decoders[0], "picture_at", wraps=decoders[0].picture_at) as request:
                viewer.render()
                assert request.call_count == 1, "Main comparison must reuse the displayed frame"
                assert main_card.frame_key == viewer.canvas.frame_key
            label = viewer.comparison_panel.cards["1"][1]
            with patch.object(label, "setStyleSheet", wraps=label.setStyleSheet) as styles, \
                    patch.object(main_card, "update", wraps=main_card.update) as redraw:
                for _ in range(10):
                    viewer.comparison_panel.render(viewer.audio.clock(), viewer.shifts())
                assert styles.call_count == 0, "Stable labels must not repolish each tick"
                assert redraw.call_count == 0, "Unchanged main comparisons must not redraw"
            opened = measure()
            assert decoders[0].analysis_size == decoders[1].analysis_size == (640, 360)
            assert decoders[2].analysis_size == (640, 360)
            assert decoders[2].pictures.active and decoders[3].pictures.active
            assert viewer.comparison_panel.shown_rooms == ("1", "2", "3", "4")
            assert viewer.comparison_panel.target.isHidden()
            print(f"MEASURE: actual four-stream Viewer, closed {closed:.1f} fps; comparison + zoom open {opened:.1f} fps")
            assert opened >= 45 and opened >= closed * .8, (closed, opened)
            reactions = []
            presented = viewer.canvas.presented
            for mode in ('light', 'dark'):
                started = time.perf_counter()
                theme.apply(mode)
                reactions.append((time.perf_counter() - started) * 1000)
            started = time.perf_counter()
            dialog = SettingsDialog({}, {}, viewer, plugin_manager=context.manager)
            dialog.show()
            app.processEvents()
            reactions.append((time.perf_counter() - started) * 1000)
            started = time.perf_counter()
            dialog.confirm_button.click()
            dialog.settings()
            dialog.shortcuts()
            reactions.append((time.perf_counter() - started) * 1000)
            assert not dialog._loaded_pages
            dialog.close()
            end = time.monotonic() + .3
            while time.monotonic() < end:
                viewer.render()
                app.processEvents()
                time.sleep(.002)
            assert max(reactions) < 250, reactions
            assert viewer.canvas.presented > presented + 5 and not viewer.canvas.waiting
            print(f'MEASURE: active four-stream theme/settings reactions {reactions} ms; playback resumed from cached originals')
            viewer.comparison_panel.zoom.setChecked(False)
            viewer.render()
            assert not main_card.zoom_crop
            viewer.show_comparison("3")
            viewer.render()
            assert viewer.comparison_panel.shown_rooms == ("1", "2", "3", "4")
            assert decoders[1].pictures.active
            assert decoders[2].pictures.active and decoders[2].analysis_size == (640, 360)
            viewer.compare.setChecked(False)
            viewer.render()
            assert viewer.comparison_panel.isHidden()
            assert all(d.video_size == (2560, 1440) for d in decoders)
        finally:
            viewer.close()
            for decoder in decoders:
                decoder.thread.join(4)
                assert not decoder.thread.is_alive()
            host.close()
            app.processEvents()
    print("PASS: crop without copies, shared main frame, stable styles, comparison selection/close and native quality")


if __name__ == "__main__":
    faulthandler.dump_traceback_later(40, exit=True)
    try:
        main()
    finally:
        faulthandler.cancel_dump_traceback_later()
