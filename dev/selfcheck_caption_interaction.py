"""Functional caption interaction checks; native video/input ordering is manual."""
import unittest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtGui import QColor, QFontMetricsF
from PySide6.QtWidgets import QApplication, QWidget
from ddm.caption_geometry import caption_rect
from ddm.caption_preview import CaptionPlacementPreview
from ddm.plugins import PluginContext, PluginManager
from ddm.video_caption import VideoCaption

APP = QApplication.instance() or QApplication([])


class CaptionInteractionChecks(unittest.TestCase):
    def setUp(self):
        self.owner = QWidget()
        self.owner.resize(800, 480)
        self.owner.video = QWidget(self.owner)
        self.owner.video.setGeometry(0, 0, 800, 450)
        self.owner.show()
        self.caption = self.owner.video_caption = VideoCaption(self.owner)
        self.caption.set_caption('こんにちは', '你好', style={'locked': False})
        APP.processEvents()

    def tearDown(self):
        self.owner.close()
        self.owner.deleteLater()
        APP.processEvents()

    def test_move_resize_lock_and_normalized_window_resize(self):
        caption = self.caption
        changed = []
        caption.styleChanged.connect(changed.append)
        before = caption.geometry()
        point = QPoint(50, 20)
        QTest.mousePress(caption, Qt.LeftButton, pos=point)
        QTest.mouseMove(caption, point + QPoint(-35, -70))
        QTest.mouseRelease(caption, Qt.LeftButton, pos=point)
        self.assertNotEqual(before.topLeft(), caption.geometry().topLeft())
        self.assertEqual(len(changed), 1)
        self.assertLess(changed[-1]['y'], 100)
        before = caption.size()
        point = caption.rect().bottomRight() - QPoint(4, 4)
        QTest.mousePress(caption, Qt.LeftButton, pos=point)
        QTest.mouseMove(caption, point + QPoint(-100, 40))
        QTest.mouseRelease(caption, Qt.LeftButton, pos=point)
        self.assertNotEqual(before, caption.size())
        self.assertTrue(caption._safe_rect().contains(caption.geometry()))
        style = caption._style.as_dict()
        caption.set_caption('原文', '译文', style=dict(style, locked=True))
        self.assertTrue(caption.testAttribute(Qt.WA_TransparentForMouseEvents))
        before = caption.geometry()
        QTest.mousePress(caption, Qt.LeftButton, pos=QPoint(20, 20))
        QTest.mouseMove(caption, QPoint(100, 100))
        QTest.mouseRelease(caption, Qt.LeftButton, pos=QPoint(100, 100))
        self.assertEqual(before, caption.geometry())
        self.owner.video.resize(400, 225)
        caption.sync_geometry()
        self.assertEqual(caption.geometry(), caption_rect(caption._safe_rect(), caption._style))

    def test_quick_actions_and_reset(self):
        menu = self.caption._interaction.menu()
        next(action for action in menu.actions() if action.text() == '增大字号').trigger()
        self.assertEqual(self.caption._style.font_size, 26)
        next(action for action in menu.actions() if action.text() == '锁定位置').trigger()
        self.assertTrue(self.caption._style.locked)
        menu.deleteLater()

    def test_icon_toolbar_stays_above_caption_and_actions_update_style(self):
        caption = self.caption
        toolbar = caption._interaction.toolbar
        before = caption.geometry()
        toolbar.reveal()
        APP.processEvents()
        self.assertTrue(toolbar.isVisible())
        self.assertEqual(caption.geometry(), before)
        self.assertLessEqual(toolbar.geometry().bottom(), caption.geometry().top())
        self.assertLessEqual(abs(toolbar.geometry().center().x() - before.center().x()), 1)
        self.assertTrue(all(button.toolTip() and button.accessibleName() and button.text() == ''
                            for button in toolbar.buttons.values()))
        toolbar.buttons['larger'].click()
        self.assertEqual(caption._style.font_size, 26)
        toolbar.buttons['reset'].click()
        self.assertEqual((caption._style.x, caption._style.y), (50, 100))
        toolbar.buttons['lock'].click()
        self.assertTrue(caption._style.locked)
        self.assertFalse(toolbar.isVisible())
        self.assertTrue(caption.testAttribute(Qt.WA_TransparentForMouseEvents))

    def test_toolbar_tracks_caption_center_and_uses_its_background_opacity(self):
        caption = self.caption
        toolbar = caption._interaction.toolbar
        toolbar.reveal()
        for opacity in (35, 75):
            caption.set_caption('こんにちは', '你好', style={'x': 30, 'y': 70, 'width': 50, 'opacity': opacity})
            APP.processEvents()
            self.assertLessEqual(abs(toolbar.geometry().center().x() - caption.geometry().center().x()), 1)
            color = toolbar.grab().toImage().pixelColor(toolbar.width() // 2, 2)
            self.assertEqual(color, QColor(0, 0, 0, round(255 * opacity / 100)))

    def test_toolbar_hides_with_caption_and_preview_remains_embedded(self):
        toolbar = self.caption._interaction.toolbar
        toolbar.reveal()
        self.caption.clear_caption()
        APP.processEvents()
        self.assertFalse(toolbar.isVisible())
        preview = CaptionPlacementPreview()
        self.assertFalse(preview.caption._interaction.toolbar.isWindow())
        preview.close()
        preview.deleteLater()

    def test_preview_and_parameters_use_the_actual_renderer_without_native_window(self):
        preview = CaptionPlacementPreview()
        preview.resize(420, 240)
        preview.show()
        preview.set_style({'x': 5, 'y': 20, 'width': 50, 'height': 30, 'locked': True})
        APP.processEvents()
        self.assertFalse(preview.caption.isWindow())
        self.assertFalse(preview.caption.qt_composited)
        self.assertEqual(preview.caption._style.x, 5)
        changes = []
        preview.styleChanged.connect(changes.append)
        preview.caption._interaction.apply(x=75, width=60)
        self.assertEqual(changes[-1]['x'], 75)
        self.assertTrue(changes[-1]['locked'])
        preview.close()
        preview.deleteLater()

    def test_caption_callback_is_owned_and_disconnected_on_takeover_and_clear(self):
        manager = PluginManager()
        context = PluginContext(manager, 'first')
        other = PluginContext(manager, 'second')
        self.owner.set_translation_caption = lambda original, translated='', **kwargs: self.caption.set_caption(original, translated, **kwargs)
        self.owner.clear_translation_caption = self.caption.clear_caption
        first, second = [], []
        context.set_tile_caption(self.owner, '原文', '译文', on_style_changed=lambda tile, value: first.append(value))
        self.caption._interaction.apply(x=15)
        self.assertEqual(first[-1]['x'], 15)
        other.set_tile_caption(self.owner, 'other', on_style_changed=lambda tile, value: second.append(value))
        self.caption._interaction.apply(x=25)
        self.assertEqual(len(first), 1)
        self.assertEqual(second[-1]['x'], 25)
        other.clear_tile_caption(self.owner)
        self.caption.styleChanged.emit({'x': 50})
        self.assertEqual(len(second), 1)

    def test_small_preview_keeps_both_lines_inside_the_caption_box(self):
        preview = CaptionPlacementPreview()
        preview.resize(400, 170)
        preview.show()
        APP.processEvents()
        caption = preview.caption
        font = caption._font(caption.height(), 2)
        height = QFontMetricsF(font).height() * 2 + 4 + caption._padding() * 2
        self.assertLessEqual(height, caption.height() + 1)
        preview.close()
        preview.deleteLater()


if __name__ == '__main__':
    unittest.main()
