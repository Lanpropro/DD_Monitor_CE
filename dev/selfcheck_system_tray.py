"""Offline tray lifecycle and close-choice checks with isolated configuration."""
from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QTimer, Qt, Signal
from PySide6.QtWidgets import QApplication, QDialog, QSystemTrayIcon
from ddm import config, system_tray
from ddm.app import MainWindow
from ddm.dialogs import GeneralSettingsPage


class FakeTray(QObject):
    activated = Signal(object)
    messageClicked = Signal()
    ActivationReason = QSystemTrayIcon.ActivationReason
    MessageIcon = QSystemTrayIcon.MessageIcon
    supported = True

    def __init__(self, icon, parent):
        super().__init__(parent)
        self.visible = False
        self.messages = []

    @classmethod
    def isSystemTrayAvailable(cls):
        return cls.supported

    def setToolTip(self, text):
        pass

    def setContextMenu(self, menu):
        self.menu = menu

    def show(self):
        self.visible = True

    def hide(self):
        self.visible = False

    def isVisible(self):
        return self.visible

    def showMessage(self, *message):
        self.messages.append(message)


class SystemTrayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        root = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix='ddm-tray-')))
        self.stack.enter_context(patch.object(config, 'CONFIG_PATH', str(root / 'config.json')))
        self.stack.enter_context(patch.dict(os.environ, {'DDM_NO_SAVE': ''}))
        self.stack.enter_context(patch.object(system_tray, 'QSystemTrayIcon', FakeTray))
        self.stack.enter_context(patch('ddm.app.QTimer.singleShot'))
        FakeTray.supported = True
        self.windows = []

    def tearDown(self):
        for window in self.windows:
            if not window._closing:
                window._tray.request_exit()
            window.deleteLater()
        self.app.processEvents()

    def window(self, behavior='ask', state=None):
        state = state or {'plugins_enabled': [], 'settings': {'close_behavior': behavior}}
        window = MainWindow([], [], layout_id='1x1', state=state)
        self.windows.append(window)
        window.show()
        self.app.processEvents()
        return window

    def choice(self, action, remember=False, accepted=True):
        dialog = Mock()
        dialog.exec.return_value = QDialog.Accepted if accepted else QDialog.Rejected
        dialog.choice = action
        dialog.remember.isChecked.return_value = remember
        return patch.object(system_tray, 'CloseWindowDialog', return_value=dialog)

    def test_dialog_buttons_and_default_settings(self):
        self.assertEqual(config.DEFAULT_SETTINGS['close_behavior'], 'ask')
        for action in ('tray', 'exit'):
            dialog = system_tray.CloseWindowDialog()
            self.assertFalse(dialog.remember.isChecked())
            getattr(dialog, 'hide_button' if action == 'tray' else 'exit_button').click()
            self.assertEqual(dialog.choice, action)
            self.assertEqual(dialog.result(), QDialog.Accepted)
            dialog.deleteLater()
        page = GeneralSettingsPage({})
        self.assertEqual(page.values()['close_behavior'], 'ask')
        for action in ('tray', 'exit'):
            page.close_behavior_combo.setCurrentIndex(page.close_behavior_combo.findData(action))
            self.assertEqual(page.values()['close_behavior'], action)
        page.reset()
        self.assertEqual(page.values()['close_behavior'], 'ask')
        page.deleteLater()

    def test_unremembered_choice_hides_without_teardown_and_asks_again(self):
        window = self.window()
        player = Mock()
        window.players[object()] = player
        with (patch.object(window.recorder, 'shutdown', wraps=window.recorder.shutdown) as shutdown,
              patch.object(window.plugins, 'unload', wraps=window.plugins.unload) as unload,
              self.choice('tray') as prompt):
            for _ in range(2):
                window.close()
                self.assertFalse(window.isVisible())
                self.assertFalse(window._closing)
                player.release.assert_not_called()
                shutdown.assert_not_called()
                unload.assert_not_called()
                window._tray.restore()
                self.assertTrue(window.isVisible())
            self.assertEqual(prompt.call_count, 2)
            self.assertEqual(len(window._tray.icon.messages), 1)
        self.assertEqual(config.load()['settings']['close_behavior'], 'ask')
        window._tray.exit_action.trigger()
        self.assertTrue(window._closing)
        player.release.assert_called_once()
        self.assertFalse(window._tray.icon.isVisible())

    def test_remember_tray_choice_and_hint_survive_reopen(self):
        window = self.window()
        with self.choice('tray', remember=True):
            window.close()
        saved = config.load()
        self.assertEqual(saved['settings']['close_behavior'], 'tray')
        self.assertTrue(saved['ui']['tray_hint_shown'])
        window._tray.request_exit()
        reopened = self.window(state=config.load())
        with self.choice('exit') as prompt:
            reopened.close()
            prompt.assert_not_called()
        self.assertFalse(reopened._closing)
        self.assertEqual(reopened._tray.icon.messages, [])

    def test_exit_choice_is_remembered_and_exits_without_prompt_next_time(self):
        window = self.window()
        with self.choice('exit', remember=True):
            window.close()
        self.assertTrue(window._closing)
        self.assertEqual(config.load()['settings']['close_behavior'], 'exit')
        reopened = self.window(state=config.load())
        with self.choice('tray') as prompt:
            reopened.close()
            prompt.assert_not_called()
        self.assertTrue(reopened._closing)

    def test_cancel_keeps_window_and_choice_unchanged(self):
        window = self.window()
        with self.choice('', accepted=False):
            window.close()
        self.assertTrue(window.isVisible())
        self.assertFalse(window._closing)
        self.assertEqual(window.settings['close_behavior'], 'ask')

    def test_double_click_menu_and_restore_preserve_window_state(self):
        window = self.window('tray')
        tray = window._tray
        window.showMaximized()
        tray.icon.activated.emit(FakeTray.ActivationReason.Trigger)
        self.assertTrue(window.isVisible(), 'Single-click before double-click must not toggle twice')
        tray.icon.activated.emit(FakeTray.ActivationReason.DoubleClick)
        self.assertFalse(window.isVisible())
        tray.update_menu()
        self.assertEqual(tray.toggle_action.text(), '显示窗口')
        tray.toggle_action.trigger()
        self.assertTrue(window.isMaximized())
        tray.update_menu()
        self.assertEqual(tray.toggle_action.text(), '隐藏窗口')
        window.showMinimized()
        tray.icon.messageClicked.emit()
        self.assertFalse(window.isMinimized())
        self.assertTrue(window.isMaximized())
        self.assertTrue(window.isVisible())

    def test_no_tray_or_update_and_restart_can_still_exit(self):
        FakeTray.supported = False
        window = self.window('tray')
        window.close()
        self.assertTrue(window._closing)
        FakeTray.supported = True
        for attribute, value in (('_restart_requested', True), ('_update_plan', 'test-plan')):
            window = self.window('tray')
            setattr(window, attribute, value)
            with self.choice('tray') as prompt:
                window.close()
                prompt.assert_not_called()
            self.assertTrue(window._closing)

    def test_hidden_window_keeps_event_loop_alive_until_explicit_exit(self):
        window = self.window('tray')
        previous = self.app.quitOnLastWindowClosed()
        self.app.setQuitOnLastWindowClosed(False)
        steps, errors = [], []
        timer, timeout = QTimer(), QTimer()
        timeout.setSingleShot(True)
        timeout.timeout.connect(self.app.quit)

        def advance():
            try:
                if not steps:
                    window.close()
                    self.assertFalse(window.isVisible())
                    self.assertFalse(window._closing)
                    steps.append('hidden')
                else:
                    window._tray.restore()
                    window._tray.exit_action.trigger()
                    self.assertTrue(window._closing)
                    steps.append('exited')
                    timer.stop()
            except Exception as error:
                errors.append(error)
                self.app.quit()

        timer.timeout.connect(advance)
        try:
            timer.start(10)
            timeout.start(2000)
            self.app.exec()
        finally:
            timer.stop()
            timeout.stop()
            self.app.setQuitOnLastWindowClosed(previous)
        self.assertEqual(errors, [])
        self.assertEqual(steps, ['hidden', 'exited'])


