"""Detached generic credentials, conditional device publication and account events."""
from contextlib import ExitStack
import os
from pathlib import Path
import sys
import threading
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('DDM_NO_SAVE', '1')
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QLineEdit, QWidget
from PySide6.QtTest import QTest
from ddm import bili, plugins as api
from ddm.fullscreen_cursor import FullscreenCursor
from ddm.widgets import Tile

APP = QApplication.instance() or QApplication([])


class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(hasattr(api, 'TileControl'), 'public tile extension API is missing')
        self.manager = api.PluginManager()
        self.events = []
        self.manager.plugins.append(SimpleNamespace(on_event=lambda event, payload: self.events.append((event, payload))))
        self.values = {'session': 'private-session', 'csrf': 'private-csrf', 'device': ''}
        self.manager.register_credentials('demo', lambda: self.values,
            update=lambda changes: self.values.update(changes),
            identity_keys=('session', 'csrf'), writable_fields=('device',))
        self.context = api.PluginContext(self.manager, 'demo')

    def test_snapshots_are_detached_and_secret_free(self):
        snapshot = self.context.credentials('demo')
        self.assertIsNone(self.context.credentials('absent'))
        self.assertNotIn('private-session', repr(snapshot))
        with self.assertRaises(TypeError):
            snapshot.values['session'] = 'forbidden'
        self.values['session'] = 'replacement'
        self.assertEqual(snapshot.values['session'], 'private-session')
        self.manager.notify_credentials('demo')
        self.assertNotEqual(snapshot.generation, self.context.credentials('demo').generation)
        self.assertNotIn('private-', repr(self.events))
        self.assertEqual(self.events[-1][0], 'account.changed')

    def test_device_refresh_keeps_account_generation(self):
        old = self.context.credentials('demo')
        self.assertTrue(self.context.update_credentials('demo', {'device': 'device-secret'}, expected_generation=old.generation))
        self.assertEqual(self.context.credentials('demo').generation, old.generation)
        self.assertEqual(self.events[-1], ('account.credentials_updated', {'platform': 'demo', 'generation': old.generation, 'fields': ['device']}))
        self.assertNotIn('device-secret', repr(self.events))
        with self.assertRaises(ValueError):
            self.context.update_credentials('demo', {'session': 'wrong'}, expected_generation=old.generation)

    def test_old_device_update_after_login_is_rejected(self):
        old = self.context.credentials('demo')
        self.values.update(session='new-login', device='new-device')
        self.manager.notify_credentials('demo')
        self.assertFalse(self.context.update_credentials('demo', {'device': 'old-device'}, expected_generation=old.generation))
        self.assertEqual(self.values['device'], 'new-device')

    def test_calls_from_worker_are_rejected(self):
        errors = []
        def work():
            try:
                self.context.credentials('demo')
            except RuntimeError as error:
                errors.append(str(error))
        thread = threading.Thread(target=work)
        thread.start()
        thread.join()
        self.assertEqual(len(errors), 1)

    def test_existing_login_device_is_preserved(self):
        with patch.object(bili, 'SESSION_DATA', ''), patch.object(bili, 'BILI_JCT', ''), patch.object(bili, 'BUVID3', ''):
            self.assertEqual(bili.remember_buvid3('first'), 'first')
            bili.set_login_cookies('new-session', 'new-csrf', 'login-device')
            self.assertEqual(bili.remember_buvid3('late'), 'login-device')
            self.assertEqual(bili._cookies()['buvid3'], 'login-device')

    def test_restored_login_and_logout_notify_synchronously(self):
        from ddm.app import MainWindow
        with patch.object(bili, 'SESSION_DATA', 'restored'), patch.object(bili, 'BILI_JCT', 'csrf'), patch.object(bili, 'BUVID3', 'device'):
            manager = api.PluginManager()
            seen = []
            manager.plugins.append(SimpleNamespace(on_event=lambda e, p: seen.append((e, manager.credentials('bilibili')))))
            manager.register_credentials('bilibili', bili._cookies, identity_keys=('SESSDATA', 'bili_jct'))
            self.assertEqual(manager.credentials('bilibili').values['SESSDATA'], 'restored')
            window = SimpleNamespace(plugins=manager, state={}, current_state=lambda: {},
                _render_account=lambda: None, refresh_account=lambda: None,
                stop_danmaku=lambda: None, sync_danmaku=lambda: None,
                _clear_platform_account=lambda k: None)
            with patch('ddm.config.save'):
                MainWindow._on_login(window, 'new-session')
                self.assertEqual(seen[-1][1].values['SESSDATA'], 'new-session')
                MainWindow.logout(window, 'bilibili')
                self.assertNotIn('SESSDATA', seen[-1][1].values)

    def test_real_host_persists_device_and_rejects_old_account_publication(self):
        from ddm import config
        from ddm.app import MainWindow
        with tempfile.TemporaryDirectory() as root, patch.object(config, 'CONFIG_PATH', str(Path(root) / 'state.json')), \
                patch.object(bili, 'SESSION_DATA', ''), patch.object(bili, 'BILI_JCT', ''), patch.object(bili, 'BUVID3', ''), \
                patch('ddm.app.QTimer.singleShot'), patch.dict(os.environ, {'DDM_NO_SAVE': ''}):
            window = MainWindow([], [], layout_id='1x1', state={
                'plugins_enabled': [], 'sessdata': 'fake-session', 'bili_jct': 'fake-csrf',
                'settings': {'auto_update': False}})
            try:
                ctx = api.PluginContext(window.plugins, 'fixture')
                initial = ctx.credentials('bilibili')
                self.assertTrue(ctx.update_credentials('bilibili', {'buvid3': 'fixture-device'}, expected_generation=initial.generation))
                self.assertEqual(config.load()['buvid3'], 'fixture-device')
                self.assertEqual(ctx.credentials('bilibili').generation, initial.generation)
                bili.set_login_cookies('new-account', 'new-csrf', 'new-device')
                window.plugins.notify_credentials('bilibili')
                self.assertFalse(ctx.update_credentials('bilibili', {'buvid3': 'stale-device'}, expected_generation=initial.generation))
                self.assertEqual(bili._cookies()['buvid3'], 'new-device')
            finally:
                window.close()


