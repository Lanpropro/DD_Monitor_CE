"""Native Windows overlay erasure while the match-sync Canvas is repainting."""
import os
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
os.environ["DDM_NO_SAVE"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "windows" if sys.platform == "win32" else "offscreen")

from PySide6.QtCore import QBuffer, QIODevice, QPoint, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import QApplication, QWidget
from ddm import plugins, theme
from dev.selfcheck_match_sync import FakeChat, FakeDecoder
from plugins_user._match_sync import viewer as module


def settle(app):
    until = time.monotonic() + .15
    while time.monotonic() < until:
        app.processEvents()
        time.sleep(.01)


def capture(viewer):
    video = viewer.picture.video
    point = video.mapToGlobal(QPoint())
    return video.screen().grabWindow(0, point.x(), point.y(), video.width(), video.height()).toImage()


def main():
    app = QApplication([])
    if app.platformName() != "windows":
        print("SKIP: native Windows overlay check")
        return
    app.setStyleSheet(theme.qss())
    with tempfile.TemporaryDirectory() as root, \
            patch.object(module, "Chat", FakeChat), patch.object(module, "Decoder", FakeDecoder), \
            patch.object(module.AudioPump, "start", lambda _self: None):
        host = QWidget()
        host.settings = {"video_danmaku_scale": False, "video_danmaku_size": 28,
                         "video_danmaku_area": 100, "video_danmaku_opacity": 100}
        manager = plugins.PluginManager(window=host, plugins_dir=root)
        viewer = module.Viewer(plugins.PluginContext(manager, "native_check"), {})
        viewer.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        viewer.setGeometry(40, 60, 1500, 900)
        viewer.show()
        viewer.raise_()
        viewer.activateWindow()
        try:
            viewer.add_room("1", {"alias": "主画面"})
            viewer.add_room("2", {"alias": "对照画面"})
            viewer.toggle_running()
            viewer.render_timer.stop()
            viewer.match_timer.stop()
            viewer.audio.clock = lambda: 100
            image = QImage(640, 360, QImage.Format_RGB32)
            image.fill(QColor("blue"))
            buffer = QBuffer()
            buffer.open(QIODevice.WriteOnly)
            assert image.save(buffer, "JPEG")
            for row in viewer.rows.values():
                for stamp in range(80, 101):
                    row.decoder.history.append(stamp, bytes(buffer.data()))
            viewer.render()
            viewer.picture.danmaku_button.setChecked(True)
            settle(app)
            background = capture(viewer)
            (REPO / "work").mkdir(exist_ok=True)
            background.save(str(REPO / "work/match-sync-native-background.png"))
            viewer.grab().save(str(REPO / "work/match-sync-native-widget.png"))
            center = background.pixelColor(background.width() // 2, background.height() // 2)
            assert center.blue() > 180 and center.green() < 60, "Enabling comments must keep the Qt Canvas visible"
            overlay = viewer.video_danmaku
            assert overlay.add_event({"text": "移动后必须清除原位置", "color": "#ffffff"})
            comment = overlay.comments[0]
            comment.x, comment.lane = 30, 3
            overlay.update()
            settle(app)
            initial = capture(viewer)
            scale = initial.devicePixelRatio()
            top = round(comment.lane * overlay.lane_height() * scale)
            def green(image):
                return max(image.pixelColor(x, y).green()
                           for y in range(top, min(image.height(), top + round(overlay.lane_height() * scale)))
                           for x in range(round(30 * scale), round(280 * scale)))
            assert green(initial) > 200, "Native comments must be above the Canvas"
            comment.x = 650
            for _ in range(30):
                viewer.render()
            overlay.update()
            settle(app)
            moved = capture(viewer)
            (REPO / "work").mkdir(exist_ok=True)
            initial.save(str(REPO / "work/match-sync-native-before.png"))
            moved.save(str(REPO / "work/match-sync-native-moved.png"))
            assert green(moved) < 100, "Canvas repaint must not leave old native-layer glyphs"
            center = moved.pixelColor(moved.width() // 2, moved.height() // 2)
            assert center.blue() > 180 and center.green() < 60
            comment.x = -comment.image.width() / comment.image.devicePixelRatioF() - 1
            overlay._tick()
            settle(app)
            assert not overlay.comments and not overlay.timer.isActive()
            assert green(capture(viewer)) < 100
            viewer.show_comparison("2")
            settle(app)
            viewer.comparison_panel.close_button.click()
            settle(app)
            assert viewer.canvas.isVisible() and not viewer.picture._buffering
            print("PASS: native match-sync Canvas, moving/expired glyph erasure, repeated renders and collapse preserve video")
        finally:
            viewer.close()
            host.close()
            app.processEvents()


if __name__ == "__main__":
    main()
