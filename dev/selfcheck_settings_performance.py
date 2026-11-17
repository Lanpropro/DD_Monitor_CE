"""Settings capture contracts only; these are not performance measurements."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication
from ddm import config, theme
from ddm.dialogs import SettingsDialog
from ddm.settings_autosave import SettingsAutoSave
from ddm.settings_performance import SettingsProbe, install
from ddm.settings_window import SettingsWindow

APP = QApplication.instance() or QApplication([])


class CaptureTests(unittest.TestCase):
    def test_disabled_capture_does_not_install_or_create_logs(self):
        with patch.dict(os.environ, {'DDM_SETTINGS_PERFORMANCE_CAPTURE': '0'}):
            self.assertIsNone(install('worker'))
            self.assertIsNone(getattr(APP, '_settings_performance', None))

    def test_nested_calls_preserve_result_and_exception_without_input_values(self):
        class Example:
            def outer(self, value):
                return self.inner(value) + 1

            def inner(self, value):
                return len(value)

            def failed(self):
                raise ValueError('fixture')

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'capture.jsonl'
            probe = SettingsProbe(path)
            try:
                for name in ('outer', 'inner', 'failed'):
                    probe.wrap(Example, name)
                self.assertEqual(Example().outer('private-input-marker'), 21)
                with self.assertRaisesRegex(ValueError, 'fixture'):
                    Example().failed()
                self.assertEqual(probe.active, [])
            finally:
                probe.stop()
            content = path.read_text(encoding='utf-8')
            self.assertNotIn('private-input-marker', content)
            records = [json.loads(line) for line in content.splitlines()]
            calls = {record['function']: record for record in records if record['phase'] == 'settings-call'}
            self.assertTrue(calls['Example.outer']['functions'])
            self.assertEqual(calls['Example.inner']['functions'], [])
            # Stopping capture restores pass-through behavior of installed wrappers.
            self.assertEqual(Example().outer('x'), 2)

    def test_log_limit(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'capture.jsonl'
            probe = SettingsProbe(path)
            probe.records = 1199
            probe.write('last')
            probe.write('overflow')
            probe.stop()
            self.assertEqual(len(path.read_text(encoding='utf-8').splitlines()), 1)

    def test_real_dialog_is_observed_without_consuming_events_or_changing_values(self):
        baseline = SettingsDialog(dict(config.DEFAULT_SETTINGS), {}, preview=True)
        baseline.nav.setCurrentRow(6)
        expected = baseline.settings()
        baseline.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        methods = [(cls, name, getattr(cls, name)) for cls, names in (
            (SettingsDialog, ('__init__', '_page', '_on_page_changed')),
            (SettingsWindow, ('_sync_frame',)),
            (SettingsAutoSave, ('start', 'watch_page', 'flush')),
        ) for name in names]
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {
            'DDM_SETTINGS_PERFORMANCE_CAPTURE': '1', 'DDM_DIAGNOSTIC_LOG_DIR': temporary,
        }):
            probe = install('worker')
            dialog = None
            try:
                self.assertIs(install('worker'), probe)
                dialog = SettingsDialog(dict(config.DEFAULT_SETTINGS), {}, preview=True)
                dialog.show()
                APP.processEvents()
                dialog.nav.setCurrentRow(6)
                APP.processEvents()
                self.assertEqual(dialog.stack.currentIndex(), 6)
                self.assertFalse(APP._settings_paint_capture.eventFilter(dialog, QEvent(QEvent.User)))
                self.assertEqual(dialog.settings(), expected)
            finally:
                if dialog is not None:
                    dialog.hide()
                    dialog.deleteLater()
                    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
                probe.stop()
                APP._settings_performance_timer.stop()
                APP._settings_performance_timer.deleteLater()
                APP.removeEventFilter(APP._settings_paint_capture)
                APP._settings_paint_capture.deleteLater()
                for cls, name, original in methods:
                    setattr(cls, name, original)
                for name in ('_settings_performance', '_settings_performance_timer', '_settings_paint_capture'):
                    delattr(APP, name)
            records = [json.loads(line) for line in
                       (Path(temporary) / f'settings-performance-{os.getpid()}.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertTrue(any(record['phase'] == 'first-paint' for record in records))
            self.assertTrue(any(record.get('page') == 6 for record in records))
            self.assertTrue(any(record.get('function') == 'SettingsDialog.__init__' for record in records))


if __name__ == '__main__':
    theme.apply('dark')
    unittest.main()