class InteractionTests(unittest.TestCase):
    def test_active_interaction_protects_shortcuts_on_another_tile(self):
        from ddm.app import MainWindow
        with ExitStack() as stack:
            for method in ('refresh_status', 'refresh_stats', 'refresh_account',
                           'sync_danmaku', 'stop_danmaku', 'load_room_avatars', '_check_startup_update'):
                stack.enter_context(patch.object(MainWindow, method))
            stack.enter_context(patch('ddm.app.QTimer.singleShot'))
            window = MainWindow([], [{'room_id': '12'}, {'room_id': '13'}], layout_id='2x2',
                state={'plugins_enabled': [], 'settings': {'auto_update': False}})
            controls = []
            class ActiveControl(api.TileControl):
                active = False
                def set_room(self, room):
                    self.widget.show()
                def interaction_active(self):
                    return self.active
            def factory(ctx):
                control = ActiveControl(QLineEdit(ctx.parent), minimum_width=90)
                controls.append(control)
                return control
            try:
                window.resize(1900, 1000)
                window.show()
                window.activateWindow()
                window.plugins.register_tile_control('generic', 'active', factory)
                APP.processEvents()
                target = window.wall.tiles[1]
                before = target.danmaku_button.isChecked()
                stack.enter_context(patch.object(window, '_tile_under_cursor', return_value=target))
                control = controls[0]
                self.assertTrue(control.widget.isVisible())
                control.active = True
                QTest.keyClick(window, Qt.Key_B)
                self.assertEqual(target.danmaku_button.isChecked(), before)
                with patch.object(window, '_on_fullscreen') as fullscreen:
                    QTest.keyClick(window, Qt.Key_F)
                    fullscreen.assert_not_called()
                muted = target.muted
                QTest.keyClick(window, Qt.Key_M)
                self.assertEqual(target.muted, muted)
                control.widget.setFocus()
                QTest.keyClick(control.widget, Qt.Key_B)
                self.assertEqual(control.widget.text(), 'b')
                self.assertEqual(target.danmaku_button.isChecked(), before)
                control.active = False
                window.sidebar.settings_button.setFocus()
                QTest.keyClick(window, Qt.Key_B)
                self.assertNotEqual(target.danmaku_button.isChecked(), before)
                control.active = True
                control.widget.setEnabled(False)
                QTest.keyClick(window, Qt.Key_B)
                self.assertEqual(target.danmaku_button.isChecked(), before)
            finally:
                window.close()
                APP.processEvents()

    def test_focus_keeps_fullscreen_controls_over_video_and_outside(self):
        window = QWidget()
        tile = Tile({'room_id': '12'}, window)
        tile.resize(600, 300)
        window.resize(600, 300)
        window._fullscreen_tile = tile
        window.settings = {}
        window.isActiveWindow = lambda: True
        manager = api.PluginManager()
        class FocusControl(api.TileControl):
            def interaction_active(self):
                return True
        manager.register_tile_control('demo', 'focus', lambda ctx: FocusControl(QLineEdit(ctx.parent), minimum_width=90))
        manager.attach_tile(tile)
        window.show()
        APP.processEvents()
        cursor = FullscreenCursor(window)
        cursor.IDLE_SECONDS = 0
        for point in (tile.video.mapToGlobal(tile.video.rect().center()), window.mapToGlobal(QPoint(-100, -100))):
            with patch.object(QCursor, 'pos', return_value=point):
                cursor.update_cursor()
                cursor.update_cursor()
            self.assertFalse(cursor.hidden)
            self.assertFalse(getattr(tile, '_fullscreen_controls_hidden', False))
        control = tile._plugin_controls.entries[0].control
        control.widget.setEnabled(False)
        self.assertFalse(tile.plugin_interaction_active())
        control.widget.setEnabled(True)
        control.widget.hide()
        self.assertFalse(tile.plugin_interaction_active())
        cursor.stop()
        manager.unload()
        window.close()


if __name__ == '__main__':
    unittest.main()
