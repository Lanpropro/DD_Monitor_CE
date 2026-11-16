"""Isolated loopback transfers and production update preview lifecycle."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'dev')]
from ddm import online
from update_preview_server import PreviewServer


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='ddm-preview-check-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.server = PreviewServer(self.root, unit=256 * 1024, delay=.001)
        self.addCleanup(self.server.stop)
        self.client = online.session()
        self.client.trust_env = False
        self.addCleanup(self.client.close)

    def test_actual_transfer_checks_hash_and_does_not_relax_official_source_validation(self):
        offer = self.server.offer('app')
        progress = []
        target = self.root / 'download.zip'
        online.download(offer, target, self.client, progress=lambda *values: progress.append(values))
        self.assertEqual(target.read_bytes(), self.server.assets['/app.zip'].read_bytes())
        self.assertEqual(progress[-1], (offer['size'], offer['size']))
        self.assertGreater(len(progress), 3)
        with self.assertRaises(ValueError):
            online.asset_info({'browser_download_url': offer['url']}, online.APP_REPOSITORY)

    def test_disconnect_failure_then_manual_retry_and_corruption(self):
        offer = self.server.offer('app')
        target = self.root / 'retry.zip'
        self.server.scenario(2)
        self.server.delay = .001
        with self.assertRaises(online.requests.exceptions.ChunkedEncodingError):
            online.download(offer, target, self.client)
        self.assertFalse(target.exists())
        self.assertFalse(target.with_suffix('.zip.part').exists())
        online.download(offer, target, self.client)
        self.assertEqual(target.stat().st_size, offer['size'])
        self.server.scenario(3)
        self.server.delay = .001
        target.unlink()
        with self.assertRaisesRegex(ValueError, '完整性校验失败'):
            online.download(offer, target, self.client)
        self.assertFalse(target.exists())
        online.download(offer, target, self.client)
        self.assertTrue(target.exists())

    def test_preview_smoke_uses_production_widgets_without_real_installation(self):
        result = subprocess.run([sys.executable, str(ROOT / 'dev/checks/bootstrap.py'),
                                 str(ROOT / 'dev/update_preview.py'), '--smoke'], cwd=ROOT,
                                env=dict(os.environ, QT_QPA_PLATFORM='offscreen', DDM_CHECK_MODE='offline'),
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn('confirmation without installation', result.stdout)


if __name__ == '__main__':
    unittest.main()
