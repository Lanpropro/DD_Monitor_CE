"""Offline public plugin notification/login API and owner lifecycle regressions."""
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from contextlib import redirect_stderr
from io import StringIO

os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEvent, QThread, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
import shiboken6
from ddm.plugins import PluginContext, PluginManager

APP = QApplication.instance() or QApplication([])


class Window(QWidget):
    def __init__(self):
        super().__init__()
        self._closing = False
        self.notices, self.logins = [], []

    def _show_notice(self, message, **options):
        self.notices.append((message, options, QThread.currentThread()))

    def open_login(self, platform, *, reauthenticate=False):
        self.logins.append((platform, reauthenticate, QThread.currentThread()))


class PluginNoticeTests(unittest.TestCase):
    def setUp(self):
        self.window = Window()
        self.manager = PluginManager(self.window)
        self.context = PluginContext(self.manager, 'demo')

    def tearDown(self):
        self.manager.unload()
        if shiboken6.isValid(self.window):
            self.window.close()
            self.window.deleteLater()
        APP.sendPostedEvents(None, QEvent.DeferredDelete)
        APP.processEvents()

    def flush(self):
        for _ in range(3):
            APP.processEvents()

    def test_public_api_is_available(self):
        self.assertTrue(callable(getattr(self.context, 'notify', None)),
                        'public plugin notify API is missing')
        self.assertTrue(callable(getattr(self.context, 'request_login', None)),
                        'public plugin login API is missing')

    def test_worker_delivery_uses_gui_thread_and_copies_rooms(self):
        self.test_public_api_is_available()
        rooms = [{'room_id': '120', 'uname': 'synthetic'}]
        accepted = []
        worker = threading.Thread(target=lambda: accepted.append(self.context.notify(
            '发送失败', rooms=rooms, kind='warning')))
        worker.start()
        worker.join()
        rooms[0]['uname'] = 'changed'
        self.assertEqual(self.window.notices, [])
        self.flush()
        self.assertEqual(accepted, [True])
        message, options, thread = self.window.notices[0]
        self.assertEqual(message, '发送失败')
        self.assertEqual(options['rooms'], ({'room_id': '120', 'uname': 'synthetic'},))
        self.assertEqual(options['kind'], 'warning')
        self.assertEqual(thread, APP.thread())

    def test_click_defers_reauthentication_until_after_callback_returns(self):
        self.test_public_api_is_available()
        self.context.notify('登录失效', on_click=lambda: self.context.request_login(
            'demo-platform', reauthenticate=True))
        self.flush()
        callback = self.window.notices[0][1]['on_click']
        callback()
        self.assertEqual(self.window.logins, [])
        self.flush()
        self.assertEqual(self.window.logins, [('demo-platform', True, APP.thread())])

    def test_unload_cancels_pending_delivery_and_retained_actions(self):
        self.test_public_api_is_available()
        actions = []
        self.context.notify('visible', on_click=lambda: actions.append('clicked'))
        self.flush()
        callback = self.window.notices[0][1]['on_click']
        self.context.notify('pending')
        self.context.request_login('demo-platform')
        self.manager.unload()
        callback()
        self.flush()
        self.assertEqual(len(self.window.notices), 1)
        self.assertEqual(self.window.logins, [])
        self.assertEqual(actions, [])
        self.assertFalse(self.context.notify('late'))
        self.assertFalse(self.context.request_login('demo-platform'))

    def test_close_and_qt_deletion_make_queued_calls_and_clicks_inert(self):
        self.test_public_api_is_available()
        self.context.notify('visible', on_click=lambda: self.context.request_login('demo-platform'))
        self.flush()
        callback = self.window.notices[0][1]['on_click']
        self.context.notify('pending')
        self.window._closing = True
        callback()
        self.flush()
        self.assertEqual(len(self.window.notices), 1)
        self.assertEqual(self.window.logins, [])
        self.assertFalse(self.context.notify('closed'))
        self.window.deleteLater()
        APP.sendPostedEvents(None, QEvent.DeferredDelete)
        callback()
        self.assertFalse(self.context.notify('deleted'))

    def test_failed_load_only_revokes_its_own_pending_calls(self):
        self.test_public_api_is_available()
        self.context.notify('other-owner')
        with tempfile.TemporaryDirectory() as root:
            invalid = Path(root) / 'a_invalid_import'
            invalid.mkdir()
            (invalid / 'plugin.py').write_text('this is invalid (', encoding='utf-8')
            folder = Path(root) / 'broken'
            folder.mkdir()
            (folder / 'plugin.py').write_text(
                'from ddm.plugins import Plugin\n'
                'class Broken(Plugin):\n'
                ' def on_load(self, context):\n'
                '  context.notify("must not display")\n'
                '  context.request_login("demo-platform")\n'
                '  raise ValueError("intentional load failure")\n'
                'plugin=Broken()\n', encoding='utf-8')
            self.manager.plugins_dir = root
            with redirect_stderr(StringIO()):
                self.manager.load()
        self.flush()
        self.assertEqual([n[0] for n in self.window.notices], ['other-owner'])
        self.assertEqual(self.window.logins, [])

    def test_window_destroyed_during_payload_capture_returns_false(self):
        self.test_public_api_is_available()
        def rooms():
            self.window.deleteLater()
            APP.sendPostedEvents(None, QEvent.DeferredDelete)
            yield {'room_id': '120'}
        self.assertFalse(self.context.notify('late', rooms=rooms()))

    def test_headless_manager_returns_false(self):
        self.test_public_api_is_available()
        manager = PluginManager()
        context = PluginContext(manager, 'headless')
        self.assertFalse(context.notify('not shown'))
        self.assertFalse(context.request_login('demo-platform'))
        manager.unload()

    def test_invalid_notice_arguments_are_rejected_without_scheduling(self):
        self.test_public_api_is_available()
        with self.assertRaises(ValueError):
            self.context.notify('invalid', kind='unknown')
        with self.assertRaises(ValueError):
            self.context.notify('invalid', on_click='not callable')
        self.flush()
        self.assertEqual(self.window.notices, [])

    def test_real_notice_click_dismisses_before_deferred_login(self):
        self.test_public_api_is_available()
        from ddm.online_ui import show_result
        self.window._show_notice = lambda message, **options: show_result(self.window, message, **options)
        self.window.resize(800, 600)
        self.window.show()
        self.context.notify('房间 120：登录失效，点击重新登录', kind='warning', on_click=lambda:
                            self.context.request_login('demo-platform', reauthenticate=True))
        self.flush()
        notice = self.window._result_notice
        self.assertIn('120', notice.title.text())
        self.assertTrue(notice.isVisible())
        self.assertNotIn('B 站', notice.toolTip())
        QTest.mouseClick(notice, Qt.LeftButton)
        self.assertFalse(notice.isVisible())
        self.assertEqual(self.window.logins, [])
        self.flush()
        self.assertEqual(self.window.logins, [('demo-platform', True, APP.thread())])


if __name__ == '__main__':
    unittest.main()
