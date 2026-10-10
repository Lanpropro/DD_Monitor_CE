"""静音巡检回归：使用真实方法与确定性音频替身，不联网、不播放、不写用户配置。"""
from contextlib import redirect_stderr
import ctypes
import io
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
os.environ.setdefault('DDM_NO_SAVE', '1')
os.environ.setdefault('PYTHON_VLC_LIB_PATH', str(REPO / 'libvlc.dll'))

from ddm.app import MainWindow  # noqa: E402
from ddm.audio_output import StereoOutput, linear_to_vlc_volume as vlc_volume  # noqa: E402
from ddm.player import SILENT_VOLUME, TilePlayer  # noqa: E402

audit = MainWindow._audit_audio

class FakeVlc:
    def __init__(self, volume, pcm=False):
        self.volume, self.pcm = volume, pcm
    def audio_get_mute(self):
        return 0  # 正常静音时此标志仍为 False：复现用户报告
    def audio_get_volume(self):
        if self.pcm:
            raise AssertionError('PCM routing must not query VLC volume')
        return self.volume
    def audio_set_volume(self, volume):
        self.volume = volume

class FakePlayer:
    silent = False
    _released = False
    _audio_ready = True
    def __init__(self, muted, volume, pcm=False):
        self.muted, self.volume, self.uses_pcm_routing = muted, volume, pcm
        self.player = FakeVlc(SILENT_VOLUME if muted else vlc_volume(volume), pcm)
        self._audio_output = SimpleNamespace(enabled=not muted, volume=volume)
        self.calls = []
    def set_muted(self, muted):
        self.calls.append(('mute', muted))
        self.muted = muted
        self.player.volume = SILENT_VOLUME if muted else vlc_volume(self.volume)
        self._audio_output.enabled = not muted
    def set_volume(self, volume):
        self.calls.append(('volume', volume))
        self.volume = volume
        self._audio_output.volume = volume
        self.player.volume = SILENT_VOLUME if self.muted else vlc_volume(volume)

class AuditTests(unittest.TestCase):
    def make(self, muted=True, pcm=False):
        tile = SimpleNamespace(room={'room_id': '1', 'uname': 'test'}, muted=muted, volume=60)
        player = FakePlayer(muted, tile.volume, pcm)
        win = SimpleNamespace(wall=SimpleNamespace(tiles=[tile]),
                              players=SimpleNamespace(get=lambda item: player if item is tile else None))
        return win, tile, player
    def check(self, win, repetitions=1):
        log = io.StringIO()
        with redirect_stderr(log):
            for _ in range(repetitions):
                audit(win)
        return log.getvalue()
    def test_muted_native_does_not_repeat(self):
        for volume in (0, 1):
            with self.subTest(volume=volume):
                win, _, player = self.make()
                player.player.volume = volume
                self.assertEqual(self.check(win, 10), '')
                self.assertEqual(player.calls, [])
    def test_pcm_mute_and_unmute_do_not_repeat(self):
        for muted in (False, True):
            with self.subTest(muted=muted):
                win, _, player = self.make(muted, True)
                self.assertEqual(self.check(win, 10), '')
                self.assertEqual(player.calls, [])
    def test_player_mute_drift_is_repaired(self):
        for muted in (False, True):
            for pcm in (False, True):
                with self.subTest(muted=muted, pcm=pcm):
                    win, _, player = self.make(muted, pcm)
                    player.muted = not muted
                    self.assertTrue(self.check(win))
                    self.assertEqual(player.calls, [('mute', muted)])
                    self.assertEqual(self.check(win, 5), '')
    def test_pcm_output_switch_drift_is_repaired(self):
        for muted in (False, True):
            with self.subTest(muted=muted):
                win, _, player = self.make(muted, True)
                player._audio_output.enabled = muted
                self.assertTrue(self.check(win))
                self.assertEqual(player.calls, [('mute', muted)])
                self.assertEqual(self.check(win, 5), '')
    def test_pcm_output_volume_drift_is_repaired(self):
        for muted in (False, True):
            with self.subTest(muted=muted):
                win, _, player = self.make(muted, True)
                player._audio_output.volume = 5
                self.assertTrue(self.check(win))
                self.assertEqual(player.calls, [('volume', 60)])
                self.assertEqual(self.check(win, 5), '')
    def test_native_muted_output_drift_is_repaired(self):
        win, _, player = self.make()
        player.player.volume = 80
        self.assertTrue(self.check(win))
        self.assertEqual(player.calls, [('mute', True)])
        self.assertEqual(self.check(win, 5), '')
    def test_native_unmuted_volume_drift_is_repaired(self):
        win, _, player = self.make(False)
        player.player.volume = 5
        self.assertTrue(self.check(win))
        self.assertEqual(player.calls, [('volume', 60)])
        self.assertEqual(self.check(win, 5), '')
    def test_consistent_native_output_is_quiet(self):
        win, _, player = self.make(False)
        self.assertEqual(self.check(win, 10), '')
        self.assertEqual(player.calls, [])
    def test_unavailable_native_volume_is_skipped(self):
        win, _, player = self.make()
        player.player.volume = -1
        self.assertEqual(self.check(win), '')
        self.assertEqual(player.calls, [])
    def test_loading_preview_and_released_players_are_skipped(self):
        for attribute, value in (('_audio_ready', False), ('silent', True), ('_released', True)):
            with self.subTest(attribute=attribute):
                win, _, player = self.make()
                setattr(player, attribute, value)
                player.muted = False
                self.assertEqual(self.check(win), '')
                self.assertEqual(player.calls, [])

    def test_real_pcm_setters_repair_output_without_repeating_or_affecting_neighbor(self):
        """实际播放器控制方法与 PCM 处理，只替换 VLC 和音频设备。"""
        win, tile, player = self.make(True, True)
        sink = Mock(active=True)
        neighbor_sink = Mock(active=True)
        neighbor = StereoOutput(lambda: neighbor_sink)
        player._audio_output = StereoOutput(lambda: sink)
        player._apply_volume = lambda: TilePlayer._apply_volume(player)
        player.set_muted = Mock(side_effect=lambda value: TilePlayer.set_muted(player, value))
        player.set_volume = Mock(side_effect=lambda value: TilePlayer.set_volume(player, value))
        samples = ctypes.create_string_buffer(b'\x10\x27\xf0\xd8')
        address = ctypes.addressof(samples)
        try:
            player.set_volume(tile.volume)
            player.set_muted(tile.muted)
            player.set_volume.reset_mock()
            player.set_muted.reset_mock()
            neighbor.set_enabled(True)
            for muted in (True, False, True):
                tile.muted = muted
                player.set_muted(muted)
                player.set_muted.reset_mock()
                self.assertEqual(self.check(win, 10), '')
                player.set_muted.assert_not_called()
                # 人为让输出开关与格子相反，巡检必须修复实际样本输出。
                player._audio_output.set_enabled(muted)
                self.assertTrue(self.check(win))
                player.set_muted.assert_called_once_with(muted)
                self.assertEqual(self.check(win, 5), '')
                sink.write.reset_mock()
                player._audio_output.write(address, 1)
                if muted:
                    sink.write.assert_not_called()
                else:
                    sink.write.assert_called_once_with(b'\x70\x17\x90\xe8')
                neighbor.write(address, 1)
                self.assertTrue(neighbor.enabled)
                self.assertEqual(neighbor.volume, 100)
            self.assertEqual(neighbor_sink.write.call_count, 3)
        finally:
            player._audio_output.close()
            neighbor.close()

if __name__ == '__main__':
    unittest.main(verbosity=2)
