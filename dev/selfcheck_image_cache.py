"""Isolated image replacement, shared references, clearing and interactive pie checks."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, QThreadPool, Qt
from PySide6.QtGui import QFont, QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from ddm import config, image_cache, images, theme
from ddm.cache_settings import ImageCachePanel


class CacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='ddm-image-cache-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.patch = patch.object(images, 'REPO', str(self.root))
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.network = patch.object(images.requests, 'get', side_effect=AssertionError('Unexpected network'))
        self.network.start()
        self.addCleanup(self.network.stop)

    def file(self, name, data=b'fixture'):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def image(self, url, kind='avatars', color=Qt.red):
        path = Path(images._cache_path(url, kind))
        path.parent.mkdir(parents=True, exist_ok=True)
        picture = QPixmap(24, 24)
        picture.fill(color)
        self.assertTrue(picture.save(str(path), 'PNG'))
        return path

    def commit(self, room, url, kind='avatars'):
        return (images.remember_room_avatar(room, url) if kind == 'avatars'
                else images.remember_room_cover(room, url))

    def test_new_avatar_removes_old_and_keeps_cover_and_last_snapshot(self):
        old = self.image('old')
        self.assertTrue(self.commit('bilibili:1', 'old'))
        cover = self.image('cover', 'covers')
        self.assertTrue(self.commit('bilibili:1', 'cover', 'covers'))
        new = self.image('new', color=Qt.blue)
        self.assertTrue(self.commit('bilibili:1', 'new'))
        self.assertFalse(old.exists())
        self.assertTrue(cover.exists())
        self.assertEqual(Path(images.room_avatar_path('bilibili:1')).read_bytes(), new.read_bytes())
        self.assertIsNotNone(images.load_room_cover('bilibili:1'))

    def test_failed_or_empty_download_keeps_old_and_unknown_history(self):
        old = self.image('old')
        unknown = self.image('unknown-history')
        self.assertTrue(self.commit('1', 'old'))
        for url in ('failed', ''):
            worker = images.AvatarLoader({'1': url})
            delivered = []
            worker.loaded.connect(lambda *_args: delivered.append(True))
            worker.run()
            self.assertEqual(delivered, [])
        self.assertTrue(old.exists())
        self.assertTrue(unknown.exists())
        self.assertIsNotNone(images.load_room_avatar('1'))

    def test_shared_image_removed_only_after_last_room_replaces_it(self):
        shared = self.image('shared')
        self.assertTrue(self.commit('1', 'shared'))
        self.assertTrue(self.commit('huya:1', 'shared'))
        self.image('one')
        self.assertTrue(self.commit('1', 'one'))
        self.assertTrue(shared.exists())
        self.image('two')
        self.assertTrue(self.commit('huya:1', 'two'))
        self.assertFalse(shared.exists())
        self.assertIsNotNone(images.load_room_avatar('huya:1'))

    def test_invalid_download_does_not_replace_or_delete_usable_image(self):
        old = self.image('old')
        self.commit('1', 'old')
        before = Path(images.room_avatar_path('1')).read_bytes()
        with patch.object(images.requests, 'get', return_value=SimpleNamespace(
                status_code=200, content=b'not an image')):
            images.AvatarLoader({'1': 'broken-image'}).run()
        self.assertTrue(old.exists())
        self.assertFalse(Path(images._cache_path('broken-image')).exists())
        self.assertEqual(Path(images.room_avatar_path('1')).read_bytes(), before)

    def test_same_source_is_not_deleted(self):
        source = self.image('same')
        for _ in range(3):
            self.assertTrue(self.commit('1', 'same'))
        self.assertTrue(source.exists())

    def test_new_cover_records_actual_cdn_fallback_path(self):
        url = 'https://i0.hdslb.com/cover.jpg'
        old = self.image(url, 'covers')
        self.assertTrue(self.commit('1', url, 'covers'))
        next_url = 'https://i0.hdslb.com/next.jpg'
        new = self.image(images._cdn_url(next_url, images.CDN_SIZE), 'covers')
        self.assertTrue(self.commit('1', next_url, 'covers'))
        self.assertFalse(old.exists())
        self.assertEqual(Path(images.room_cover_path('1')).read_bytes(), new.read_bytes())

    def test_late_result_cannot_overwrite_newer_room_image(self):
        first, second = images.AvatarLoader({'1': 'first'}), images.AvatarLoader({'1': 'second'})
        for worker in (first, second):
            image_cache.begin(self.root, 'avatars', {'1': images._image_candidates(worker.items['1'], 'avatars')}, worker._stamp)
            self.image(worker.items['1'], color=Qt.blue if worker is second else Qt.red)
        self.assertTrue(images.remember_room_avatar('1', 'second', stamp=second._stamp))
        self.assertFalse(images.remember_room_avatar('1', 'first', stamp=first._stamp))
        self.assertEqual(Path(images.room_avatar_path('1')).read_bytes(), Path(images._cache_path('second')).read_bytes())
        old_path = Path(images._cache_path('first'))
        old_path.unlink()
        self.assertFalse(image_cache.store(self.root, 'avatars', old_path, b'late download',
                                           first._stamp, room='1'))
        self.assertFalse(old_path.exists())

    def test_save_failure_preserves_previous_snapshot_and_source(self):
        old = self.image('old')
        self.commit('1', 'old')
        original = Path(images.room_avatar_path('1')).read_bytes()
        self.image('new')
        with patch.object(image_cache.os, 'replace', side_effect=OSError('disk full')):
            self.assertFalse(self.commit('1', 'new'))
        self.assertEqual(Path(images.room_avatar_path('1')).read_bytes(), original)
        self.assertTrue(old.exists())

    def test_loader_commits_local_image_and_cleans_old(self):
        old = self.image('old')
        self.commit('1', 'old')
        self.image('new')
        worker = images.AvatarLoader({'1': 'new'})
        delivered = []
        worker.loaded.connect(lambda room, _pixmap: delivered.append(room))
        worker.run()
        self.assertEqual(delivered, ['1'])
        self.assertFalse(old.exists())

    def test_selective_clear_reports_actual_bytes_and_preserves_personal_files(self):
        avatar = self.file('cache/avatars/a.png', b'aaa')
        self.file('cache/avatars/room/1.png', b'aa')
        protected = [self.file(name) for name in ('cache/covers/c.png', 'cache/banners/b.png',
            'cache/emoticons/e.png', 'utils/config.json', 'utils/accounts/bilibili.bin',
            'utils/skins/custom.png', 'plugins_user/.updates/p/state.json', 'recordings/video.mp4',
            'recordings/.ddm-parts/recover.mkv', 'cache/avatars/unrelated.txt')]
        self.assertEqual(image_cache.usage(self.root)['avatars'], {'bytes': 5, 'files': 2})
        self.assertEqual(image_cache.clear(self.root, ['avatars']), {'bytes': 5, 'files': 2, 'skipped': 0})
        self.assertFalse(avatar.exists())
        self.assertTrue(all(path.exists() for path in protected))
        with self.assertRaises(ValueError):
            image_cache.clear(self.root, ['../utils'])
        with self.assertRaises(ValueError):
            image_cache.store(self.root, 'avatars', self.root / 'cache/avatars/../../../outside.png',
                              b'outside', image_cache.ticket())

    def test_manual_clear_invalidates_inflight_writes_across_processes(self):
        worker = images.AvatarLoader({'1': 'old-request'})
        path = self.image('old-request')
        code = 'from ddm.image_cache import clear; import sys; clear(sys.argv[1], ["avatars"])'
        subprocess.run([sys.executable, '-c', code, str(self.root)], cwd=ROOT, check=True)
        self.assertFalse(path.exists())
        self.assertFalse(image_cache.store(self.root, 'avatars', path, b'late', worker._stamp))
        worker.run()
        self.assertFalse(path.exists())
        self.assertTrue(image_cache.store(self.root, 'avatars', path, b'new-request', image_cache.ticket()))

    def test_cached_cover_preparation_cannot_write_back_after_clear(self):
        self.image('cover', 'covers')
        self.commit('1', 'cover', 'covers')
        cached = images.load_room_cover('1')
        worker = images.CachedCoverLoader(['1'])
        image_cache.clear(self.root, ['covers'])
        prepared = QPixmap(24, 24)
        prepared.fill(Qt.blue)
        with patch.object(images, 'load_room_cover', return_value=cached), \
                patch('ddm.cover_focus.prepare_cover', return_value=prepared):
            worker.run()
        self.assertEqual(image_cache.usage(self.root)['covers']['files'], 0)

    def test_in_use_file_is_skipped_and_retained(self):
        path = self.file('cache/covers/a.png')
        original = Path.unlink
        def unlink(candidate, *args, **kwargs):
            if candidate == path:
                raise PermissionError('in use')
            return original(candidate, *args, **kwargs)
        with patch.object(Path, 'unlink', unlink):
            result = image_cache.clear(self.root, ['covers'])
        self.assertEqual(result, {'bytes': 0, 'files': 0, 'skipped': 1})
        self.assertTrue(path.exists())

    def test_cache_link_does_not_delete_external_files(self):
        outside = self.root / 'outside'
        outside.mkdir()
        keep = outside / 'keep.png'
        keep.write_bytes(b'keep')
        (self.root / 'cache').mkdir()
        link = self.root / 'cache/avatars'
        with patch.object(Path, 'is_symlink', autospec=True, side_effect=lambda path: path == link):
            with self.assertRaises(ValueError):
                image_cache.clear(self.root, ['avatars'])
        self.assertEqual(keep.read_bytes(), b'keep')

    def settle(self, panel):
        deadline = time.monotonic() + 5
        while panel._task is not None and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.005)
        self.app.processEvents()
        self.assertIsNone(panel._task, 'Background cache task did not finish')

    def test_pie_selection_clears_only_clicked_category(self):
        self.file('cache/avatars/a.png', b'a' * 100)
        cover = self.file('cache/covers/c.png', b'c' * 300)
        panel = ImageCachePanel(root=str(self.root))
        panel.show()
        self.addCleanup(panel.close)
        self.settle(panel)
        self.assertFalse(panel.selected_button.isEnabled())
        self.assertIn('25.0%', panel.details['avatars'].text())
        self.assertIn('75.0%', panel.details['covers'].text())
        QTest.mouseClick(panel.pie, Qt.LeftButton, pos=QPoint(158, 43))
        self.assertEqual(panel.selected(), {'avatars'})
        self.assertTrue(panel.selected_button.isEnabled())
        QTest.mouseClick(panel.selected_button, Qt.LeftButton)
        self.settle(panel)
        self.assertTrue(cover.exists())
        self.assertEqual(panel.values['avatars']['files'], 0)
        self.assertIn('100 B', panel.status.text())
        self.assertEqual(panel.pie.segment_at(QPointF(107, 30)), 'covers')
        QTest.mouseClick(panel.all_button, Qt.LeftButton)
        self.settle(panel)
        self.assertFalse(cover.exists())
        self.assertFalse(panel.all_button.isEnabled())

    def test_empty_single_category_and_theme_switch(self):
        panel = ImageCachePanel(root=str(self.root))
        panel.show()
        self.addCleanup(panel.close)
        self.settle(panel)
        self.assertIsNone(panel.pie.segment_at(QPointF(107, 30)))
        self.assertFalse(panel.all_button.isEnabled())
        self.file('cache/avatars/zero.png', b'')
        panel.refresh()
        self.settle(panel)
        self.assertTrue(panel.all_button.isEnabled())
        for mode in ('light', 'dark'):
            theme.apply(mode)
            panel.grab()
        QTest.mouseClick(panel.all_button, Qt.LeftButton)
        self.settle(panel)
        self.assertEqual(panel.values['avatars']['files'], 0)

    def test_chart_and_legend_adapt_to_both_themes_without_losing_selection(self):
        self.file('cache/avatars/a.png', b'a' * 100)
        self.file('cache/covers/c.png', b'c' * 300)
        panel = ImageCachePanel(root=str(self.root))
        panel.show()
        self.addCleanup(panel.close)
        self.settle(panel)
        panel.checks['covers'].setChecked(True)
        dark_pixel = None
        for mode, expected in (('dark', '#7ab8a2'), ('light', '#39846f'), ('dark', '#7ab8a2')):
            theme.apply(mode)
            self.app.processEvents()
            picture = panel.pie.grab().toImage()
            self.assertEqual(picture.pixelColor(107, 182).name(), expected)
            self.assertIn(expected, panel.dots['covers'].styleSheet())
            self.assertEqual(panel.selected(), {'covers'})
            self.assertTrue(panel.selected_button.isEnabled())
            if mode == 'dark':
                if dark_pixel is not None:
                    self.assertEqual(picture.pixelColor(107, 182), dark_pixel)
                dark_pixel = picture.pixelColor(107, 182)

    def test_settings_data_root_is_used_and_closing_during_task_is_safe(self):
        from ddm.data_settings import DataSettingsPage
        with patch.object(config, 'DATA_ROOT', str(self.root)):
            page = DataSettingsPage()
        self.assertEqual(page.image_cache.root, str(self.root))
        page.image_cache.refresh()
        page.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        QThreadPool.globalInstance().waitForDone(5000)
        self.app.processEvents()


def snapshots(directory):
    directory.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    family = theme.danmaku_font_family()
    app.setFont(QFont(family, 10))
    theme.FONT_FAMILY = f'"{family}"'
    with tempfile.TemporaryDirectory(prefix='ddm-cache-preview-') as root:
        for kind, size in (('avatars', 2300000), ('covers', 6700000)):
            path = Path(root) / 'cache' / kind / 'preview.png'
            path.parent.mkdir(parents=True)
            path.write_bytes(b'0' * size)
        with patch.object(config, 'DATA_ROOT', root):
            from ddm.data_settings import DataSettingsPage
            page = DataSettingsPage()
        page.resize(640, 710)
        page.show()
        deadline = time.monotonic() + 5
        while page.image_cache._task is not None and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        page.image_cache.checks['covers'].setChecked(True)
        for mode in ('dark', 'light'):
            theme.apply(mode)
            app.setStyleSheet(theme.qss())
            page.setStyleSheet(f'QWidget#SettingsPage {{ background: {theme.BG}; }}')
            app.processEvents()
            page.grab().save(str(directory / f'image-cache-{mode}.png'))
            page.image_cache.grab().save(str(directory / f'image-cache-panel-{mode}.png'))
        page.close()
        app.processEvents()


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--snapshots':
        snapshots(Path(sys.argv[2]))
    else:
        unittest.main()
