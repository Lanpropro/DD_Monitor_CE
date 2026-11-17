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
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QFont, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import QApplication, QComboBox, QWidget
from ddm import config, theme
from ddm.dialogs import SettingsDialog
from ddm.settings_autosave import SettingsAutoSave
from ddm.settings_performance import SettingsProbe, install
from ddm.settings_window import SettingsWindow

APP = QApplication.instance() or QApplication([])


class SettingsPreparationTests(unittest.TestCase):
    def test_select_reuses_measurements_and_refreshes_for_text_model_and_font_changes(self):
        from ddm.ui import SelectControl

        class CountedSelect(SelectControl):
            reads = 0

            def itemText(self, index):
                self.reads += 1
                return super().itemText(index)

        control = CountedSelect()
        try:
            control.addItems(['短', 'some longer option', '字体设置'])

            def expected():
                metrics = control.fontMetrics()
                return max((metrics.horizontalAdvance(QComboBox.itemText(control, i))
                            for i in range(control.count())), default=80) + 46

            def check_refresh():
                control.reads = 0
                self.assertEqual(control.sizeHint().width(), expected())
                for _ in range(8):
                    self.assertEqual(control.sizeHint().width(), expected())
                    self.assertEqual(control.minimumSizeHint().width(), min(180, expected()))
                self.assertEqual(control.reads, control.count())

            check_refresh()
            control.setItemText(0, 'updated text that must be measured again')
            check_refresh()
            control.addItem('new option')
            check_refresh()
            control.removeItem(0)
            check_refresh()
            font = QFont(control.font())
            font.setPointSize(font.pointSize() + 6)
            control.setFont(font)
            check_refresh()
            model = QStandardItemModel(control)
            model.appendRow(QStandardItem('replacement model'))
            control.setModel(model)
            check_refresh()
            model.item(0).setText('replacement model changed')
            check_refresh()
            model.setItem(0, 1, QStandardItem('another model column'))
            control.setModelColumn(1)
            check_refresh()
            branch = QStandardItem('nested choices')
            branch.appendRow([QStandardItem('child'), QStandardItem('nested column choice')])
            model.appendRow([branch, QStandardItem('branch label')])
            control.setRootModelIndex(model.index(1, 0))
            check_refresh()
            control.setRootModelIndex(model.index(-1, -1))
            control.clear()
            check_refresh()
        finally:
            control.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_adding_cards_keeps_existing_layout_items_and_responsive_positions(self):
        from ddm.settings_layout import SettingsColumns

        class CountedColumns(SettingsColumns):
            arrangements = 0

            def _arrange(self):
                self.arrangements += 1
                return super()._arrange()

        columns = CountedColumns()
        columns.resize(1100, 800)
        try:
            columns.add_section('first', QWidget())
            first = columns.grid.itemAt(0)
            for name, wide in (('second', False), ('wide', True), ('fourth', False), ('fifth', False)):
                columns.add_section(name, QWidget(), wide=wide)
                self.assertIs(columns.grid.itemAt(0), first)
            self.assertEqual(columns.arrangements, 1)
            positions = [columns.grid.getItemPosition(i) for i in range(5)]
            self.assertEqual(positions, [(0, 0, 1, 1), (0, 1, 1, 1), (1, 0, 1, 2),
                                         (2, 0, 1, 1), (2, 1, 1, 1)])
            columns._arrange()
            self.assertEqual([columns.grid.getItemPosition(i) for i in range(5)], positions)
            columns.setProperty('settings_card_layout', 'vertical')
            columns._arrange()
            self.assertEqual([columns.grid.getItemPosition(i) for i in range(5)],
                             [(row, 0, 1, 1) for row in range(5)])
            columns.add_section('sixth', QWidget())
            self.assertEqual(columns.grid.getItemPosition(5), (5, 0, 1, 1))
            columns.setProperty('settings_card_layout', 'auto')
            columns.resize(600, 800)
            columns._arrange()
            self.assertEqual(columns.columns, 1)
        finally:
            columns.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_irrelevant_events_are_read_once_by_global_settings_filters(self):
        from ddm.settings_focus import SettingsInputFocus

        class CountedEvent:
            reads = 0

            def type(self):
                self.reads += 1
                return QEvent.User

        widget = QWidget()
        try:
            for event_filter in (theme.signals(), SettingsInputFocus(widget)):
                event = CountedEvent()
                self.assertFalse(event_filter.eventFilter(widget, event))
                self.assertEqual(event.reads, 1)
        finally:
            widget.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


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
