"""开发版比赛二路自行处理 PCM，兼容移除旧音频输出的 libmpv 宿主。"""
import os
from array import array
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['DDM_NO_SAVE'] = '1'
from ddm import audio_output
from plugins_user._match_sync import engine, viewer


class CompatibilityTests(unittest.TestCase):
    def test_plugin_owns_routing(self):
        self.assertIs(viewer.route_pcm_s16_stereo, engine.route_pcm_s16_stereo)
        self.assertFalse(hasattr(audio_output, 'route_pcm_s16_stereo'))

    def test_stereo_unchanged(self):
        pcm = array('h', [32767, -32768, 123, 456]).tobytes()
        for channel in (0, 1, 2, 5):
            self.assertIs(engine.route_pcm_s16_stereo(pcm, channel), pcm)

    def test_routing_and_fallback(self):
        pcm = array('h', [32767, 32767, -32768, -32768, 100, -200, 1, -2]).tobytes()
        for implementation in (engine.audioop, None):
            with patch.object(engine, 'audioop', implementation):
                self.assertEqual(list(array('h', engine.route_pcm_s16_stereo(pcm, 3))),
                                 [32767, 0, -32768, 0, -50, 0, -1, 0])
                self.assertEqual(list(array('h', engine.route_pcm_s16_stereo(pcm, 4))),
                                 [0, 32767, 0, -32768, 0, -50, 0, -1])

    def test_frame_boundaries(self):
        for channel in (3, 4):
            self.assertEqual(engine.route_pcm_s16_stereo(b'', channel), b'')
            for length in (1, 2, 3, 5):
                with self.assertRaises(ValueError):
                    engine.route_pcm_s16_stereo(bytes(length), channel)


if __name__ == '__main__':
    unittest.main()
