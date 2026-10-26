"""Offline checks for embedded player audio teardown options."""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication, QWidget
from ddm.player import TilePlayer


class PlayerLifetimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_audio_output_is_not_retained_until_gui_thread_termination(self):
        for silent in (False, True):
            with self.subTest(silent=silent), patch('ddm.player.mpv.MPV') as create:
                widget = QWidget()
                player = TilePlayer(widget, silent=silent)
                try:
                    player.bind()
                    options = create.call_args.kwargs
                    self.assertIs(options.get('gapless_audio'), False)
                    self.assertEqual(options['ao'], 'null' if silent else 'wasapi')
                    self.assertEqual(options['audio'], 'no' if silent else 'auto')
                    self.assertTrue(options['idle'])
                    self.assertTrue(options['keep_open'])
                    player.bind()
                    self.assertEqual(create.call_count, 1)
                    player.release()
                    player.release()
                    create.return_value.terminate.assert_called_once_with()
                finally:
                    player.release()
                    widget.close()

    def test_rebound_core_keeps_the_audio_teardown_option(self):
        widget = Mock()
        widget.winId.side_effect = (100, 200)
        with patch('ddm.player.mpv.MPV', side_effect=(Mock(), Mock())) as create:
            player = TilePlayer(widget)
            try:
                player.bind()
                first = player.player
                player.bind()
                first.terminate.assert_called_once_with()
                self.assertEqual(create.call_count, 2)
                for call in create.call_args_list:
                    self.assertIs(call.kwargs.get('gapless_audio'), False)
            finally:
                player.release()

    def test_shared_popup_keeps_one_idle_core_but_releases_media_and_watchers(self):
        widget = QWidget()
        with patch('ddm.player.mpv.MPV') as create:
            player = TilePlayer(widget, silent=True)
            try:
                player.bind()
                core = player.player
                for _ in range(25):
                    player._media = 'local-test.mp4'
                    player._watch.start()
                    player._picture_watch.start()
                    proxy = player._hls_proxy = Mock()
                    player.stop(keep_core=True)
                    self.assertIsNone(player._media)
                    self.assertIsNone(player._hls_proxy)
                    proxy.stop.assert_called_once_with()
                    self.assertFalse(player._watch.isActive())
                    self.assertFalse(player._picture_watch.isActive())
                    core.terminate.assert_not_called()
                    player.bind()
                self.assertEqual(create.call_count, 1, 'Only the shared popup retains a core')
                self.assertEqual(core.command.call_count, 25)
                self.assertTrue(all(call.args == ('stop',) for call in core.command.call_args_list))
                player.release()
                player.release()
                core.terminate.assert_called_once_with()
            finally:
                player.release()
                widget.close()

    def test_normal_thumbnail_stop_still_destroys_its_silent_core(self):
        widget = QWidget()
        with patch('ddm.player.mpv.MPV') as create:
            player = TilePlayer(widget, silent=True)
            try:
                player.bind()
                player.stop()
                create.return_value.terminate.assert_called_once_with()
                self.assertIsNone(player.player)
            finally:
                player.release()
                widget.close()


if __name__ == '__main__':
    unittest.main()
