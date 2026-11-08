"""Settings categories, real Qt pointer dwell, interruption and lifetime regression."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import tempfile
from copy import deepcopy

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['DDM_NO_SAVE'] = '1'
from PySide6.QtCore import QAbstractAnimation, QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtGui import QColor, QCursor, QImage, QKeyEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu, QWidget
from ddm import config, theme
from ddm.dialogs import SettingsDialog
from ddm.settings_navigation import SettingsNavigation

APP = QApplication.instance() or QApplication([])


class SettingsNavigationTests(unittest.TestCase):
    def setUp(self):
        self.dialog = SettingsDialog(dict(config.DEFAULT_SETTINGS), {}, preview=True)
        self.dialog.resize(1000, 750)
        self.dialog.show()
        self.dialog.activateWindow()
        APP.processEvents()
        self.navigation = self.dialog.navigation
        self.pointer = self.dialog.pointer_navigation
        self.pointer.timer.stop()
        self.clock = 100.0
        self.position = self.dialog.content.mapToGlobal(QPoint(250, 160))
        self.patches = [patch('ddm.settings_navigation.monotonic', side_effect=lambda: self.clock),
                        patch.object(QCursor, 'pos', side_effect=lambda: QPoint(self.position)),
                        patch.object(self.dialog, 'isActiveWindow', return_value=True),
                        patch('ddm.settings_navigation.motion.enabled', return_value=False)]
        for item in self.patches:
            item.start()
        self.addCleanup(self.dispose)

    def dispose(self):
        for item in reversed(self.patches):
            item.stop()
        self.dialog.close()
        self.dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def dwell(self, seconds):
        self.clock += seconds
        self.pointer.sample()

    def test_grouped_search_keeps_page_indices_and_laziness(self):
        nav = self.dialog.nav
        self.assertEqual(nav.count(), 9)
        self.assertFalse(self.dialog._loaded_pages)
        self.assertEqual([nav.item(i).data(Qt.UserRole) for i in range(nav.count())],
                         [key for key, _label in self.dialog.PAGES])
        self.navigation.search.setText('lu zhi')
        self.assertFalse(nav.isRowHidden(3))
        self.assertEqual(self.navigation.heading(3), '观看与互动')
        self.assertTrue(nav.isRowHidden(2))
        nav.setCurrentRow(3)
        self.assertEqual(self.dialog.stack.currentIndex(), 3)
        self.assertEqual(list(self.dialog._loaded_pages), [3])
        self.navigation.search.setText('no-such-setting')
        self.assertTrue(self.navigation.empty_hint.isVisible())
        self.navigation.search.clear()
        self.navigation.set_collapsed(True, animate=False)
        self.assertFalse(self.navigation.search.isVisible())
        self.assertTrue(all(not nav.isRowHidden(i) for i in range(nav.count())))
        self.assertEqual(self.navigation.width(), SettingsNavigation.COMPACT_WIDTH)
        self.assertEqual(nav.item(3).toolTip(), '录制')
        nav.item(8).setData(Qt.UserRole+1, True)
        self.assertTrue(nav.item(8).data(Qt.UserRole+1))
        self.assertFalse(self.navigation.grab().isNull())
        nav.setCurrentRow(2)
        self.assertEqual(self.dialog.stack.currentWidget(), self.dialog.danmaku_page)

    def test_continuous_two_seconds_and_return_expansion(self):
        self.pointer.sample()
        self.dwell(1.0)
        self.position += QPoint(10, 10)
        self.dwell(.99)
        self.assertFalse(self.navigation.collapsed)
        self.dwell(.02)
        self.assertTrue(self.navigation.collapsed)
        selected = self.dialog.nav.currentRow()
        self.position = self.navigation.mapToGlobal(QPoint(18, 150))
        self.dwell(.01)
        self.assertFalse(self.navigation.collapsed)
        self.assertEqual(self.dialog.nav.currentRow(), selected)

    def test_leaving_region_resets_deadline_and_inactive_popups_suspend(self):
        self.pointer.sample()
        self.dwell(1.8)
        self.position = self.dialog.mapToGlobal(QPoint(-50, -20))
        self.dwell(.1)
        self.position = self.dialog.content.mapToGlobal(QPoint(200, 180))
        self.dwell(.1)
        self.dwell(1.9)
        self.assertFalse(self.navigation.collapsed)
        popup = QMenu()
        self.addCleanup(popup.deleteLater)
        with patch.object(QApplication, 'activePopupWidget', return_value=popup):
            self.dwell(1)
        self.dwell(.1)
        with patch.object(self.dialog, 'isActiveWindow', return_value=False):
            self.dwell(3)
        self.dwell(.1)
        self.dwell(1.9)
        self.assertFalse(self.navigation.collapsed)
        self.dwell(.2)
        self.assertTrue(self.navigation.collapsed)

    def test_dragging_and_keyboard_do_not_collapse_or_trap_focus(self):
        self.pointer.sample()
        with patch.object(QApplication, 'mouseButtons', return_value=Qt.LeftButton):
            self.dwell(3)
        self.assertFalse(self.navigation.collapsed)
        self.navigation.set_collapsed(True, animate=False)
        self.pointer.eventFilter(self.dialog.nav, QKeyEvent(QEvent.KeyPress, Qt.Key_Down, Qt.NoModifier))
        self.assertFalse(self.navigation.collapsed)
        self.dwell(3)
        self.assertFalse(self.navigation.collapsed)
        self.position += QPoint(15, 10)
        self.dwell(.1)
        self.dwell(2.1)
        self.assertTrue(self.navigation.collapsed)

    def test_interrupted_transition_and_reduced_motion(self):
        with patch('ddm.settings_navigation.motion.enabled', return_value=True):
            self.navigation.set_collapsed(True)
            self.navigation.animation.setCurrentTime(70)
            width = self.navigation.width()
            self.navigation.set_collapsed(False)
            self.assertEqual(self.navigation.animation.startValue(), width)
            self.navigation.animation.setCurrentTime(200)
            self.assertEqual(self.navigation.width(), SettingsNavigation.EXPANDED_WIDTH)
        self.navigation.set_collapsed(True)
        self.assertEqual(self.navigation.animation.state(), QAbstractAnimation.Stopped)
        self.assertEqual(self.navigation.width(), SettingsNavigation.COMPACT_WIDTH)
        self.pointer.timer.start()
        self.dialog.hide()
        self.assertFalse(self.pointer.timer.isActive())
        self.assertEqual(self.navigation.width(), SettingsNavigation.EXPANDED_WIDTH)
        self.assertIsNone(self.pointer.since)

    def test_retired_python_owner_stops_application_filter_and_timer(self):
        self.pointer.timer.start()
        with patch.object(self.pointer, 'dialog', return_value=None):
            self.assertFalse(self.pointer.eventFilter(APP, QEvent(QEvent.User)))
            self.assertFalse(self.pointer.timer.isActive())
            self.pointer.sample()

    def test_transparent_navigation_keeps_the_settings_skin_visible(self):
        from ddm import skin_parts
        package, personal = deepcopy(skin_parts._package), deepcopy(skin_parts._personal)
        try:
            with tempfile.TemporaryDirectory() as directory:
                image = QImage(24, 24, QImage.Format_ARGB32)
                image.fill(QColor('#ff8800'))
                path = Path(directory)/'background.png'
                image.save(str(path))
                skin_parts.configure({}, {'settings': {'image': path.as_posix()},
                                          'settings.navigation': {'background': '#00000000'}})
                APP.processEvents()
                capture = self.dialog.grab().toImage()
                point = self.dialog.nav.mapTo(self.dialog, QPoint(5, 5))
                self.assertEqual(capture.pixelColor(point), QColor('#ff8800'))
        finally:
            skin_parts.configure(package, personal)

    def test_real_poll_timer_waits_two_seconds_and_closes_cleanly(self):
        # Keep real Qt timers and real monotonic time for this integration check;
        # the cursor/window are isolated test inputs, never the running client.
        self.patches[0].stop()
        self.patches.pop(0)
        self.pointer.last_position = None
        self.pointer.since = None
        self.pointer.timer.start()
        QTest.qWait(1850)
        self.assertFalse(self.navigation.collapsed)
        QTest.qWait(400)
        self.assertTrue(self.navigation.collapsed)
        self.dialog.close()
        self.assertFalse(self.pointer.timer.isActive())
        self.assertIsNone(self.pointer.since)
        from shiboken6 import isValid
        probe = SettingsDialog(dict(config.DEFAULT_SETTINGS), {}, preview=True)
        probe.show()
        APP.processEvents()
        timer = probe.pointer_navigation.timer
        self.assertTrue(timer.isActive())
        probe.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertFalse(isValid(timer))


if __name__ == '__main__':
    APP.setStyleSheet(theme.qss())
    unittest.main()
