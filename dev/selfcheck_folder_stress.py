"""Offline scale-probe report contracts and real bulk-capture routing; no timing thresholds."""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'dev')]
os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from ddm import config, images, motion
from ddm.folder_motion_capture import FolderMotionCapture
from ddm.responsiveness_probe import Probe
from ddm.sidebar_widgets import Sidebar


class FolderStressTests(unittest.TestCase):
    def test_smoke_report_tracks_resources_and_deferred_covers_without_media(self):
        with tempfile.TemporaryDirectory(prefix='ddm-stress-report-') as temporary:
            result = subprocess.run([sys.executable, str(ROOT / 'dev/checks/bootstrap.py'),
                str(ROOT / 'dev/folder_stress_preview.py'), '--preview-folder-stress', '--rooms', '100', '--folders', '8',
                '--smoke', '--output', temporary], cwd=ROOT,
                env=dict(os.environ, QT_QPA_PLATFORM='offscreen', DDM_CHECK_MODE='offline'),
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8',
                errors='replace', timeout=90)
            self.assertEqual(result.returncode, 0, result.stdout[-6000:])
            directory = Path(temporary)
            report = json.loads((directory / 'summary.json').read_text(encoding='utf-8'))
            self.assertTrue(report['success'])
            self.assertEqual(report['rooms_requested'], 100)
            self.assertIn('Synthetic', report['scope'])
            stages = {row['stage']: row for row in report['stages']}
            self.assertTrue({'setup', 'expand_all', 'collapse_all', 'scroll_bottom',
                             'scroll_to_deferred', 'live_only'} <= stages.keys())
            expanded = next(row for row in report['stages'] if row['stage'] == 'expand_all')
            self.assertGreater(expanded['dirty_covers'], 0)
            self.assertEqual(expanded['dirty_visible_covers'], 0)
            self.assertGreater(expanded['visible_cards'], 0)
            self.assertIn('resort', expanded['methods'])
            self.assertIn('cover_renders', expanded['render_calls'])
            for row in report['stages']:
                self.assertEqual(row['rooms'], 100)
                self.assertEqual(row['active_players'], 0)
                self.assertGreater(row['widgets'], 0)
                self.assertIn('cpu_seconds', row['counters'])
                self.assertGreaterEqual(row['operation_ms'], 0)
                self.assertGreaterEqual(row['max_event_gap_ms'], 0)
            for name in ('summary.json', 'events.jsonl'):
                self.assertLess((directory / name).stat().st_size, 1024 * 1024)

    def test_bulk_capture_covers_controller_toggle_toolbar_and_sidebar_setter(self):
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory(prefix='ddm-bulk-capture-') as temporary, ExitStack() as stack:
            stack.enter_context(patch.object(config, 'DATA_ROOT', temporary))
            stack.enter_context(patch.object(config, 'CONFIG_PATH', str(Path(temporary) / 'config.json')))
            stack.enter_context(patch.object(images, 'REPO', temporary))
            stack.enter_context(patch.object(motion, 'enabled', return_value=False))
            sidebar = Sidebar([dict(room_id=f'fixture:{index}', uname='合成主播', live=True)
                               for index in range(3)], auto_compact=False)
            sidebar.resize(320, 700)
            sidebar.show()
            probe = Probe(Path(temporary) / 'bulk.jsonl')
            capture = FolderMotionCapture(probe, sidebar)
            try:
                sidebar.toggle_all_folders()
                self.assertEqual(capture.record['action'], 'collapse-all')
                capture.finish('test')
                sidebar.set_all_folders_collapsed(False)
                self.assertEqual(capture.record['action'], 'expand-all')
                capture.finish('test')
                app.processEvents()
                QTest.mouseClick(sidebar.navigation.folder_toggle_button, Qt.LeftButton)
                self.assertEqual(capture.record['action'], 'collapse-all')
                capture.finish('test')
                rows = [json.loads(line) for line in (Path(temporary) / 'bulk.jsonl').read_text(
                    encoding='utf-8').splitlines()]
                bulk = [row for row in rows if row['phase'] == 'folder-motion']
                self.assertEqual([row['action'] for row in bulk],
                                 ['collapse-all', 'expand-all', 'collapse-all'])
                self.assertTrue(all('toggle_ms' in row and row['layouts'] for row in bulk))
            finally:
                capture.close()
                probe.stop()
                sidebar.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


if __name__ == '__main__':
    unittest.main()
