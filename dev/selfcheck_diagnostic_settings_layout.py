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
                    for button in (page.generate, page.summary, page.open_folder, page.open_issue):
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
                    for button in (page.folders, page.drag, page.dock_hover, page.cancel):
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
        self.assertEqual(page.dump_enabled.toolTip(), '仅对保存设置后的崩溃生效。')
        self.assertFalse(page.include_dumps.isChecked())
        privacy_hint = next(label for label in page.findChildren(QLabel) if '无法自动脱敏' in label.text())
        self.assertTrue(privacy_hint.isHidden())
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
                page.include_dumps.setChecked(True)
                self.app.processEvents()
                self.assertTrue(privacy_hint.isVisible())
                self.assertGreaterEqual(privacy_hint.height(), privacy_hint.heightForWidth(privacy_hint.width()))
                page.generate.click()
                self.assertTrue(start.call_args.args[0]['include_native_dumps'])
        page._progress(37, 'fixture progress')
        self.assertEqual(page.progress_text.text(), '37%')
        page.reset()
        self.assertEqual(page.values(), {'native_crash_dump': False})
        self.assertTrue(privacy_hint.isHidden())

    def test_condensed_copy_keeps_attachment_limits_and_capture_tooltips(self):
        _host, page = self.page(720, 600)
        header = page.layout().itemAt(0).layout()
        self.assertEqual([header.itemAt(i).widget().text() for i in range(header.count())], ['诊断与反馈'])
        attachments = page.sections.section('attachments')
        self.assertEqual(attachments.grid.itemAtPosition(2, 0).widget().text(),
                         '最多 5 张，每张不超过 20 MB。导出时移除元数据。')
        collection = page.sections.section('collection')
        visible_hints = [label.text() for label in collection.findChildren(QLabel, 'SettingsHint') if label.isVisible()]
        self.assertEqual(visible_hints, [
            '无需复现即可导出系统与版本信息、脱敏配置、插件版本、近期日志和已有崩溃记录，收集时不读取账号文件、不自动截图或上传。'])
        self.assertEqual(page.sections.section('live').grid.count(), 1)
        self.assertEqual(page.folders.toolTip(), '问题仍在时，点击读取当前文件夹状态。')
        self.assertEqual(page.drag.toolTip(), '点击后回到主窗口复现拖放，最长采集 60 秒。')
        self.assertEqual(page.dock_hover.toolTip(), '点击后回到主窗口，将鼠标移过左侧功能栏，最长采集 60 秒。')

    def test_function_rail_button_requests_capture_from_main_process(self):
        _host, page = self.page(720, 600)
        with patch.dict(os.environ, DDM_DIAGNOSTIC_HOST_PID='12345'), patch.object(page.export, 'start') as start:
            page.dock_hover.click()
            start.assert_called_once_with({'pid': 12345, 'mode': 'dock-hover'}, capture=True)
        self.assertIn('60 秒', page.status.text())

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

    def test_issue_button_opens_the_template_picker_without_exporting(self):
        _host, page = self.page(500, 850)
        self.assertEqual(page.actions.indexOf(page.open_issue), 3)
        self.assertEqual(page.open_issue.toolTip(), '打开 GitHub 问题模板，可手动附上诊断包。')
        page.description.setPlainText('本地填写的诊断内容')
        with patch('ddm.settings_diagnostics.QDesktopServices.openUrl') as browser, patch.object(page.export, 'start') as export:
            page.open_issue.click()
        browser.assert_called_once()
        self.assertEqual(browser.call_args.args[0].toString(),
                         'https://github.com/Lanpropro/DD_Monitor_CE/issues/new/choose')
        export.assert_not_called()


if __name__ == '__main__':
    unittest.main()