def native_contract():
    """Exercise the actual tray outside the desktop without restoring or taking focus."""
    app = QApplication.instance() or QApplication([])
    if not QSystemTrayIcon.isSystemTrayAvailable():
        raise RuntimeError('Native system tray is unavailable')
    with tempfile.TemporaryDirectory(prefix='ddm-tray-native-') as temporary:
        with (patch.object(config, 'CONFIG_PATH', str(Path(temporary) / 'config.json')),
              patch('ddm.app.QTimer.singleShot')):
            window = MainWindow([], [], layout_id='1x1', state={
                'plugins_enabled': [], 'settings': {'close_behavior': 'tray'},
                'ui': {'tray_hint_shown': True}})
            window.setAttribute(Qt.WA_ShowWithoutActivating)
            window.setGeometry(-10000, -10000, 900, 600)
            try:
                window.show()
                app.processEvents()
                assert window._tray.available(), 'Real Windows tray icon was not installed'
                window.close()
                assert not window.isVisible() and not window._closing
                assert window._tray.icon.isVisible(), 'Hiding removed the restore entry point'
                window._tray.exit_action.trigger()
                assert window._closing and not window._tray.icon.isVisible()
            finally:
                if not window._closing:
                    window._tray.request_exit()
                window.deleteLater()
                app.processEvents()
                QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    print('Real Windows tray registration, hide and exit passed; no foreground input')


if __name__ == '__main__':
    if '--native-contract' in sys.argv:
        native_contract()
    else:
        unittest.main()
