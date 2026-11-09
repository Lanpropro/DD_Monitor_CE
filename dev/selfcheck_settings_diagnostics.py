"""Diagnostic UI/export regression with temporary installations and no accounts."""
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import weakref
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QTimer
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QDialog, QVBoxLayout
import shiboken6

from ddm import qt_lifecycle, theme
from ddm.diagnostic_export import DiagnosticExport
from ddm.settings_diagnostics import DiagnosticsPage


class DiagnosticSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        font = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'Fonts/msyh.ttc'
        if font.is_file():
            QFontDatabase.addApplicationFont(str(font))
        cls.app.setFont(QFont('Microsoft YaHei', 10))
        theme.apply('dark')
        cls.build = tempfile.TemporaryDirectory(prefix='ddm-diagnostic-ui-backend-')
        cls.addClassCleanup(cls.build.cleanup)
        cls.executable = Path(cls.build.name) / 'DDMonitorDiagnostics.exe'
        subprocess.run(['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File',
            str(ROOT / 'dev/build_diagnostics.ps1'), '-OutDir', cls.build.name, '-NoZip'], check=True, timeout=60, capture_output=True)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='ddm-diagnostic-page-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / 'main.py').write_text('raise RuntimeError("must not run app")', encoding='utf-8')
        (self.root / 'out').mkdir()
        self.env = patch.dict(os.environ, DDM_DIAGNOSTIC_APP_ROOT=str(self.root))
        self.env.start()
        self.addCleanup(self.env.stop)
        self.tool = patch('ddm.diagnostic_export.collector_path', return_value=self.executable)
        self.tool.start()
        self.addCleanup(self.tool.stop)

    def wait(self, predicate, timeout=20):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.01)
        self.assertTrue(predicate(), 'Timed out waiting for diagnostic child')

    def page(self):
        dialog = QDialog()
        layout = QVBoxLayout(dialog)
        page = DiagnosticsPage({}, dialog)
        layout.addWidget(page)
        dialog.resize(720, 600)
        dialog.show()
        self.app.processEvents()
        self.addCleanup(dialog.close)
        self.addCleanup(page.export.stop)
        page.destination.setText(str(self.root / 'out'))
        return dialog, page

    def test_page_export_keeps_defaults_and_manual_delivery(self):
        dialog, page = self.page()
        self.assertFalse(page.dump_enabled.isChecked())
        self.assertFalse(page.include_dumps.isChecked())
        page.description.setPlainText('fixture report')
        page._generate()
        self.assertFalse(page.generate.isEnabled())
        self.wait(lambda: page.zip_path is not None or not page.export.busy)
        self.assertIsNotNone(page.zip_path, page.status.text())
        self.assertIn('手动发送', page.status.text())
        with zipfile.ZipFile(page.zip_path) as archive:
            self.assertEqual(json.loads(archive.read('problem.json'))['description'], 'fixture report')
            self.assertFalse(json.loads(archive.read('native-crashes.json'))['dump_export_requested'])
        self.assertTrue(page.generate.isEnabled())
        self.assertTrue(page.summary.isEnabled())
        self.assertIsNone(page.export.request)
        # Fixed actions remain in the viewport while long form content scrolls.
        self.assertLessEqual(page.generate.mapTo(dialog, page.generate.rect().bottomRight()).y(), dialog.height())
        if os.environ.get('DDM_DIAGNOSTIC_UI_IMAGE'):
            dialog.grab().save(os.environ['DDM_DIAGNOSTIC_UI_IMAGE'])

    def test_cancel_and_dialog_close_stop_child_and_remove_private_request(self):
        dialog, page = self.page()
        # A real sleeping child makes cancellation deterministic; it is not a timing benchmark.
        exporter = page.export
        exporter.busy = True
        exporter.request = self.root / 'private-request.json'
        exporter.request.write_text('private fixture')
        request = exporter.request
        exporter.partial = self.root / 'out/DDMonitorCE-diagnostics-fixture.zip.part'
        exporter.partial.write_bytes(b'incomplete')
        partial = exporter.partial
        exporter.process.start(sys.executable, ['-c', 'import time; time.sleep(30)'])
        self.assertTrue(exporter.process.waitForStarted(3000))
        dialog.reject()
        self.wait(lambda: not exporter.busy)
        self.assertFalse(request.exists())
        self.assertFalse(partial.exists())
        self.assertEqual(list((self.root / 'out').glob('*.zip')), [])

    def test_missing_tool_is_visible_and_does_not_disable_form(self):
        _dialog, page = self.page()
        with patch('ddm.diagnostic_export.collector_path', return_value=None):
            page._generate()
        self.assertIn('未找到', page.status.text())
        self.assertTrue(page.generate.isEnabled())

    def test_setting_reset_and_snapshot_survive_without_exporting_dumps(self):
        from ddm.dialogs import SettingsDialog
        dialog = SettingsDialog({'native_crash_dump': True}, {}, preview=True)
        self.addCleanup(dialog.close)
        self.addCleanup(dialog.deleteLater)
        self.assertEqual(dialog.PAGE_INDEX['updates'], 8)
        self.assertEqual(dialog.PAGE_INDEX['diagnostics'], 9)
        page = dialog._page(9)
        self.assertTrue(page.dump_enabled.isChecked())
        self.assertFalse(page.include_dumps.isChecked())
        page.reset()
        self.assertFalse(dialog.settings()['native_crash_dump'])

    def test_independent_settings_worker_exports_from_host_installation_and_saves_option(self):
        from ddm import config, settings_process
        shutil.copyfile(self.executable, self.root / 'DDMonitorDiagnostics.exe')
        client = settings_process.SettingsProcess()
        saved, failures = [], []
        client.saved.connect(saved.append)
        client.failed.connect(failures.append)
        command = (sys.executable, [str(Path(__file__).resolve()), '--diagnostic-worker'])
        with patch.object(config, 'REPO', str(self.root)), \
                patch.object(settings_process, 'worker_command', return_value=command), \
                patch.dict(os.environ, DDM_DIAGNOSTIC_TEST_OUTPUT=str(self.root / 'out')):
            try:
                client.open(dict(config.DEFAULT_SETTINGS), {})
                self.wait(lambda: bool(saved) or bool(failures))
                self.assertFalse(failures)
                self.assertTrue(saved[0]['settings']['native_crash_dump'])
                with zipfile.ZipFile(next((self.root / 'out').glob('*.zip'))) as archive:
                    self.assertEqual(json.loads(archive.read('problem.json'))['description'], 'worker fixture')
            finally:
                client.finish()

    def test_lifecycle_links_parent_during_its_own_constructor(self):
        qt_lifecycle.start(self.root)
        self.addCleanup(qt_lifecycle.close)

        class Child(QObject):
            @qt_lifecycle.construction
            def __init__(self, parent=None):
                super().__init__(parent)

        class Parent(QObject):
            @qt_lifecycle.construction
            def __init__(self):
                super().__init__()
                self.child = Child(parent=self)

        parent = Parent()
        rows = [json.loads(line) for line in next(self.root.glob('qt-lifecycle-*.jsonl')).read_text().splitlines()]
        self.assertEqual(rows[1]['parent'], rows[0]['object'])
        self.assertEqual([row['stage'] for row in rows], ['construct.request', 'construct.request', 'construct.ready', 'construct.ready'])
        parent.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_lifecycle_records_failed_constructor_run_and_destruction_without_retention(self):
        qt_lifecycle.start(self.root)
        self.addCleanup(qt_lifecycle.close)

        class Worker(QObject):
            @qt_lifecycle.construction
            def __init__(self, fail=False):
                if fail:
                    raise ValueError('fixture')
                super().__init__()

            @qt_lifecycle.running
            def run(self):
                raise ValueError('fixture')

        with self.assertRaises(ValueError):
            Worker(True)
        worker = Worker()
        with self.assertRaises(ValueError):
            worker.run()
        qt_lifecycle.delete_requested(worker)
        worker.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertFalse(shiboken6.isValid(worker))
        reference = weakref.ref(worker)
        del worker
        self.assertIsNone(reference())
        rows = [json.loads(line) for line in next(self.root.glob('qt-lifecycle-*.jsonl')).read_text().splitlines()]
        self.assertEqual([row['stage'] for row in rows], ['construct.request', 'construct.failed',
            'construct.request', 'construct.ready', 'run.begin', 'run.end', 'deleteLater.request', 'destroyed'])
        self.assertEqual(len({row['object'] for row in rows[2:]}), 1)
        self.assertTrue(all(set(row) == {'stage', 'object', 'kind', 'parent', 'pid', 'thread', 'at_ns', 'mono_ns'} for row in rows))


def diagnostic_worker():
    from ddm import dialogs, settings_process
    original = dialogs.SettingsDialog

    class AutomatedDialog(original):
        def showEvent(self, event):
            super().showEvent(event)
            QTimer.singleShot(40, self.exercise)

        def exercise(self):
            self.nav.setCurrentRow(9)
            page = self._page(9)
            assert not page.include_dumps.isChecked()
            page.destination.setText(os.environ['DDM_DIAGNOSTIC_TEST_OUTPUT'])
            page.description.setPlainText('worker fixture')

            def done(_path):
                page.dump_enabled.setChecked(True)
                self.confirm_button.click()

            page.export.completed.connect(done)
            page._generate()

    dialogs.SettingsDialog = AutomatedDialog
    return settings_process.run_worker()


if __name__ == '__main__' and sys.argv[1:] == ['--diagnostic-worker']:
    raise SystemExit(diagnostic_worker())
elif __name__ == '__main__':
    unittest.main()
