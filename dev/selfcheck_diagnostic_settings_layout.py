"""Offline diagnostic form layout and export contract; no real account or files."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QFontDatabase, QWheelEvent
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QVBoxLayout
from ddm import theme
from ddm.settings_diagnostics import DiagnosticsPage
from ddm.ui import ActionButton, SettingsProgressBar, ToggleSwitch


class DiagnosticLayoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        font = QFontDatabase.addApplicationFont(str(
            Path(__file__).resolve().parents[1] / 'ddm/assets/fonts/SourceHanSansSC-Regular.otf'))
        cls.family = QFontDatabase.applicationFontFamilies(font)[0]

    def tearDown(self):
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        theme.configure_appearance({'appearance_font': '', 'appearance_font_size': 13})
        theme.apply('dark')

    def page(self, width, height, *, mode='dark', size=13):
        theme.configure_appearance({'appearance_font': self.family, 'appearance_font_size': size})
        theme.apply(mode)
        host = QDialog()
        host.setStyleSheet(theme.qss())
        page = DiagnosticsPage({'native_crash_dump': True}, host)
        QVBoxLayout(host).addWidget(page)
        host.resize(width, height)
        host.show()
        for _ in range(5):
            self.app.processEvents()
        self.addCleanup(host.deleteLater)
        self.addCleanup(host.close)
        return host, page

    def test_portrait_large_text_and_landscape_keep_actions_visible(self):
        for mode in ('dark', 'light'):
            for width, height, size in ((500, 850, 13), (720, 600, 13), (1100, 760, 13), (580, 950, 18)):
                with self.subTest(mode=mode, width=width, size=size):
                    host, page = self.page(width, height, mode=mode, size=size)
                    self.assertEqual(page.sections.columns, 2 if width == 1100 else 1)
                    self.assertEqual(page.scroll.horizontalScrollBar().maximum(), 0)
                    for button in (page.generate, page.summary, page.open_folder):
                        rect = button.rect()
                        top = button.mapTo(host, rect.topLeft())
                        bottom = button.mapTo(host, rect.bottomRight())
                        self.assertGreaterEqual(top.x(), 0)
                        self.assertGreaterEqual(top.y(), 0)
                        self.assertLess(bottom.x(), host.width())
                        self.assertLess(bottom.y(), host.height())
                        self.assertGreaterEqual(button.width(), button.minimumSizeHint().width())
                    live = page.sections.section('live')
                    page.scroll.ensureWidgetVisible(live)
                    self.app.processEvents()
                    for button in (page.folders, page.drag, page.cancel):
                        self.assertLessEqual(button.mapTo(live, button.rect().bottomRight()).x(), live.width())
                    if os.environ.get('DDM_DIAGNOSTIC_LAYOUT_IMAGES') and size == 13:
                        out = Path(os.environ['DDM_DIAGNOSTIC_LAYOUT_IMAGES'])
                        out.mkdir(parents=True, exist_ok=True)
                        host.grab().save(str(out / f'{mode}-{width}.png'))
                    host.close()

    def test_shared_controls_privacy_defaults_and_original_export_payload(self):
        _host, page = self.page(720, 800)
        self.assertIsInstance(page.generate, ActionButton)
        self.assertIsInstance(page.dump_enabled, ToggleSwitch)
        self.assertIsInstance(page.progress, SettingsProgressBar)
        self.assertTrue(page.dump_enabled.isChecked())
        self.assertFalse(page.include_dumps.isChecked())
        self.assertTrue(any('无法自动脱敏' in label.text() for label in page.findChildren(QLabel)))
        with tempfile.TemporaryDirectory(prefix='ddm-diagnostic-form-') as root:
            page.destination.setText(root)
            page.description.setPlainText('fixture issue')
            page.happened.setText('fixture time')
            page.reproduction.setCurrentIndex(1)
            page.evidence = {'fixture': True}
            with patch.object(page.export, 'start') as start:
                page.generate.click()
                self.assertEqual(start.call_args.args[0], dict(
                    destination=root, description='fixture issue', happened='fixture time',
                    reproduction='稳定复现', attachments=[], evidence={'fixture': True}, include_native_dumps=False))
        page._progress(37, 'fixture progress')
        self.assertEqual(page.progress_text.text(), '37%')
        page.reset()
        self.assertEqual(page.values(), {'native_crash_dump': False})

    def test_description_scroll_stays_local(self):
        _host, page = self.page(720, 600)
        page.description.setPlainText('\n'.join(f'line {i}' for i in range(90)))
        page.description.verticalScrollBar().setValue(0)
        outer = page.scroll.verticalScrollBar().value()
        target = page.description.viewport()
        pos = QPointF(target.rect().center())
        wheel = QWheelEvent(pos, pos, QPoint(), QPoint(0, -120), Qt.NoButton,
                            Qt.NoModifier, Qt.NoScrollPhase, False)
        QApplication.sendEvent(target, wheel)
        self.assertTrue(wheel.isAccepted())
        self.assertGreater(page.description.verticalScrollBar().value(), 0)
        self.assertEqual(page.scroll.verticalScrollBar().value(), outer)


if __name__ == '__main__':
    unittest.main()
