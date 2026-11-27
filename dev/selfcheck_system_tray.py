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
from ddm.dialogs import GeneralSettingsPage, SettingsDialog, TraySettingsPage
from ddm.single_instance import restore_main_window


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
        self.current_icon = icon

    def setIcon(self, icon):
        self.current_icon = icon

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
        FakeTray.supported = True
        self.windows = []

    def tearDown(self):
        for window in self.windows:
            if not window._closing:
                window._tray.request_exit()
            window.deleteLater()
        self.app.processEvents()

    def test_window_icon_changes_update_the_tray(self):
        from ddm import app_icon

        self.addCleanup(self.app.setWindowIcon, self.app.windowIcon())
        self.app.setWindowIcon(app_icon.load_icon('d'))
        window = self.window()
        self.assertEqual(window._tray.icon.current_icon.cacheKey(), window.windowIcon().cacheKey())
        for style in ('b', 'f', 'd'):
            with self.subTest(style=style):
                window.settings['app_icon_style'] = style
                app_icon.apply_icon(style, window)
                expected = app_icon.load_icon(style).pixmap(24, 24).toImage()
                self.assertEqual(window.windowIcon().pixmap(24, 24).toImage(), expected)
                self.assertEqual(window._tray.icon.current_icon.cacheKey(), window.windowIcon().cacheKey())

    def window(self, behavior='ask', state=None, layout_id='1x1'):
        state = state or {'plugins_enabled': [], 'settings': {'close_behavior': behavior}}
        # Suppress startup work only; native PiP queues its reparent/start after
        # the shell is shown and must keep that real event-loop delivery.
        with patch('ddm.app.QTimer.singleShot'):
            window = MainWindow([], [], layout_id=layout_id, state=state)
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
        self.assertFalse(hasattr(page, 'close_behavior_combo'))
        self.assertNotIn('close_behavior', page.values())
        page.deleteLater()
        page = TraySettingsPage({})
        self.assertEqual(page.values()['close_behavior'], 'ask')
        for action in ('tray', 'exit'):
            page.close_behavior_combo.setCurrentIndex(page.close_behavior_combo.findData(action))
            self.assertEqual(page.values()['close_behavior'], action)
        page.reset()
        self.assertEqual(page.values()['close_behavior'], 'ask')
        page.deleteLater()

    def test_tray_settings_save_cancel_and_reset(self):
        self.assertTrue(config.DEFAULT_SETTINGS['tray_pause_playback'])
        page = TraySettingsPage({})
        self.assertTrue(page.values()['tray_pause_playback'])
        page.pause_playback.setChecked(False)
        self.assertFalse(page.values()['tray_pause_playback'])
        page.reset()
        self.assertTrue(page.values()['tray_pause_playback'])
        page.deleteLater()
        original = {'tray_pause_playback': False}
        dialog = SettingsDialog(original, {}, preview=True)
        index = dialog.PAGE_INDEX['tray']
        dialog.nav.setCurrentRow(index)
        self.assertEqual(dialog.nav.item(index).text(), '托盘行为')
        self.assertFalse(dialog.settings()['tray_pause_playback'])
        dialog._reset_current()
        self.assertTrue(dialog.settings()['tray_pause_playback'])
        self.assertEqual(dialog.settings()['close_behavior'], 'ask')
        dialog.reject()
        self.assertEqual(original, {'tray_pause_playback': False})
        dialog.deleteLater()

    def test_default_hide_releases_watching_and_restore_reconnects(self):
        window = self.window('tray')
        tile = window.wall.tiles[0]
        tile.set_room({'room_id': '123', 'uname': 'Fixture', 'live': True})
        player, resolver = Mock(), Mock()
        window.players[tile] = player
        window._resolvers[tile] = resolver
        with patch.object(window.recorder, 'stop') as stop_recording:
            window._tray.hide()
            player.release.assert_called_once()
            resolver.cancel.assert_called_once()
            self.assertTrue(tile.paused)
            self.assertNotIn(tile, window.players)
            self.assertNotIn(tile, window._resolvers)
            window._sync_tile_playback(start_visible=True)
            stop_recording.assert_not_called()
        # Poll/retry and late stream results must not reopen watching in tray.
        window.start_tile(tile)
        window._play_on(tile, 'http://127.0.0.1:9/unused')
        self.assertNotIn(tile, window.players)
        self.assertNotIn(tile, window._resolvers)
        window._tray.hide()  # Do not overwrite the original pause state.
        with patch.object(window, 'start_tile') as start:
            window._tray.restore()
            start.assert_called_once_with(tile)
            self.assertFalse(tile.paused)
            window._tray.restore()
            start.assert_called_once()

    def test_disabled_and_minimized_keep_playback(self):
        window = self.window('tray')
        tile = window.wall.tiles[0]
        tile.set_room({'room_id': '123', 'live': True})
        player = Mock()
        window.players[tile] = player
        window.showMinimized()
        self.app.processEvents()
        player.release.assert_not_called()
        self.assertFalse(window._tray.playback_suspended)
        window.settings['tray_pause_playback'] = False
        window._tray.hide()
        window._tray.restore()
        player.release.assert_not_called()
        self.assertFalse(tile.paused)

    def test_tray_preview_retains_pre_minimize_layout_and_restores_window(self):
        from PySide6.QtWidgets import QWidgetAction
        window = self.window('tray')
        tile = window.wall.tiles[0]
        tile.set_room({'room_id': '123', 'uname': 'Before minimize', 'live': False})
        tray = window._tray
        window.showMinimized()
        self.app.processEvents()
        before = tray._layout_snapshot
        self.assertTrue(before['panes'])
        self.assertIn('Before minimize', [pane['title'] for pane in before['panes']])
        tile.set_room({'room_id': '456', 'uname': 'Later change', 'live': False})
        tray.update_menu()
        self.assertEqual(tray._layout_snapshot, before)
        self.assertIsInstance(tray.menu.actions()[0], QWidgetAction)
        self.assertIs(tray.menu.actions()[0].defaultWidget(), tray.layout_preview)
        self.assertFalse(tray.menu_actions['streamer_monitor'].isVisible())
        self.assertEqual([action.text() for action in tray.menu.actions()
                          if action.isVisible() and action.text()], ['显示窗口', '画中画…', '退出'])
        with patch.object(window.picture_in_picture, 'manage') as manage:
            tray.pip_action.trigger()
            manage.assert_called_once_with()
            self.assertTrue(window.isMinimized())
        tray.layout_preview.click()
        self.assertTrue(window.isVisible())
        self.assertFalse(window.isMinimized())

    def test_tray_picture_in_picture_resumes_only_selected_and_reholds_on_close(self):
        window = self.window('tray', layout_id='2x2')
        first, manually_paused, other = window.wall.tiles[:3]
        for index, tile in enumerate((first, manually_paused, other)):
            tile.set_room({'room_id': str(123 + index), 'uname': 'Fixture', 'live': True})
        manually_paused.set_paused(True)
        tray = window._tray
        tray.hide()
        saved = dict(tray._saved_playback)
        pip = window.picture_in_picture
        with patch.object(window, 'start_tile') as start:
            self.assertTrue(pip.start([0, 1]))
            self.app.processEvents()
            self.assertFalse(first.paused)
            self.assertTrue(manually_paused.paused)
            self.assertTrue(other.paused)
            self.assertFalse(tray.hold_playback(first))
            self.assertTrue(tray.hold_playback(other))
            start.assert_called_once_with(first)
            first.set_paused(True)
            self.assertTrue(pip.start([0, 1]))
            self.assertTrue(first.paused, 'Rearranging PiP must retain a new manual pause')
            start.assert_called_once_with(first)
            first.set_paused(False)
            player = Mock()
            window.players[first] = player
            pip.restore(activate=False)
            # Qt retires the floating window before the later tray restore action.
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            self.app.processEvents()
            player.release.assert_called_once()
            self.assertTrue(first.paused)
            self.assertTrue(tray.playback_suspended)
            self.assertEqual(tray._saved_playback, saved)
            start.reset_mock()
            tray.restore()
            self.assertEqual({call.args[0] for call in start.call_args_list}, {first, other})
            self.assertTrue(manually_paused.paused)

    def test_manual_pause_and_changed_room_are_not_resumed(self):
        window = self.window('tray')
        tile = window.wall.tiles[0]
        tile.set_room({'room_id': '123', 'live': True})
        tile.set_paused(True)
        window._tray.hide()
        with patch.object(window, 'start_tile') as start:
            window._tray.restore()
            start.assert_not_called()
            self.assertTrue(tile.paused)
        window._tray.hide()
        tile.set_room({'room_id': '456', 'live': True})
        with patch.object(window, 'start_tile') as start:
            window._tray.restore()
            start.assert_not_called()

    def test_recording_and_pending_capture_are_preserved(self):
        window = self.window('tray')
        tile = window.wall.tiles[0]
        tile.set_room({'room_id': '123', 'live': True})
        player = Mock()
        window.players[tile] = player
        window._pending_capture[tile] = {'fixture': True}
        window._tray.hide()
        player.release.assert_not_called()
        self.assertFalse(window._tray.hold_playback(tile))
        with (patch.object(window.recorder, 'stop') as stop,
              patch.object(window, '_finish_pending_capture',
                           side_effect=lambda current: window._pending_capture.pop(current)) as finish):
            window._play_on(tile, 'http://127.0.0.1:9/unused')
            finish.assert_called_once_with(tile)
            player.release.assert_called_once()
            stop.assert_not_called()
            self.assertNotIn(tile, window.players)

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

    def test_duplicate_launch_restores_tray_and_minimized_windows(self):
        window = self.window('tray')
        window._tray.hide()
        self.assertFalse(window.isVisible())
        restore_main_window(window)
        self.assertTrue(window.isVisible())
        window.showMinimized()
        restore_main_window(window)
        self.assertFalse(window.isMinimized())
        window._tray.request_exit()
        restore_main_window(window)
        self.assertFalse(window.isVisible())

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


class TrayMenuChoicesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_choices_clean_restore_defaults_and_keep_explicit_all_off(self):
        from ddm.tray_menu import TRAY_MENU_ITEMS, tray_menu_choices
        defaults = [{'id': key, 'enabled': key != 'streamer_monitor'} for key, _label in TRAY_MENU_ITEMS]
        self.assertIsNone(config.DEFAULT_SETTINGS['tray_context_menu'])
        for value in (None, [], 'invalid'):
            self.assertEqual(tray_menu_choices(value), defaults)
        result = tray_menu_choices([
            {'id': 'pip', 'enabled': False}, {'id': 'unknown'}, None,
            {'id': 'pip', 'enabled': True}, {'id': 'exit'}, {'id': 'toggle', 'enabled': 0}])
        self.assertEqual(result, [dict(id='pip', enabled=False), dict(id='exit', enabled=True),
                                  dict(id='toggle', enabled=False), dict(id='layout_preview', enabled=True),
                                  dict(id='streamer_monitor', enabled=False)])
        self.assertFalse(tray_menu_choices([{'id': 'streamer_monitor'}])[0]['enabled'])
        disabled = [{'id': key, 'enabled': False} for key, _label in TRAY_MENU_ITEMS]
        self.assertEqual(tray_menu_choices(disabled), disabled)

    def tray(self):
        from types import SimpleNamespace
        from PySide6.QtWidgets import QWidget
        window = QWidget()
        window.settings = {}
        window._closing = False
        window.capture_control = SimpleNamespace(monitor_rows=Mock(return_value=()))
        window.picture_in_picture = SimpleNamespace(active=False, manage=Mock())
        window.wall = QWidget(window)
        window.wall.resize(400, 200)
        window.wall.tiles = []
        window.wall.pane_danmaku = SimpleNamespace(rendered=lambda: [])
        FakeTray.supported = True
        with patch.object(system_tray, 'QSystemTrayIcon', FakeTray):
            tray = system_tray.SystemTray(window)
        self.addCleanup(window.deleteLater)
        self.addCleanup(tray.shutdown)
        return window, tray

    def visible_ids(self, tray):
        return [key for action in tray.menu.actions() if action.isVisible()
                for key, candidate in tray.menu_actions.items() if action is candidate]

    def test_about_to_show_reorders_and_hides_persistent_actions(self):
        window, tray = self.tray()
        actions = dict(tray.menu_actions)
        separators = list(tray.menu_separators)
        initial_action_count = len(tray.menu.findChildren(type(tray.exit_action)))
        tray.menu.aboutToShow.emit()
        self.assertEqual(self.visible_ids(tray), ['layout_preview', 'toggle', 'pip', 'exit'])
        choices = [dict(id='exit', enabled=True), dict(id='pip', enabled=False),
                   dict(id='layout_preview', enabled=True), dict(id='toggle', enabled=True)]
        window.settings['tray_context_menu'] = choices
        for _ in range(5):
            tray.menu.aboutToShow.emit()
            self.assertEqual(self.visible_ids(tray), ['exit', 'layout_preview', 'toggle'])
            self.assertEqual(sum(action.isSeparator() for action in tray.menu.actions()), 2)
            self.assertEqual(tray.menu_actions, actions)
            self.assertEqual(tray.menu_separators, separators)
            self.assertIs(tray.preview_action.defaultWidget(), tray.layout_preview)
        choices[1]['enabled'] = True
        tray.menu.aboutToShow.emit()
        self.assertEqual(self.visible_ids(tray), ['exit', 'pip', 'layout_preview', 'toggle'])
        self.assertEqual(sum(action.isSeparator() for action in tray.menu.actions()), 3)
        self.assertEqual(len(tray.menu.findChildren(type(tray.exit_action))), initial_action_count)
        window.settings['tray_context_menu'] = [dict(id=key, enabled=True) for key in
            ('layout_preview', 'toggle', 'streamer_monitor', 'pip', 'exit')]
        tray.menu.aboutToShow.emit()
        self.assertEqual(self.visible_ids(tray), ['layout_preview', 'toggle', 'streamer_monitor', 'pip', 'exit'])
        self.assertEqual(sum(action.isSeparator() for action in tray.menu.actions()), 4)

    def test_all_off_defaults_and_callbacks_keep_restore_accessible(self):
        from ddm.tray_menu import TRAY_MENU_ITEMS
        window, tray = self.tray()
        window.settings['tray_context_menu'] = [dict(id=key, enabled=False) for key, _ in TRAY_MENU_ITEMS]
        tray.menu.aboutToShow.emit()
        self.assertEqual(self.visible_ids(tray), [])
        self.assertFalse(any(action.isSeparator() for action in tray.menu.actions()))
        with patch.object(tray, 'toggle') as toggle:
            tray.icon.activated.emit(QSystemTrayIcon.ActivationReason.DoubleClick)
            toggle.assert_called_once()
        window.settings['tray_context_menu'] = []
        tray.menu.aboutToShow.emit()
        self.assertEqual(len(self.visible_ids(tray)), 4)
        with patch.object(tray, 'restore') as restore:
            tray.toggle_action.trigger()
            restore.assert_called_once()
        tray.pip_action.trigger()
        window.picture_in_picture.manage.assert_called_once()
        with patch.object(window, 'close') as close:
            tray.exit_action.trigger()
            self.assertTrue(tray.exit_requested)
            close.assert_called_once()

    def test_choices_roundtrip_uses_only_temporary_configuration(self):
        from ddm.tray_menu import tray_menu_choices
        choices = tray_menu_choices([dict(id='exit', enabled=False), dict(id='streamer_monitor', enabled=True),
                                     dict(id='pip', enabled=True)])
        with tempfile.TemporaryDirectory(prefix='ddm-tray-menu-') as temporary:
            with (patch.object(config, 'CONFIG_PATH', str(Path(temporary) / 'config.json')),
                  patch.dict(os.environ, {'DDM_NO_SAVE': ''})):
                config.save({'version': 1, 'settings': {'tray_context_menu': choices}}, raise_errors=True)
                self.assertEqual(config.load()['settings']['tray_context_menu'], choices)

    def test_streamer_monitor_opens_inline_with_read_only_groups(self):
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QColor, QHelpEvent, QPixmap
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QLabel, QToolTip, QWidget
        from ddm.capture_control import MonitorEntry
        from ddm.streamer_defaults import streamer_profile_group

        window, tray = self.tray()
        provider = window.capture_control.monitor_rows
        window.open_settings = Mock()
        page = TraySettingsPage(window.settings)
        self.addCleanup(page.deleteLater)
        enabled = page.tray_menu.checks['streamer_monitor']
        self.assertFalse(enabled.isChecked())
        enabled.click()
        window.settings.update(page.values())
        self.assertIn('streamer_monitor', [key for key, _ in page.tray_menu.preview.rows()])

        provider.assert_not_called()
        group = streamer_profile_group({'auto_record': True, 'recording': 720})
        another_group = streamer_profile_group({'auto_record': True, 'recording': 1080})
        provider.return_value = (MonitorEntry('1001', '录制示例', 'recording', 'bilibili', '9090', started_at=100),
                                 MonitorEntry('1002', '同组录制甲', 'recording', account_id='9091', started_at=95,
                                              profile_group=group),
                                 MonitorEntry('1003', '同组录制乙', 'recording', started_at=150, profile_group=group),
                                 MonitorEntry('failed', '启动失败示例', 'failed', profile_group=group),
                                 *(MonitorEntry(f'fixture:{index}', f'监控示例 {index}', 'monitoring', 'douyin',
                                                profile_group=group, live=index == 0) for index in range(8)),
                                 MonitorEntry('other', '其他分类', 'monitoring', profile_group=another_group))
        with patch('ddm.streamer_monitor_panel.time.monotonic', return_value=161):
            tray.menu.popup(QPoint(30, 30))
            self.app.processEvents()
        self.assertEqual(self.visible_ids(tray), ['layout_preview', 'streamer_monitor', 'toggle', 'pip', 'exit'])
        monitor_action = tray.menu_actions['streamer_monitor']
        panel = tray.monitor_panel
        self.assertIs(monitor_action.defaultWidget(), panel)
        self.assertFalse(monitor_action.isEnabled())
        self.assertTrue(panel.isVisible())
        self.assertTrue(panel.scroll.isEnabled())
        self.assertTrue(panel._timer.isActive())
        self.assertFalse(window.isVisible())
        headers = [panel.rows.itemAt(index).widget() for index in (0, 3)]
        self.assertEqual([header.findChild(QLabel, 'AppTitle').text() for header in headers], ['录制', '监控'])
        self.assertEqual([header.findChild(QLabel, 'AppSubtitle').text() for header in headers], ['3 位', '10 位'])
        row = panel.rows.itemAt(1).widget()
        self.assertEqual(row.identifier.text(), 'ID 9090')
        self.assertEqual(row.platform_badge.accessibleName(), '哔哩哔哩')
        self.assertEqual(row.status.text(), '正在录制')
        self.assertEqual(row.elapsed.text(), '00:01:01')
        recording_group = panel.rows.itemAt(2).widget()
        self.assertEqual(list(recording_group.avatars), ['1002', '1003'])
        self.assertEqual(recording_group.avatars['1002'].recording_state, 'recording')
        self.assertEqual(recording_group.elapsed.text(), '最长 00:01:06')
        self.assertIn('同组录制甲 · ID 9091 · 00:01:06', recording_group.toolTip())
        self.assertIn('同组录制乙 · 房间号 1003 · 00:00:11', recording_group.toolTip())
        avatar = recording_group.avatars['1002']
        point = avatar.rect().center()
        self.app.sendEvent(avatar, QHelpEvent(QEvent.ToolTip, point, avatar.mapToGlobal(point)))
        self.assertIn('同组录制乙 · 房间号 1003 · 00:00:11', QToolTip.text())
        QToolTip.hideText()
        self.assertEqual(panel.rows.itemAt(4).widget().status.text(), '录制启动失败')
        monitored_group = panel.rows.itemAt(5).widget()
        self.assertIn('监控示例 0 · 房间号 fixture:0 · 直播中', monitored_group.toolTip())
        self.assertIn('监控示例 1 · 房间号 fixture:1 · 未开播', monitored_group.toolTip())
        stack = monitored_group.findChild(QWidget, 'TrayMonitorAvatars')
        rims = stack.findChildren(QWidget, 'TrayMonitorAvatarRim')
        self.assertEqual(len(rims), 5)
        self.assertTrue(rims[0].geometry().intersects(rims[1].geometry()))
        self.assertEqual(stack.findChild(QLabel, 'BadgeOff').text(), '+3')
        self.assertEqual(panel.rows.itemAt(6).widget().name.accessibleName(), '其他分类')
        self.assertEqual(panel.rows.itemAt(6).widget().avatar.width(), 24)
        picture = QPixmap(28, 28)
        picture.fill(QColor('red'))
        panel.set_room_avatar('fixture:0', picture)
        self.assertFalse(panel._stack_avatars['fixture:0'].pixmap().isNull())
        with patch('ddm.streamer_monitor_panel.time.monotonic', return_value=162):
            panel._timer.timeout.emit()
        self.assertEqual(row.elapsed.text(), '00:01:02')
        self.assertEqual(recording_group.elapsed.text(), '最长 00:01:07')
        QTest.mouseClick(row, Qt.LeftButton)
        self.assertTrue(tray.menu.isVisible())
        self.assertFalse(window.isVisible())
        window.open_settings.assert_not_called()
        tray.menu.hide()
        self.assertFalse(tray.menu.isVisible())
        self.assertFalse(panel._timer.isActive())

        provider.return_value = (MonitorEntry('watch', '单个监控示例', 'monitoring'),
                                 *(MonitorEntry(f'record:{index}', f'录制示例 {index}', 'recording', started_at=100)
                                   for index in range(12)))
        tray.menu.popup(QPoint(30, 30))
        self.app.processEvents()
        self.assertEqual(panel._room_rows['watch'].name.accessibleName(), '单个监控示例')
        self.assertFalse(panel._stack_avatars)
        self.assertTrue(panel.scroll.verticalScrollBar().isEnabled())
        self.assertGreater(panel.scroll.verticalScrollBar().maximum(), 0)
        tray.menu.hide()

    def test_settings_preview_references_choices_selects_and_renders_all_off(self):
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QFont, QFontDatabase, QImage
        from PySide6.QtTest import QTest
        from ddm.tray_menu import TrayMenuPreview, tray_menu_choices
        preview = TrayMenuPreview()
        self.addCleanup(preview.deleteLater)
        font_id = QFontDatabase.addApplicationFont(str(
            Path(__file__).resolve().parents[1] / 'ddm/assets/fonts/SourceHanSansSC-Regular.otf'))
        self.assertGreaterEqual(font_id, 0)
        preview.setFont(QFont(QFontDatabase.applicationFontFamilies(font_id)[0]))
        choices = tray_menu_choices([dict(id='exit', enabled=True), dict(id='toggle', enabled=False)])
        preview.set_choices(choices)
        self.assertIs(preview.choices, choices)
        self.assertEqual([key for key, _ in preview.rows()], ['exit', 'layout_preview', 'pip'])
        preview.show()
        self.app.processEvents()
        changed = Mock()
        preview.selectedChanged.connect(changed)
        point = preview.rows()[1][1].center().toPoint()
        QTest.mouseClick(preview, Qt.LeftButton, pos=point)
        self.assertEqual(preview.selected, 'layout_preview')
        changed.assert_called_once_with('layout_preview')
        image = QImage(preview.size(), QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        preview.render(image)
        self.assertEqual(preview.width(), 260)
        self.assertGreater(preview.rows()[1][1].height(), preview.rows()[0][1].height())
        output = os.environ.get('DDM_TRAY_MENU_OUTPUT')
        if output:
            self.assertTrue(image.save(output))
        for choice in choices:
            choice['enabled'] = False
        preview.set_choices(choices)
        self.assertEqual(preview.rows(), [])
        self.assertEqual(preview.height(), 100)
        empty = QImage(preview.size(), QImage.Format_ARGB32_Premultiplied)
        empty.fill(Qt.transparent)
        preview.render(empty)
        center = empty.pixelColor(QPoint(130, 50))
        self.assertTrue(any(empty.pixelColor(x, y) != center
                            for x in range(30, 230) for y in range(40, 60)),
                        'The all-off preview must paint its explanation')


class TrayLayoutPreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def wall(self):
        from types import SimpleNamespace
        from PySide6.QtWidgets import QWidget
        wall = QWidget()
        wall.resize(400, 200)
        wall.tiles = []
        panels, targets = [], {}
        wall.pane_danmaku = SimpleNamespace(rendered=lambda: panels, target=targets.get)
        self.addCleanup(wall.deleteLater)

        def pane(rect, room=None, kind='video', parent=None):
            widget = QWidget(parent or wall)
            widget.setGeometry(*rect)
            widget.room = room or {}
            widget.show()
            if kind == 'video':
                wall.tiles.append(widget)
            else:
                panels.append(widget)
            return widget

        return wall, pane, targets

    def test_irregular_nested_clipped_and_hidden_panes(self):
        from PySide6.QtWidgets import QWidget
        from ddm.tray_preview import capture_layout
        wall, pane, targets = self.wall()
        container = QWidget(wall)
        container.setGeometry(40, 20, 320, 160)
        container.show()
        pane((-60, 10, 180, 90), {'room_id': '1', 'uname': '主播甲'}, parent=container)
        empty = pane((180, 0, 220, 70))
        pane((0, 100, 80, 100), {'room_id': 'hidden'}).hide()
        pane((500, 0, 60, 60))
        panel = pane((180, 70, 220, 130), kind='danmaku')
        targets[panel] = empty
        snapshot = capture_layout(wall)
        self.assertEqual(snapshot['aspect'], 2)
        self.assertEqual(len(snapshot['panes']), 3)
        self.assertEqual(snapshot['panes'][0], dict(
            rect=(0, .15, .4, .45), kind='video', title='主播甲', occupied=True))
        self.assertEqual(snapshot['panes'][1]['title'], '空视频格')
        self.assertFalse(snapshot['panes'][1]['occupied'])
        self.assertEqual(snapshot['panes'][2]['rect'], (.45, .35, .55, .65))
        self.assertEqual(snapshot['panes'][2]['title'], '未绑定')
        self.assertFalse(snapshot['panes'][2]['occupied'])
        self.assertTrue(wall.isHidden(), 'Parent hiding must not discard explicitly shown panes')

    def test_room_title_fallbacks_and_bound_danmaku(self):
        from ddm.tray_preview import capture_layout
        wall, pane, targets = self.wall()
        for index, room in enumerate((
                {'room_id': '1', 'uname': '姓名', 'title': '标题', 'name': '名称'},
                {'room_id': '2', 'title': '标题', 'name': '名称'},
                {'room_id': '3', 'name': '名称'}, {'room_id': 4})):
            pane((index * 100, 0, 100, 100), room)
        panel = pane((0, 100, 200, 100), kind='danmaku')
        targets[panel] = wall.tiles[0]
        pane((200, 100, 200, 100), kind='danmaku')
        panes = capture_layout(wall)['panes']
        self.assertEqual([item['title'] for item in panes], ['姓名', '标题', '名称', '4', '姓名', '未绑定'])
        self.assertTrue(panes[4]['occupied'])
        self.assertFalse(panes[5]['occupied'])

    def test_diagram_types_tiny_panes_and_restore_button(self):
        from PySide6.QtCore import QPoint
        from PySide6.QtGui import QFont, QFontDatabase, QImage
        from PySide6.QtTest import QTest
        from ddm import theme
        from ddm.tray_preview import TrayLayoutPreview
        preview = TrayLayoutPreview()
        self.addCleanup(preview.deleteLater)
        font_path = Path(__file__).resolve().parents[1] / 'ddm/assets/fonts/SourceHanSansSC-Regular.otf'
        font_id = QFontDatabase.addApplicationFont(str(font_path))
        self.assertGreaterEqual(font_id, 0)
        preview.setFont(QFont(QFontDatabase.applicationFontFamilies(font_id)[0]))
        preview.resize(preview.sizeHint())
        preview.set_snapshot(dict(aspect=2, panes=[
            dict(rect=(0, 0, .5, 1), kind='video', title='完整主播名不应从提示中省略', occupied=True),
            dict(rect=(.5, 0, .5, .5), kind='video', title='空视频格', occupied=False),
            dict(rect=(.5, .5, .5, .5), kind='danmaku', title='弹幕主播', occupied=True),
            dict(rect=(.9, .05, .06, .12), kind='danmaku', title='很小的弹幕格', occupied=True),
        ]))
        preview.show()
        self.app.processEvents()
        image = QImage(preview.size(), QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        preview.render(image)
        # Video, occupied chat and empty cells remain distinct even without readable labels.
        self.assertNotEqual(image.pixelColor(70, 18), image.pixelColor(170, 18))
        self.assertNotEqual(image.pixelColor(70, 18), image.pixelColor(170, 80))
        self.assertEqual(image.pixelColor(227, 22), theme.qcolor(theme.PINK),
                         'A narrow pane must retain its type-colored marker')
        self.assertIn('完整主播名不应从提示中省略', preview.toolTip())
        self.assertIn('弹幕格 · 有内容：很小的弹幕格', preview.toolTip())
        self.assertIn('视频格 · 空格', preview.toolTip())
        self.assertIn('恢复主窗口', preview.accessibleName())
        clicked = Mock()
        preview.clicked.connect(clicked)
        QTest.mouseClick(preview, Qt.LeftButton, pos=QPoint(100, 70))
        clicked.assert_called_once()
        output = os.environ.get('DDM_TRAY_PREVIEW_OUTPUT')
        if output:
            self.assertTrue(image.save(output))

    def test_snapshot_has_only_detached_serializable_layout_data(self):
        import json
        from ddm.tray_preview import TrayLayoutPreview, capture_layout
        wall, pane, targets = self.wall()
        room = {'room_id': '1', 'uname': '原名', 'media_url': 'private-media'}
        pane((0, 0, 400, 200), room)
        with tempfile.TemporaryDirectory(prefix='ddm-tray-layout-') as temporary:
            with patch.object(config, 'CONFIG_PATH', str(Path(temporary) / 'config.json')):
                with patch.object(config, 'save') as save:
                    snapshot = capture_layout(wall)
                    preview = TrayLayoutPreview()
                    self.addCleanup(preview.deleteLater)
                    preview.set_snapshot(snapshot)
                    room['uname'] = '已改名'
                    snapshot['panes'][0]['title'] = '已改快照'
                    self.assertEqual(preview.snapshot['panes'][0]['title'], '原名')
                    encoded = json.dumps(preview.snapshot, ensure_ascii=False)
                    self.assertNotIn('media_url', encoded)
                    self.assertNotIn('private-media', encoded)
                    save.assert_not_called()
                    self.assertEqual(list(Path(temporary).iterdir()), [])


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
    elif len(sys.argv) == 1:
        from checks.widget_cases import run_widget_cases
        results = [run_widget_cases(case, __file__)
                   for case in (SystemTrayTests, TrayMenuChoicesTests, TrayLayoutPreviewTests)]
        raise SystemExit(int(any(results)))
    else:
        unittest.main()
