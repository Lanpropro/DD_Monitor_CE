"""Room-card drop feedback, immediate dispatch, native surface identity and cleanup."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['DDM_NO_SAVE'] = '1'
if '--native' in sys.argv:
    sys.argv.remove('--native')
    os.environ['QT_QPA_PLATFORM'] = 'windows'

from PySide6.QtCore import QCoreApplication, QEvent, QMimeData, QPoint, Qt, Signal
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication, QFrame, QWidget
from shiboken6 import delete, isValid
from ddm import card_drop, motion
from ddm.pane_source_picker import SourceAvatar
from ddm.sidebar_drag import ROOM_MIME
from ddm.video_surface import VideoSurface
from ddm.widgets import Sidebar, Tile

APP = QApplication.instance() or QApplication([])


class DropTile(QFrame):
    roomDropped = Signal(str)
    dragEnterEvent = Tile.dragEnterEvent
    dragLeaveEvent = Tile.dragLeaveEvent
    dropEvent = Tile.dropEvent

    def __init__(self, parent):
        super().__init__(parent)
        self.room = {}
        self.video = VideoSurface(self)
        self.video.setGeometry(0, 0, 520, 300)
        self.setAcceptDrops(True)


class CardDropTests(unittest.TestCase):
    def setUp(self):
        self.window = QWidget()
        self.window.setAttribute(Qt.WA_ShowWithoutActivating)
        self.window.setGeometry(-10000, -10000, 900, 600)
        self.sidebar = Sidebar([dict(room_id='1001', uname='Offline card', live=False)],
                               self.window, auto_compact=False)
        self.sidebar.setGeometry(0, 0, 248, 580)
        self.tile = DropTile(self.window)
        self.tile.setGeometry(280, 10, 520, 340)
        self.window.show()
        for _ in range(3):
            APP.processEvents()
        self.animation = patch.object(motion, 'enabled', return_value=True)
        self.animation.start()
        self.mime = QMimeData()
        self.mime.setData(ROOM_MIME, b'1001')
        self.snapshot = QPixmap(480, 160)
        self.snapshot.setDevicePixelRatio(2)
        self.snapshot.fill(QColor('#467f9a'))
        self.hotspot = QPoint(40, 20)
        self.position = self.tile.video.mapToGlobal(QPoint(120, 90))
        self.tile.room = {'room_id': '1001'}
        card_drop.remember_card(self.mime, self.snapshot, self.hotspot)

    def tearDown(self):
        self.sidebar.drag_session.cancel()
        self.window.close()
        self.window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        APP.processEvents()
        self.animation.stop()

    def overlay(self):
        return card_drop.play_card_drop(self.tile, self.mime, self.position, '1001')

    def test_empty_source_is_a_line_icon_and_bound_source_keeps_its_avatar(self):
        button = SourceAvatar(self.window)
        button.sync('选择弹幕来源', 0, '', None)
        button.show()
        self.assertIsNone(button.avatar)
        self.assertEqual(button.accessibleName(), '选择弹幕来源')
        self.assertFalse(button.grab().isNull())
        button.sync('Fixture', 0, '1001', self.snapshot)
        self.assertIsNotNone(button.avatar)
        self.assertEqual(button.face_key, self.snapshot.cacheKey())
        button.sync('选择弹幕来源', 0, '', None)
        self.assertIsNone(button.avatar)
        self.assertIsNone(button.face_key)

    def test_sidebar_release_dispatches_playback_before_animating_without_mouse_capture(self):
        self.tile.room = {}
        calls = []
        def play(room_id):
            calls.append((room_id, QWidget.mouseGrabber(),
                          getattr(self.tile, '_card_drop_overlay', None)))
            self.tile.room = {'room_id': room_id}
        self.tile.roomDropped.connect(play)
        source = self.sidebar.items()[0]
        handle = int(self.tile.video.winId())
        geometry = self.tile.geometry()
        session = self.sidebar.drag_session
        session.start(source, self.mime, self.snapshot, self.hotspot, self.position)
        with patch('ddm.sidebar_drag.widget_at', return_value=self.tile):
            self.assertTrue(session.finish())
        self.assertEqual(calls, [('1001', None, None)])
        overlay = self.tile._card_drop_overlay
        self.assertTrue(overlay.timer.isActive())
        self.assertIsNone(session.ghost)
        self.assertEqual(int(self.tile.video.winId()), handle)
        self.assertEqual(self.tile.geometry(), geometry)
        self.assertTrue(overlay.testAttribute(Qt.WA_TransparentForMouseEvents))
        self.assertTrue(overlay.windowFlags() & Qt.WindowDoesNotAcceptFocus)
        self.assertEqual(overlay.snapshot.devicePixelRatio(), 2)

    def test_reduced_motion_unresolved_room_and_missing_image_do_not_start(self):
        with patch.object(motion, 'enabled', return_value=False):
            self.assertIsNone(self.overlay())
        self.tile.room = {'room_id': 'different'}
        self.assertIsNone(self.overlay())
        self.tile.room = {'room_id': '1001'}
        self.assertIsNone(card_drop.play_card_drop(self.tile, QMimeData(), self.position, '1001'))

    def test_hot_swap_feedback_follows_the_incoming_widget_at_the_drop_position(self):
        self.tile.room = {'room_id': 'previous'}
        incoming = DropTile(self.window)
        incoming.setGeometry(280, 360, 520, 200)
        incoming.room = {'room_id': '1001'}
        incoming.show()
        APP.processEvents()
        target_geometry = self.tile.geometry()
        handle = int(incoming.video.winId())
        def swap(_room_id):
            self.tile.setGeometry(incoming.geometry())
            incoming.setGeometry(target_geometry)
        self.tile.roomDropped.connect(swap)
        session = self.sidebar.drag_session
        session.start(self.sidebar.items()[0], self.mime, self.snapshot, self.hotspot, self.position)
        with patch('ddm.sidebar_drag.widget_at', return_value=self.tile):
            self.assertTrue(session.finish())
        self.assertIsNone(getattr(self.tile, '_card_drop_overlay', None))
        self.assertTrue(incoming._card_drop_overlay.timer.isActive())
        self.assertEqual(int(incoming.video.winId()), handle)

    def test_same_room_and_cancelled_gesture_do_not_replay_feedback(self):
        session = self.sidebar.drag_session
        session.start(self.sidebar.items()[0], self.mime, self.snapshot, self.hotspot, self.position)
        with patch('ddm.sidebar_drag.widget_at', return_value=self.tile):
            self.assertTrue(session.finish())
        self.assertIsNone(getattr(self.tile, '_card_drop_overlay', None))
        session.start(self.sidebar.items()[0], self.mime, self.snapshot, self.hotspot, self.position)
        session.cancel()
        self.assertIsNone(getattr(self.tile, '_card_drop_overlay', None))

    def test_clock_endpoints_rendering_and_late_tick_cleanup(self):
        overlay = self.overlay()
        self.assertEqual(overlay.card_rect(), overlay.source)
        overlay.progress = .5
        self.assertNotEqual(overlay.card_rect(), overlay.source)
        self.assertFalse(overlay.grab().isNull())
        overlay.progress = 1
        self.assertAlmostEqual(overlay.card_rect().width(), overlay.target.width())
        self.assertAlmostEqual(overlay.card_rect().y(), overlay.target.y())
        with patch.object(card_drop.time, 'monotonic', return_value=overlay.started + 2):
            overlay.advance()
        self.assertTrue(overlay.finished)
        self.assertFalse(overlay.timer.isActive())
        self.assertTrue(overlay.snapshot.isNull())
        self.assertIsNone(self.tile._card_drop_overlay)

    def test_new_drop_resize_hide_and_target_destruction_clean_up(self):
        first = self.overlay()
        second = self.overlay()
        self.assertTrue(first.finished)
        self.assertIs(self.tile._card_drop_overlay, second)
        self.tile.resize(530, 340)
        self.assertTrue(second.finished)
        third = self.overlay()
        self.window.hide()
        self.assertTrue(third.finished)
        self.window.show()
        APP.processEvents()
        fourth = self.overlay()
        delete(self.tile)
        self.assertFalse(isValid(self.tile))
        self.assertTrue(fourth.finished)
        self.assertFalse(fourth.timer.isActive())

    def test_target_removed_by_drop_callback_does_not_leave_a_window(self):
        self.tile.room = {}
        self.tile.roomDropped.connect(lambda _room_id: delete(self.tile))
        session = self.sidebar.drag_session
        session.start(self.sidebar.items()[0], self.mime, self.snapshot, self.hotspot, self.position)
        with patch('ddm.sidebar_drag.widget_at', return_value=self.tile):
            self.assertTrue(session.finish())
        self.assertFalse(any(w.isVisible() for w in APP.topLevelWidgets()
                             if w.objectName() == 'CardDropOverlay'))

    @unittest.skipUnless(APP.platformName() == 'windows', 'Native libmpv surface check')
    def test_local_playback_starts_during_feedback_and_keeps_native_surface(self):
        from ddm.player import TilePlayer
        from selfcheck_mpv import pump, ready
        with tempfile.TemporaryDirectory(prefix='ddm-card-drop-') as directory:
            media = Path(directory) / 'fixture.mp4'
            subprocess.run([shutil.which('ffmpeg') or 'ffmpeg', '-hide_banner', '-loglevel', 'error',
                '-f', 'lavfi', '-i', 'testsrc2=s=320x180:r=30', '-t', '5',
                '-c:v', 'libx264', '-preset', 'ultrafast', str(media)], check=True, timeout=30)
            player = TilePlayer(self.tile.video, self.window, silent=True)
            try:
                self.tile.room = {}
                def play(room_id):
                    self.tile.room = {'room_id': room_id}
                    player.play(str(media))
                self.tile.roomDropped.connect(play)
                handle = int(self.tile.video.winId())
                session = self.sidebar.drag_session
                session.start(self.sidebar.items()[0], self.mime, self.snapshot, self.hotspot, self.position)
                with patch('ddm.sidebar_drag.widget_at', return_value=self.tile):
                    self.assertTrue(session.finish())
                overlay = self.tile._card_drop_overlay
                self.assertTrue(overlay.timer.isActive())
                self.assertIsNotNone(player.player)
                core = player.player
                ready(APP, player)
                generation = player.state_generation
                before = player._prop('time-pos')
                pump(APP, .35)
                self.assertGreater(player._prop('time-pos'), before)
                self.assertIs(player.player, core)
                self.assertEqual(player.state_generation, generation)
                self.assertEqual(int(self.tile.video.winId()), handle)
                self.assertTrue(overlay.finished)
                self.assertIsNone(self.tile._card_drop_overlay)
            finally:
                player.release()


if __name__ == '__main__':
    unittest.main()
