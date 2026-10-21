"""Offline background proxy/cache/cancellation checks with synthetic local media."""
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DDM_NO_SAVE'] = '1'
from PySide6.QtWidgets import QApplication, QWidget
from ddm import config, skin_video
from ddm.skins import BackgroundLayer


class SkinVideoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.directory = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch.object(config, 'REPO', str(self.directory)))
        self.stack.enter_context(patch.object(skin_video, '_adopt_process'))
        self.source = self.directory / 'original with spaces.mp4'
        self.source.write_bytes(b'original fixture')

    def successful_process(self, command, **kwargs):
        Path(command[-1]).write_bytes(b'completed proxy')
        return Mock(returncode=0, communicate=Mock(return_value=(None, b'')), poll=Mock(return_value=0))

    def test_cache_reuse_source_preservation_and_invalidation(self):
        original = self.source.read_bytes()
        with patch.object(skin_video, 'ffmpeg_path', return_value='ffmpeg'), \
                patch.object(skin_video.subprocess, 'Popen', side_effect=self.successful_process) as start:
            first = skin_video.prepare_video(self.source)
            self.assertEqual(first, skin_video.prepare_video(self.source))
            self.assertEqual(start.call_count, 1)
            command = start.call_args.args[0]
            self.assertIn('fps=15', command[command.index('-vf')+1])
            self.assertIn('min(1920,iw)', command[command.index('-vf')+1])
            self.assertIn('min(1080,ih)', command[command.index('-vf')+1])
            self.assertIn('-an', command)
            self.assertNotEqual(command[-1], str(self.source))
            self.assertEqual(self.source.read_bytes(), original)
            self.source.write_bytes(original + b'changed')
            self.assertNotEqual(skin_video.proxy_path(self.source), Path(first))
            self.assertNotEqual(skin_video.prepare_video(self.source), first)

    def test_failure_and_cancellation_remove_only_partial_copies(self):
        original = self.source.read_bytes()
        process = Mock(returncode=1, communicate=Mock(return_value=(None, b'bad input')),
                       poll=Mock(return_value=1))
        def failed(command, **kwargs):
            Path(command[-1]).write_bytes(b'partial')
            return process
        with patch.object(skin_video, 'ffmpeg_path', return_value='ffmpeg'), \
                patch.object(skin_video.subprocess, 'Popen', side_effect=failed):
            with self.assertRaisesRegex(ValueError, '背景副本生成失败'):
                skin_video.prepare_video(self.source)
            checks = iter((False, True))
            self.assertIsNone(skin_video.prepare_video(self.source, lambda: next(checks)))
            process.kill.assert_called_once()
        self.assertEqual(self.source.read_bytes(), original)
        self.assertFalse(list((self.directory/'cache').rglob('*.mp4')))

    def test_missing_encoder_and_pre_cancel_do_not_touch_source(self):
        with patch.object(skin_video, 'ffmpeg_path', return_value=''), \
                patch.object(skin_video.subprocess, 'Popen') as start:
            with self.assertRaisesRegex(ValueError, '找不到 FFmpeg'):
                skin_video.prepare_video(self.source)
            self.assertIsNone(skin_video.prepare_video(self.source, lambda: True))
            start.assert_not_called()

    def test_source_changed_during_conversion_does_not_publish_stale_cache(self):
        target = skin_video.proxy_path(self.source)
        def changed(command, **kwargs):
            process = self.successful_process(command, **kwargs)
            self.source.write_bytes(b'new source')
            return process
        with patch.object(skin_video, 'ffmpeg_path', return_value='ffmpeg'), \
                patch.object(skin_video.subprocess, 'Popen', side_effect=changed):
            with self.assertRaisesRegex(ValueError, '转换期间发生变化'):
                skin_video.prepare_video(self.source)
        self.assertFalse(target.exists())
        self.assertFalse(list(target.parent.glob('*.partial.mp4')))

    def test_layer_ignores_old_jobs_and_keeps_original_asset_identity(self):
        root = QWidget()
        layer = BackgroundLayer(root, root)
        self.addCleanup(root.close)
        with patch.object(layer, '_play_video') as play:
            old, current = Mock(), Mock()
            layer.path = str(self.source)
            layer._proxy_job = current
            layer.preparing = True
            layer._proxy_ready(old, 'old.mp4')
            layer._proxy_failed(old, 'old failure')
            play.assert_not_called()
            self.assertTrue(layer.preparing)
            layer._proxy_ready(current, 'cached.mp4')
            play.assert_called_once_with('cached.mp4')
            self.assertFalse(layer.preparing)
            self.assertEqual(layer.path, str(self.source))
            layer._proxy_failed(current, 'conversion failed')
            self.assertEqual(layer.warning, 'conversion failed')
            self.assertEqual(play.call_args.args, (str(self.source),))
            layer.cancel_preparation()
            current.requestInterruption.assert_called_once()
            self.assertIsNone(layer._proxy_job)

    def test_cached_load_and_static_first_frame_skip_transcoding(self):
        root = QWidget()
        layer = BackgroundLayer(root, root)
        self.addCleanup(root.close)
        target = skin_video.proxy_path(self.source)
        target.parent.mkdir(parents=True)
        target.write_bytes(b'cached')
        with patch.object(layer, '_play_video') as play, \
                patch.object(skin_video, 'VideoProxy') as worker:
            layer.load(str(self.source))
            play.assert_called_once_with(target)
            self.assertEqual(layer.path, str(self.source))
            layer.load(str(self.source), video_enabled=False)
            self.assertEqual(play.call_args.args, (self.source,))
            worker.assert_not_called()

    def test_real_4k_60fps_becomes_1080p_15fps_silent_video_without_touching_source(self):
        executable = skin_video.ffmpeg_path()
        probe = shutil.which('ffprobe') or str(Path(executable).with_name('ffprobe.exe'))
        if not executable or not Path(probe).is_file():
            self.skipTest('Local FFmpeg and ffprobe are required for media validation')
        self.source.unlink()
        subprocess.run([executable, '-v', 'error', '-f', 'lavfi', '-i',
                        'testsrc2=size=3840x2160:rate=60', '-t', '0.5',
                        '-c:v', 'libx264', '-preset', 'ultrafast', '-threads', '2',
                        '-pix_fmt', 'yuv420p', str(self.source)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        original = hashlib.sha256(self.source.read_bytes()).hexdigest()
        job = skin_video.VideoProxy(str(self.source))
        ready, errors = [], []
        job.ready.connect(ready.append)
        job.failed.connect(errors.append)
        job.start()
        self.assertTrue(job.wait(30000))
        self.app.processEvents()
        self.assertFalse(errors)
        self.assertEqual(len(ready), 1)
        output = subprocess.check_output([probe, '-v', 'error', '-show_streams',
                                          '-of', 'json', ready[0]])
        streams = json.loads(output)['streams']
        self.assertEqual(len(streams), 1)
        self.assertEqual((streams[0]['width'], streams[0]['height']), (1920, 1080))
        self.assertEqual(streams[0]['r_frame_rate'], '15/1')
        self.assertEqual(streams[0]['codec_type'], 'video')
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), original)
        self.assertFalse(list(Path(ready[0]).parent.glob('*.partial.mp4')))


if __name__ == '__main__':
    unittest.main()
