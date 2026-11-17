"""Settings preparation and capture contracts; not performance measurements."""
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from copy import deepcopy
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QCoreApplication, QEvent, QObject, QThreadPool, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QStandardItem, QStandardItemModel
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QSpinBox, QWidget
from ddm import config, theme
from ddm.dialogs import SettingsDialog
from ddm.settings_autosave import SettingsAutoSave
from ddm.settings_performance import SettingsProbe, install, measure
from ddm.settings_window import SettingsWindow

APP = QApplication.instance() or QApplication([])


class PartPreparationTests(unittest.TestCase):
    def test_simple_artwork_editor_omits_professional_controls_and_preserves_saved_styles(self):
        from ddm.skin_part_settings import PartSettings

        class Layer(QObject):
            frameReady = Signal()
            image, mask, path = None, 35, ''

        class Controller(QObject):
            changed = Signal()
            override, error = None, ''

        with tempfile.TemporaryDirectory() as temporary, patch.object(config, 'REPO', temporary), \
                patch('ddm.skin_preview.SkinPreview.capture_interface'):
            folder = Path(temporary) / 'utils/skins'
            folder.mkdir(parents=True)
            image = QImage(8, 8, QImage.Format_RGB32)
            image.fill(QColor('red'))
            for name in ('old.png', 'new.png'):
                image.save(str(folder / name))
            style = {'background': '#112233', 'foreground': '#ddeeff', 'border_color': '#556677',
                     'border_width': 2, 'radius': 12, 'image': 'old.png',
                     'hover': {'background': '#334455'}, 'builtin': True}
            owner = QWidget()
            owner.settings = {**config.DEFAULT_SETTINGS, 'skin_parts': {'settings': deepcopy(style)}}
            owner.shortcuts = {}
            owner.set_skin = lambda values: owner.settings.update(values)
            owner.set_skin_parts = lambda values: owner.settings.update(skin_parts=deepcopy(values))
            controller = owner.skin_controller = Controller(owner)
            controller.window, controller.layer = owner, Layer(owner)
            page = professional = None
            try:
                page = PartSettings(owner, embedded=True)
                self.assertEqual(set(page.fields), {'image', 'icon'})
                page._select_part('settings')
                self.assertFalse(page._drafts)
                page.fields['image'][1].setText('new.png')
                self.assertTrue(page.save_changes())
                self.assertEqual(owner.settings['skin_parts']['settings'], {**style, 'image': 'new.png'})
                professional = PartSettings(owner, professional=True)
                self.assertEqual(set(professional.fields),
                                 {'background', 'foreground', 'border_color', 'border_width', 'radius', 'image', 'icon'})
                professional._select_part('settings')
                professional.fields['radius'][1].setValue(18)
                self.assertTrue(professional.save_changes())
                self.assertEqual(owner.settings['skin_parts']['settings']['radius'], 18)
            finally:
                for widget in (page, professional, owner):
                    if widget is not None:
                        widget.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


class HostedGeneralTests(unittest.TestCase):
    def test_host_keeps_general_snapshot_without_constructing_duplicate_editors(self):
        settings = {**config.DEFAULT_SETTINGS, 'default_volume': 17, 'poll_minutes': 23,
                    'decode_mode': 'software', 'sidebar_platform_logos': False}
        with patch('ddm.dialogs.GeneralSettingsPage', side_effect=AssertionError('Duplicate general editors')):
            dialog = SettingsDialog(settings, {'focus': 'G'}, preview=True, hosted=True)
        try:
            for key in ('default_volume', 'poll_minutes', 'decode_mode', 'sidebar_platform_logos'):
                self.assertEqual(dialog.settings()[key], settings[key])
            self.assertEqual(dialog.shortcuts()['focus'], 'G')
            self.assertEqual(dialog.general_page.findChildren(QSpinBox), [])
            self.assertEqual(dialog.general_page.findChildren(QComboBox), [])
            self.assertEqual(dialog.general_page.plugin_controls(), {})
        finally:
            dialog.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_legacy_show_hook_anchor_control_identity_and_accepted_callback_survive(self):
        dialog = SettingsDialog(dict(config.DEFAULT_SETTINGS), {}, preview=True, hosted=True)
        saved = []

        class Extension(QObject):
            def eventFilter(self, watched, event):
                if watched is dialog and event.type() == QEvent.Show:
                    page = dialog.general_page
                    if page.findChild(QCheckBox, 'fixture_show_platform_logo') is None:
                        anchor = page._checks['sidebar_platform_logos']
                        grid = page.layout().itemAt(1).layout()
                        row = grid.getItemPosition(grid.indexOf(anchor))[0] + 1
                        check = QCheckBox('Fixture logo', page)
                        check.setObjectName('fixture_show_platform_logo')
                        check.setChecked(True)
                        grid.addWidget(check, row, 0, 1, 2)
                        dialog.accepted.connect(lambda: saved.append(check.isChecked()))
                return False

        extension = Extension(APP)
        APP.installEventFilter(extension)
        try:
            QApplication.sendEvent(dialog, QEvent(QEvent.Show))
            controls = dialog.general_page.plugin_controls()
            check = controls['fixture_show_platform_logo']
            check.setChecked(False)
            QApplication.sendEvent(dialog, QEvent(QEvent.Show))
            self.assertIs(dialog.general_page.plugin_controls()['fixture_show_platform_logo'], check)
            dialog.accepted.emit()
            self.assertEqual(saved, [False])
        finally:
            APP.removeEventFilter(extension)
            extension.deleteLater()
            dialog.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


