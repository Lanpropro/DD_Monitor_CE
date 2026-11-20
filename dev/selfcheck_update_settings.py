"""Offline update-page layout, action and automatic-save regression checks."""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtGui import QFontDatabase, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel
from ddm import config, theme, version
from ddm.app_update_ui import AppUpdatePage
from ddm.cache_settings import ImageCachePanel
from ddm.data_settings import DataSettingsPage
from ddm.ui import ActionButton, ToggleSwitch


class UpdateSettingsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        font_id = QFontDatabase.addApplicationFont(str(
            Path(__file__).resolve().parents[1] / 'ddm/assets/fonts/SourceHanSansSC-Regular.otf'))
        cls.font_family = QFontDatabase.applicationFontFamilies(font_id)[0]

    def setUp(self):
        self.stack = ExitStack()
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix='ddm-update-settings-')))
        self.stack.enter_context(patch.object(config, 'REPO', str(self.root)))
        self.stack.enter_context(patch.object(config, 'CONFIG_PATH', str(self.root / 'config.json')))
        self.stack.enter_context(patch.object(config, 'data_root', return_value=str(self.root / 'data')))
        self.stack.enter_context(patch('ddm.app_update_ui.update_install.result_message', return_value=''))
        self.stack.enter_context(patch.object(ImageCachePanel, 'refresh'))
        notes = self.root / 'docs/releases' / f'RELEASE-v{version.VERSION}.md'
        notes.parent.mkdir(parents=True)
        notes.write_text('# 当前版本说明\n\n离线说明夹具。', encoding='utf-8')
        self.pages = []
        self.appearance()

    def tearDown(self):
        for page in self.pages:
            page.stop()
            page.close()
            page.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.stack.close()
        theme.configure_appearance({'appearance_font': '', 'appearance_font_size': 13})
        theme.apply('dark')

    def appearance(self, mode='dark', size=13):
        theme.configure_appearance({'appearance_font': self.font_family, 'appearance_font_size': size})
        theme.apply(mode)

    def page(self, *, frozen=True, width=1100, height=800):
        self.stack.enter_context(patch.object(sys, 'frozen', frozen, create=True))
        page = AppUpdatePage({'auto_update': True})
        self.pages.append(page)
        page.resize(width, height)
        page.show()
        self.app.processEvents()
        return page

    @staticmethod
    def offer():
        return dict(version='9.9.9', revision=2, size=12 * 1024 * 1024,
                    notes='# 更新内容\n\n下载和进度显示离线夹具。')

    def test_shared_controls_fixed_header_bounded_notes_and_original_data_page(self):
        page = self.page()
        self.assertIsInstance(page.auto, ToggleSwitch)
        for button in (page.check, page.action, page.release_button):
            self.assertIsInstance(button, ActionButton)
        self.assertTrue(page.auto.isChecked())
        self.assertEqual(page.values(), {'auto_update': True})
        self.assertIsInstance(page.data_page, DataSettingsPage)
        self.assertTrue(page.data_page.isAncestorOf(page.data_page.image_cache))
        self.assertEqual(page.data_page.path.text(), str(self.root / 'data'))
        self.assertIn('离线说明夹具', page.notes.toPlainText())
        self.assertIs(page.notes_title, page.notes_section.layout().itemAt(0).widget())
        self.assertTrue(page.notes.openExternalLinks())
        self.assertEqual(page.notes.height(), 240)
        self.assertLess(page.notes.height(), page.height() // 2)
        header = next(label for label in page.findChildren(QLabel)
                      if label.text() == '软件更新')
        self.assertFalse(page.scroll.isAncestorOf(header))
        top = header.mapTo(page, QPoint())
        page.scroll.verticalScrollBar().setValue(page.scroll.verticalScrollBar().maximum())
        self.app.processEvents()
        self.assertEqual(header.mapTo(page, QPoint()), top)
        self.assertGreater(page.data_page.y(), page.notes_section.y())
        with patch('ddm.app_update_ui.QDesktopServices.openUrl') as open_url:
            page.release_button.click()
            self.assertTrue(open_url.call_args.args[0].toString().endswith('/releases'))

    def test_source_and_exe_idle_busy_and_release_states(self):
        source = self.page(frozen=False)
        self.assertIn('源码', source.status.text())
        self.assertFalse(source.action.isEnabled())
        source._release_ready(self.offer())
        self.assertIn('源码', source.status.text())
        self.assertIn('9.9.9', source.notes_title.text())
        with patch.object(source, 'start') as start:
            source.download_update()
            start.assert_not_called()
        exe = self.page()
        self.assertFalse(exe.action.isEnabled())
        self.assertTrue(exe.check.isEnabled())
        exe._busy(True)
        self.assertFalse(exe.check.isEnabled())
        self.assertIn('检查中', exe.action.text())
        exe._release_ready(None)
        self.assertIn('最新', exe.action.text())
        self.assertFalse(exe.action.isEnabled())
        exe._release_ready(self.offer())
        self.assertTrue(exe.action.isEnabled())
        self.assertEqual(exe.action.text(), '下载更新')
        self.assertIn('9.9.9', exe.notes_title.text())

    def test_check_download_prepare_retry_and_explicit_restart_keep_business_contract(self):
        page = self.page()
        offer = self.offer()
        operations = []
        with patch.object(page, 'start', side_effect=lambda operation, callback: operations.append((operation, callback))):
            page.check_update()
        with (patch('ddm.app_update_ui.online.session') as session,
              patch('ddm.app_update_ui.online.app_release', return_value=offer) as release,
              patch('ddm.app_update_ui.installed_revision', return_value=0)):
            result = operations.pop()[0](lambda: False, Mock())
            release.assert_called_once_with(session.return_value.__enter__.return_value, version.VERSION, 0)
        page._check_ready(result)
        self.assertIs(page.offer, offer)
        with patch.object(page, 'start', side_effect=lambda operation, callback: operations.append((operation, callback))):
            page.download_update()
        state = dict(received=1024, total=4096, speed=512, percent=25, phase='downloading')
        page._transfer_progress(state)
        reason = '下载连接提前中断，文件未接收完整，请检查网络或代理后重试'
        page._failed((None, reason))
        self.assertEqual(page.action.text(), '重试')
        self.assertIn('文件未接收完整', page.download_progress.failure.text())
        self.assertIn('文件未接收完整', page.status.text())
        operation, callback = operations.pop()
        plan = self.root / 'plan.json'
        plan.write_text(json.dumps({'elevate': True}), encoding='utf-8')
        with (patch('ddm.app_update_ui.online.session'),
              patch('ddm.app_update_ui.online.download', return_value=self.root / 'app.zip') as download,
              patch('ddm.app_update_ui.update_install.prepare', return_value=str(plan)) as prepare):
            cancelled, progress = Mock(return_value=False), Mock()
            prepared = operation(cancelled, progress)
            self.assertIs(download.call_args.args[3], cancelled)
            self.assertIs(download.call_args.args[4], progress)
            self.assertEqual(prepare.call_args.kwargs['expected_revision'], 2)
            self.assertEqual(prepare.call_args.kwargs['data_root'], str(self.root / 'data'))
        saved = Mock()
        page.saveRequested.connect(saved)
        callback(prepared)
        page._busy(False)
        self.assertEqual(page.action.text(), '重启并更新')
        self.assertTrue(page.action.property('updateReady'))
        self.assertFalse(page.action.icon().isNull())
        self.assertIn('管理员授权', page.status.text())
        saved.assert_not_called()
        self.assertFalse(page.install_requested)
        page.download_update()
        saved.assert_called_once()
        self.assertTrue(page.install_requested)
        with patch('ddm.app_update_ui.update_install.discard_plan') as discard:
            page.stop()
            discard.assert_not_called()

    def test_closing_discards_unrequested_prepared_plan(self):
        page = self.page()
        page.plan_path = str(self.root / 'prepared.json')
        with patch('ddm.app_update_ui.update_install.discard_plan') as discard:
            page.stop()
            discard.assert_called_once_with(str(self.root / 'prepared.json'), str(self.root))
        self.assertTrue(page.stopping)
        self.assertEqual(page.plan_path, '')

    def test_wide_narrow_large_font_and_progress_keep_left_anchor(self):
        for mode, size, width in (('dark', 13, 1100), ('light', 13, 560),
                                  ('dark', 20, 560), ('dark', 20, 500), ('light', 20, 1100)):
            with self.subTest(mode=mode, size=size, width=width):
                self.appearance(mode, size)
                page = self.page(width=width)
                page._release_ready(self.offer())
                self.app.processEvents()
                anchor = page.action.mapTo(page, QPoint()).x()
                self.assertLess(anchor, page.check.mapTo(page, QPoint()).x())
                self.assertEqual(page.scroll.horizontalScrollBar().maximum(), 0)
                self.assertLessEqual(page.version_section.width(), page.scroll.viewport().width())
                self.assertLessEqual(page.notes_section.width(), page.scroll.viewport().width())
                for phase in ('downloading', 'verifying', 'failed', 'ready'):
                    page._transfer_progress(dict(received=1024, total=4096, speed=512,
                                                 percent=25, phase=phase, error='网络连接中断，请检查代理'))
                    self.app.processEvents()
                    control = page.download_progress.bar if phase in ('downloading', 'verifying') else page.action
                    self.assertEqual(control.mapTo(page, QPoint()).x(), anchor)
                    self.assertFalse(page.download_progress.details.toolTip().startswith('0 B'))
                    self.assertLessEqual(page.check.mapTo(page, page.check.rect().topRight()).x(), width)
                plan = self.root / 'preview-plan.json'
                plan.write_text('{}', encoding='utf-8')
                page._prepared(str(plan))
                page._busy(False)
                # A wrapped label posts a second parent-layout request after its width resolves.
                QTest.qWait(30)
                self.assertGreaterEqual(page.status.height(), page.status.heightForWidth(page.status.width()),
                                        'Wrapped ready feedback must not be clipped')
                output = os.environ.get('DDM_UPDATE_SETTINGS_PREVIEW')
                if output:
                    directory = Path(output)
                    directory.mkdir(parents=True, exist_ok=True)
                    image = QImage(page.size(), QImage.Format_ARGB32_Premultiplied)
                    image.fill(theme.qcolor(theme.BG))
                    page.render(image)
                    self.assertTrue(image.save(str(directory / f'{mode}-{size}-{width}.png')))
                page.close()

    def test_notes_wheel_scrolls_only_the_document_including_its_boundaries(self):
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QWheelEvent
        from ddm.settings_focus import SettingsInputFocus
        page = self.page()
        page.notes.setPlainText('\n'.join(f'发行说明 {index}' for index in range(100)))
        QTest.qWait(30)
        focus = SettingsInputFocus(page)
        try:
            inner, outer = page.notes.verticalScrollBar(), page.scroll.verticalScrollBar()
            self.assertGreater(inner.maximum(), 0)
            self.assertGreater(outer.maximum(), 0)
            point = page.notes.viewport().rect().center()
            def wheel(delta):
                event = QWheelEvent(QPointF(point), QPointF(page.notes.viewport().mapToGlobal(point)),
                                    QPoint(), QPoint(0, delta), Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False)
                self.app.sendEvent(page.notes.viewport(), event)
            wheel(-120)
            self.assertGreater(inner.value(), 0)
            self.assertEqual(outer.value(), 0)
            inner.setValue(inner.maximum())
            wheel(-120)
            self.assertEqual(outer.value(), 0, 'Notes must consume wheels at the document boundary')
            inner.setValue(0)
            wheel(120)
            self.assertEqual(outer.value(), 0)
        finally:
            self.app.removeEventFilter(focus)
            focus.deleteLater()

    def test_notes_embedded_wheel_delivery_targets_the_document(self):
        from importlib.util import find_spec
        if find_spec('ddm.settings_wheel') is None:
            self.skipTest('Native wheel bridge exists in the integrated root checkout')
        from ddm.settings_focus import SettingsInputFocus
        from ddm.settings_wheel import deliver
        page = self.page()
        page.notes.setPlainText('\n'.join(f'发行说明 {index}' for index in range(100)))
        QTest.qWait(30)
        focus = SettingsInputFocus(page)
        try:
            point = page.notes.viewport().mapTo(page, page.notes.viewport().rect().center())
            values = dict(x=point.x(), y=point.y(), delta=-120, buttons=0, modifiers=0)
            inner, outer = page.notes.verticalScrollBar(), page.scroll.verticalScrollBar()
            deliver(page, values)
            self.assertGreater(inner.value(), 0)
            self.assertEqual(outer.value(), 0)
            inner.setValue(inner.maximum())
            deliver(page, values)
            self.assertEqual(outer.value(), 0)
        finally:
            self.app.removeEventFilter(focus)
            focus.deleteLater()

    def test_idle_and_ready_actions_stay_adjacent_on_the_left(self):
        for frozen in (True, False):
            page = self.page(frozen=frozen)
            for state in (None, self.offer()):
                if state is not None:
                    page._release_ready(state)
                QTest.qWait(30)
                gap = page.check.mapTo(page, QPoint()).x() - page.action.mapTo(
                    page, page.action.rect().topRight()).x()
                self.assertGreater(gap, 0)
                self.assertLessEqual(gap, 20, 'Idle actions must not sit at opposite edges')
            page._transfer_progress(dict(received=4096, total=4096, percent=100, phase='ready'))
            QTest.qWait(30)
            gap = page.check.mapTo(page, QPoint()).x() - page.action.mapTo(
                page, page.action.rect().topRight()).x()
            self.assertLessEqual(gap, 20)

    def test_toggle_in_real_settings_dialog_saves_only_after_receipt(self):
        from ddm.dialogs import SettingsDialog
        dialog = SettingsDialog(dict(config.DEFAULT_SETTINGS), {}, preview=True)
        try:
            # Preview mode substitutes an empty update page; load the real page for this check.
            dialog._page_factories[8] = lambda: AppUpdatePage(dialog._initial_settings)
            dialog._auto_save_enabled = True
            dialog.auto_save.start()
            page = dialog.update_page
            self.assertIsInstance(page.auto, ToggleSwitch)
            requested = []
            dialog.auto_save.requested.connect(requested.append)
            page.auto.setChecked(True)
            dialog.auto_save.flush()
            self.assertEqual(requested, [{'settings': {'auto_update': True}}])
            self.assertFalse(dialog.auto_save.confirmed['settings']['auto_update'])
            self.assertIsNotNone(dialog.auto_save.pending)
            dialog.auto_save.acknowledge()
            self.assertTrue(dialog.auto_save.confirmed['settings']['auto_update'])
            self.assertIsNone(dialog.auto_save.pending)
            self.assertTrue(dialog.settings()['auto_update'])
            page.stop()
        finally:
            dialog.auto_save.stop()
            dialog.close()
            dialog.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


if __name__ == '__main__':
    unittest.main()
