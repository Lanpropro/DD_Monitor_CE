"""Core Bilibili login/playback/receiving work without an interaction plugin."""
from contextlib import ExitStack
import importlib.util
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication, QLineEdit
from ddm import bili, plugins
from ddm.app import MainWindow

APP = QApplication.instance() or QApplication([])


class BiliPluginBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.saved = bili._cookies()
        self.addCleanup(lambda: bili.set_login_cookies(
            self.saved.get('SESSDATA', ''), self.saved.get('bili_jct', ''),
            self.saved.get('buvid3', '')))
        for method in ('refresh_status', 'refresh_stats', 'refresh_account', 'load_room_avatars'):
            self.stack.enter_context(patch.object(MainWindow, method))
        self.stack.enter_context(patch('ddm.app.QTimer.singleShot'))
        self.window = MainWindow([], [{'room_id': '101', 'live': False}], layout_id='1x1', state={
            'plugins_enabled': [], 'sessdata': 'fake-session', 'bili_jct': 'fake-csrf',
            'buvid3': 'fake-device', 'settings': {'auto_update': False}})
        self.addCleanup(self.window.close)

    def test_legacy_emoticon_order_is_preserved_for_rollback(self):
        orders = {'_tabs': ['standard'], 'room': ['emote-1']}
        self.window.state['emoticon_order'] = orders
        saved = self.window.current_state()['emoticon_order']
        self.assertEqual(saved, orders)
        self.assertIsNot(saved, orders)

    def test_no_builtin_sending_capability_or_editor(self):
        self.assertIsNone(importlib.util.find_spec('ddm.danmaku_send'))
        self.assertFalse(callable(getattr(bili, 'send_danmaku', None)))
        self.assertFalse(callable(getattr(bili, 'get_emoticons', None)))
        self.assertEqual(self.window.plugins.plugins, [])
        self.assertEqual(self.window.wall.tiles[0].bottom.findChildren(QLineEdit), [])

    def test_cookie_restoration_room_and_fullscreen_without_plugin(self):
        self.assertEqual(bili._cookies(), {'SESSDATA': 'fake-session',
            'bili_jct': 'fake-csrf', 'buvid3': 'fake-device'})
        tile = self.window.wall.tiles[0]
        for room in ({'room_id': '202', 'live': False}, {}, {'room_id': '303', 'live': False}):
            tile.set_room(room)
            self.assertEqual(tile.room.get('room_id'), room.get('room_id'))
            self.assertTrue(tile.danmaku_settings_button.isEnabled())
        self.window._on_fullscreen(tile)
        self.window._clear_fullscreen_cover()
        self.window._exit_fullscreen()
        self.window._clear_fullscreen_cover()
        self.assertIsNone(self.window._fullscreen_tile)
        saved = self.window.current_state()
        self.assertEqual((saved['sessdata'], saved['bili_jct'], saved['buvid3']),
                         ('fake-session', 'fake-csrf', 'fake-device'))

    def test_current_platform_codec_and_legacy_sender_apis_survive(self):
        class Legacy(plugins.Platform):
            def play_url(self, room_id, quality=250):
                return ('https://example.invalid/live', quality, 'fixture')
        platform = Legacy()
        self.assertEqual(platform.play_url_for_codec('1'),
                         ('https://example.invalid/live', 250, 'fixture', {}, ''))
        with self.assertRaises(plugins.StreamCodecUnavailable):
            platform.play_url_for_codec('1', codec='hevc')
        self.assertTrue(callable(plugins.PluginContext.register_danmaku_sender))


if __name__ == '__main__':
    unittest.main()
