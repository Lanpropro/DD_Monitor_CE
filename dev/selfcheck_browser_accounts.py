"""Offline application-owned browser, proxy routing, stored sessions and cancellation."""
import os
from pathlib import Path
import sys
import threading
import time
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtWidgets import QApplication, QWidget
from ddm.account_store import AccountStore
from ddm import account_browser as browser
from ddm.browser_account_worker import BrowserAccountLoader, cookie_jar, cookie_records
from ddm.browser_account_dialog import BrowserAccountDialog, prefer_browser_login
from ddm.plugins import LoginRequiredError


COOKIES = [{'name': 'auth-token', 'value': 'fixture-only', 'domain': '.twitch.tv',
            'path': '/', 'secure': True, 'httpOnly': True, 'expires': -1}]


class BrowserAccountTests(unittest.TestCase):
    def platform(self):
        return SimpleNamespace(kind='twitch', browser_login_url='https://www.twitch.tv/login',
            browser_cookie_domains=('twitch.tv',), browser_account_info=Mock(return_value={'uid': '123', 'uname': 'Fixture'}),
            browser_follow_rooms=Mock(return_value=[{'room_id': 'twitch:fixture'}]))

    def test_proxy_is_explicit_and_credentials_not_put_on_command_line(self):
        with patch.object(browser, 'getproxies', return_value={'https': 'http://127.0.0.1:1234'}):
            self.assertEqual(browser.browser_proxy(), 'http://127.0.0.1:1234')
        with patch.object(browser, 'getproxies', return_value={'https': 'http://user:secret@host:80'}):
            with self.assertRaisesRegex(RuntimeError, '本机') as error:
                browser.browser_proxy()
            self.assertNotIn('secret', str(error.exception))

    def test_cookie_roundtrip_preserves_secure_domain_and_discards_other_sites(self):
        records = cookie_records(COOKIES + [{**COOKIES[0], 'domain': '.example.com'}])
        jar = cookie_jar(records, ('twitch.tv',))
        self.assertEqual(len(jar), 1)
        cookie = next(iter(jar))
        self.assertEqual(cookie.domain, '.twitch.tv')
        self.assertTrue(cookie.secure)
        self.assertEqual(cookie.value, 'fixture-only')

    def test_browser_uses_fresh_profile_proxy_and_closes_only_its_process(self):
        process = Mock()
        process.poll.side_effect = [0, None, None, None]
        def spawn(args, **_kwargs):
            profile = next(arg.split('=', 1)[1] for arg in args if arg.startswith('--user-data-dir='))
            Path(profile, 'DevToolsActivePort').write_text('12345\n/devtools/browser/fixture\n', encoding='utf-8')
            return process
        operation = browser.AccountBrowser('https://www.twitch.tv/login', ('twitch.tv',), threading.Event())
        operation._command = AsyncMock(return_value={})
        with patch.object(browser, 'find_browser', return_value='fixture-browser.exe'), \
                patch.object(browser, 'browser_proxy', return_value='http://127.0.0.1:1234'), \
                patch.object(browser.subprocess, 'Popen', side_effect=spawn) as launched:
            with operation:
                directory = operation.directory.name
                self.assertTrue(Path(directory).is_dir())
                self.assertEqual(operation.cookies(), [])
                self.assertEqual(operation.socket_url, 'ws://127.0.0.1:12345/devtools/browser/fixture')
        args = launched.call_args.args[0]
        self.assertIn('--proxy-server=http://127.0.0.1:1234', args)
        self.assertIn('--remote-debugging-address=127.0.0.1', args)
        first_args = launched.call_args_list[0].args[0]
        self.assertFalse(any(arg.startswith('--remote-debugging') for arg in first_args))
        self.assertNotIn('--profile-directory=Default', args)
        self.assertFalse(Path(directory).exists())
        self.assertEqual([call.args[0] for call in operation._command.await_args_list],
                         ['Storage.getCookies', 'Browser.close'])
        process.terminate.assert_not_called()

    def run_loader(self, platform, saved, *, login_only=False):
        loader = BrowserAccountLoader(platform, saved, login_only=login_only)
        identity, loaded, failed = [], [], []
        loader.identity.connect(lambda *args: identity.append(args))
        loader.loaded.connect(loaded.append)
        loader.failed.connect(failed.append)
        loader.run()
        return loader, identity, loaded, failed

    def test_saved_session_loads_follows_without_browser(self):
        platform = self.platform()
        with patch('ddm.browser_account_worker.AccountBrowser', side_effect=AssertionError('Unexpected browser')):
            _worker, identity, loaded, failed = self.run_loader(platform, cookie_records(COOKIES))
        self.assertFalse(failed)
        self.assertEqual(identity[0][0]['uid'], '123')
        self.assertEqual(loaded[0][0]['room_id'], 'twitch:fixture')

    def test_existing_oauth_session_keeps_its_original_flow(self):
        owner = SimpleNamespace(_platform_login_sessions={'twitch': {'auth': {'access_token': 'fixture'}}})
        self.assertFalse(prefer_browser_login(self.platform(), owner))
        owner._platform_login_sessions = {'twitch': {'cookies': cookie_records(COOKIES)}}
        self.assertTrue(prefer_browser_login(self.platform(), owner))

    def test_first_login_needs_no_oauth_configuration(self):
        native = Mock()
        native.__enter__ = Mock(return_value=native)
        native.__exit__ = Mock()
        native.cookies.return_value = COOKIES
        with patch('ddm.browser_account_worker.AccountBrowser', return_value=native):
            _worker, identity, loaded, failed = self.run_loader(self.platform(), [], login_only=True)
        self.assertFalse(failed)
        self.assertTrue(identity and loaded == [[]])
        native.__exit__.assert_called_once()

    def test_configured_official_client_is_used_for_first_login(self):
        owner = SimpleNamespace(_platform_login_sessions={}, _accounts={})
        with TemporaryDirectory() as root, patch.dict(os.environ, {'DDM_NO_SAVE': '0'}), \
                patch('ddm.browser_account_dialog.AccountStore',
                      side_effect=lambda kind: AccountStore(kind, root=root)):
            for kind in ('youtube', 'twitch'):
                platform = self.platform()
                platform.kind = kind
                platform.oauth_provider = kind
                self.assertTrue(prefer_browser_login(platform, owner))
                AccountStore(kind + '_oauth_client', root=root).save([], {'client_id': 'fixture'})
                self.assertFalse(prefer_browser_login(platform, owner))
                owner._platform_login_sessions[kind] = {'cookies': cookie_records(COOKIES)}
                self.assertTrue(prefer_browser_login(platform, owner))
                owner._platform_login_sessions.clear()
                AccountStore(kind + '_oauth_client', root=root).path.write_bytes(b'invalid-fixture')
                self.assertTrue(prefer_browser_login(platform, owner))

    def test_offline_login_selection_does_not_read_client_configuration(self):
        platform = self.platform()
        platform.oauth_provider = 'twitch'
        with patch('ddm.browser_account_dialog.AccountStore', side_effect=AssertionError('Real client read')):
            self.assertTrue(prefer_browser_login(platform, SimpleNamespace()))

    def test_network_failure_does_not_discard_saved_session_or_open_browser(self):
        platform = self.platform()
        platform.browser_account_info.side_effect = RuntimeError('Fixture network error')
        with patch('ddm.browser_account_worker.AccountBrowser', side_effect=AssertionError('Unexpected browser')):
            _worker, identity, loaded, failed = self.run_loader(platform, cookie_records(COOKIES))
        self.assertFalse(identity or loaded)
        self.assertEqual(failed, ['Fixture network error'])

    def test_rejected_session_reopens_browser_and_cancel_discards_late_identity(self):
        platform = self.platform()
        platform.browser_account_info.side_effect = LoginRequiredError('expired')
        loader = BrowserAccountLoader(platform, cookie_records(COOKIES))
        native = Mock()
        def opened():
            loader.cancel()
            return native
        native.__enter__ = Mock(side_effect=opened)
        native.__exit__ = Mock()
        identity, loaded = [], []
        loader.identity.connect(lambda *args: identity.append(args))
        loader.loaded.connect(loaded.append)
        with patch('ddm.browser_account_worker.AccountBrowser', return_value=native):
            loader.run()
        self.assertFalse(identity or loaded)
        platform.browser_follow_rooms.assert_not_called()
        native.__exit__.assert_called_once()

    def test_dialog_cancelled_results_do_not_change_owner_and_logout_is_separate(self):
        owner = QWidget()
        owner._accounts = {'youtube': {'uid': 'keep'}}
        owner._platform_login_sessions = {'youtube': {'cookies': []}}
        owner._render_account = Mock()
        page = BrowserAccountDialog(self.platform(), owner=owner)
        try:
            page._read_cancelled = True
            page._identity({'uid': 'late'}, ['fixture'])
            self.assertNotIn('twitch', owner._accounts)
            page._read_cancelled = False
            page._identity({'uid': '123'}, cookie_records(COOKIES))
            self.assertEqual(owner._accounts['twitch']['uid'], '123')
            self.assertNotIn('auth', owner._platform_login_sessions['twitch'])
            page._forget()
            self.assertEqual(page._cookies, [])
            self.assertNotIn('twitch', owner._accounts)
            self.assertEqual(owner._accounts['youtube'], {'uid': 'keep'})
        finally:
            page.deleteLater()
            owner.deleteLater()

    def test_remembered_session_is_encrypted_and_restores_without_oauth_client(self):
        with TemporaryDirectory() as directory, patch.dict(os.environ, DDM_NO_SAVE='0'), \
                patch('ddm.browser_account_dialog.AccountStore',
                      side_effect=lambda kind: AccountStore(kind, root=directory)):
            page = BrowserAccountDialog(self.platform())
            try:
                records = cookie_records(COOKIES)
                page._identity({'uid': '123', 'uname': 'Fixture'}, records)
                stored = AccountStore('twitch', root=directory)
                self.assertNotIn(b'fixture-only', stored.path.read_bytes())
                self.assertEqual(stored.load(), records)
                restored = BrowserAccountDialog(self.platform())
                self.assertEqual(restored._cookies, records)
                restored.deleteLater()
            finally:
                page.deleteLater()

    def test_platform_menu_login_import_and_reread_use_native_list(self):
        from ddm.account_dialog import AccountPlatformDialog
        from ddm.dialogs import FollowImportDialog
        owner = QWidget()
        owner._accounts, owner._platform_login_sessions = {}, {}
        owner._closing, owner._follow_loader = False, None
        owner.plugins = SimpleNamespace(_platform_owner={'twitch': 'global_live'})
        owner.sidebar = SimpleNamespace(rooms=lambda: [], folder_state=lambda: {}, create_folder=Mock())
        owner._render_account, owner._start_avatar_loader, owner._wait_background = Mock(), Mock(), Mock()
        owner._clear_platform_account = Mock()
        platform = self.platform()
        platform.label, platform.oauth_provider = 'Twitch', 'twitch'
        platform.browser_follow_rooms.return_value = [
            {'room_id': 'twitch:fixture', 'platform': 'twitch', 'uname': 'Fixture', 'live': False}]
        dialog = AccountPlatformDialog(owner, {'Twitch': platform}, import_follows=True, platform_kind='twitch')
        native = Mock()
        native.__enter__ = Mock(return_value=native)
        native.__exit__ = Mock()
        native.cookies.return_value = COOKIES
        def wait_for_list():
            deadline = time.monotonic() + 4
            while time.monotonic() < deadline:
                app.processEvents()
                if isinstance(dialog.page, FollowImportDialog) and owner._follow_loader is None:
                    return
                time.sleep(.01)
            self.fail('Native login did not return to the follow-selection list')
        try:
            self.assertIsInstance(dialog.page, BrowserAccountDialog)
            with patch('ddm.browser_account_worker.AccountBrowser', return_value=native) as launched:
                dialog.page._read()
                wait_for_list()
                self.assertEqual([room['room_id'] for room in dialog.page.rooms], ['twitch:fixture'])
                self.assertTrue(dialog.platform_buttons['twitch'].property('loggedIn'))
                dialog.select_platform('twitch', reread=True)
                wait_for_list()
                self.assertEqual(launched.call_count, 1)
                self.assertEqual(platform.browser_follow_rooms.call_count, 2)
        finally:
            dialog.reject()
            dialog.deleteLater()
            owner.deleteLater()


if __name__ == '__main__':
    app = QApplication.instance() or QApplication([])
    unittest.main()
