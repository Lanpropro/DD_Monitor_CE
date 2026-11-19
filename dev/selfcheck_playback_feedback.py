"""Isolated playback failure feedback UI; no MainWindow, media or accounts."""
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['DDM_NO_SAVE'] = '1'
from PySide6.QtCore import QCoreApplication, QEvent, QObject, Qt
from PySide6.QtWidgets import QApplication
from ddm.playback_recovery import PlaybackRecovery


class FeedbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.host = QObject()
        self.host._resolvers, self.host.players = {}, {}
        self.host._closing = False
        self.host.start_tile, self.host.refresh_status = Mock(), Mock()
        self.recovery = PlaybackRecovery(self.host)

    def tearDown(self):
        self.recovery.shutdown()
        self.host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_feedback_is_centered_over_video_and_clears_on_success_or_room_change(self):
        from ddm.tile_widgets import Tile
        from ddm.widget_support import TILE_BAR_HEIGHT
        tile = Tile({'room_id': '1001', 'live': True})
        tile.setAttribute(Qt.WA_ShowWithoutActivating)
        tile.setWindowFlag(Qt.WindowDoesNotAcceptFocus)
        tile.move(-10000, -10000)
        tile.show()
        try:
            for active in (False, True):
                tile.set_video_active(active)
                for width, height in ((720, 450), (260, 180), (480, 600)):
                    tile.resize(width, height)
                    tile.set_status('断流，10 秒后重连（第 2 次）', detail='网络连接异常，请检查网络或代理')
                    self.app.processEvents()
                    if self.app.platformName() == 'windows':
                        self.app.processEvents()
                        self.assertTrue(tile.spinner._alpha_uploaded)
                    self.assertTrue(tile.spinner.isVisible())
                    self.assertIn('网络', tile.spinner._text.text())
                    self.assertEqual(tile.status_label.text(), '')
                    self.assertLessEqual(tile.spinner.width(), tile.video.width() - 12)
                    self.assertLessEqual(abs(tile.spinner.geometry().center().x() - tile.video.geometry().center().x()), 2)
                    self.assertLessEqual(abs(tile.spinner.geometry().center().y() - tile.video.geometry().center().y()), 2)
                    self.assertLess(tile.spinner.geometry().bottom(), height - TILE_BAR_HEIGHT)
                    if not active:
                        self.assertEqual(tile.cover.text(), '')
            tile.set_status('')
            self.assertTrue(tile.spinner.isHidden())
            self.assertEqual(tile._status_detail, '')
            tile.set_status('重连中', detail='原因暂未确定')
            tile.set_room({'room_id': '2002', 'live': True})
            self.assertEqual(tile._status_detail, '')
            self.assertTrue(tile.spinner.isHidden())
            tile.set_status('重连中', detail='原因暂未确定')
            tile.set_offline()
            self.assertEqual(tile._status_detail, '')
            self.assertTrue(tile.spinner.isHidden())
        finally:
            tile.close()
            tile.deleteLater()


    def test_failure_callbacks_update_feedback_using_current_evidence(self):
        from ddm.codec_control import CodecControl
        from ddm.stream_playback import StreamPlayback
        from ddm.tile_widgets import Tile
        tile = Tile({'room_id': '1001', 'uname': 'fixture', 'live': True})
        self.host.playback_recovery = self.recovery
        self.host._pending_capture = {}
        self.host._freeze_refreshed = self.recovery.freeze_refreshed
        self.host._schedule_retry = self.recovery.schedule_retry
        self.host._clear_freeze_recovery = self.recovery.clear_freeze
        self.host._on_picture_frozen = self.recovery.picture_frozen
        self.host._tile_of_player = lambda player: tile
        self.host.plugins = SimpleNamespace(emit=Mock(), platforms={})
        playback, codecs = StreamPlayback(self.host), CodecControl(self.host)
        tile.move(-10000, -10000)
        tile.setAttribute(Qt.WA_ShowWithoutActivating)
        tile.show()
        try:
            playback.resolve_failed(tile, 'ConnectionError: private token')
            self.assertEqual(tile._status_detail, '')
            self.recovery.cancel_retry(tile)
            playback.resolve_failed(tile, 'ConnectionError: private token')
            self.assertIn('网络', tile._status_detail)
            self.assertNotIn('private', tile.spinner._text.text())
            self.assertTrue(tile.spinner.isVisible())
            self.recovery.cancel_retry(tile)
            playback.on_player_state(tile, 'connecting')
            self.assertIn('网络', tile._status_detail)
            player = Mock(source_failure='', _source_read_error=False, _decoder_error=False)
            self.host.players[tile] = player
            codecs.decoder_fallback(player, 'none')
            self.assertIn('解码异常', tile._status_detail)
            self.assertIn('CPU', tile._status_text)
            self.assertTrue(tile.spinner.isVisible())
            player.source_failure = 'HTTP_403'
            player._decoder_error = True
            playback.on_player_state(tile, 'error')
            self.assertIn('HTTP 403', tile._status_detail)
            self.assertNotIn('解码', tile._status_detail)
            playback.on_player_state(tile, 'playing')
            self.assertEqual(tile._status_detail, '')
            self.assertTrue(tile.spinner.isHidden())
            self.assertNotIn(tile, self.recovery.failure_details)
        finally:
            tile.close()
            tile.deleteLater()

    def test_only_opted_in_wall_playback_requests_a_cover(self):
        from ddm.stream_playback import StreamPlayback
        room = {'room_id': 'm3u:test', 'platform': 'm3u'}
        tile = Mock(room=room)
        player = Mock()
        provider = SimpleNamespace(capture_first_playback_cover=False)
        host = SimpleNamespace(players={tile: player}, playback_recovery=Mock(), room_images=Mock(),
                               plugins=SimpleNamespace(platforms={'m3u': provider}, emit=Mock()))
        playback = StreamPlayback(host)
        tile.property.return_value = False
        playback.on_player_state(tile, 'connecting')
        playback.on_player_state(tile, 'playing')
        provider.capture_first_playback_cover = True
        tile.property.return_value = True
        playback.on_player_state(tile, 'playing')
        host.room_images.capture_first_frame.assert_not_called()
        tile.property.return_value = False
        playback.on_player_state(tile, 'playing')
        host.room_images.capture_first_frame.assert_called_once_with(room, player)

    def test_channel_card_becomes_live_after_playback_only(self):
        from ddm.room_status import RoomStatus
        from ddm.sidebar_item import NavItem
        from ddm.stream_playback import StreamPlayback

        room = dict(room_id='m3u:test', live=False, live_known=False, live_from_playback=True)
        item = NavItem(dict(room), 0)
        other = NavItem(dict(room_id='1001', live=False), 1)
        tile = Mock(room=dict(room))
        tile.property.return_value = False
        host = SimpleNamespace(players={tile: Mock()}, playback_recovery=Mock(),
                               plugins=SimpleNamespace(platforms={}, emit=Mock()),
                               sidebar=SimpleNamespace(items_control=SimpleNamespace(items=lambda: [item, other]),
                                                       _folder_pending={room['room_id']}, resort=Mock()))
        host.room_status = RoomStatus(host)
        playback = StreamPlayback(host)
        try:
            playback.on_player_state(tile, 'connecting')
            self.assertEqual((item.badge.text(), item.sub._full_text), ('待播放', '待播放'))
            self.assertFalse(item.room['live'])
            playback.on_player_state(tile, 'playing')
            self.assertEqual((item.badge.text(), item.sub._full_text), ('直播中', '直播中'))
            self.assertTrue(item.room['live_known'] and tile.room['live_known'])
            playback.on_player_state(tile, 'buffering')
            playback.on_player_state(tile, 'playing')
            self.assertEqual(item.badge.text(), '直播中')
            self.assertEqual(other.badge.text(), '未开播')
            host.sidebar.resort.assert_called_once_with()
        finally:
            item.deleteLater()
            other.deleteLater()


if __name__ == '__main__':
    if sys.argv[1:] == ['--native-feedback']:
        sys.argv[1:] = ['FeedbackTests.test_feedback_is_centered_over_video_and_clears_on_success_or_room_change']
    unittest.main()