class GalleryPreparationTests(unittest.TestCase):
    def test_thumbnail_decode_does_not_hold_show_or_selection_and_ignores_stale_results(self):
        from ddm import skin_thumbnails
        from ddm.skin_gallery import SkinGallery
        entered, release = threading.Event(), threading.Event()
        threads = []
        image = QImage(8, 8, QImage.Format_RGB32)
        image.fill(QColor('red'))

        def decode(_path):
            threads.append(threading.get_ident())
            entered.set()
            release.wait(3)
            return image

        with tempfile.TemporaryDirectory() as temporary, patch.object(config, 'REPO', temporary), \
                patch.object(skin_thumbnails, 'read_thumbnail', side_effect=decode):
            folder = Path(temporary) / 'utils/skins'
            folder.mkdir(parents=True)
            image.save(str(folder / 'choice.png'))
            gallery = SkinGallery()
            try:
                gallery.set_current('utils/skins/choice.png')
                gallery.show()
                self.assertTrue(entered.wait(1))
                self.assertNotEqual(threads[0], threading.get_ident())
                self.assertIsNone(gallery.item(1).data(Qt.UserRole + 2))
                self.assertEqual(gallery.currentItem().data(Qt.UserRole), 'utils/skins/choice.png')
                pulses = []
                QTimer.singleShot(0, lambda: pulses.append(True))
                QTest.qWait(20)
                self.assertTrue(pulses)
                generation = gallery._thumbnail_generation
                gallery.refresh()
                blue = QImage(image)
                blue.fill(QColor('blue'))
                gallery._thumbnail_ready(generation, 'utils/skins/choice.png', blue)
                self.assertIsNone(gallery.item(1).data(Qt.UserRole + 2))
                release.set()
                until = time.monotonic() + 2
                while gallery.item(1).data(Qt.UserRole + 2) is None and time.monotonic() < until:
                    QTest.qWait(10)
                self.assertEqual(gallery.item(1).data(Qt.UserRole + 2).toImage().pixelColor(0, 0), QColor('red'))
            finally:
                release.set()
                gallery.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
                self.assertTrue(QThreadPool.globalInstance().waitForDone(3000))

    def test_destroying_gallery_cancels_blocked_decode_before_result_delivery(self):
        from ddm import skin_thumbnails
        from ddm.skin_gallery import SkinGallery
        entered, release = threading.Event(), threading.Event()
        image = QImage(8, 8, QImage.Format_RGB32)
        image.fill(QColor('red'))

        def decode(_path):
            entered.set()
            release.wait(3)
            return image

        with tempfile.TemporaryDirectory() as temporary, patch.object(config, 'REPO', temporary), \
                patch.object(skin_thumbnails, 'read_thumbnail', side_effect=decode):
            folder = Path(temporary) / 'utils/skins'
            folder.mkdir(parents=True)
            image.save(str(folder / 'choice.png'))
            gallery = SkinGallery()
            try:
                gallery.refresh()
                self.assertTrue(entered.wait(1))
                cancelled = gallery._thumbnail_cancel
                gallery.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
                self.assertTrue(cancelled.is_set())
            finally:
                release.set()
                self.assertTrue(QThreadPool.globalInstance().waitForDone(3000))


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
    def test_stage_timings_preserve_results_arguments_and_exceptions_without_recording_input(self):
        sentinel = object()

        def construct(value, *, enabled):
            self.assertEqual(value, 'private-stage-input')
            self.assertTrue(enabled)
            return sentinel

        def failed():
            raise ValueError('stage fixture')

        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'capture.jsonl'
            probe = SettingsProbe(path)
            try:
                with patch.object(APP, '_settings_performance', probe, create=True):
                    self.assertIs(measure('fixture.construct', construct, 'private-stage-input', enabled=True), sentinel)
                    with self.assertRaisesRegex(ValueError, 'stage fixture'):
                        measure('fixture.failed', failed)
                with patch.object(APP, '_settings_performance', None, create=True):
                    self.assertIs(measure('fixture.disabled', construct, 'private-stage-input', enabled=True), sentinel)
            finally:
                probe.stop()
            content = path.read_text(encoding='utf-8')
            self.assertNotIn('private-stage-input', content)
            self.assertNotIn('stage fixture', content)
            records = [json.loads(line) for line in content.splitlines()]
            self.assertEqual([r['function'] for r in records if r['phase'] == 'settings-stage'],
                             ['fixture.construct', 'fixture.failed'])

    def test_default_capture_does_not_profile_or_wait_for_disk_writer(self):
        class Example:
            def value(self):
                return 7

        with tempfile.TemporaryDirectory() as temporary:
            probe = SettingsProbe(Path(temporary) / 'capture.jsonl')
            entered, release = threading.Event(), threading.Event()
            original = probe.output_handler.emit

            def slow_write(record):
                entered.set()
                release.wait(3)
                original(record)

            try:
                with patch.object(probe.output_handler, 'emit', side_effect=slow_write), \
                        patch('ddm.settings_performance.cProfile.Profile', side_effect=AssertionError('Profiling enabled')):
                    probe.wrap(Example, 'value')
                    self.assertEqual(Example().value(), 7)
                    self.assertTrue(entered.wait(1))
                    probe.write('still-responsive')
                    release.set()
                    probe.stop()
            finally:
                release.set()
                probe.stop()
            records = [json.loads(line) for line in
                       (Path(temporary) / 'capture.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertEqual([r['phase'] for r in records], ['settings-call', 'still-responsive', 'stop'])

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
            probe = SettingsProbe(path, profile_calls=True)
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
