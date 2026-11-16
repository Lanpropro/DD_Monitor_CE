"""Offline regression: notification/settings share byte progress and update tasks."""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QVBoxLayout, QWidget
from shiboken6 import isValid
from ddm import config, motion, online, theme, update_install
from ddm.app_updates import AppUpdates
from ddm.download_progress import DownloadSample, progress_text
from ddm.plugin_store_ui import PluginStorePage
from ddm.plugins import PluginManager
from ddm.settings_control import SettingsControl
from ddm.update_notice import UpdateNotice
from ddm.update_progress_ui import UpdateProgress


class Session:
    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass


class Host(QWidget):
    def __init__(self, manager):
        super().__init__()
        self.resize(900, 640)
        self.settings = {'auto_update': True}
        self.plugins = manager
        self._closing = False
        self._update_notice = self._available_update = None
        self._plugin_update_offers = self._plugin_catalog_offers = []
        self.sidebar = SimpleNamespace(notification_button=SimpleNamespace(center=Mock()), settings_button=QWidget(self))
        self.app_updates = AppUpdates(self)
        self.settings_control = SettingsControl(self)
        self.open_settings = Mock()
        self.current_state = lambda: {}

    def _show_update_notice(self):
        self.app_updates.show_update_notice()

    def _unread_app_update(self):
        return self.app_updates.unread_app_update()

    def _unread_plugin_updates(self):
        return self.app_updates.unread_plugin_updates()

    def _get_update_page(self, settings):
        return self.settings_control.get_update_page(settings)

    def _set_app_update(self, offer):
        self._available_update = offer

    def _set_plugin_updates(self, offers):
        from ddm.update_offers import plugin_update_offers
        self._plugin_catalog_offers = offers
        self._plugin_update_offers = plugin_update_offers(self.plugins, offers)


class UpdateDownloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        family = theme.danmaku_font_family()
        theme.configure_appearance({'appearance_font': family})

    def setUp(self):
        self.stack = ExitStack()
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix='ddm-update-progress-')))
        self.stack.enter_context(patch.object(config, 'REPO', str(self.root)))
        self.stack.enter_context(patch.object(config, 'data_root', return_value=str(self.root)))
        self.stack.enter_context(patch.object(motion, 'enabled', return_value=False))
        self.manager = PluginManager(plugins_dir=str(self.root / 'plugins'), enabled=[])
        self.manager._save_settings = Mock()
        self.host = Host(self.manager)
        self.host.show()

    def tearDown(self):
        if getattr(self.host, '_plugin_downloads', None):
            self.host._plugin_downloads.stop()
        if getattr(self.host, '_app_update_page', None):
            self.host._app_update_page.stop()
        self.host.close()
        self.host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()
        self.stack.close()

    def wait_for(self, predicate):
        deadline = time.monotonic() + 5
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.005)
        self.app.processEvents()
        self.assertTrue(predicate())

    def package(self, key, version='2.0'):
        path = self.root / (key + '.zip')
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr(key + '/plugin.json', json.dumps(dict(
                id=key, name=key, description='Test', version=version, min_app_version='0.3')))
            archive.writestr(key + '/plugin.py', "raise RuntimeError('must not execute')")
        return path

    def test_sampling_reset_and_units(self):
        now = [0.0]
        sample = DownloadSample(lambda: now[0])
        sample.update(0, 4096)
        now[0] = 1
        state = sample.update(1024, 4096)
        self.assertEqual(state['speed'], 1024)
        self.assertEqual(state['percent'], 25)
        self.assertIn('1.00 KB / 4.00 KB', progress_text(state))
        self.assertIn('1.00 KB/s', progress_text(state))
        now[0] = 2
        reset = sample.update(0, 4096)
        self.assertEqual(reset['speed'], 0)
        self.assertEqual(reset['percent'], 0)
        self.assertEqual(sample.update(4096, 4096)['phase'], 'verifying')

    def test_download_button_is_replaced_in_place_and_restored(self):
        surface = QWidget()
        surface.resize(800, 90)
        layout = QVBoxLayout(surface)
        button = QPushButton('下载更新')
        progress = UpdateProgress(surface, button=button)
        layout.addWidget(progress)
        surface.show()
        self.app.processEvents()
        original = progress.geometry()
        button_width, button_height = button.width(), button.height()
        state = dict(received=50 * 1024 * 1024, total=250 * 1024 * 1024,
                     speed=10 * 1024 * 1024, percent=20, phase='downloading')
        progress.set_state(state)
        self.app.processEvents()
        self.assertFalse(button.isVisible())
        self.assertTrue(progress.bar.isVisible())
        self.assertGreater(progress.bar.width(), button_width)
        self.assertLess(progress.bar.height(), button_height)
        self.assertEqual(progress.geometry(), original)
        self.assertIn('50.00 MB / 250.00 MB', progress.details.text())
        progress.set_state(dict(state, phase='ready', percent=100))
        self.app.processEvents()
        self.assertTrue(button.isVisible())
        self.assertFalse(progress.bar.isVisible())
        progress.set_state(dict(state, phase='failed', error='test disconnect'))
        self.assertEqual(button.text(), '重试')
        surface.close()
        surface.deleteLater()

    def test_plugin_cards_keep_text_inside_at_large_font_and_narrow_width(self):
        from ddm.settings_plugins import PluginSettingsPage
        self.stack.enter_context(patch.object(PluginStorePage, 'open_catalog'))
        key = 'fixture'
        self.manager.install_zip(str(self.package(key, '1.0')))
        offer = dict(id=key, name='测试插件一', description='本地样式验收测试包',
                     version='2.0', available=True, author='ExampleAuthor')
        state = dict(received=4 * 1024 * 1024, total=8 * 1024 * 1024,
                     speed=1024 * 1024, percent=50, phase='downloading')
        for font_size in (13, 20):
            theme.configure_appearance({'appearance_font': theme.danmaku_font_family(),
                                        'appearance_font_size': font_size})
            theme.apply('dark')
            page = PluginSettingsPage(self.manager)
            store = page.store_page
            store.downloads.states[key] = state
            store.show_offers([offer])
            page.resize(650, 560)
            page.show()
            for tab in (0, 1):
                page.tabs.setCurrentIndex(tab)
                page._show_update_notes([offer])
                self.app.processEvents()
                card = page._installed_cards[key] if tab == 0 else store._offer_cards[key]
                progress = page._installed_progress[key] if tab == 0 else store._progress_widgets[key]
                self.assertTrue(progress.bar.isVisible())
                self.assertFalse(progress.button.isVisible())
                self.assertGreaterEqual(card.height(), card.minimumSizeHint().height())
                for label in card.findChildren(QLabel):
                    if label.isVisible():
                        self.assertGreaterEqual(label.height(), label.fontMetrics().height())
                        self.assertLessEqual(label.mapTo(card, label.rect().topLeft()).y() + label.height(), card.height())
                self.assertEqual((page.installed_scroll if tab == 0 else store.scroll).horizontalScrollBar().maximum(), 0)
                directory = os.environ.get('DDM_UPDATE_PREVIEW')
                if directory:
                    Path(directory).mkdir(parents=True, exist_ok=True)
                    card.grab().save(str(Path(directory) / f'plugin-{font_size}-{tab}.png'))
            store.downloads.states[key] = dict(state, phase='ready', percent=100)
            store._busy(False)
            self.app.processEvents()
            self.assertFalse(store._progress_widgets[key].bar.isVisible())
            page.store_page.stop()
            page.close()
            page.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        theme.configure_appearance({'appearance_font': theme.danmaku_font_family(), 'appearance_font_size': 13})
        theme.apply('dark')

    def test_notification_plugin_progress_reopen_and_retry(self):
        key = 'fixture'
        archive = self.package(key)
        offer = dict(id=key, name='测试插件', version='2.0', available=True, size=4096, description='test')
        self.host._plugin_update_offers = self.host._plugin_catalog_offers = [offer]
        self.host._show_update_notice()
        notice = self.host._update_notice
        downloads = self.host.app_updates.plugin_downloads()
        gate = threading.Event()
        calls = []

        def download(_offer, destination, client, cancelled, progress):
            calls.append(_offer['id'])
            progress(1024, 4096)
            while not gate.wait(.005):
                if cancelled():
                    raise InterruptedError('cancelled')
            if len(calls) == 1:
                raise OSError('test connection lost')
            progress(4096, 4096)
            return str(archive)

        with patch.object(online, 'session', return_value=Session()), patch.object(online, 'download', side_effect=download):
            try:
                notice._update_rows[key][2].click()
                self.wait_for(lambda: downloads.states.get(key, {}).get('percent') == 25)
                store = PluginStorePage(self.manager)
                store.set_downloads(downloads)
                store.show_offers([offer])
                self.assertEqual(store._progress_widgets[key].bar.value(), 25)
                self.assertEqual(notice._update_rows[key][1].details.toolTip(), store._progress_widgets[key].details.toolTip())
                self.assertFalse(notice.timer.isActive())
                store.install_offer(offer)
                self.assertEqual(calls, [key], 'Two entry points must not start a duplicate transfer')
                store.stop()
                store.deleteLater()
                self.assertFalse(downloads.stopping, 'Closing settings must keep the shared download')
                gate.set()
                self.wait_for(lambda: not downloads.jobs)
                self.assertEqual(notice._update_rows[key][2].text(), '重试')
                self.assertIn('test connection lost', notice._update_rows[key][1].details.toolTip())
                notice._update_rows[key][2].click()
                self.wait_for(lambda: not downloads.jobs)
                self.assertEqual(calls, [key, key])
                self.assertEqual(downloads.states[key]['phase'], 'ready')
                self.assertEqual(self.manager.enabled, {key})
                self.assertFalse(self.manager.plugins, 'Downloading must not execute plugin code')
                reopened = PluginStorePage(self.manager)
                reopened.set_downloads(downloads)
                reopened.show_offers([offer])
                self.assertEqual(reopened._progress_widgets[key].bar.value(), 100)
                self.assertEqual(notice._update_rows[key][2].text(), '重启以应用')
                notice.settings_action.click()
                self.host.open_settings.assert_called_with('plugins')
                reopened.stop()
                reopened.deleteLater()
            finally:
                gate.set()
                self.wait_for(lambda: not downloads.jobs)

    def test_app_download_from_notice_and_settings_share_task(self):
        gate = threading.Event()
        offer = dict(version='9.0', size=100, notes='test')
        self.host._available_update = offer
        self.host._show_update_notice()
        notice = self.host._update_notice
        plan = self.root / 'plan.json'
        plan.write_text('{}', encoding='utf-8')

        def download(_offer, destination, client, cancelled, progress):
            progress(25, 100)
            while not gate.wait(.005):
                if cancelled():
                    raise InterruptedError('cancelled')
            progress(100, 100)
            return str(destination)

        with patch.object(sys, 'frozen', True, create=True), patch.object(online, 'session', return_value=Session()), \
                patch.object(online, 'download', side_effect=download) as call, \
                patch.object(update_install, 'prepare', return_value=str(plan)):
            try:
                # Refresh the source/EXE permission state before using the button.
                self.host._show_update_notice()
                notice._update_rows['app'][2].click()
                page = self.host._get_update_page({})
                self.wait_for(lambda: page.download_progress.bar.value() == 25)
                page.download_update()
                self.assertEqual(len(page.jobs), 1)
                self.assertEqual(notice._update_rows['app'][1].bar.value(), 25)
                notice.settings_action.click()
                self.host.open_settings.assert_called_with('updates')
                gate.set()
                self.wait_for(lambda: not page.jobs)
                call.assert_called_once()
                self.assertEqual(page.plan_path, str(plan))
                self.assertEqual(notice._update_rows['app'][2].text(), '重启以应用')
                self.assertFalse(page.install_requested, 'Download completion must not restart automatically')
                with patch.object(self.host, 'close') as close:
                    notice._update_rows['app'][2].click()
                    self.assertEqual(self.host._update_plan, str(plan))
                    close.assert_called_once()
            finally:
                gate.set()
                if getattr(self.host, '_app_update_page', None):
                    self.wait_for(lambda: not self.host._app_update_page.jobs)

    def test_parallel_plugin_progress_and_application_exit(self):
        downloads = self.host.app_updates.plugin_downloads()
        first, second = threading.Event(), threading.Event()
        offers = [dict(id=key, name=key, version='2.0', size=100, available=True)
                  for key in ('first', 'second')]
        self.host._plugin_update_offers = self.host._plugin_catalog_offers = offers

        def download(offer, destination, client, cancelled, progress):
            progress(20 if offer['id'] == 'first' else 60, 100)
            while not cancelled():
                time.sleep(.005)
            (first if offer['id'] == 'first' else second).set()
            raise InterruptedError('cancelled')

        with patch.object(online, 'session', return_value=Session()), patch.object(online, 'download', side_effect=download):
            downloads.start(offers[0])
            downloads.start(offers[1])
            self.wait_for(lambda: downloads.states.get('first', {}).get('percent') == 20
                          and downloads.states.get('second', {}).get('percent') == 60)
            notice = self.host._update_notice
            self.assertEqual(notice._update_rows['first'][1].bar.value(), 20)
            self.assertEqual(notice._update_rows['second'][1].bar.value(), 60)
            jobs = list(downloads.jobs)
            downloads.stop()
            self.assertTrue(first.wait(2) and second.wait(2))
            self.wait_for(lambda: all(not isValid(task) or not task.isRunning() for task in jobs))

    def test_existing_disabled_plugin_is_staged_and_reopened_settings_can_restart(self):
        from ddm.plugins import read_manifest
        from ddm.settings_plugins import PluginSettingsPage
        key = 'fixture'
        self.manager.install_zip(str(self.package(key, '1.0')))
        self.manager.enabled.clear()
        installed = Path(self.manager.plugins_dir) / key
        (installed / 'user-data.txt').write_text('keep', encoding='utf-8')
        archive = self.package(key)
        downloads = self.host.app_updates.plugin_downloads()
        with patch.object(online, 'session', return_value=Session()), \
                patch.object(online, 'download', return_value=str(archive)):
            downloads.start(dict(id=key, name=key, version='2.0', size=100, available=True))
            self.wait_for(lambda: not downloads.jobs)
        self.assertEqual(read_manifest(str(installed), key)['version'], '1.0')
        self.assertEqual(read_manifest(str(installed.parent / '.updates' / key), key)['version'], '2.0')
        self.assertEqual((installed / 'user-data.txt').read_text(encoding='utf-8'), 'keep')
        self.assertEqual(self.manager.enabled, set())
        page = PluginSettingsPage(self.manager)
        page.store_page.set_downloads(downloads)
        self.assertTrue(page.needs_restart())
        self.assertFalse(page.checks[key].isChecked())
        page.store_page.stop()
        page.deleteLater()

    def test_setting_start_opens_progress_notice_without_startup_notice(self):
        self.host.settings = {'auto_update': False}
        page = self.host._get_update_page({})
        page._release_ready(dict(version='9.0', size=100))
        self.assertIsNone(self.host._update_notice)
        page._transfer_progress(dict(received=25, total=100, speed=10, percent=25, phase='downloading'))
        self.assertEqual(self.host._update_notice._update_rows['app'][1].bar.value(), 25)

    def test_notification_restart_waits_for_hosted_settings_save(self):
        page = self.host._get_update_page({})
        page.plan_path = 'staged-test-plan.json'
        client = SimpleNamespace(_send=Mock())
        plugin_page = SimpleNamespace(_files_changed=False)
        self.host._settings_host = SimpleNamespace(
            client=client, dialog=SimpleNamespace(update_page=page, plugin_page=plugin_page))
        with patch.object(self.host, 'close') as close:
            self.host.app_updates.restart_updates(page)
            self.assertTrue(page.install_requested)
            client._send.assert_called_with({'kind': 'host-request-save'})
            close.assert_not_called()
            page.plan_path = ''
            self.host.app_updates.restart_updates(None)
            self.assertTrue(plugin_page._files_changed)
            self.assertEqual(client._send.call_count, 2)
            close.assert_not_called()

    def test_preparation_error_is_visible_and_does_not_offer_restart(self):
        page = self.host._get_update_page({})
        page._release_ready(dict(version='9.0', size=100))
        with patch.object(sys, 'frozen', True, create=True), patch.object(online, 'session', return_value=Session()), \
                patch.object(online, 'download', return_value='test.zip'), \
                patch.object(update_install, 'prepare', side_effect=ValueError('invalid update archive')):
            page.download_update()
            self.wait_for(lambda: not page.jobs)
            self.assertEqual(page.download_state['phase'], 'failed')
            self.assertIn('invalid update archive', page.download_progress.details.toolTip())
            self.assertIn('invalid update archive', page.status.text())
            self.assertEqual(page.plan_path, '')
            self.assertEqual(self.host._update_notice._update_rows['app'][2].text(), '重试')

    def test_progress_control_themes_and_narrow_notice(self):
        notice = UpdateNotice(self.host)
        notice.set_updates([dict(key='fixture', title='长插件名称' * 10)])
        notice.show_offer({'version': '9.0'}, persistent=True)
        state = dict(received=50 * 1024 * 1024, total=250 * 1024 * 1024, speed=10 * 1024 * 1024,
                     percent=20, phase='downloading')
        for appearance in ('dark', 'light'):
            theme.apply(appearance)
            notice.set_transfer('fixture', state)
            self.app.processEvents()
            image = notice.grab().toImage()
            self.assertFalse(image.isNull())
            self.assertLessEqual(notice.width(), self.host.width())
            progress = notice._update_rows['fixture'][1]
            self.assertTrue(progress.details.text().endswith('10.00 MB/s'))
            self.assertEqual(progress.bar.value(), 20)
            directory = os.environ.get('DDM_UPDATE_PREVIEW')
            if directory:
                notice.set_updates([dict(key='fixture', title='比赛二路同步 v2.0')])
                notice.set_transfer('fixture', state)
                Path(directory).mkdir(parents=True, exist_ok=True)
                notice.grab().save(str(Path(directory) / ('notice-' + appearance + '.png')))
        notice.set_updates([dict(key=str(index), title='插件 ' + str(index)) for index in range(12)])
        self.assertLessEqual(notice.height(), self.host.height())
        notice.dismiss(animate=False)
        notice.deleteLater()


if __name__ == '__main__':
    unittest.main()
