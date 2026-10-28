"""Offline checks for per-tile D shortcut, compact notices and startup live baseline."""
from contextlib import ExitStack
import os
import json
from pathlib import Path
import runpy
import sys
import tempfile
from unittest.mock import Mock, patch
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
runpy.run_path(str(ROOT / 'main.py'), run_name='bootstrap')
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QContextMenuEvent, QKeySequence, QPixmap, QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu, QPushButton, QWidget, QLineEdit
from ddm import motion, theme
from ddm.app import MainWindow
from ddm.dialogs import ShortcutSettingsPage
from ddm.online_ui import show_result, UpdateNotice


class MainNoticesTests(unittest.TestCase):
    def focused_cover(self, boxes, width=1000, height=600):
        from ddm import cover_focus
        cover = QPixmap(width, height)
        cover.fill(QColor('green'))
        with patch.object(cover_focus, '_detect_faces', return_value=boxes):
            return cover_focus.prepare_cover(cover)

    def test_cover_face_cache_persists_positive_and_negative_results(self):
        from ddm import cover_focus, images
        for boxes in ([], [[0.7, 0.05, 0.15, 0.2]]):
            with self.subTest(boxes=boxes), tempfile.TemporaryDirectory() as directory, \
                    patch.object(images, 'REPO', directory):
                url = 'https://example.invalid/cover.jpg'
                path = Path(images._cache_path(url, 'covers'))
                path.parent.mkdir(parents=True)
                original = QPixmap(400, 240)
                original.fill(QColor('red'))
                original.save(str(path))
                with patch.object(cover_focus, '_detect_faces', return_value=boxes) as detect:
                    prepared = images.load_cover(url)
                    self.assertEqual(cover_focus.faces_for(prepared), boxes)
                    images.remember_room_cover('123', url)
                    loader = images.CachedCoverLoader(['123'])
                    seen = []
                    loader.loaded.connect(lambda _, cover: seen.append(cover))
                    loader.run()
                    self.assertEqual(cover_focus.faces_for(seen[0]), boxes)
                    images.load_cover(url)
                    detect.assert_called_once()

    def test_cover_detector_failure_is_retryable(self):
        from ddm import cover_focus
        cover = QPixmap(400, 240)
        with patch.object(cover_focus, '_detect_faces', return_value=None) as detect:
            self.assertIs(cover_focus.prepare_cover(cover), cover)
            self.assertIsNone(cover_focus.faces_for(cover))
            cover_focus.prepare_cover(cover)
            self.assertEqual(detect.call_count, 2)

    def test_cached_cover_detection_runs_on_worker_thread(self):
        import threading
        from ddm import cover_focus, images
        with tempfile.TemporaryDirectory() as directory, patch.object(images, 'REPO', directory):
            path = Path(images.room_cover_path('123'))
            path.parent.mkdir(parents=True)
            cover = QPixmap(400, 240)
            cover.fill(QColor('black'))
            cover.save(str(path))
            called_on = []
            def detect(_):
                called_on.append(threading.get_ident())
                return []
            with patch.object(cover_focus, '_detect_faces', side_effect=detect):
                loader = images.CachedCoverLoader(['123'])
                loader.start()
                self.assertTrue(loader.wait(5000))
            self.assertEqual(len(called_on), 1)
            self.assertNotEqual(called_on[0], threading.get_ident())
            self.assertEqual(cover_focus.faces_for(images.load_room_cover('123')), [])

    def test_cover_focus_keeps_top_face_and_banner_stays_centered(self):
        from ddm import cover_focus
        from PySide6.QtCore import QRectF
        cover = self.focused_cover([[0.75, 0.02, 0.12, 0.18]])
        with patch.object(cover_focus, '_detect_faces', side_effect=AssertionError('paint detection')):
            crop = cover_focus.source_rect(cover, 420, 120)
            self.assertTrue(crop.contains(QRectF(750, 12, 120, 108)))
            centered = cover_focus.source_rect(cover, 420, 120, focus=False)
            self.assertAlmostEqual(centered.center().y(), 300)
            self.assertLess(crop.top(), centered.top())

    def test_cover_focus_group_and_largest_face_selection(self):
        from ddm import cover_focus
        from PySide6.QtCore import QRectF
        cover = self.focused_cover([[0.5, 0.1, 0.1, 0.1], [0.7, 0.12, 0.1, 0.1]])
        crop = cover_focus.source_rect(cover, 420, 120)
        self.assertTrue(crop.contains(QRectF(500, 60, 300, 72)))
        cover = self.focused_cover([[0.4, 0.1, 0.1, 0.1], [0.6, 0.12, 0.1, 0.1]])
        crop = cover_focus.source_rect(cover, 60, 100)
        self.assertTrue(crop.contains(QRectF(400, 60, 300, 72)))
        cover = self.focused_cover([[0.1, 0.05, 0.2, 0.2], [0.7, 0.75, 0.1, 0.1]])
        crop = cover_focus.source_rect(cover, 420, 120)
        self.assertTrue(crop.contains(QRectF(100, 30, 200, 120)))

    def test_cover_focus_edges_thin_strips_and_no_face_fallback(self):
        from ddm import cover_focus
        for box in ([0., 0., 0.3, 0.5], [0.7, 0.5, 0.3, 0.5]):
            cover = self.focused_cover([box])
            for width, height in ((420, 48), (60, 100), (1920, 1080)):
                crop = cover_focus.source_rect(cover, width, height)
                self.assertGreaterEqual(crop.left(), 0)
                self.assertGreaterEqual(crop.top(), 0)
                self.assertLessEqual(crop.right(), cover.width() + 1e-8)
                self.assertLessEqual(crop.bottom(), cover.height() + 1e-8)
                self.assertAlmostEqual(crop.width() / crop.height(), width / height)
        cover = self.focused_cover([])
        crop = cover_focus.source_rect(cover, 420, 120)
        self.assertAlmostEqual(crop.center().x(), 500)
        self.assertAlmostEqual(crop.center().y(), 300)

    def test_cover_models_match_pinned_sources_and_load_offline(self):
        import hashlib
        from ddm import cover_focus
        assets = ROOT / 'ddm/assets'
        records = json.loads((assets / 'licenses/cover-focus-SOURCE.json').read_text())
        for record in records:
            self.assertEqual(hashlib.sha256((assets / record['file']).read_bytes()).hexdigest(),
                             record['sha256'])
        cover = QPixmap(412, 232)
        cover.fill(QColor('black'))
        self.assertEqual(cover_focus._detect_faces(cover.toImage()), [])

    def test_room_background_crops_the_center_and_clips_corners(self):
        from PySide6.QtCore import QRectF
        from PySide6.QtGui import QPainter
        from ddm.room_artwork import paint_room_background
        source = QPixmap(300, 100)
        source.fill(QColor('red'))
        painter = QPainter(source)
        painter.fillRect(100, 0, 100, 100, QColor('green'))
        painter.fillRect(200, 0, 100, 100, QColor('blue'))
        painter.end()
        target = QPixmap(60, 100)
        target.fill(Qt.transparent)
        painter = QPainter(target)
        paint_room_background(painter, QRectF(0, 0, 60, 100), source, 12)
        painter.end()
        image = target.toImage()
        self.assertEqual(image.pixelColor(0, 0).alpha(), 0)
        for x in (4, 30, 55):
            color = image.pixelColor(x, 50)
            self.assertGreater(color.green(), max(color.red(), color.blue()))

    def test_streamer_background_priority_and_platform_logo(self):
        self.addCleanup(theme.apply, theme.mode())
        from ddm import images
        from ddm.room_artwork import RoomArtwork
        from ddm.notification_center import NoticeEntry, NoticeRow
        from ddm.online_ui import ResultNotice
        from ddm.widgets import NavItem
        with tempfile.TemporaryDirectory() as directory, patch.object(images, 'REPO', directory):
            cover = QPixmap(160, 90)
            cover.fill(QColor('#20b060'))
            banner = QPixmap(300, 70)
            banner.fill(QColor('#e06020'))
            for rid in ('1001', 'huya:2', 'douyin:3', 'douyin:4'):
                path = Path(images.room_cover_path(rid))
                path.parent.mkdir(parents=True, exist_ok=True)
                cover.save(str(path))
                if rid == 'douyin:4':
                    continue
                path = Path(images.room_banner_path(rid))
                path.parent.mkdir(parents=True, exist_ok=True)
                banner.save(str(path))
            owner = QWidget()
            owner.resize(900, 700)
            self.addCleanup(owner.close)
            room = {'room_id': '1001', 'uname': '示例主播'}
            self.assertEqual(RoomArtwork([room]).source.toImage().pixelColor(0, 0).name(), '#e06020')
            self.assertEqual(RoomArtwork([{'room_id': 'huya:2'}]).source.toImage().pixelColor(0, 0).name(), '#20b060')
            self.assertEqual(RoomArtwork([{'room_id': 'douyin:3'}]).source.toImage().pixelColor(0, 0).name(), '#e06020')
            self.assertEqual(RoomArtwork([{'room_id': 'douyin:4'}]).source.toImage().pixelColor(0, 0).name(), '#20b060')
            self.assertIsNone(RoomArtwork([room, {'room_id': 'huya:2'}]).source)
            notice = ResultNotice(owner)
            notice.show_message('示例主播 开播了', [room], kind='live')
            row = NoticeRow(NoticeEntry('示例主播 开播了', 'live', '20:36', rooms=(room,)), owner)
            row.resize(360, row.sizeHint().height())
            row.show()
            item = NavItem(room, 0)
            self.addCleanup(item.close)
            item.set_card_mode(False)
            item.resize(300, 60)
            item.show()
            owner.show()
            self.app.processEvents()
            for card in (notice, row):
                self.assertIsNotNone(card.artwork.source)
                self.assertTrue(card.findChildren(QWidget, 'NoticePlatform'))
                for mode in ('light', 'dark'):
                    theme.apply(mode)
                    self.app.processEvents()
                    rendered = card.grab().toImage()
                    scale = rendered.devicePixelRatio()
                    pixel = rendered.pixelColor(round((card.width() - 8) * scale), round(card.height() / 2 * scale))
                    self.assertGreater(pixel.red(), pixel.green(), 'Banner must be painted, not the theme surface')
                    self.assertGreater(card.title.palette().color(card.title.foregroundRole()).lightness()
                                       if hasattr(card, 'title') else card.message.palette().color(card.message.foregroundRole()).lightness(), 200,
                                       (type(card).__name__, card.property('roomBackdrop'), mode))
            self.assertFalse(item.thumb.cover.isHidden())
            self.assertEqual(item.thumb._banner_source.toImage().pixelColor(0, 0).name(), '#e06020')
            item.set_compact(True)
            self.assertTrue(item.thumb.cover.isHidden(), 'The avatar rail must remain compact')

    def test_profile_banner_accepts_current_and_legacy_api_fields(self):
        from ddm import bili
        for data, expected in (
                ({'top_photo': 'bfs/space/old.png', 'top_photo_v2': {'l_img': 'https://i1.hdslb.com/new.png'}},
                 'https://i1.hdslb.com/new.png'),
                ({'top_photo': 'bfs/space/old.png'}, 'https://i0.hdslb.com/bfs/space/old.png'),
                ({'top_photo': '//i0.hdslb.com/old.png'}, 'https://i0.hdslb.com/old.png'),
                ({}, '')):
            with patch.object(bili, '_wbi_key', return_value='test'), \
                    patch.object(bili.requests, 'get', return_value=Mock(json=lambda: {'code': 0, 'data': data})):
                self.assertEqual(bili.profile_banner(12), expected)
        with patch.object(bili, '_wbi_key', return_value='test'), \
                patch.object(bili.requests, 'get', side_effect=bili.requests.Timeout):
            self.assertEqual(bili.profile_banner(12), '')

    def test_bili_default_headers_are_not_personal_banners(self):
        from ddm import bili
        legacy = 'bfs/space/cb1c3ef50e22b6096fde67febe863494caefebad.png'
        current = 'https://i1.hdslb.com/bfs/activity-plat/static/0977767b2e79d8ad0a36a731068a83d7/1sz3p8w2Sk.png'
        for data, expected in (
                ({'top_photo': legacy, 'top_photo_v2': {'sid': 1,
                    'l_img': 'https://i0.hdslb.com/' + legacy, 'l_200h_img': current}}, ''),
                ({'top_photo': '//i2.hdslb.com/' + legacy + '@960w.webp'}, ''),
                ({'top_photo': current + '@3840w_400h_1c_100q.avif?from=space'}, ''),
                ({'top_photo_v2': {'l_img': 'https://i0.hdslb.com/custom-old.png',
                    'l_200h_img': current}}, ''),
                ({'top_photo': legacy, 'top_photo_v2': {'sid': 0,
                    'l_200h_img': 'https://i1.hdslb.com/custom-current.png'}},
                 'https://i1.hdslb.com/custom-current.png')):
            with self.subTest(data=data), patch.object(bili, '_wbi_key', return_value='test'), \
                    patch.object(bili.requests, 'get', return_value=Mock(json=lambda: {'code': 0, 'data': data})):
                self.assertEqual(bili.profile_banner(1298779265), expected)

    def test_official_space_preset_ids_are_not_personal_banners(self):
        from ddm import bili
        # The official Fresh Space client excludes these IDs from custom headers.
        presets = (1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12, 13, 14, 15, 19)
        for sid in (*presets, 0, 103):
            photo = {'sid': sid, 'l_img': 'https://i1.hdslb.com/legacy.png',
                     'l_200h_img': 'https://i0.hdslb.com/arbitrary-header.png'}
            with self.subTest(sid=sid), patch.object(bili, '_wbi_key', return_value='test'), \
                    patch.object(bili.requests, 'get', return_value=Mock(json=lambda: {'code': 0, 'data': {
                        'top_photo_v2': photo}})):
                expected = '' if sid in presets else photo['l_200h_img']
                self.assertEqual(bili.profile_banner(193559518), expected)

    def test_all_space_header_categories_fall_back_without_rejecting_uploads(self):
        from ddm import bili
        catalog = json.loads((ROOT / 'ddm/assets/bilibili-space-presets.json').read_text(encoding='utf-8'))
        groups = catalog['categories']
        self.assertEqual({key: len(value) for key, value in groups.items()}, {'经典': 15, '季节': 29, '其他': 8})
        paths = [item['path'] for group in groups.values() for item in group]
        self.assertEqual(len(set(paths)), 52)
        for path in paths:
            for url in ('https://i0.hdslb.com' + path,
                        '//i2.hdslb.com' + path + '@3840w_400h_1c_100q.avif?from=space'):
                with self.subTest(url=url), patch.object(bili, '_wbi_key', return_value='test'), \
                        patch.object(bili.requests, 'get', return_value=Mock(json=lambda: {'code': 0, 'data': {
                            'top_photo_v2': {'sid': 103, 'l_200h_img': url}}})):
                    self.assertEqual(bili.profile_banner(12), '')
        for sid, filename in ((7759001, '66c1d9886a5f73a4f8e18f990cc1ce4e559e73ee.png'),
                              (36402681, '451d967c8418b4b88551bb905d63721006ab3bee.png')):
            url = 'https://i1.hdslb.com/bfs/space/' + filename
            with self.subTest(sid=sid), patch.object(bili, '_wbi_key', return_value='test'), \
                    patch.object(bili.requests, 'get', return_value=Mock(json=lambda: {'code': 0, 'data': {
                        'top_photo_v2': {'sid': sid, 'l_200h_img': url}}})):
                self.assertEqual(bili.profile_banner(12), url)

    def test_default_banner_invalidates_old_cache_and_updates_visible_notices(self):
        from ddm import images
        from ddm.room_artwork import RoomArtwork
        with tempfile.TemporaryDirectory() as directory, patch.object(images, 'REPO', directory):
            room = {'room_id': '1001', 'uid': 12, 'uname': '主播甲'}
            cover, banner = QPixmap(100, 50), QPixmap(100, 50)
            cover.fill(QColor('green'))
            banner.fill(QColor('red'))
            for path, pixmap in (
                    (Path(directory) / 'cache/banners/room/1001.png', banner),
                    (Path(directory) / 'cache/banners/custom-room/1001.png', banner),
                    (Path(directory) / 'cache/banners/personal-room/1001.png', banner),
                    (Path(images.room_cover_path('1001')), cover)):
                path.parent.mkdir(parents=True, exist_ok=True)
                pixmap.save(str(path))
            self.assertIsNone(RoomArtwork([room]).banner, 'The old unfiltered banner cache must be ignored')
            target = Path(images.room_banner_path('1001'))
            target.parent.mkdir(parents=True, exist_ok=True)
            banner.save(str(target))
            window = self.window([room])
            window._show_notice('主播甲开播了', rooms=[room], kind='live')
            notice = window._result_notice
            center = window.sidebar.notification_button.center
            entry = center.entries[-1]
            center._add_row(entry)
            row = center.rows[entry]
            self.assertIsNotNone(notice.artwork.banner)
            loader = images.AvatarLoader({'1001': room}, subdir='banners')
            loader.loaded.connect(window._on_room_banner)
            with patch.object(images.bili, '_wbi_key', return_value='test'), \
                    patch.object(images.bili.requests, 'get', return_value=Mock(json=lambda: {'code': 0, 'data': {
                        'top_photo': 'bfs/space/c919a9818172a8297f8b0597722f96504a1e1d88.png',
                        'top_photo_v2': {'sid': 11,
                            'l_200h_img': 'https://i0.hdslb.com/bfs/activity-plat/static/0977767b2e79d8ad0a36a731068a83d7/UIAMgvvo2L.png'}}})), \
                    patch.object(images, 'load_pixmap') as download:
                loader.run()
            download.assert_not_called()
            self.assertFalse(target.exists())
            self.assertIsNone(notice.artwork.banner)
            self.assertIsNone(row.artwork.banner)
            self.assertIsNotNone(row.artwork.source)
            self.assertEqual(notice.artwork.source.toImage().pixelColor(0, 0).name(), '#008000')
            self.assertIsNone(window.sidebar._items[0].thumb._banner_source)

    def test_streamer_background_failure_and_late_updates(self):
        from ddm import images
        from ddm.room_artwork import RoomArtwork
        with tempfile.TemporaryDirectory() as directory, patch.object(images, 'REPO', directory):
            room = {'room_id': '1001', 'uname': '主播甲', 'uid': 12}
            window = self.window([room])
            window._show_notice('主播甲 开播了', rooms=[{'room_id': '1001'}], kind='live')
            notice = window._result_notice
            center = window.sidebar.notification_button.center
            entry = center.entries[-1]
            center._add_row(entry)
            row = center.rows[entry]
            self.assertIsNone(notice.artwork.source)
            image = QPixmap(100, 40)
            image.fill(QColor('#e06020'))
            window._on_room_artwork('1001', image, 'banners')
            self.assertIsNotNone(notice.artwork.source)
            self.assertIsNotNone(row.artwork.source)
            window._on_room_cover('1001', image)
            self.assertIsNotNone(notice.artwork.banner)
            plain = RoomArtwork([])
            self.assertIsNone(plain.source)
            self.assertFalse(plain.set_image('1001', image, 'banners'))
            with patch.object(images.bili, 'profile_banner', return_value='https://example.test/banner') as profile, \
                    patch.object(images, 'load_pixmap', return_value=None):
                loader = images.AvatarLoader({'1001': room}, subdir='banners')
                loader.run()
                profile.assert_called_once_with(12)
                self.assertFalse(Path(images.room_banner_path('1001')).exists())
            with patch.object(images.bili, 'profile_banner', return_value='https://example.test/banner'), \
                    patch.object(images, 'load_pixmap', return_value=image):
                received = []
                loader = images.AvatarLoader({'1001': room}, subdir='banners')
                loader.loaded.connect(lambda rid, pixmap: received.append(rid))
                loader.run()
                self.assertEqual(received, ['1001'])
                self.assertIsNotNone(images.load_room_banner('1001'))

    def test_toasts_anchor_on_the_left_and_stack_down(self):
        window = self.window([])
        window.resize(1200, 800)
        update = UpdateNotice(window)
        update.show_offer({'version': 'test'}, persistent=True)
        show_result(window, '左侧通知', persistent=True)
        result = window._result_notice
        for side in ('left', 'top', 'left'):
            window.sidebar.set_side(side)
            for collapsed in (False, True):
                window.sidebar.set_collapsed(collapsed, animate=False)
                self.app.processEvents()
                for card in (update, result):
                    expected = 16
                    expected = max(0, min(expected, window.width() - card.width() - 16))
                    self.assertEqual(card.x(), window.mapToGlobal(QPoint(expected, 0)).x())
                self.assertGreater(result.y(), update.geometry().bottom())

    def test_notice_history_collects_results_and_update_once(self):
        window = self.window([{'room_id': '1001', 'uname': '主播甲'}])
        center = window.sidebar.notification_button.center
        window._show_notice('主播甲开播了', rooms=[{'room_id': '1001'}], kind='live')
        window._record_notice('录制已完成')
        self.assertEqual([entry.message for entry in center.entries], ['主播甲开播了', '录制已完成'])
        with patch.object(window, '_unread_app_update', return_value={'version': '0.5'}), \
                patch.object(window, '_unread_plugin_updates', return_value=[]), \
                patch.object(window, 'open_settings') as settings:
            window._show_update_notice()
            window._show_update_notice()
            self.assertEqual(len(center.entries), 3)
            self.assertEqual(center.entries[-1].message, '软件有新版 v0.5')
            center.entries[-1].callback()
            settings.assert_called_once_with('updates')

    def test_single_line_notice_keeps_heading_message_and_action_visible(self):
        owner = QWidget()
        owner.resize(1000, 700)
        owner.show()
        self.addCleanup(owner.close)
        from ddm.online_ui import ResultNotice
        notice = ResultNotice(owner)
        notice.title.setWordWrap(False)
        notice.show_message('已保存录制：example.mp4', on_click=Mock())
        self.assertEqual(notice.text_column.layout().geometry().width(), notice.text_column.width())
        self.app.processEvents()
        self.assertGreaterEqual(notice.category.height(), notice.category.fontMetrics().height())
        self.assertGreaterEqual(notice.title.height(), notice.title.fontMetrics().height())
        self.assertGreater(notice.action.y(), notice.text_column.geometry().bottom())
        self.assertGreaterEqual(notice.height(), notice.layout().totalSizeHint().height())
    def test_recording_file_notices_shorten_paths_and_reflow_on_resize(self):
        room = {'room_id': '1001', 'uname': '主播甲'}
        window = self.window([room])
        filename = '主播甲_' + '很长的录像文件名_' * 18 + '20261020_120000_part002.mp4'
        path = str(Path(tempfile.gettempdir()) / ('深层目录' * 25) / filename)
        for prefix in ('已保存录制', '已保存即时回放', '正在导出录制', '正在导出即时回放'):
            window.recorder._say(prefix + '：' + path, room)
            notice = window._result_notice
            self.assertEqual(notice._file_path, path)
            entry = window.sidebar.notification_button.center.entries[-1]
            self.assertIn(path, entry.message)
            with patch('ddm.notification_center.reveal_file') as reveal:
                if prefix.startswith('正在导出'):
                    self.assertIsNone(entry.callback)
                else:
                    entry.callback()
                    reveal.assert_called_once_with(path)
            self.assertIn('1001', notice._avatars)
            self.assertNotIn(str(Path(path).parent), notice.title.text())
            self.assertIn('…', notice.title.text())
            self.assertTrue(notice.title.text().endswith('.mp4'))
            self.assertIn(path, notice.toolTip())
            self.assertFalse(notice.title.wordWrap())
            self.assertGreaterEqual(notice.category.height(), notice.category.fontMetrics().height())
            self.assertGreaterEqual(notice.title.height(), notice.title.fontMetrics().height())
            self.assertEqual(notice.action.text(), '正在导出…' if prefix.startswith('正在导出') else '打开文件位置')
            self.assertGreaterEqual(notice.height(), 76)
            for width in (320, 1000):
                window.resize(width, 700)
                self.app.processEvents()
                self.assertLessEqual(notice.width(), min(480, window.width() - 32))
                self.assertGreaterEqual(notice.height(), 76)
                self.assertLessEqual(notice.title.fontMetrics().horizontalAdvance(notice.title.text()),
                                     notice.title.width())
            notice.dismiss(animate=False)
        window.recorder._say('已保存录制：' + str(Path(tempfile.gettempdir()) / 'short.mp4'), room)
        self.assertEqual(window._result_notice.title.text(), '已保存录制：short.mp4')
        window.recorder._say('导出失败；原始分段仍保留在 .ddm-parts：错误目录', room)
        self.assertEqual(window._result_notice._file_path, '')
        self.assertIn('错误目录', window._result_notice.title.text())

    def test_recording_status_has_no_unrelated_browser_action(self):
        room = {'room_id': '1001', 'uname': '主播甲'}
        window = self.window([room])
        with patch.object(window, '_open_room_browser') as browser:
            for message in ('主播甲 开始录制', '主播甲 没有可导出的录制分段'):
                window.recorder._say(message, room)
                notice = window._result_notice
                self.assertTrue(notice.action.isHidden())
                self.assertIsNone(notice._on_click)
                self.assertIsNone(window.sidebar.notification_button.center.entries[-1].callback)
                QTest.mouseClick(notice.title, Qt.LeftButton)
            browser.assert_not_called()

    def test_export_updates_one_card_and_history_entry_per_file(self):
        room = {'room_id': '1001', 'uname': '主播甲'}
        window = self.window([room])
        center = window.sidebar.notification_button.center
        cards = []
        for label, path in (('录制', '/synthetic/record.mp4'), ('即时回放', '/synthetic/replay.mp4')):
            window.recorder._say('正在导出' + label + '：' + path, room)
            card = window._result_notice
            cards.append(card)
            self.assertFalse(card.action.isEnabled())
            self.assertFalse(card.timer.isActive(), 'Export card must survive long exports')
        entries = list(center.entries)
        center.show()
        self.app.processEvents()
        for index, (label, path) in enumerate((('录制', '/synthetic/record.mp4'), ('即时回放', '/synthetic/replay.mp4'))):
            window.recorder._say('已保存' + label + '：' + path, room)
            self.assertIs(window._result_notice, cards[index])
            self.assertIs(center.entries[index], entries[index])
            self.assertEqual(cards[index].category.text(), '已完成')
            self.assertTrue(cards[index].action.isEnabled())
            self.assertEqual(cards[index].action.text(), '打开文件位置')
            self.assertTrue(cards[index].timer.isActive())
            self.assertEqual(center.rows[entries[index]].message.text(), '已保存' + label + '：' + path)
        self.assertEqual(len(window._notices), 2)
        self.assertEqual(len(center.entries), 2)
        center.hide()

    def test_export_failure_updates_pending_card_and_dismissed_export_can_complete(self):
        room = {'room_id': '1001'}
        window = self.window([room])
        path = Path('/synthetic/failed.mp4')
        window.recorder._say('正在导出录制：' + str(path), room)
        card = window._result_notice
        process = Mock(returncode=1)
        process.poll.return_value = 1
        window.recorder.exports.append((process, path, [], True))
        window.recorder._export_rooms[path] = room
        window.recorder._poll()
        self.assertIs(window._result_notice, card)
        self.assertEqual(card.category.text(), '导出失败')
        self.assertIn('原始分段保留', card.title.text())
        self.assertTrue(card.timer.isActive())
        card.dismiss(animate=False, handled=True)
        window.recorder._say('已保存录制：' + str(path), room)
        self.assertEqual(len(window._notices), 1)
        self.assertEqual(window._result_notice.category.text(), '已完成')
        self.assertEqual(len(window.sidebar.notification_button.center.entries), 1)

    def test_recording_file_click_and_context_copy_use_full_path(self):
        window = self.window([{'room_id': '1001', 'uname': '主播甲'}])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '中文 name, & test.mp4'
            path.touch()
            window.recorder._say('已保存录制：' + str(path), {'room_id': '1001'})
            notice = window._result_notice
            with patch('ddm.online_ui.subprocess.Popen') as reveal, \
                    patch('ddm.online_ui.sys.platform', 'win32'), \
                    patch.object(window, '_open_room_browser') as browser:
                QTest.mouseClick(notice.title, Qt.LeftButton)
                reveal.assert_called_once_with(['explorer.exe', '/select,', str(path)])
                browser.assert_not_called()
                self.assertFalse(notice.isVisible())
            window.recorder._say('已保存录制：' + str(path), {'room_id': '1001'})
            notice = window._result_notice
            original_clipboard = self.app.clipboard().text()
            self.addCleanup(self.app.clipboard().setText, original_clipboard)
            def select_copy(menu, point):
                actions = menu.actions()
                self.assertEqual([action.text() for action in actions], ['打开文件位置', '复制完整路径'])
                actions[1].trigger()
            menu = QMenu(notice)
            with patch('ddm.online_ui.QMenu', return_value=menu), \
                    patch.object(menu, 'exec', side_effect=lambda point: select_copy(menu, point)) as context:
                point = notice.rect().center()
                event = QContextMenuEvent(QContextMenuEvent.Mouse, point, notice.mapToGlobal(point))
                self.assertTrue(notice.isEnabled())
                self.assertEqual(notice.contextMenuPolicy(), Qt.DefaultContextMenu)
                self.assertEqual(notice._file_path, str(path))
                self.app.sendEvent(notice, event)
                context.assert_called_once()
            self.assertEqual(self.app.clipboard().text(), str(path))
            self.assertTrue(notice.isVisible())
            self.assertTrue(notice.timer.isActive())
            path.unlink()
            with patch('ddm.online_ui.QDesktopServices.openUrl', return_value=True) as folder:
                notice._open_file_location()
                self.assertEqual(Path(folder.call_args.args[0].toLocalFile()), path.parent)

    def test_room_notices_include_room_and_update_all_avatars(self):
        room = {'room_id': '1001', 'uname': '主播甲'}
        window = self.window([room])
        window.recorder._say('主播甲 开始录制', room)
        recording = window._result_notice
        self.assertIn('1001', recording._avatars)
        window._show_notice('房间提示', rooms=[room])
        sending = window._result_notice
        self.assertIn('1001', sending._avatars)
        with patch.object(recording, 'set_room_avatar') as first, \
                patch.object(sending, 'set_room_avatar') as second:
            pixmap = QPixmap(32, 32)
            pixmap.fill(QColor('#00a1d6'))
            window._on_room_avatar('1001', pixmap)
            first.assert_called_once_with('1001', pixmap)
            second.assert_called_once_with('1001', pixmap)

    def test_notification_settings_defaults_save_and_reset(self):
        from ddm.dialogs import SettingsDialog
        from ddm.config import DEFAULT_SETTINGS
        dialog = SettingsDialog(DEFAULT_SETTINGS, {}, preview=True)
        self.addCleanup(dialog.close)
        page = dialog.notification_page
        self.assertTrue(page.values()['notice_persist_updates'])
        self.assertTrue(page.values()['notice_persist_pinned_live'])
        self.assertFalse(page.values()['notice_persist_live'])
        page._checks['notice_persist_warning'].setChecked(True)
        page._checks['live_alert'].setChecked(False)
        self.assertTrue(dialog.settings()['notice_persist_warning'])
        self.assertFalse(dialog.settings()['live_alert'])
        page.reset()
        self.assertFalse(page.values()['notice_persist_warning'])
        self.assertTrue(page.values()['live_alert'])

    def test_notifications_stack_reflow_close_and_jump_independently(self):
        owner = QWidget()
        owner.resize(1000, 700)
        owner.show()
        self.addCleanup(owner.close)
        activated = Mock()
        update = UpdateNotice(owner)
        update.activated.connect(activated)
        update.show_offer({'version': 'test'}, persistent=True)
        show_result(owner, '持续提示', persistent=True, on_click=activated)
        first = owner._result_notice
        show_result(owner, '普通提示')
        second = owner._result_notice
        self.app.processEvents()
        self.assertEqual(len(owner._notices), 3)
        self.assertFalse(update.timer.isActive())
        self.assertFalse(first.timer.isActive())
        self.assertTrue(second.timer.isActive())
        self.assertGreater(first.y(), update.y() + update.height())
        self.assertGreater(second.y(), first.y() + first.height())
        before = second.y()
        first.findChild(QPushButton, 'NoticeClose').click()
        self.assertLess(second.y(), before)
        activated.assert_not_called()
        self.assertTrue(second.isVisible())
        QTest.mouseClick(update.title, Qt.LeftButton)
        activated.assert_called_once()
        self.assertEqual(len(owner._notices), 1)

    def test_pinned_live_policy_and_room_navigation(self):
        window = self.window([{'room_id': '1001', 'uname': '主播甲', 'live': False},
                              {'room_id': '1002', 'uname': '主播乙', 'live': False}])
        window.sidebar.apply_pins(['1001'])
        for tile in window.wall.tiles:
            tile.set_room(None)
        window.start_tile.reset_mock()
        with patch.object(window, '_open_room_browser') as browser:
            window._show_notice('甲开播了', rooms=[{'room_id': '1001'}], kind='live')
            notice = window._result_notice
            self.assertFalse(notice.timer.isActive())
            QTest.mouseClick(notice.title, Qt.LeftButton)
            browser.assert_not_called()
            self.assertIsNotNone(window._tile_of('1001'))
            window.start_tile.assert_called_once()
        window._show_notice('乙开播了', rooms=[{'room_id': '1002'}], kind='live')
        self.assertTrue(window._result_notice.timer.isActive())
        window.settings['notice_persist_warning'] = True
        window._show_notice('警告', kind='warning')
        self.assertFalse(window._result_notice.timer.isActive())

    def test_live_notice_dismisses_without_expanding_or_replacing_full_wall(self):
        window = self.window([{'room_id': str(index), 'live': False} for index in range(1, 5)])
        original = [dict(tile.room) for tile in window.wall.tiles]
        with patch.object(window.wall, 'add_room') as add, \
                patch.object(window, '_open_room_browser') as browser:
            window._show_notice('新主播开播了', rooms=[{'room_id': '999'}], kind='live')
            notice = window._result_notice
            QTest.mouseClick(notice.title, Qt.LeftButton)
            self.assertFalse(notice.isVisible())
            self.assertEqual([tile.room for tile in window.wall.tiles], original)
            add.assert_not_called()
            browser.assert_not_called()

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyleSheet(theme.qss())

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for method in ('start_tile', 'refresh_status', 'refresh_stats', 'refresh_account',
                       'sync_danmaku', 'load_avatars_for', 'load_room_avatars',
                       'load_cached_covers', 'load_cached_avatars', '_start_avatar_loader'):
            self.stack.enter_context(patch.object(MainWindow, method))
        self.stack.enter_context(patch.object(motion, 'enabled', return_value=False))
        self.stack.enter_context(patch('ddm.images.load_room_avatar', return_value=None))
        self.stack.enter_context(patch('ddm.images.load_cached_avatar', return_value=None))

    def window(self, rooms):
        window = MainWindow([dict(room) for room in rooms], [dict(room) for room in rooms],
                            layout_id='2x2', state={'plugins_enabled': []})
        window.resize(1000, 700)
        window.show()
        self.app.processEvents()
        self.addCleanup(window.close)
        return window

    def status(self, live, **values):
        return dict(live=live, viewers='', title='', uname='', face='', **values)

    def complete_startup(self, window):
        poller = Mock()
        window._poller = poller
        window._on_poller_finished(poller)
        self.assertTrue(window._startup_status_complete)

    def test_b_targets_one_tile_remaps_and_preserves_typing(self):
        window = self.window([{'room_id': '1001'}, {'room_id': '1001'}])
        first, second = window.wall.tiles[:2]
        cursor = self.stack.enter_context(patch.object(window, '_tile_under_cursor', return_value=second))
        self.assertEqual(window.shortcuts['video_danmaku'], 'B')
        QTest.keyClick(window, Qt.Key_B)
        self.assertTrue(second.danmaku_button.isChecked())
        self.assertFalse(first.danmaku_button.isChecked())
        self.assertTrue(window.current_state()['wall'][1]['video_danmaku_enabled'])
        QTest.keyClick(window, Qt.Key_B)
        self.assertFalse(second.danmaku_button.isChecked())
        page = ShortcutSettingsPage(window.shortcuts)
        page._edits['video_danmaku'].setKeySequence(QKeySequence('K'))
        window.shortcuts = page.values()
        QTest.keyClick(window, Qt.Key_B)
        self.assertFalse(second.danmaku_button.isChecked())
        QTest.keyClick(window, Qt.Key_K)
        self.assertTrue(second.danmaku_button.isChecked())
        page.reset()
        window.shortcuts = page.values()
        self.assertEqual(window.shortcuts['video_danmaku'], 'B')
        window.sidebar.search.clear()
        QTest.keyClick(window.sidebar.search, Qt.Key_B)
        self.assertEqual(window.sidebar.search.text(), 'b')
        self.assertTrue(second.danmaku_button.isChecked())
        for target in (None, window.wall.tiles[2]):
            cursor.return_value = target
            QTest.keyClick(window, Qt.Key_B)
        self.assertFalse(first.danmaku_button.isChecked())
        window.sync_danmaku.assert_called()

    def test_record_shortcut_routes_to_hovered_tile_and_preserves_typing(self):
        window = self.window([{'room_id': '1001'}, {'room_id': '1002'}])
        tile = window.wall.tiles[1]
        with patch.object(window, '_tile_under_cursor', return_value=tile) as cursor, \
                patch.object(window, '_toggle_recording') as toggle:
            self.assertEqual(window.shortcuts['record'], 'R')
            QTest.keyClick(window, Qt.Key_R)
            toggle.assert_called_once_with(tile)
            toggle.reset_mock()
            for target in (None, window.wall.tiles[2]):
                cursor.return_value = target
                QTest.keyClick(window, Qt.Key_R)
            toggle.assert_not_called()
            cursor.return_value = tile
            window.sidebar.search.clear()
            QTest.keyClick(window.sidebar.search, Qt.Key_R)
            self.assertEqual(window.sidebar.search.text(), 'r')
            toggle.assert_not_called()
            page = ShortcutSettingsPage(window.shortcuts)
            self.addCleanup(page.close)
            page._edits['record'].setKeySequence(QKeySequence('Ctrl+R'))
            window.shortcuts = page.values()
            self.assertEqual(window.current_state()['ui']['shortcuts']['record'], 'Ctrl+R')
            window._handle_shortcut('R')
            toggle.assert_not_called()
            window._handle_shortcut('Ctrl+R')
            toggle.assert_called_once_with(tile)
            page.reset()
            self.assertEqual(page.values()['record'], 'R')
        with patch.object(window, '_start_capture') as start:
            window._toggle_recording(tile)
            start.assert_called_once_with(tile, recording=True)
        with patch.dict(window.recorder.sessions, {tile: Mock(recording=True)}), \
                patch.object(window.recorder, 'stop') as stop:
            window._toggle_recording(tile)
            stop.assert_called_once_with(tile)

    def test_compact_background_switch_hides_banner_and_cover_only_in_compact_mode(self):
        window = self.window([{'room_id': '1001', 'uname': '背景测试'}])
        window.settings['sidebar_card_mode'] = False
        window.apply_preview_settings()
        thumb = window.sidebar._items[0].thumb
        cover, banner = QPixmap(400, 200), QPixmap(800, 80)
        cover.fill(QColor('green'))
        banner.fill(QColor('red'))
        thumb.set_cover(cover)
        thumb.set_banner(banner)
        thumb.set_face(cover)
        self.app.processEvents()
        self.assertFalse(thumb.cover.isHidden())
        window.settings['sidebar_compact_background'] = False
        window.apply_preview_settings()
        self.assertTrue(thumb.cover.isHidden())
        thumb.set_banner(None)
        self.assertTrue(thumb.cover.isHidden(), 'Cover fallback must also respect the switch')
        self.assertFalse(thumb.face.isHidden())
        self.assertFalse(thumb._overlay_widgets[0].isHidden())
        window.sidebar.add_room({'room_id': '1002', 'uname': '新关注'})
        added = window.sidebar._items[-1].thumb
        added.set_cover(cover)
        self.assertTrue(added.cover.isHidden(), 'New items inherit the saved policy')
        self.assertFalse(window.current_state()['settings']['sidebar_compact_background'])
        window.settings['sidebar_card_mode'] = True
        window.apply_preview_settings()
        self.app.processEvents()
        self.assertFalse(thumb.cover.isHidden(), 'Large cover cards keep their artwork')
        window.settings['sidebar_card_mode'] = False
        window.settings['sidebar_compact_background'] = True
        window.apply_preview_settings()
        self.app.processEvents()
        self.assertFalse(thumb.cover.isHidden(), 'Re-enabling restores the cached cover')

    def test_tile_selection_does_not_change_border_in_dark_or_light_theme(self):
        window = self.window([{'room_id': '1001'}])
        tile = window.wall.tiles[0]
        for mode in ('dark', 'light'):
            theme.apply(mode)
            self.app.processEvents()
            tile.set_focused(False)
            before = tile.grab().toImage()
            tile.set_focused(True)
            after = tile.grab().toImage()
            self.assertTrue(tile.property('focused'), 'Selection behavior is retained')
            for x, y in ((before.width() // 2, 0), (0, before.height() // 2),
                         (before.width() - 1, before.height() // 2)):
                self.assertEqual(before.pixelColor(x, y), after.pixelColor(x, y), mode)
        theme.apply('dark')

    def test_delete_closes_only_hovered_tile_and_keeps_empty_slot(self):
        window = self.window([{'room_id': '1001'}, {'room_id': '1001'}])
        first, second = window.wall.tiles[:2]
        original_tiles = list(window.wall.tiles)
        with patch.object(window, '_tile_under_cursor', return_value=second), \
                patch.object(window.recorder, 'stop', wraps=window.recorder.stop) as stop:
            self.assertEqual(window.shortcuts['close_tile'], 'Del')
            QTest.keyClick(window, Qt.Key_Delete)
            self.assertEqual(first.room['room_id'], '1001')
            self.assertFalse(second.room.get('room_id'))
            self.assertEqual(window.wall.tiles, original_tiles)
            stop.assert_called_once_with(second)
            self.assertFalse(window.current_state()['wall'][1].get('room_id'))
            QTest.keyClick(window, Qt.Key_Delete)
            self.assertEqual(stop.call_count, 1)
        with patch.object(window, '_tile_under_cursor', return_value=None), \
                patch.object(window, '_clear_tile_room') as clear:
            QTest.keyClick(window, Qt.Key_Delete)
            clear.assert_not_called()

    def test_delete_preserves_search_and_composer_editing(self):
        window = self.window([{'room_id': '1001'}])
        tile = window.wall.tiles[0]
        with patch.object(window, '_tile_under_cursor', return_value=tile), \
                patch.object(window, '_clear_tile_room') as clear:
            for edit in (window.sidebar.search, QLineEdit(tile.bottom)):
                edit.setText('abc')
                edit.setCursorPosition(0)
                edit.setFocus()
                self.app.processEvents()
                QTest.keyClick(edit, Qt.Key_Delete)
                self.assertEqual(edit.text(), 'bc')
                clear.assert_not_called()
                edit.clear()

    def test_close_shortcut_can_be_remapped_saved_and_reset(self):
        window = self.window([{'room_id': '1001'}])
        page = ShortcutSettingsPage(window.shortcuts)
        self.addCleanup(page.close)
        page._edits['close_tile'].setKeySequence(QKeySequence('Ctrl+K'))
        window.shortcuts = page.values()
        window._refresh_shortcuts()
        tile = window.wall.tiles[0]
        with patch.object(window, '_tile_under_cursor', return_value=tile):
            QTest.keyClick(window, Qt.Key_Delete)
            self.assertEqual(tile.room['room_id'], '1001')
            QTest.keyClick(window, Qt.Key_K, Qt.ControlModifier)
            self.assertFalse(tile.room.get('room_id'))
        self.assertEqual(window.current_state()['ui']['shortcuts']['close_tile'], 'Ctrl+K')
        page.reset()
        self.assertEqual(page.values()['close_tile'], 'Del')

    def test_reauthentication_opens_login_without_discarding_existing_cookies(self):
        from ddm import bili
        from ddm.account_dialog import AccountPlatformDialog
        from ddm.login import LoginWindow
        window = self.window([])
        with patch.object(bili, 'SESSION_DATA', 'existing-session'), \
                patch.object(LoginWindow, 'start_login'):
            dialog = AccountPlatformDialog(window, {}, reauthenticate=True)
            try:
                self.assertIsInstance(dialog.page, LoginWindow)
                self.assertEqual(bili.SESSION_DATA, 'existing-session')
            finally:
                dialog.reject()

    def test_notice_width_wrap_and_warning_feedback(self):
        owner = QWidget()
        owner.resize(1000, 600)
        owner.show()
        self.addCleanup(owner.close)
        show_result(owner, '完成')
        notice = owner._result_notice
        self.app.processEvents()
        short_width = notice.width()
        self.assertEqual(short_width, 420)
        self.assertGreaterEqual(notice.height(), 76)
        show_result(owner, '主播甲 开播了', rooms=[{'room_id': 'test', 'uname': '主播甲'}], kind='live')
        notice = owner._result_notice
        self.assertEqual(notice.width(), short_width)
        self.assertEqual(notice.timer.interval(), 5000)
        self.assertEqual(len(notice._avatars), 1)
        self.app.processEvents()
        self.assertGreaterEqual(notice.title.width(), notice.title.fontMetrics().horizontalAdvance(notice.title.text()))
        self.assertGreaterEqual(notice.height(), 76)
        show_result(owner, '主播甲、主播乙 等 4 位主播开播了',
                    rooms=[{'room_id': str(index), 'uname': '主播'} for index in range(3)], kind='live')
        notice = owner._result_notice
        self.app.processEvents()
        self.assertGreaterEqual(notice.title.height(),
                                notice.title.heightForWidth(notice.title.width()))
        show_result(owner, '请先选择录制保存目录，再开始录制。' * 8, kind='warning')
        notice = owner._result_notice
        self.app.processEvents()
        self.assertLessEqual(notice.width(), 480)
        self.assertGreater(notice.height(), 48)
        self.assertEqual(notice.timer.interval(), 6000)
        self.assertFalse(notice._avatars)
        owner.resize(240, 600)
        self.app.processEvents()
        self.assertLessEqual(notice.width(), 208)
        owner.hide()
        self.assertFalse(notice.isVisible())
        self.assertFalse(notice.timer.isActive())

    def test_card_actions_and_close_do_not_duplicate_navigation(self):
        owner = QWidget()
        owner.resize(1000, 700)
        owner.show()
        self.addCleanup(owner.close)
        for kind, text, label in (('live', '主播开播了', '放入画面墙'),
                                  ('warning', '请重新登录', '前往登录'),
                                  ('info', '操作完成', '查看详情')):
            callback = Mock()
            show_result(owner, text, kind=kind, on_click=callback, persistent=True)
            notice = owner._result_notice
            self.app.processEvents()
            self.assertTrue(notice.action.isVisible())
            self.assertEqual(notice.action.text(), label)
            self.assertGreater(notice.action.y(), notice.text_column.geometry().bottom())
            self.assertGreater(notice.action.x(), notice.width() // 2)
            self.assertEqual(notice.findChild(QPushButton, 'NoticeClose').y(), 14)
            QTest.mouseClick(notice.action, Qt.LeftButton)
            callback.assert_called_once_with()
            self.assertFalse(notice.isVisible())
        show_result(owner, '普通提示')
        self.assertTrue(owner._result_notice.action.isHidden())
        self.assertEqual(owner._result_notice.category.text(), '操作提示')

    def test_cards_follow_theme_and_resize_without_clipping(self):
        owner = QWidget()
        owner.resize(1000, 700)
        owner.show()
        self.addCleanup(owner.close)
        self.addCleanup(theme.apply, theme._mode)
        update = UpdateNotice(owner)
        update.show_offer({'version': '0.5'}, persistent=True)
        show_result(owner, '需要检查的说明。' * 12, kind='warning', on_click=Mock())
        notice = owner._result_notice
        for mode in ('light', 'dark'):
            theme.apply(mode)
            self.app.processEvents()
            for card in (update, notice):
                rendered = card.grab().toImage()
                self.assertEqual(rendered.pixelColor(4, card.height() // 2).name(),
                                 theme.qcolor(theme.ELEVATED).name())
                self.assertEqual(rendered.pixelColor(0, 0).alpha(), 0)
                scale = rendered.devicePixelRatio()
                x, y = card.action.x(), card.action.y()
                corner = rendered.pixelColor(round(x * scale), round(y * scale))
                self.assertEqual(corner.name(), theme.qcolor(theme.ELEVATED).name())
                self.assertNotEqual(corner, rendered.pixelColor(
                    round((x + card.action.width() // 2) * scale), round((y + 1) * scale)))
            for width in (240, 800):
                owner.resize(width, 700)
                self.app.processEvents()
                for card in (update, notice):
                    self.assertLessEqual(card.width(), width - 32)
                    self.assertEqual(card.x(), owner.mapToGlobal(owner.rect().topLeft()).x()
                                     + 16)
                    self.assertGreaterEqual(card.title.height(),
                                            card.title.heightForWidth(card.title.width()))
                    self.assertLess(card.action.geometry().bottom(), card.height())
                self.assertGreater(notice.y(), update.geometry().bottom())

    def test_startup_all_platform_batches_and_shared_room_are_silent(self):
        rooms = [{'room_id': '1001', 'live': False, 'live_known': False},
                 {'room_id': 'douyu:1002', 'live': False, 'live_known': True}]
        window = self.window(rooms)
        window.wall.tiles[0].room = window.sidebar._items[0].room
        with patch.object(window, '_show_notice') as notice, patch.object(window.sidebar, 'play_live_alerts') as alerts:
            window._on_status_updated({'1001': self.status(True)})
            window._on_status_updated({'douyu:1002': self.status(True)})
            notice.assert_not_called()
            alerts.assert_not_called()
            self.complete_startup(window)
            window._on_status_updated({'1001': self.status(True)})
            notice.assert_not_called()
            window._on_status_updated({'1001': self.status(False)})
            window._on_status_updated({'1001': self.status(True)})
            notice.assert_called_once()
            alerts.assert_called_once()
            self.assertEqual(notice.call_args.kwargs['kind'], 'live')
            window._on_status_updated({'1001': self.status(True)})
            self.assertEqual(notice.call_count, 1)

    def test_unknown_recovery_and_disabled_live_alert_are_silent(self):
        window = self.window([{'room_id': '1001', 'live': False, 'live_known': False}])
        self.complete_startup(window)
        with patch.object(window, '_show_notice') as notice:
            window._on_status_updated({'1001': self.status(False, live_known=False)})
            window._on_status_updated({'1001': self.status(True)})
            notice.assert_not_called()
            window._on_status_updated({'1001': self.status(False)})
            window.settings['live_alert'] = False
            window._on_status_updated({'1001': self.status(True)})
            notice.assert_not_called()

    def test_large_startup_snapshot_and_enrichment_do_not_notify(self):
        window = self.window([{'room_id': str(index), 'live': False, 'live_known': False}
                              for index in range(1001, 1061)])
        with patch.object(window, '_show_notice') as notice, patch.object(window.sidebar, 'play_live_alerts') as alerts:
            first = {str(index): self.status(True) for index in range(1001, 1031)}
            second = {str(index): self.status(True) for index in range(1031, 1061)}
            window._on_status_updated(first)
            window._on_status_updated(second)
            window._on_status_updated({**first, **second})
            self.complete_startup(window)
            window._on_status_updated({**first, **second})
            notice.assert_not_called()
            alerts.assert_not_called()
            self.assertTrue(all(item.room['live'] for item in window.sidebar._items))

    def test_simultaneous_live_rooms_receive_independent_notices(self):
        window = self.window([{'room_id': str(index), 'uname': '主播' + str(index),
                               'live': False, 'live_known': True} for index in range(1, 5)])
        self.complete_startup(window)
        with patch.object(window, '_show_notice') as notice:
            window._on_status_updated({str(index): self.status(True) for index in range(1, 5)})
            self.assertEqual(notice.call_count, 4)
            self.assertEqual({call.args[0] for call in notice.call_args_list},
                             {f'主播{index} 开播了' for index in range(1, 5)})
            self.assertEqual({call.kwargs['rooms'][0]['room_id'] for call in notice.call_args_list},
                             {str(index) for index in range(1, 5)})
            self.assertTrue(all(len(call.kwargs['rooms']) == 1 and call.kwargs['kind'] == 'live'
                                for call in notice.call_args_list))
        window._on_status_updated({str(index): self.status(False) for index in range(1, 5)})
        window.sidebar.apply_pins(['1', '2'])
        for tile in window.wall.tiles:
            tile.set_room(None)
        with patch.object(window, '_place_live_notice_rooms') as place:
            window._on_status_updated({str(index): self.status(True) for index in range(1, 5)})
            notices = [notice for notice in window._notices if hasattr(notice, 'artwork')]
            self.assertEqual(len(notices), 4)
            self.assertEqual(len(window.sidebar.notification_button.center.entries), 4)
            for card in notices:
                rid = card.artwork.room['room_id']
                self.assertEqual(card.timer.isActive(), rid not in ('1', '2'))
                QTest.mouseClick(card.action, Qt.LeftButton)
                self.assertEqual([room['room_id'] for room in place.call_args.args[0]], [rid])
            self.assertEqual(place.call_count, 4)

    def test_recording_uses_main_notice(self):
        window = self.window([])
        window._record_notice('请先选择录制保存目录')
        self.assertEqual(window._result_notice.title.text(), '请先选择录制保存目录')
        self.assertEqual(window._result_notice.timer.interval(), 6000)
        window._closing = True
        with patch('ddm.online_ui.show_result') as result:
            window._record_notice('录制已完成')
            result.assert_not_called()
        window._closing = False


if __name__ == '__main__':
    unittest.main()
