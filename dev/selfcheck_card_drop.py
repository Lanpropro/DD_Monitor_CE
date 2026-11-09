"""Room-card drop feedback, immediate dispatch, native surface identity and cleanup."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['DDM_NO_SAVE'] = '1'
if '--native' in sys.argv:
    sys.argv.remove('--native')
    os.environ['QT_QPA_PLATFORM'] = 'windows'

from PySide6.QtCore import QCoreApplication, QEvent, QMimeData, QPoint, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPixmap
from PySide6.QtWidgets import QApplication, QFrame, QWidget
from shiboken6 import delete, isValid
from ddm import card_drop, motion
from ddm.pane_source_picker import SourceAvatar
from ddm.playback_badges import LoadingIndicator
from ddm.sidebar_drag import ROOM_MIME, TILE_MIME
from ddm.tile_drag import tile_drag_visual
from ddm.video_surface import VideoSurface
from ddm.widgets import Sidebar, Tile

APP = QApplication.instance() or QApplication([])


class DropTile(QFrame):
    roomDropped = Signal(str)
    tileDropped = Signal(str)
    dragEnterEvent = Tile.dragEnterEvent
    dragLeaveEvent = Tile.dragLeaveEvent
    dropEvent = Tile.dropEvent
    mouseMoveEvent = Tile.mouseMoveEvent

    def __init__(self, parent):
        super().__init__(parent)
        self.room = {}
        self._player_active = False
        self._connecting = False
        self.video = VideoSurface(self)
        self.video.setGeometry(0, 0, 520, 300)
        self.setAcceptDrops(True)
        self.spinner = LoadingIndicator(self)


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
        self.assertEqual(button.text(), '')
        self.assertTrue(button.property('sourceEmpty'))
        self.assertEqual(button.accessibleName(), '选择弹幕来源')
        self.assertFalse(button.grab().isNull())
        button.sync('Fixture', 0, '1001', None)
        self.assertIsNone(button.avatar, 'Missing photos use the neutral icon, never a colored text avatar')
        self.assertEqual(button.text(), '')
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
        self.assertLess(overlay.card_rect().width(), overlay.source.width())
        self.assertGreater(overlay.card_rect().center().y(), overlay.source.center().y())
        with patch.object(card_drop.time, 'monotonic', return_value=overlay.started + 2):
            overlay.advance()
        self.assertTrue(overlay.finished)
        self.assertFalse(overlay.timer.isActive())
        self.assertTrue(overlay.snapshot.isNull())
        self.assertIsNone(self.tile._card_drop_overlay)

    def test_sinking_stays_at_the_release_hotspot_in_every_corner(self):
        for ratio in (1, 2):
            snapshot = QPixmap(240 * ratio, 80 * ratio)
            snapshot.setDevicePixelRatio(ratio)
            snapshot.fill(QColor('#467f9a'))
            card_drop.remember_card(self.mime, snapshot, self.hotspot)
            for point in (QPoint(8, 8), QPoint(510, 8), QPoint(8, 290), QPoint(510, 290)):
                self.position = self.tile.video.mapToGlobal(point)
                overlay = self.overlay()
                self.assertEqual(overlay.origin.toPoint() + overlay.pos(), self.position)
                source = overlay.source
                anchor_x = (overlay.origin.x() - source.x()) / source.width()
                anchor_y = (overlay.origin.y() - source.y()) / source.height()
                for progress in (0, .25, .5, 1):
                    overlay.progress = progress
                    rect = overlay.card_rect()
                    self.assertAlmostEqual(rect.x() + rect.width() * anchor_x, overlay.origin.x())
                    descent = rect.y() + rect.height() * anchor_y - overlay.origin.y()
                    self.assertGreaterEqual(descent, -1e-6)
                    self.assertLessEqual(descent, 18 + 1e-6)
                overlay.finish()

    def test_loading_indicator_is_unchanged_and_feedback_has_a_fixed_deadline(self):
        self.tile._connecting = True
        self.tile.spinner.start()
        overlay = self.overlay()
        self.assertTrue(self.tile.spinner.isVisible())
        self.tile.spinner.start()
        self.assertTrue(self.tile.spinner.isVisible())
        with patch.object(card_drop.time, 'monotonic', return_value=overlay.started + 5):
            overlay.advance()
        self.assertTrue(overlay.finished)
        self.assertTrue(self.tile.spinner.isVisible(), 'Drop feedback must never stop or restart the original indicator')

    def test_playing_frame_closes_feedback_immediately_and_has_no_backdrop(self):
        self.tile._connecting = True
        self.tile.spinner.start()
        overlay = self.overlay()
        image = overlay.grab().toImage()
        self.assertEqual(image.pixelColor(image.width() - 3, image.height() - 3).alpha(), 0)
        self.assertLess(overlay.width() * overlay.height(), self.tile.video.width() * self.tile.video.height())
        self.tile._player_active, self.tile._connecting = True, False
        self.tile.spinner.stop()  # The original playback callback owns this state.
        overlay.advance()
        self.assertTrue(overlay.finished)
        self.assertFalse(overlay.isVisible())
        self.assertTrue(overlay.snapshot.isNull())
        self.assertFalse(self.tile.spinner.isVisible())

    def test_loading_failure_room_change_and_cancel_restore_normal_presentation(self):
        self.tile._connecting = True
        self.tile.spinner.start()
        overlay = self.overlay()
        self.tile._connecting = False
        self.tile.spinner.stop()
        overlay.advance()
        self.assertTrue(overlay.finished)
        self.assertFalse(self.tile.spinner.isVisible())
        self.tile._connecting = True
        self.tile.spinner.start()
        overlay = self.overlay()
        overlay.finish()
        self.assertTrue(self.tile.spinner.isVisible())
        overlay = self.overlay()
        self.tile.room = {'room_id': 'another'}
        overlay.advance()
        self.assertTrue(overlay.finished)

    def test_wall_pickup_uses_a_visible_card_and_keeps_the_source_surface(self):
        import ctypes
        self.window.sidebar = self.sidebar
        self.tile._press_pos = QPoint(1, 1)
        point = QPoint(70, 60)
        event = QMouseEvent(QEvent.MouseMove, point, self.tile.mapToGlobal(point),
                            Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
        handle = int(self.tile.video.winId())
        session = self.sidebar.drag_session
        with patch.object(ctypes, 'windll', SimpleNamespace(user32=SimpleNamespace(
                GetAsyncKeyState=Mock(return_value=0x8000))), create=True):
            self.tile.mouseMoveEvent(event)
        self.assertTrue(session.active)
        self.assertIs(session.source, self.tile)
        self.assertTrue(session.ghost.isVisible())
        self.assertFalse(session.ghost.pixmap().isNull())
        self.assertEqual(session.actions, Qt.MoveAction)
        self.assertEqual(bytes(session.mime.data(TILE_MIME)), b'1001')
        self.assertEqual(int(self.tile.video.winId()), handle)
        with patch.object(self.sidebar, 'end_drag') as sidebar_end:
            session.cancel()
        sidebar_end.assert_not_called()
        self.assertIsNone(session.ghost)
        self.assertIsNone(self.tile._press_pos)

    def test_wall_drop_keeps_move_semantics_and_routes_feedback_to_incoming_tile(self):
        self.window.sidebar = self.sidebar
        self.tile.room = {'room_id': 'previous'}
        incoming = DropTile(self.window)
        incoming.setGeometry(280, 360, 520, 200)
        incoming.room = {'room_id': '1001'}
        incoming.show()
        APP.processEvents()
        before = self.tile.geometry()
        def swap(_room_id):
            self.tile.setGeometry(incoming.geometry())
            incoming.setGeometry(before)
        self.tile.tileDropped.connect(swap)
        mime = QMimeData()
        mime.setData(TILE_MIME, b'1001')
        session, snapshot, hotspot = tile_drag_visual(incoming, QPoint(70, 60))
        session.start(incoming, mime, snapshot, hotspot, self.position)
        with patch('ddm.sidebar_drag.widget_at', return_value=self.tile):
            self.assertTrue(session.finish())
        self.assertEqual(incoming.geometry(), before)
        self.assertTrue(incoming._card_drop_overlay.timer.isActive())
        self.assertIsNone(session.ghost)

    def test_wall_card_falls_back_to_room_metadata_without_reading_video_pixels(self):
        with patch.object(self.tile.video, 'grab', side_effect=AssertionError('Do not capture native video')):
            session, snapshot, hotspot = tile_drag_visual(self.tile, QPoint(70, 60))
        self.assertIsNone(session)
        self.assertFalse(snapshot.isNull())
        self.assertTrue(snapshot.rect().contains(hotspot))

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
                def state_changed(state):
                    self.tile._player_active = state == 'playing'
                    self.tile._connecting = state in ('connecting', 'buffering')
                    if self.tile._connecting:
                        self.tile.spinner.start()
                    else:
                        self.tile.spinner.stop()
                player.stateChanged.connect(state_changed)
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
                overlay_handle = int(overlay.winId())
                spinner_handle = int(self.tile.spinner.winId())
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
                self.assertFalse(self.tile.spinner.isVisible())
                import ctypes
                from ctypes import wintypes
                visible = ctypes.windll.user32.IsWindowVisible
                visible.argtypes = (wintypes.HWND,)
                visible.restype = wintypes.BOOL
                self.assertFalse(visible(overlay_handle), 'No native transition window may remain above playback')
                self.assertFalse(visible(spinner_handle), 'The original native loader must hide after playing')
                self.window.sidebar = self.sidebar
                mime = QMimeData()
                mime.setData(TILE_MIME, b'1001')
                session, snapshot, hotspot = tile_drag_visual(self.tile, QPoint(70, 60))
                session.start(self.tile, mime, snapshot, hotspot, self.position)
                self.assertTrue(session.ghost.isVisible())
                before = player._prop('time-pos')
                pump(APP, .12)
                self.assertGreater(player._prop('time-pos'), before)
                session.cancel()
                self.assertIsNone(session.ghost)
                self.assertIs(player.player, core)
                self.assertEqual(int(self.tile.video.winId()), handle)
            finally:
                player.release()


if __name__ == '__main__':
    unittest.main()
