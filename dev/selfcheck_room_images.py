"""Room image orchestration: synthetic loaders and local-cache Qt thread delivery."""
from contextlib import ExitStack
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QThread, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication
from ddm import app as app_module, images
from ddm.app import MainWindow
from ddm.room_images import RoomImages
from ddm.room_images import RoomImages


METHODS = ('load_cached_covers', 'load_cached_avatars', 'load_room_avatars',
    '_prime_cached_avatars', 'load_avatars_for', '_load_room_banners', '_on_room_banner',
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
    return SimpleNamespace(room=room, thumb=SimpleNamespace(
        set_face=Mock(), set_cover=Mock(), set_banner=Mock()))


class Host:
    def __init__(self, rooms):
        self.sidebar = SimpleNamespace(rooms=lambda: rooms, _items=[item(room) for room in rooms],
            set_room_face=Mock(), notification_button=SimpleNamespace(center=SimpleNamespace(rows={})))
        self.room_images = RoomImages(self)
        self.room_images = RoomImages(self)
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

    def test_full_refresh_primes_cache_and_routes_images_to_independent_loaders(self):
        host = Host([{'room_id': '1001', 'face': 'face-a', 'cover_url': 'cover-a'},
                     {'room_id': 'fixture:2', 'cover_url': 'cover-b'}])
        picture = object()
        self.cached.return_value = picture
        host.load_room_avatars()
        self.assertEqual(host._room_avatar_loader.items, {'1001': 'face-a'})
        self.assertEqual(host._cover_loader.items, {'1001': 'cover-a', 'fixture:2': 'cover-b'})
        self.assertEqual(host._cover_loader.kwargs, {'subdir': 'covers'})
        host.sidebar._items[0].thumb.set_face.assert_called_once_with(picture)
        self.assertEqual(len(host._avatar_loaders), 2)
        for loader in host._avatar_loaders:
            self.assertIs(loader.parent, host)
            self.assertTrue(loader.running)

    def test_cache_misses_and_removed_rooms_are_skipped(self):
        host = Host([{'room_id': '1001'}])
        self.assertEqual(host._prime_cached_avatars({'1001': 'miss', 'removed': 'url'}), 0)
        self.cached.assert_called_once_with('miss')
        host.sidebar._items[0].thumb.set_face.assert_not_called()

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
        self.assertEqual(host.sidebar.set_room_face.call_count, 1)


class ImageThreadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

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
