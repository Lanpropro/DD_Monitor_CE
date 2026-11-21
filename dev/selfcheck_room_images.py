"""Room image orchestration: synthetic loaders and local-cache Qt thread delivery."""
from concurrent.futures import Future
from contextlib import ExitStack
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QObject, QThread, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication
from ddm import app as app_module, images
from ddm.app import MainWindow
from ddm.player import TilePlayer
from ddm.room_images import RoomImages
from ddm.sidebar_item import NavItem


METHODS = ('load_cached_covers', 'load_cached_avatars', 'load_room_avatars',
    'load_avatars_for', '_load_room_banners', '_on_room_banner',
    '_on_room_artwork', '_start_avatar_loader', '_on_room_avatar', '_on_room_cover')


class Signal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def emit(self, *args):
        for callback in self.callbacks:
            callback(*args)


class Loader:
    instances = []

    def __init__(self, items, parent, **kwargs):
        self.items, self.parent, self.kwargs = items, parent, kwargs
        self.loaded, self.finished = Signal(), Signal()
        self.running = self.deleted = False
        self.instances.append(self)

    def start(self):
        self.running = True

    def isRunning(self):
        return self.running

    def deleteLater(self):
        self.deleted = True


def item(room):
    thumb = SimpleNamespace(set_face=Mock(), set_cover=Mock(), set_banner=Mock())

    def set_room_avatar(picture):
        thumb.set_face(picture)
        return picture

    return SimpleNamespace(room=room, thumb=thumb, set_room_avatar=set_room_avatar)


class Host(QObject):
    def __init__(self, rooms):
        super().__init__()
        self.sidebar = SimpleNamespace(rooms=lambda: rooms, _items=[item(room) for room in rooms],
            set_room_face=Mock(), notification_button=SimpleNamespace(center=SimpleNamespace(rows={})),
            navigation=SimpleNamespace(monitor_menu=Mock()))
        self.wall = SimpleNamespace(pane_danmaku=Mock())
        self.room_images = RoomImages(self)
        self._closing = False
        self._avatar_loaders = []
        self._notices = []

    _loader_running = staticmethod(MainWindow._loader_running)


for name in METHODS:
    setattr(Host, name, getattr(MainWindow, name))


