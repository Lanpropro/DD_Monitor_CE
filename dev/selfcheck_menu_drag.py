"""Offline Qt menu drag feedback, cancellation and commit boundaries."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
from ddm import motion, theme
from ddm.tile_menu import MenuOrderList, TileMenuEditor

APP = QApplication.instance() or QApplication([])


class MenuDragTests(unittest.TestCase):
    def setUp(self):
        self.editor = TileMenuEditor()
        self.editor.setStyleSheet(theme.qss())
        self.editor.resize(850, 650)
        self.editor.show()
        APP.processEvents()
        self.changed = []
        self.editor.changed.connect(lambda: self.changed.append(self.editor.values()))

    def tearDown(self):
        self.editor.close()
        self.editor.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def start(self, surface):
        rows = dict(surface.rows())
        start = rows['reload'].center().toPoint()
        end = rows['quality'].topLeft().toPoint() + QPoint(25, 1)
        QTest.mousePress(surface, Qt.LeftButton, pos=start)
        QTest.mouseMove(surface, end)
        self.assertTrue(surface._dragging)
        self.assertIsNotNone(surface._ghost)
        self.assertTrue(surface._ghost.isVisible())
        self.assertTrue(surface._ghost.testAttribute(Qt.WA_TransparentForMouseEvents))
        return end

    def test_both_surfaces_show_ghost_and_neighbors_then_commit_only_on_release(self):
        for name in ('items', 'preview'):
            self.editor.set_choices(None)
            self.changed.clear()
            surface = getattr(self.editor, name)
            before = self.editor.values()
            with patch.object(motion, 'enabled', return_value=True):
                end = self.start(surface)
                self.assertEqual(self.editor.values(), before)
                self.assertEqual(self.changed, [])
                self.assertTrue(surface._animation_started)
                QTest.qWait(250)
                self.assertFalse(surface._animation_clock.isActive())
                self.assertTrue(any(surface._positions[key].y() != round(rect.y())
                                    for key, rect in surface.rows() if key != 'reload'))
                QTest.mouseRelease(surface, Qt.LeftButton, pos=end)
            self.assertEqual(len(self.changed), 1)
            ids = [entry['id'] for entry in self.editor.values()]
            self.assertLess(ids.index('reload'), ids.index('quality'))
            self.assertIsNone(surface._ghost)
            self.assertFalse(surface._animation_clock.isActive())
            self.assertEqual(surface._animations, {})

    def test_esc_hide_and_lost_capture_cancel_without_saving(self):
        for name in ('items', 'preview'):
            surface = getattr(self.editor, name)
            for cancel in ('escape', 'hide', 'ungrab'):
                before = self.editor.values()
                self.changed.clear()
                self.start(surface)
                if cancel == 'escape':
                    QTest.keyClick(surface, Qt.Key_Escape)
                elif cancel == 'hide':
                    surface.hide()
                else:
                    APP.sendEvent(surface, QEvent(QEvent.UngrabMouse))
                self.assertEqual(self.editor.values(), before)
                self.assertEqual(self.changed, [])
                self.assertIsNone(surface._pressed)
                self.assertIsNone(surface._ghost)
                self.assertFalse(surface._animation_clock.isActive())
                self.assertIsNot(QWidget.mouseGrabber(), surface)
                QTest.mouseRelease(surface, Qt.LeftButton, pos=QPoint(20, 20))
                self.assertEqual(self.changed, [])
                surface.show()
                APP.processEvents()

    def test_same_target_preserves_shared_animation_and_gui_clock_finishes_it(self):
        surface = self.editor.items
        with patch.object(motion, 'enabled', return_value=True):
            end = self.start(surface)
            target = next(iter(surface._animations))
            animation = surface._animations[target]
            animation.setCurrentTime(70)
            started = surface._animation_started[animation]
            for _ in range(6):
                QTest.mouseMove(surface, end)
                self.assertIs(surface._animations[target], animation)
                self.assertEqual(surface._animation_started[animation], started)
            QTest.qWait(250)
            self.assertEqual(target.pos(), animation.endValue())
            self.assertFalse(surface._animation_clock.isActive())
            QTest.keyClick(surface, Qt.Key_Escape)

    def test_animation_disabled_moves_neighbors_immediately_and_return_to_origin_is_noop(self):
        for name in ('items', 'preview'):
            surface = getattr(self.editor, name)
            before = self.editor.values()
            self.changed.clear()
            with patch.object(motion, 'enabled', return_value=False):
                self.start(surface)
                self.assertFalse(surface._animation_clock.isActive())
                self.assertEqual(surface._animations, {})
                self.assertTrue(any(surface._positions[key].y() != round(rect.y())
                                    for key, rect in surface.rows() if key != 'reload'))
                original = dict(surface.rows())['reload'].center().toPoint()
                QTest.mouseMove(surface, original)
                QTest.mouseRelease(surface, Qt.LeftButton, pos=original)
            self.assertEqual(self.editor.values(), before)
            self.assertEqual(self.changed, [])

    def test_switch_click_never_starts_drag_and_custom_menu_labels_are_supported(self):
        surface = self.editor.items
        check = surface.checks['reload']
        before = check.isChecked()
        QTest.mouseClick(check, Qt.LeftButton)
        self.assertEqual(check.isChecked(), not before)
        self.assertFalse(surface._dragging)
        self.assertIsNone(surface._ghost)
        self.assertEqual(len(self.changed), 1)
        rows = MenuOrderList(items=(('show', '显示主窗口'), ('quit', '退出程序')))
        try:
            choices = [{'id': 'show', 'enabled': True}, {'id': 'quit', 'enabled': False}]
            rows.set_choices(choices)
            rows.show()
            APP.processEvents()
            self.assertIs(rows.choices, choices)
            self.assertEqual(set(rows.checks), {'show', 'quit'})
            self.assertEqual([key for key, _rect in rows.rows()], ['show', 'quit'])
            self.assertFalse(rows.grab().isNull())
        finally:
            rows.close()
            rows.deleteLater()

    def test_drag_outside_then_release_or_escape_cancels_without_changing_order(self):
        for name in ('items', 'preview'):
            surface = getattr(self.editor, name)
            for cancel in ('release', 'escape'):
                before = self.editor.values()
                self.changed.clear()
                self.start(surface)
                outside = QPoint(surface.width() + 40, -20)
                QTest.mouseMove(surface, outside)
                self.assertTrue(surface._dragging)
                self.assertEqual(self.editor.values(), before)
                if cancel == 'escape':
                    QTest.keyClick(surface, Qt.Key_Escape)
                QTest.mouseRelease(surface, Qt.LeftButton, pos=outside)
                self.assertEqual(self.editor.values(), before)
                self.assertEqual(self.changed, [])
                self.assertIsNone(surface._ghost)
                self.assertFalse(surface._animation_clock.isActive())
                self.assertIsNot(QWidget.mouseGrabber(), surface)


if __name__ == '__main__':
    if len(sys.argv) == 1:
        from checks.widget_cases import run_widget_cases
        raise SystemExit(run_widget_cases(MenuDragTests, __file__))
    else:
        unittest.main()
