"""Additional-cache checks: temporary data only, fake network and no real login profile."""
from contextlib import ExitStack
import os
from pathlib import Path
import sys
import subprocess
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QObject, QPoint, QThreadPool, Signal, Qt
from PySide6.QtGui import QFontDatabase, QImage, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from ddm import cache_cleanup, config, image_cache, images, online


class ExtraCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix='ddm-extra-cache-')))
        self.stack.enter_context(patch.object(config, 'DATA_ROOT', str(self.root)))
        self.stack.enter_context(patch.object(images, 'REPO', str(self.root)))
        self.stack.enter_context(patch.object(images.requests, 'get', side_effect=AssertionError('Unexpected network')))

    def file(self, relative, data=b'fixture', old=False):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        if old:
            os.utime(path, (time.time() - 172800, time.time() - 172800))
        return path

    def png(self):
        pixmap = QPixmap(20, 20)
        pixmap.fill(Qt.blue)
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(QIODevice.WriteOnly)
        pixmap.save(buffer, 'PNG')
        return pixmap, bytes(data)

    def test_queued_image_workers_cannot_recreate_cleared_categories(self):
        pixmap, content = self.png()
        for kind in cache_cleanup.IMAGE_KINDS:
            with self.subTest(kind=kind):
                url = 'https://example.invalid/' + self.root.name + '/' + kind
                item = dict(room_id='1', uid='2', platform='bilibili', banner_url=url) if kind == 'banners' else url
                worker = images.AvatarLoader({'1': item}, subdir=kind)
                image_cache.clear(self.root, {kind})
                with patch.object(images.requests, 'get', return_value=SimpleNamespace(status_code=200, content=content)):
                    worker.run()
                self.assertEqual(image_cache.usage(self.root, (kind,))[kind]['files'], 0)
        self.assertEqual(tuple(image_cache.usage(self.root)), ('avatars', 'covers'))

    def test_banner_room_snapshot_uses_same_cleanup_ticket(self):
        pixmap, content = self.png()
        room = dict(room_id='1', uid='2', platform='bilibili', banner_url='https://example.invalid/banner')
        def loaded(*args, **kwargs):
            image_cache.clear(self.root, {'banners'})
            return pixmap
        with patch.object(images, 'load_pixmap', side_effect=loaded):
            self.assertIsNone(images.load_banner(room))
        self.assertFalse(Path(images.room_banner_path('1')).exists())

    def test_clearing_catalog_blocks_inflight_save_but_next_refresh_rebuilds(self):
        path = self.file('cache/plugin-catalog.json', b'{}')
        def published(*args, **kwargs):
            cache_cleanup.clear(self.root, {'plugin-catalog'})
            return []
        with patch.object(online, 'plugin_catalog', side_effect=published):
            online.cached_plugin_catalog(None, '0.7.3', path, force=True)
        self.assertFalse(path.exists())
        with patch.object(online, 'plugin_catalog', return_value=[]):
            online.cached_plugin_catalog(None, '0.7.3', path, force=True)
        self.assertTrue(path.exists())

    def test_fixed_categories_never_touch_accounts_recordings_or_plugin_updates(self):
        protected = [self.file(name) for name in ('utils/config.json', 'utils/accounts/bilibili.bin',
            'recordings/.ddm-parts/part.ts', 'plugins_user/.updates/plugin/plugin.py', 'plugins_user/.updates/plugin.backup/data')]
        for kind in cache_cleanup.IMAGE_KINDS:
            self.file(f'cache/{kind}/room/a.png')
        self.file('cache/plugin-catalog.json')
        self.file('cache/web-login/Cache/entry')
        cookies = self.file('cache/web-login/Cookies')
        result = cache_cleanup.clear(self.root, set(cache_cleanup.KINDS) - {'logs'})
        self.assertEqual(result['files'], 4)
        self.assertTrue(result['deferred'])
        self.assertTrue(cookies.exists())
        self.assertTrue(all(path.exists() for path in protected))
        with self.assertRaises(ValueError):
            cache_cleanup.clear(self.root, {'../utils'})
        with self.assertRaises(ValueError):
            image_cache._inside(self.root, self.root.parent / 'escaped')
        blocked = self.root / 'cache'
        original = image_cache._is_link
        with patch.object(image_cache, '_is_link', side_effect=lambda p: p == blocked or original(p)):
            with self.assertRaises(ValueError):
                cache_cleanup.clear(self.root, {'plugin-catalog'})

    def test_links_are_not_followed(self):
        with tempfile.TemporaryDirectory(prefix='ddm-extra-outside-') as external:
            outside = Path(external)
            protected = outside / 'a.png'
            protected.write_bytes(b'outside')
            folder = self.root / 'cache/emoticons'
            folder.mkdir(parents=True)
            try:
                (folder / 'linked').symlink_to(outside, target_is_directory=True)
            except OSError as error:
                self.skipTest('Symbolic links unavailable: ' + str(error))
            result = cache_cleanup.clear(self.root, {'emoticons'})
            self.assertEqual(result['files'], 0)
            self.assertEqual(protected.read_bytes(), b'outside')

    @unittest.skipUnless(os.name == 'nt', 'Windows junction boundary')
    def test_real_junction_is_skipped_and_top_level_junction_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix='ddm-junction-target-') as external:
            outside = Path(external)
            protected = outside / 'a.png'
            protected.write_bytes(b'outside')
            folder = self.root / 'cache/emoticons'
            folder.mkdir(parents=True)
            link = folder / 'linked'
            subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(outside)],
                           check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                self.assertEqual(cache_cleanup.clear(self.root, {'emoticons'})['files'], 0)
                self.assertEqual(protected.read_bytes(), b'outside')
            finally:
                link.rmdir()
            link = self.root / 'cache/banners'
            subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(outside)],
                           check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                with self.assertRaises(ValueError):
                    cache_cleanup.clear(self.root, {'banners'})
                self.assertEqual(protected.read_bytes(), b'outside')
            finally:
                link.rmdir()

    def test_only_historical_known_logs_are_eligible_and_busy_logs_are_skipped(self):
        old = self.file('logs/ddm-2000-01-01.log', old=True)
        busy = self.file('logs/ddm-2000-01-02.log', old=True)
        dead = self.file('logs/native-crash-2000000000-abcd.dmp', old=True)
        current = self.file('logs/ddm-' + time.strftime('%Y-%m-%d') + '.log', old=True)
        active = self.file(f'logs/qt-lifecycle-{os.getpid()}.jsonl.1', old=True)
        fixed = self.file('logs/douyu-playback.jsonl', old=True)
        crash = self.file('logs/ddm-crash.log', old=True)
        unknown = self.file('logs/user-document.log', old=True)
        self.assertEqual(cache_cleanup.usage(self.root)['logs']['files'], 3)
        with busy.open('ab'):
            result = cache_cleanup.clear(self.root, {'logs'})
        self.assertEqual(result['files'], 2)
        self.assertEqual(result['skipped'], 1)
        self.assertFalse(old.exists())
        self.assertFalse(dead.exists())
        self.assertTrue(all(p.exists() for p in (busy, current, active, fixed, crash, unknown)))

    def test_http_clear_uses_profile_api_and_token_receipt_preserves_new_request(self):
        from ddm import web_login
        class Profile(QObject):
            clearHttpCacheCompleted = Signal()
            def __init__(self):
                super().__init__()
                self.clearHttpCache = Mock()
        profile = Profile()
        cookies = self.file('cache/web-login/Cookies', b'cookie-fixture')
        first = cache_cleanup.request_http_clear(self.root)
        with patch.object(web_login, '_profile', profile):
            self.assertIs(web_login._shared_profile(), profile)
            profile.clearHttpCache.assert_called_once()
            self.assertEqual(cache_cleanup.http_request(self.root), first)
            second = cache_cleanup.request_http_clear(self.root)
            profile.clearHttpCacheCompleted.emit()
            self.assertEqual(cache_cleanup.http_request(self.root), second)
            profile._ddm_active_logins = 1
            web_login._shared_profile()
            self.assertEqual(profile.clearHttpCache.call_count, 1)
            profile._ddm_active_logins = 0
            web_login._shared_profile()
            profile.clearHttpCacheCompleted.emit()
            self.assertEqual(cache_cleanup.http_request(self.root), '')
        self.assertEqual(cookies.read_bytes(), b'cookie-fixture')

    def settle(self, panel):
        deadline = time.monotonic() + 5
        while panel._task is not None and time.monotonic() < deadline:
            self.app.processEvents()
            QTest.qWait(10)
        self.assertIsNone(panel._task)

    def test_login_navigation_waits_for_http_completion_and_close_does_not_release_twice(self):
        from PySide6.QtWidgets import QWidget
        from ddm import web_login
        class Store(QObject):
            cookieAdded = Signal(object)
            loadAllCookies = Mock()
        class Profile(QObject):
            clearHttpCacheCompleted = Signal()
            def __init__(self):
                super().__init__()
                self.clearHttpCache = Mock()
                self.cookieStore = Mock(return_value=Store(self))
        class View(QWidget):
            loadFinished = Signal(bool)
            def __init__(self, parent):
                super().__init__(parent)
                self.setPage = Mock()
                self.load = Mock()
        profile = Profile()
        cache_cleanup.request_http_clear(self.root)
        with (patch.object(web_login, '_profile', profile), patch.object(web_login, 'QWebEngineView', View),
              patch.object(web_login, '_NoPopupPage')):
            first = web_login.WebLoginWindow()
            second = web_login.WebLoginWindow()
            self.addCleanup(first.deleteLater)
            self.addCleanup(second.deleteLater)
            profile.cookieStore.assert_not_called()
            first.browser.load.assert_not_called()
            second.browser.load.assert_not_called()
            self.assertFalse(first.reload_button.isEnabled())
            profile.clearHttpCacheCompleted.emit()
            self.assertEqual(profile.cookieStore.call_count, 2)
            first.browser.load.assert_called_once()
            second.browser.load.assert_called_once()
            self.assertTrue(first.reload_button.isEnabled())
            self.assertEqual(profile._ddm_active_logins, 2)
            first.reject()
            first.reject()
            self.assertEqual(profile._ddm_active_logins, 1)
            second.reject()
            self.assertEqual(profile._ddm_active_logins, 0)

    def test_panel_selects_only_requested_categories_and_reports_deferred_http(self):
        from ddm.cache_cleanup_ui import ExtraCachePanel
        from ddm import theme
        self.file('cache/emoticons/a.png', b'a' * 100)
        cover = self.file('cache/covers/a.png', b'cover')
        log = self.file('logs/ddm-2000-01-01.log', old=True)
        self.file('cache/web-login/Cache/entry')
        panel = ExtraCachePanel(root=str(self.root))
        self.addCleanup(panel.deleteLater)
        self.addCleanup(panel.close)
        font_id = QFontDatabase.addApplicationFont(str(
            Path(__file__).resolve().parents[1] / 'ddm/assets/fonts/SourceHanSansSC-Regular.otf'))
        theme.configure_appearance({'appearance_font': QFontDatabase.applicationFontFamilies(font_id)[0],
                                    'appearance_font_size': 20})
        theme.apply('dark')
        panel.resize(500, 1200)
        panel.show()
        self.settle(panel)
        self.assertEqual(panel.selected(), set())
        self.assertFalse(panel.checks['logs'].isChecked())
        self.assertEqual(panel.values['emoticons']['files'], 1)
        self.assertEqual(set(panel.pie.values), set(cache_cleanup.KINDS))
        self.assertEqual(panel.pie.values['logs']['files'], 1)
        QTest.mouseClick(panel.pie, Qt.LeftButton, pos=QPoint(107, 32))
        self.assertEqual(panel.selected(), {'emoticons'})
        panel.checks['web-login'].setChecked(True)
        panel.selected_button.click()
        self.settle(panel)
        self.assertEqual(panel.values['emoticons']['files'], 0)
        self.assertIn('已安排', panel.details['web-login'].text())
        self.assertTrue(cover.exists())
        self.assertTrue(log.exists())
        self.assertIn('下次打开网页登录', panel.status.text())
        output = os.environ.get('DDM_EXTRA_CACHE_PREVIEW')
        if output:
            image = QImage(panel.size(), QImage.Format_ARGB32_Premultiplied)
            image.fill(theme.qcolor(theme.BG))
            panel.render(image)
            self.assertTrue(image.save(output))
        panel.close()
        theme.configure_appearance({'appearance_font': '', 'appearance_font_size': 13})
        theme.apply('dark')

    def test_closing_panel_during_statistics_is_safe_and_data_page_preserves_old_panel(self):
        from PySide6.QtCore import QCoreApplication, QEvent
        from ddm.data_settings import DataSettingsPage
        from ddm.cache_settings import ImageCachePanel
        page = DataSettingsPage()
        self.assertIsInstance(page.image_cache, ImageCachePanel)
        self.assertEqual(page.extra_cache.root, str(self.root))
        page.extra_cache.refresh()
        page.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertTrue(QThreadPool.globalInstance().waitForDone(5000))
        self.app.processEvents()


if __name__ == '__main__':
    unittest.main()
