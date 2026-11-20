"""Isolated checks for the host-managed tile caption overlay."""
import unittest

from PySide6.QtCore import QPoint
from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QApplication, QWidget

from ddm import theme
from ddm.plugins import PluginContext, PluginManager
from ddm.video_caption import CaptionStyle, VideoCaption
from ddm.tile_widgets import Tile

APP = QApplication.instance() or QApplication([])


class CaptionHostChecks(unittest.TestCase):
    def setUp(self):
        self.owner = QWidget()
        self.owner.resize(800, 486)
        self.video = QWidget(self.owner)
        self.video.setGeometry(0, 0, 800, 450)
        self.bottom = QWidget(self.owner)
        self.bottom.setGeometry(0, 450, 800, 36)
        self.bottom.tile_y = lambda: 450
        self.owner.video = self.video
        self.owner.bottom = self.bottom
        self.owner.setProperty("fullscreen", False)
        self.owner.setProperty("pictureInPicture", False)
        self.owner.show()
        APP.processEvents()

    def tearDown(self):
        self.owner.close()
        self.owner.deleteLater()
        APP.processEvents()

    def test_style_bounds_and_text_modes(self):
        style = CaptionStyle.from_value({
            "mode": "invalid", "lines": 99, "opacity": -1,
            "width": 2, "height": 90, "font_size": 999,
        })
        self.assertEqual(
            (style.mode, style.lines, style.opacity, style.width,
             style.height, style.font_size),
            ("both", 4, 0, 20, 45, 64),
        )
        caption = VideoCaption(self.owner)
        caption.set_caption("原文", "译文", style={"mode": "translation"})
        self.assertEqual(caption._texts(), [("translation", "译文")])
        caption.clear_caption()
        self.assertFalse(caption.isVisible())

    def test_background_tracks_text_width(self):
        caption = VideoCaption(self.owner)
        caption.set_caption(
            "短", "", style={"mode": "original", "opacity": 100,
                            "width": 100, "height": 45, "font_size": 24})
        image = QImage(caption.width(), caption.height(),
                       QImage.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        caption._render_badge(painter)
        painter.end()
        middle = image.height() // 2
        self.assertEqual(image.pixelColor(1, middle).alpha(), 0)
        self.assertEqual(image.pixelColor(image.width() - 2, middle).alpha(), 0)
        self.assertGreater(image.pixelColor(image.width() // 2, middle).alpha(), 0)

    def test_pip_and_playback_bar_safe_area(self):
        caption = VideoCaption(self.owner)
        caption.set_caption(
            "原文", "译文",
            style={"width": 100, "height": 45, "font_size": 24})
        APP.processEvents()
        self.assertTrue(caption.isVisible())
        self.assertEqual(caption._font(300, 1).family(), theme.danmaku_font_family())
        self.assertEqual(caption._font(300, 1).pixelSize(), 24)
        self.owner.setProperty("fullscreen", True)
        self.bottom.tile_y = lambda: 300
        caption.sync_geometry()
        bottom = self.owner.mapFromGlobal(caption.mapToGlobal(QPoint(0, caption.height() - 1))).y()
        self.assertLessEqual(bottom, 300 - VideoCaption.GAP)
        self.owner.setProperty("fullscreen", False)
        self.owner.setProperty("pictureInPicture", True)
        caption.sync_geometry()
        self.assertFalse(caption.isVisible())

    def test_plugin_context_caption_contract(self):
        class Target:
            def __init__(self):
                self.value = None

            def set_translation_caption(self, original, translated="", *, style=None, visible=True):
                self.value = (original, translated, style, visible)

            def clear_translation_caption(self):
                self.value = None

        manager = PluginManager()
        context = PluginContext(manager, "caption_test")
        target = Target()
        self.assertTrue(context.set_tile_caption(
            target, "原文", "译文", style={"lines": 2}, visible=False))
        self.assertEqual(
            target.value,
            ("原文", "译文", {"lines": 2}, False),
        )
        self.assertTrue(context.clear_tile_caption(target))
        self.assertIsNone(target.value)
        self.assertFalse(context.set_tile_caption(object(), "原文"))

    def test_unload_clears_owned_caption_and_rejects_stale_writes(self):
        class Target:
            value = None

            def set_translation_caption(self, original, translated="", **kwargs):
                self.value = (original, translated)

            def clear_translation_caption(self):
                self.value = None

        manager = PluginManager()
        first = PluginContext(manager, 'first')
        second = PluginContext(manager, 'second')
        target = Target()
        first.set_tile_caption(target, 'first caption')
        second.set_tile_caption(target, 'second caption')
        first._active = False
        self.assertFalse(first.clear_tile_caption(target))
        self.assertEqual(target.value, ('second caption', ''))
        manager.unload()
        self.assertIsNone(target.value)
        with self.assertRaises(RuntimeError):
            second.set_tile_caption(target, 'late caption')

    def test_room_change_and_tile_close_clear_captions(self):
        tile = Tile({'room_id': 'fixture', 'uname': 'test', 'live': True})
        try:
            tile.resize(800, 486)
            tile.show()
            APP.processEvents()
            tile.set_translation_caption('original', 'translation')
            self.assertTrue(tile.video_caption.isVisible())
            tile.set_room(None)
            self.assertFalse(tile.video_caption.isVisible())
            tile.set_translation_caption('new caption')
            tile.close()
            self.assertFalse(tile.video_caption.isVisible())
        finally:
            tile.deleteLater()
            APP.processEvents()

    def test_danmaku_switch_never_recreates_a_cleared_translation(self):
        tile = Tile({'room_id': 'fixture', 'uname': 'test', 'live': True})
        try:
            tile.resize(800, 486)
            tile.show()
            APP.processEvents()
            tile.set_translation_caption('our original', '我们的译文')
            tile.video_danmaku.set_enabled(False)
            self.assertTrue(tile.video_caption.isVisible())
            tile.clear_translation_caption()
            for enabled in (True, False, True):
                tile.video_danmaku.set_enabled(enabled)
                tile.raise_overlays()
                tile.video_caption.sync_geometry()
                APP.processEvents()
                self.assertFalse(tile.video_caption.isVisible())
                self.assertEqual(tile.video_caption._texts(), [])
        finally:
            tile.close()
            tile.deleteLater()
            APP.processEvents()


if __name__ == "__main__":
    unittest.main()
