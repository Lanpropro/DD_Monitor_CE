"""Native fullscreen Enter focus regression; isolated input, no account or sending."""
from contextlib import ExitStack
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['DDM_NO_SAVE'] = '1'
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit
from ddm.app import MainWindow
from ddm.plugins import PluginManager, TileControl


class Editor(QLineEdit):
    def event(self, event):
        if event.type() == QEvent.ShortcutOverride:
            event.accept()
            return True
        return super().event(event)


@unittest.skipUnless(sys.platform == 'win32', 'Windows tool-window focus')
class FullscreenEnterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)

    def setUp(self):
        if self.app.platformName() != 'windows':
            self.skipTest('Requires native Windows backend')
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(PluginManager, 'load'))
        for name in ('start_all', 'start_tile', 'refresh_status', 'refresh_stats',
                     'refresh_account', 'sync_danmaku', 'load_avatars_for',
                     'load_room_avatars', 'load_cached_covers', 'load_cached_avatars',
                     '_check_startup_update', '_check_startup_plugins'):
            self.stack.enter_context(patch.object(MainWindow, name))
        room = dict(room_id='9000', uname='Offline input fixture')
        self.window = MainWindow([room], [dict(room)], layout_id='2x2',
            state={'plugins_enabled': [], 'settings': {'auto_update': False,
                'preview_on_hover': False, 'recording_enabled': False,
                'recording_replay_enabled': False, 'close_behavior': 'exit'}})
        self.addCleanup(self.close)
        self.window.setGeometry(60, 60, 1100, 700)
        self.window.show()
        self.calls = []
        calls = self.calls
        class Input(TileControl):
            def __init__(self, context):
                super().__init__(Editor(context.parent), minimum_width=90, preferred_width=400)
                self.widget.returnPressed.connect(lambda: calls.append('return'))
            def focus_input(self):
                self.widget.setFocus(Qt.ShortcutFocusReason)
                return True
            def interaction_active(self):
                return self.widget.hasFocus()
        self.window.plugins.register_tile_control('fixture', 'input', Input)
        self.tile = self.window.wall.tiles[0]
        self.edit = self.tile._plugin_controls.entries[0].control.widget
        self.edit.setText('unsent fixture draft')
        self.window._on_fullscreen(self.tile)
        self.window._fullscreen_cursor.stop()
        self.stack.enter_context(patch('ddm.app.QCursor.pos',
            return_value=self.tile.mapToGlobal(self.tile.rect().center())))
        QTest.qWait(100)

    def close(self):
        self.window._tray.exit_requested = True
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()

    def video_focus(self, *, hidden):
        self.edit.clearFocus()
        self.tile.set_fullscreen_controls_hidden(hidden)
        QTest.qWait(350)
        self.tile.activateWindow()
        self.tile.setFocus(Qt.OtherFocusReason)
        QTest.qWait(80)
        self.assertFalse(self.edit.hasFocus())

    def focus_with_key(self, key=Qt.Key_Return, modifiers=Qt.NoModifier):
        QTest.keyClick(self.tile, key, modifiers)
        QTest.qWait(350)
        self.assertTrue(self.edit.hasFocus(), 'Enter did not focus fullscreen tool-window editor')
        self.assertIs(QApplication.focusWidget(), self.edit)
        self.assertTrue(self.tile.bottom.isActiveWindow())
        self.assertTrue(self.tile.bottom.isVisible())
        self.assertEqual(self.calls, [], 'Focus shortcut submitted an existing draft')
        self.assertEqual(self.edit.text(), 'unsent fixture draft')

    def test_hidden_bar_first_return_focuses_without_submitting(self):
        self.video_focus(hidden=True)
        self.focus_with_key()
        QTest.keyClick(self.edit, Qt.Key_Return)
        self.assertEqual(self.calls, ['return'])

    def test_visible_bar_activates_before_focus(self):
        self.video_focus(hidden=False)
        self.focus_with_key()

    def test_keypad_enter_focuses_hidden_editor(self):
        self.video_focus(hidden=True)
        self.focus_with_key(Qt.Key_Enter)

    def test_remapped_shortcut_focuses_hidden_editor(self):
        self.window.shortcuts['danmaku_input'] = 'Ctrl+Return'
        self.window._refresh_shortcuts()
        self.video_focus(hidden=True)
        self.focus_with_key(Qt.Key_Return, Qt.ControlModifier)

    def test_fullscreen_input_does_not_depend_on_pointer_monitor(self):
        self.video_focus(hidden=True)
        with patch('ddm.app.QCursor.pos', return_value=QPoint(-20000, -20000)):
            self.focus_with_key()

    def test_editing_keeps_bar_visible_until_video_click_then_idle_hides(self):
        self.video_focus(hidden=True)
        self.focus_with_key()
        cursor = self.window._fullscreen_cursor
        cursor.timer.stop()
        cursor._last_move -= cursor.IDLE_SECONDS + 1
        cursor.update_cursor()
        self.assertTrue(self.edit.hasFocus())
        self.assertFalse(cursor.hidden)
        self.assertTrue(self.tile.bottom.isVisible(), 'Input mode hid while editing')

        QTest.mouseClick(self.tile.video, Qt.LeftButton, pos=self.tile.video.rect().center())
        QTest.qWait(80)
        self.assertFalse(self.edit.hasFocus(), 'Video click left editor focus active')
        self.assertFalse(self.tile.plugin_interaction_active())
        cursor.update_cursor()
        cursor._last_move -= cursor.IDLE_SECONDS + 1
        cursor.update_cursor()
        QTest.qWait(250)
        self.assertTrue(cursor.hidden)
        self.assertTrue(self.tile.bottom.isHidden(), 'Idle did not slide the bar away after leaving input')
        self.assertEqual(self.edit.text(), 'unsent fixture draft')
        self.assertEqual(self.calls, [])

        # A second cycle must still enter input mode after the bar has hidden.
        self.focus_with_key()
        self.assertFalse(cursor.hidden)

    def test_bar_finishes_when_shared_animation_clock_does_not_advance(self):
        self.window._fullscreen_cursor.stop()
        with patch('ddm.motion.enabled', return_value=True):
            for cycle in range(3):
                self.tile.set_fullscreen_controls_hidden(True)
                # Fault injection for the captured Running/time=0 stall.
                # This regression is not a replacement for the real idle trace.
                self.tile._bar_animation.pause()
                QTest.qWait(300)
                self.assertTrue(self.tile.bottom.isHidden(), f'Hide stalled in cycle {cycle}')
                self.tile.set_fullscreen_controls_hidden(False)
                self.tile._bar_animation.pause()
                QTest.qWait(300)
                self.assertTrue(self.tile.bottom.isVisible())
                self.assertEqual(self.tile._bar_progress, 0.0)
                if cycle < 2:
                    self.window._exit_fullscreen()
                    self.assertFalse(self.tile._bar_clock.isActive())
                    self.window._on_fullscreen(self.tile)
                    self.window._fullscreen_cursor.stop()


if __name__ == '__main__':
    unittest.main()