class RoomImageTests(unittest.TestCase):
    def setUp(self):
        Loader.instances = []
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ('AvatarLoader', 'CachedAvatarLoader', 'CachedCoverLoader'):
            self.stack.enter_context(patch.object(app_module, name, Loader))
        self.cached = self.stack.enter_context(patch.object(app_module, 'load_cached_avatar', return_value=None))

    def test_empty_rooms_do_not_start_workers(self):
        host = Host([])
        host.load_cached_covers()
        host.load_cached_avatars()
        host.load_room_avatars()
        host.load_avatars_for([])
        self.assertEqual(Loader.instances, [])
        self.assertEqual(host._avatar_loaders, [])

    def test_cache_workers_keep_host_parent_reference_and_callbacks(self):
        host = Host([{'room_id': 1001}, {'room_id': 'fixture:2'}, {}])
        for method, field, setter in (
                ('load_cached_covers', '_cover_cache_loader', 'set_cover'),
                ('load_cached_avatars', '_avatar_cache_loader', 'set_face')):
            getattr(host, method)()
            loader = getattr(host, field)
            self.assertIs(loader.parent, host)
            self.assertEqual(loader.items, ['1001', 'fixture:2'])
            self.assertTrue(loader.running)
            picture = object()
            loader.loaded.emit('1001', picture)
            getattr(host.sidebar._items[0].thumb, setter).assert_called_once_with(picture)
            loader.finished.emit()
            self.assertTrue(loader.deleted)

    def test_full_refresh_leaves_cache_reads_and_delivery_to_workers(self):
        host = Host([{'room_id': '1001', 'face': 'face-a', 'cover_url': 'cover-a'},
                     {'room_id': 'fixture:2', 'cover_url': 'cover-b'}])
        picture = object()
        self.cached.return_value = picture
        host.load_room_avatars()
        self.assertEqual(host._room_avatar_loader.items, {'1001': 'face-a'})
        self.assertEqual(host._cover_loader.items, {'1001': 'cover-a', 'fixture:2': 'cover-b'})
        self.assertEqual(host._cover_loader.kwargs, {'subdir': 'covers'})
        self.cached.assert_not_called()
        host.sidebar._items[0].thumb.set_face.assert_not_called()
        host._room_avatar_loader.loaded.emit('1001', picture)
        host.sidebar._items[0].thumb.set_face.assert_called_once_with(picture)
        self.assertEqual(len(host._avatar_loaders), 2)
        for loader in host._avatar_loaders:
            self.assertIs(loader.parent, host)
            self.assertTrue(loader.running)

    def test_added_rooms_load_immediately_and_banner_identity_deduplicates(self):
        rooms = [{'room_id': '1001', 'uid': 'u1', 'face': 'face'},
                 {'room_id': 'douyin:2', 'uid': 'u2'},
                 {'room_id': 'fixture:3', 'banner_url': 'unsupported'}]
        host = Host(rooms)
        host.load_avatars_for(rooms)
        self.assertEqual(Loader.instances[0].items, {'1001': 'face'})
        banner = Loader.instances[-1]
        self.assertEqual(banner.kwargs, {'subdir': 'banners'})
        self.assertEqual(set(banner.items), {'1001', 'douyin:2'})
        host._load_room_banners(rooms)
        self.assertEqual(len(Loader.instances), 2)
        changed = dict(rooms[0], banner_url='new-banner')
        host._load_room_banners([changed])
        self.assertEqual(Loader.instances[-1].items, {'1001': changed})
        # The request receives a snapshot, not the mutable source room.
        changed['banner_url'] = 'later'
        self.assertEqual(Loader.instances[-1].items['1001']['banner_url'], 'new-banner')

    def test_worker_list_prunes_finished_and_qt_deleted_references(self):
        host = Host([{'room_id': '1001'}])
        running, finished, deleted = Mock(), Mock(), Mock()
        running.isRunning.return_value = True
        finished.isRunning.return_value = False
        deleted.isRunning.side_effect = RuntimeError('Qt object deleted')
        host._avatar_loaders = [finished, deleted, running]
        callback = Mock()
        current = host._start_avatar_loader({'1001': 'url'}, callback)
        self.assertEqual(host._avatar_loaders, [running, current])
        picture = object()
        current.loaded.emit('1001', picture)
        callback.assert_called_once_with('1001', picture)
        current.finished.emit()
        self.assertTrue(current.deleted)
        self.assertIsNone(host._start_avatar_loader({}, callback))

    def test_callbacks_update_notices_center_and_matching_sidebar_item(self):
        host = Host([{'room_id': '1001'}, {'room_id': '1002'}])
        host._tray = SimpleNamespace(monitor_panel=Mock())
        notice, row = Mock(), Mock()
        host._notices = [notice, object()]
        host.sidebar.notification_button.center.rows = {'row': row}
        picture = object()
        host._on_room_avatar('1001', picture)
        notice.set_room_avatar.assert_called_once_with('1001', picture)
        host.sidebar.set_room_face.assert_called_once_with('1001', picture)
        host._on_room_cover('1001', picture)
        host._on_room_banner('1001', picture)
        self.assertEqual(row.set_room_artwork.call_count, 2)
        self.assertEqual(notice.set_room_artwork.call_count, 2)
        for setter in ('set_face', 'set_cover', 'set_banner'):
            getattr(host.sidebar._items[0].thumb, setter).assert_called_once_with(picture)
            getattr(host.sidebar._items[1].thumb, setter).assert_not_called()
        host._on_room_avatar('removed', picture)
        host.sidebar.navigation.monitor_menu.panel.set_room_avatar.assert_called_with('removed', picture)
        host._tray.monitor_panel.set_room_avatar.assert_called_with('removed', picture)
        self.assertEqual(host.sidebar.set_room_face.call_count, 1)


class ImageThreadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_station_badge_reuses_downloaded_avatar_and_preserves_wide_logo(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / 'fallback.png')
            fallback = QPixmap(24, 24)
            fallback.fill(Qt.red)
            self.assertTrue(fallback.save(path))
            item = NavItem({'room_id': 'm3u:test', 'platform': 'm3u'}, 0)
            item.set_room_card_branding({'avatar_path': path, 'badge_path': path,
                                         'badge_from_avatar': True, 'label': '地方台'})
            self.assertTrue(item.has_station_badge)
            self.assertEqual(item.platform_badge.toolTip(), '地方台')
            self.assertEqual(item.thumb.face_pixmap().toImage().pixelColor(10, 10), Qt.red)
            picture = QPixmap(80, 40)
            picture.fill(Qt.green)
            avatar = item.set_room_avatar(picture)
            self.assertEqual((avatar.width(), avatar.height()), (80, 80))
            self.assertEqual(avatar.toImage().pixelColor(40, 40), Qt.green)
            self.assertEqual(item.platform_badge.pixmap().toImage().pixelColor(10, 5), Qt.green)
            item.close()

    def test_first_frame_cover_uses_one_request_and_existing_room_cache(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(images, 'REPO', folder):
            room = {'room_id': 'm3u:test'}
            host = Host([room])
            result = Future()
            player = SimpleNamespace(request_video_frame=Mock(return_value=result))
            host.room_images.capture_first_frame(room, player)
            job = host.room_images._first_frame_jobs[room['room_id']]
            host.room_images.capture_first_frame(room, player)
            result.set_result({'format': 'bgr0', 'w': 32, 'h': 32, 'stride': 128,
                               'data': b'\x00\xff\x00\x00' * (32 * 32)})
            self.assertTrue(job.wait(2500))
            self.app.processEvents()
            self.assertFalse(host.room_images._first_frame_jobs)
            cached = images.load_room_cover(room['room_id'])
            self.assertIsNotNone(cached)
            self.assertGreater(cached.toImage().pixelColor(5, 5).green(), 240)
            host.sidebar._items[0].thumb.set_cover.assert_called_once()
            host.room_images.capture_first_frame(room, player)
            player.request_video_frame.assert_called_once_with()

    def test_player_drops_capture_after_the_stream_changes(self):
        core = SimpleNamespace(command_async=Mock())
        player = SimpleNamespace(player=core, _released=False, silent=False, play_session='a')
        TilePlayer.request_video_frame(player)
        self.assertEqual(core.command_async.call_args.args, ('screenshot-raw', 'video'))
        callback = core.command_async.call_args.kwargs['callback']
        frame = object()
        self.assertIs(callback(None, frame), frame)
        player.play_session = 'b'
        self.assertIsNone(callback(None, frame))

    def test_startup_url_cache_is_decoded_off_gui_and_delivered_without_network(self):
        with tempfile.TemporaryDirectory() as temp, ExitStack() as stack:
            stack.enter_context(patch.object(images, 'REPO', temp))
            network = stack.enter_context(patch.object(images.requests, 'get',
                side_effect=AssertionError('Cached avatars must not need the CDN')))
            cached = stack.enter_context(patch.object(app_module, 'load_cached_avatar',
                side_effect=AssertionError('No synchronous startup avatar decoding')))
            room = {'room_id': '1001', 'face': 'https://example.invalid/avatar.png'}
            path = Path(images._cache_path(room['face'], 'avatars'))
            path.parent.mkdir(parents=True, exist_ok=True)
            picture = QPixmap(24, 24)
            picture.fill(Qt.blue)
            self.assertTrue(picture.save(str(path), 'PNG'))
            # No room snapshot exists: the URL cache must still supply the avatar.
            self.assertFalse(Path(images.room_avatar_path('1001')).exists())
            host = Host([room])
            decoded, delivered = [], []
            load = images.load_pixmap
            def decode(*args, **kwargs):
                decoded.append(QThread.currentThread() is self.app.thread())
                return load(*args, **kwargs)
            stack.enter_context(patch.object(images, 'load_pixmap', side_effect=decode))
            host.sidebar._items[0].thumb.set_face.side_effect = lambda _pixmap: delivered.append(
                QThread.currentThread() is self.app.thread())
            try:
                host.load_room_avatars()
                cached.assert_not_called()
                self.assertEqual(delivered, [])
                deadline = time.monotonic() + 4
                while time.monotonic() < deadline:
                    self.app.processEvents()
                    if delivered and not host._loader_running(host._room_avatar_loader):
                        break
                    time.sleep(0.005)
                self.assertEqual(decoded, [False])
                self.assertEqual(delivered, [True])
                network.assert_not_called()
                self.assertIsNotNone(images.load_room_avatar('1001'))
            finally:
                for worker in host._avatar_loaders:
                    if host._loader_running(worker):
                        self.assertTrue(worker.wait(4000))

    def test_local_cache_workers_deliver_on_gui_thread_and_close_cleanly(self):
        with tempfile.TemporaryDirectory() as temp, ExitStack() as stack:
            stack.enter_context(patch.object(images, 'REPO', temp))
            stack.enter_context(patch('ddm.plugins.PluginManager.load'))
            for name in ('start_all', 'refresh_status', 'refresh_stats', 'refresh_account',
                         'sync_danmaku', 'load_room_avatars', 'load_cached_covers',
                         'load_cached_avatars', '_check_startup_update', '_check_startup_plugins'):
                stack.enter_context(patch.object(MainWindow, name))
            room = {'room_id': '1001', 'uname': 'Fixture', 'live': False}
            window = MainWindow([room], [], layout_id='1x1', state={'plugins_enabled': [],
                'settings': {'auto_update': False, 'preview_on_hover': False,
                             'close_behavior': 'exit'}})
            try:
                # Bind original methods to keep constructor startup timers isolated.
                for name in ('load_cached_covers', 'load_cached_avatars'):
                    setattr(window, name, ORIGINALS[name].__get__(window))
                thumb = window.sidebar._items[0].thumb
                seen = []
                for kind, path, color in (
                        ('cover', images.room_cover_path(room['room_id']), Qt.red),
                        ('face', images.room_avatar_path(room['room_id']), Qt.blue)):
                    Path(path).parent.mkdir(parents=True, exist_ok=True)
                    picture = QPixmap(24, 24)
                    picture.fill(color)
                    self.assertTrue(picture.save(path, 'PNG'))
                    original = getattr(thumb, 'set_' + kind)
                    def receive(pixmap, kind=kind, original=original):
                        seen.append((kind, QThread.currentThread() is self.app.thread()))
                        original(pixmap)
                    stack.enter_context(patch.object(thumb, 'set_' + kind, receive))
                for _ in range(3):
                    seen.clear()
                    window.load_cached_covers()
                    window.load_cached_avatars()
                    workers = [window._cover_cache_loader, window._avatar_cache_loader]
                    self.assertTrue(all(worker.parent() is window for worker in workers))
                    deadline = time.monotonic() + 4
                    while time.monotonic() < deadline:
                        if len(seen) == 2 and not any(window._loader_running(w) for w in workers):
                            break
                        self.app.processEvents()
                        time.sleep(0.005)
                    self.assertCountEqual(seen, [('cover', True), ('face', True)])
                    self.assertFalse(any(window._loader_running(w) for w in workers))
                    self.assertIsNotNone(thumb._cover_source)
                    self.assertIsNotNone(thumb._face_source)
            finally:
                window.close()
                self.app.processEvents()
            self.assertTrue(window._closing)
            self.assertEqual(window._avatar_loaders, [])


ORIGINALS = {name: getattr(MainWindow, name) for name in METHODS}

if __name__ == '__main__':
    unittest.main()
