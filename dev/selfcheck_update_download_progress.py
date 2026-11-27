"""Offline regression: notification/settings share byte progress and update tasks."""
from contextlib import ExitStack
import errno
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
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtTest import QTest
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
from ddm.update_errors import error_message


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

    def test_notice_download_and_settings_footer_share_one_horizontal_row(self):
        notice = UpdateNotice(self.host)
        notice.set_updates([dict(key='first', title='插件一'), dict(key='second', title='插件二')])
        notice.show_offer({'version': '9.0'}, persistent=True)
        requested, opened = [], []
        notice.updateRequested.connect(requested.append)
        notice.activated.connect(lambda: opened.append(True))
        for mode in ('dark', 'light'):
            theme.apply(mode)
            notice._resize_to_content()
            self.app.processEvents()
            self.assertTrue(notice.action.isVisible())
            self.assertTrue(notice.settings_action.isVisible())
            self.assertEqual(notice.action.text(), '全部下载')
            self.assertLess(notice.action.geometry().right(), notice.settings_action.x())
            self.assertLessEqual(abs(notice.action.geometry().center().y() - notice.settings_action.geometry().center().y()), 1)
            self.assertTrue(notice.rect().contains(notice.action.geometry()))
            self.assertTrue(notice.rect().contains(notice.settings_action.geometry()))
            directory = os.environ.get('DDM_UPDATE_PREVIEW')
            if directory:
                Path(directory).mkdir(parents=True, exist_ok=True)
                notice.grab().save(str(Path(directory) / f'notice-actions-{mode}.png'))
        notice.action.click()
        self.assertEqual(requested, ['first', 'second'])
        self.assertFalse(opened)
        notice.settings_action.click()
        self.assertEqual(opened, [True])
        self.assertEqual(requested, ['first', 'second'])
        notice.set_updates([dict(key='first', title='插件一')])
        notice.show_offer({'version': '9.0'}, persistent=True)
        self.assertTrue(notice.action.isHidden())
        self.assertTrue(notice.settings_action.isVisible())
        notice.dismiss(animate=False)
        notice.deleteLater()
        theme.apply('dark')

    def test_single_update_notice_uses_one_headline_and_horizontal_actions(self):
        notice = UpdateNotice(self.host)
        self.addCleanup(theme.apply, 'dark')
        app_entry = dict(key='app', title='软件 v0.8', enabled=True)
        notice.set_updates([app_entry])
        notice.show_offer({'version': '0.8'}, persistent=True)
        logo = QPixmap(str(Path(__file__).resolve().parents[1] / 'assets/logo.png'))
        self.assertFalse(logo.isNull())
        self.assertEqual(notice.indicator.pixmap().toImage(), logo.toImage())
        row, progress, download = notice._update_rows['app']
        settings = notice.settings_action
        requested, opened = [], []
        notice.updateRequested.connect(requested.append)
        notice.activated.connect(lambda: opened.append(True))

        for mode in ('dark', 'light'):
            theme.apply(mode)
            notice._resize_to_content()
            self.app.processEvents()
            titles = [label.text() for label in notice.findChildren(QLabel)
                      if label.isVisible() and 'v0.8' in label.text()]
            self.assertEqual(titles, ['软件 v0.8 可更新'])
            self.assertTrue(notice.indicator.isVisible())
            self.assertTrue(download.isVisible() and settings.isVisible())
            download_position = download.mapTo(notice, download.rect().center())
            settings_position = settings.mapTo(notice, settings.rect().center())
            self.assertLess(download_position.x(), settings_position.x())
            self.assertLessEqual(abs(download_position.y() - settings_position.y()), 1)
            self.assertLessEqual(notice.height(), 150)
            directory = os.environ.get('DDM_UPDATE_PREVIEW')
            if directory:
                notice.grab().save(str(Path(directory) / f'update-toast-{mode}.png'))

        QTest.mouseClick(notice.windowHandle(), Qt.LeftButton,
                         pos=download.mapTo(notice, download.rect().center()))
        self.assertEqual(requested, ['app'])
        self.assertFalse(opened)
        self.host.resize(316, 500)
        notice.set_transfer('app', dict(phase='downloading', percent=25, received=25, total=100))
        self.app.processEvents()
        self.assertTrue(progress.bar.isVisible() and settings.isVisible())
        self.assertEqual(progress.bar.value(), 25)
        self.assertTrue(notice.rect().contains(settings.geometry()))
        self.assertTrue(notice.rect().contains(progress.bar.mapTo(notice, progress.bar.rect().bottomRight())))

        notice.set_transfer('app', dict(phase='ready', percent=100, received=100, total=100))
        self.assertTrue(download.isVisible())
        self.assertEqual(download.text(), '重启以应用')
        notice.set_updates([app_entry, dict(key='plugin', title='插件 v1.0')])
        self.assertIs(notice._update_rows['app'][2], download)
        self.assertTrue(notice.updates_scroll.isVisible())
        self.assertIs(row.parentWidget(), notice.updates_container)
        notice.set_updates([app_entry])
        self.assertIs(row.parentWidget(), notice)
        self.assertTrue(notice.updates_scroll.isHidden())
        self.app.processEvents()
        QTest.mouseClick(notice.windowHandle(), Qt.LeftButton,
                         pos=settings.mapTo(notice, settings.rect().center()))
        self.assertEqual(opened, [True])
        self.assertEqual(requested, ['app'])

    def test_pointer_click_settings_edges_and_card_never_downloads(self):
        notice = UpdateNotice(self.host)
        notice.set_updates([dict(key='first', title='插件一'), dict(key='second', title='插件二')])
        requested, opened = [], []
        notice.updateRequested.connect(requested.append)
        notice.activated.connect(lambda: opened.append(True))
        for target in ('settings_center', 'settings_corner', 'button_gap', 'description'):
            notice.show_offer({'version': '9.0'}, persistent=True)
            self.app.processEvents()
            button = notice.settings_action
            if target == 'settings_center':
                point = button.mapTo(notice, button.rect().center())
            elif target == 'settings_corner':
                point = button.mapTo(notice, QPoint(1, 1))
            elif target == 'button_gap':
                point = QPoint(button.x() - 3, button.geometry().center().y())
            else:
                point = notice.description.mapTo(notice, notice.description.rect().center())
            requested.clear()
            opened.clear()
            QTest.mouseClick(notice.windowHandle(), Qt.LeftButton, pos=point)
            self.app.processEvents()
            self.assertEqual(requested, [], target)
            self.assertEqual(opened, [True], target)
        notice.show_offer({'version': '9.0'}, persistent=True)
        self.app.processEvents()
        opened.clear()
        point = notice.action.mapTo(notice, notice.action.rect().center())
        QTest.mouseClick(notice.windowHandle(), Qt.LeftButton, pos=point)
        self.app.processEvents()
        self.assertEqual(requested, ['first', 'second'])
        self.assertEqual(opened, [])
        notice.dismiss(animate=False)
        notice.deleteLater()

    def test_update_errors_explain_transport_http_storage_and_package_failures(self):
        cases = [
            (online.requests.exceptions.ChunkedEncodingError('IncompleteRead(131072 bytes read)'), '文件未接收完整'),
            (online.requests.ConnectTimeout('private URL'), '连接服务器超时'),
            (online.requests.ReadTimeout('private URL'), '传输数据超时'),
            (online.requests.exceptions.ProxyError('private proxy'), '代理服务器'),
            (online.requests.exceptions.SSLError('private certificate'), '安全连接验证失败'),
            (online.requests.ConnectionError('private host'), '无法连接服务器'),
            (OSError(errno.ENOSPC, 'private path'), '磁盘空间不足'),
            (PermissionError(errno.EACCES, 'private path'), '无法写入更新文件'),
            (zipfile.BadZipFile('private archive path'), '更新包损坏'),
            (ValueError('安装包完整性校验失败，请重新下载'), '完整性校验失败'),
            (online.requests.HTTPError('GitHub 查询额度暂时用尽，请稍后重试或打开发布页面'), '查询额度'),
            (RuntimeError('private raw exception'), '更新操作未能完成')]
        for status, phrase in ((403, '拒绝访问'), (404, '找不到此更新包'),
                               (429, '请求次数'), (503, 'HTTP 503')):
            response = online.requests.Response()
            response.status_code = status
            cases.append((online.requests.HTTPError('private signed URL', response=response), phrase))
        for error, expected in cases:
            with self.subTest(error=type(error).__name__, expected=expected):
                message = error_message(error)
                self.assertIn(expected, message)
                self.assertNotIn('private', message)
                self.assertNotIn('IncompleteRead', message)

    def test_failed_reason_is_readable_without_hover_and_clears_on_retry(self):
        surface = QWidget()
        surface.resize(510, 160)
        layout = QVBoxLayout(surface)
        progress = UpdateProgress(surface, button=QPushButton('下载更新'))
        layout.addWidget(progress)
        surface.show()
        message = error_message(online.requests.exceptions.ChunkedEncodingError('IncompleteRead(...)'))
        state = dict(received=131072, total=12 * 1024 * 1024, percent=1,
                     phase='failed', error=message)
        for mode in ('dark', 'light'):
            theme.apply(mode)
            progress.set_state(state)
            self.app.processEvents()
            self.assertTrue(progress.failure.isVisible())
            self.assertIn('文件未接收完整', progress.failure.text())
            self.assertIn('128.00 KB / 12.00 MB', progress.failure.text())
            self.assertGreaterEqual(progress.failure.height(), progress.failure.heightForWidth(progress.failure.width()))
            self.assertEqual(progress.button.text(), '重试')
            self.assertFalse(progress.bar.isVisible())
            directory = os.environ.get('DDM_UPDATE_PREVIEW')
            if directory:
                Path(directory).mkdir(parents=True, exist_ok=True)
                surface.grab().save(str(Path(directory) / f'failure-{mode}.png'))
        progress.set_state(dict(state, phase='downloading'))
        self.app.processEvents()
        self.assertFalse(progress.failure.isVisible())
        self.assertTrue(progress.bar.isVisible())
        progress.set_state(dict(state, phase='ready', percent=100))
        self.assertFalse(progress.failure.isVisible())
        surface.close()
        surface.deleteLater()
        theme.apply('dark')

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
        self.assertIsNone(progress.bar)
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
        self.assertTrue(button.property('updateReady'))
        self.assertFalse(button.icon().isNull())
        progress.set_state(dict(state, phase='failed', error='test disconnect'))
        self.assertEqual(button.text(), '重试')
        self.assertFalse(button.property('updateReady'))
        self.assertTrue(button.icon().isNull())
        surface.close()
        surface.deleteLater()

    def test_ready_feedback_stays_visible_in_both_themes_and_when_disabled(self):
        surface = QWidget()
        surface.setAutoFillBackground(True)
        layout = QVBoxLayout(surface)
        button = QPushButton('重启以应用')
        button.setObjectName('IconButton')
        progress = UpdateProgress(surface, button=button)
        layout.addWidget(progress)
        surface.show()
        state = dict(received=100, total=100, speed=0, percent=100, phase='ready')
        for mode in ('dark', 'light', 'dark'):
            theme.apply(mode)
            progress.set_state(state)
            button.setEnabled(False)
            self.app.processEvents()
            self.assertTrue(button.property('updateReady'))
            self.assertFalse(button.icon().isNull())
            capture = button.grab().toImage()
            color = capture.pixelColor(capture.width() // 2, capture.height() - 6)
            self.assertGreater(color.green(), color.red())
            self.assertGreater(color.green(), color.blue())
            directory = os.environ.get('DDM_UPDATE_PREVIEW')
            if directory:
                Path(directory).mkdir(parents=True, exist_ok=True)
                surface.grab().save(str(Path(directory) / ('ready-' + mode + '.png')))
        surface.close()
        surface.deleteLater()

    def test_plugin_details_expand_in_card_without_window_and_survive_rebuild(self):
        from ddm.settings_plugins import PluginSettingsPage
        self.stack.enter_context(patch.object(PluginStorePage, 'open_catalog'))
        key = 'fixture'
        self.manager.install_zip(str(self.package(key, '1.0')))
        offer = dict(id=key, name='测试插件', description='完整说明 ' * 30, author='作者' * 30,
                     version='2.0', available=True, notes='\n'.join('更新说明第' + str(n) for n in range(30)))
        page = PluginSettingsPage(self.manager)
        store = page.store_page
        store.show_offers([offer])
        store.offers = [offer]
        page.resize(680, 600)
        page.show()
        page.tabs.setCurrentIndex(1)
        self.app.processEvents()
        card = store._offer_cards[key]
        collapsed_height = card.height()
        windows = set(QApplication.topLevelWidgets())
        panel = store.show_details(offer)
        self.app.processEvents()
        self.assertIs(panel.parentWidget(), card)
        self.assertFalse(panel.isWindow())
        self.assertEqual(set(QApplication.topLevelWidgets()), windows)
        self.assertIsNone(QApplication.activeModalWidget())
        self.assertGreater(card.height(), collapsed_height)
        self.assertIn('更新说明第29', panel.document.text())
        self.assertEqual(store.scroll.horizontalScrollBar().maximum(), 0)
        with patch.object(store, 'install_offer') as install:
            store.buttons[key].click()
            install.assert_called_once_with(offer)
        panel.close()
        self.assertFalse(store._detail_buttons[key].isChecked())
        self.assertIs(store.show_details(offer), panel)
        store.show_offers([dict(offer, notes='新的更新记录')])
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertFalse(isValid(panel))
        self.assertTrue(store._detail_buttons[key].isChecked())
        self.assertIn('新的更新记录', store._details[key].document.text())
        page.tabs.setCurrentIndex(0)
        panel = page._show_installed_details(key)
        self.app.processEvents()
        self.assertIs(panel.parentWidget(), page._installed_cards[key])
        self.assertFalse(panel.isWindow())
        page.checks[key].setChecked(True)
        self.assertIn('本次选择：启用', panel.document.text())
        store._catalog_ready([dict(offer, notes='最新目录说明')])
        self.assertIs(page._details[key], panel)
        self.assertIn('最新目录说明', panel.document.text())
        page._store_installed(key)
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertFalse(isValid(panel))
        self.assertTrue(page._detail_buttons[key].isChecked())
        panel = page._details[key]
        for font_size in (13, 20):
            theme.configure_appearance({'appearance_font_size': font_size})
            theme.apply('dark')
            self.wait_for(lambda: panel.document.height() >= panel.document.heightForWidth(panel.document.width()))
            card = page._installed_cards[key]
            actions = card.layout().itemAt(card.layout().count() - 1)
            self.assertLessEqual(actions.geometry().height(), actions.sizeHint().height() + 1)
            self.assertGreaterEqual(panel.document.height(), panel.document.heightForWidth(panel.document.width()))
            self.assertEqual(page.installed_scroll.horizontalScrollBar().maximum(), 0)
            toggle = page._detail_buttons[key]
            self.assertGreaterEqual(toggle.width(), toggle.fontMetrics().horizontalAdvance(toggle.text()) + 50)
        directory = os.environ.get('DDM_UPDATE_PREVIEW')
        if directory:
            page._installed_cards[key].grab().save(str(Path(directory) / 'inline-details.png'))
        page.store_page.stop()
        page.close()
        page.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        theme.configure_appearance({'appearance_font_size': 13})
        theme.apply('dark')

    def test_app_update_action_keeps_its_left_anchor_through_transfer_states(self):
        page = self.host._get_update_page({})
        page.resize(1200, 700)
        page.show()
        self.app.processEvents()
        anchor = page.action.mapTo(page, QPoint()).x()
        check_right = page.check.mapTo(page, page.check.rect().topRight()).x()
        self.assertLess(anchor - check_right, 24)
        state = dict(received=1024, total=4096, speed=1024, percent=25, phase='downloading')
        for phase in ('downloading', 'verifying', 'ready', 'failed'):
            page._transfer_progress(dict(state, phase=phase, error='test disconnect'))
            self.app.processEvents()
            control = page.download_progress.bar if phase in ('downloading', 'verifying') else page.action
            self.assertEqual(control.mapTo(page, QPoint()).x(), anchor)
        page.close()

    def test_plugin_expansion_moves_only_its_column_and_keeps_one_footer(self):
        from ddm.settings_plugins import PluginSettingsPage
        self.stack.enter_context(patch.object(PluginStorePage, 'open_catalog'))
        keys = [f'column_{n}' for n in range(8)]
        for key in keys:
            self.manager.install_zip(str(self.package(key, '1.0')))
        offers = [dict(id=key, name=key, version='2.0', available=True,
                       description='插件说明', notes='更新内容\n' * 12) for key in keys]
        page = PluginSettingsPage(self.manager)
        store = page.store_page
        store.offers = offers
        store.show_offers(offers)
        page._show_update_notes(offers)
        page.setProperty('settings_card_layout', 'vertical')
        page.resize(1000, 650)
        page.show()
        for tab in (0, 1):
            page.tabs.setCurrentIndex(tab)
            cards = page._installed_cards if tab == 0 else store._offer_cards
            owner = page if tab == 0 else store
            self.app.processEvents()
            self.assertEqual(owner.cards._columns, 2,
                             (tab, page.width(), (page.installed_scroll if tab == 0 else store.scroll).viewport().width(),
                              [card.minimumSizeHint().width() for card in cards.values()]))
            self.wait_for(lambda: cards[keys[1]].x() > cards[keys[0]].x())
            before = {key: card.geometry() for key, card in cards.items()}
            owner._detail_buttons[keys[0]].setChecked(True)
            self.wait_for(lambda: cards[keys[2]].y() > before[keys[2]].y())
            for key in keys[1::2]:
                self.assertEqual(cards[key].geometry(), before[key], key)
            card = cards[keys[0]]
            panel = owner._details[keys[0]]
            footer = card.layout().itemAt(card.layout().count() - 1)
            self.assertGreaterEqual(footer.geometry().top(), panel.geometry().bottom())
            self.assertEqual(panel.findChildren(QPushButton), [], 'Details must reuse the original card controls')
            toggle = owner._detail_buttons[keys[0]]
            action = page.update_buttons[keys[0]] if tab == 0 else store.buttons[keys[0]]
            self.assertTrue(card.isAncestorOf(action))
            self.assertLessEqual(abs(action.mapTo(card, action.rect().center()).y() - toggle.mapTo(card, toggle.rect().center()).y()), 1)
            self.assertLess(action.mapTo(card, QPoint()).x(), toggle.mapTo(card, QPoint()).x())
            directory = os.environ.get('DDM_UPDATE_PREVIEW')
            if directory:
                Path(directory).mkdir(parents=True, exist_ok=True)
                page.grab().save(str(Path(directory) / f'independent-columns-{tab}.png'))
            owner._detail_buttons[keys[0]].setChecked(False)
            self.wait_for(lambda: cards[keys[2]].geometry() == before[keys[2]])
        page.resize(680, 650)
        self.wait_for(lambda: store._offer_cards[keys[0]].x() == store._offer_cards[keys[1]].x())
        self.assertEqual(store.scroll.horizontalScrollBar().maximum(), 0)
        page.store_page.stop()
        page.close()
        page.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

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

    def test_plugin_columns_resize_filter_sort_and_keep_download_controls(self):
        from ddm.settings_plugins import PluginSettingsPage
        self.stack.enter_context(patch.object(PluginStorePage, 'open_catalog'))
        keys = [f'responsive_{n}' for n in range(4)]
        for key in keys:
            self.manager.install_zip(str(self.package(key, '1.0')))
        offers = [dict(id=key, name=f'插件{4-index}', description='布局验收', author='Fixture',
                       version='2.0', available=True) for index, key in enumerate(keys)]
        page = PluginSettingsPage(self.manager)
        try:
            page.setProperty('settings_card_layout', 'vertical')
            store = page.store_page
            store.offers = offers
            store.show_offers(offers)
            page._show_update_notes(offers)
            state = dict(received=128 * 1024 * 1024, total=256 * 1024 * 1024,
                         speed=12 * 1024 * 1024, percent=50, phase='downloading')
            store.downloads.states[keys[0]] = state
            store._busy(False)
            with patch.object(self.manager, 'catalog', side_effect=AssertionError('unexpected catalog rescan')):
                page._sync_update_buttons()
                store.update_dots()
            page.show()
            for tab in (0, 1):
                page.tabs.setCurrentIndex(tab)
                owner = page if tab == 0 else store
                cards = dict(page._installed_cards if tab == 0 else store._offer_cards)
                buttons = dict(page.update_buttons if tab == 0 else store.buttons)
                progress = page._installed_progress[keys[0]] if tab == 0 else store._progress_widgets[keys[0]]
                browser = page.installed_browser if tab == 0 else store.browser
                scroll = page.installed_scroll if tab == 0 else store.scroll
                for width, columns in ((1000, 2), (680, 1), (1000, 2)):
                    page.resize(width, 650)
                    self.app.processEvents()
                    self.assertEqual(owner.cards._columns, columns)
                    self.assertEqual(scroll.horizontalScrollBar().maximum(), 0)
                    self.assertEqual(progress.bar.value(), 50)
                    self.assertTrue(progress.bar.isVisible())
                    self.assertFalse(progress.button.isVisible())
                    for key in keys:
                        current = page._installed_cards if tab == 0 else store._offer_cards
                        self.assertIs(current[key], cards[key])
                        self.assertIs((page.update_buttons if tab == 0 else store.buttons)[key], buttons[key])
                browser.search.setText(keys[0])
                self.assertEqual(owner.cards.count(), 1)
                self.assertIs(owner.cards.itemAt(0).widget(), cards[keys[0]])
                browser.search.clear()
                browser.sort.setCurrentIndex(1)
                # Installed packages retain their manifest names; store offers
                # deliberately use the reverse name order in this fixture.
                first = keys[0] if tab == 0 else keys[-1]
                self.assertIs(owner.cards.itemAt(0).widget(), cards[first])
                browser.filter.setCurrentIndex(3)
                self.assertEqual(owner.cards.count(), 4)
                self.assertEqual(progress.bar.value(), 50)
                self.assertEqual(len(buttons), 4)
                self.assertEqual(owner.cards._columns, 2)
        finally:
            page.store_page.stop()
            page.close()
            page.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_plugin_controls_use_shared_library_and_preserve_actions_and_check_signals(self):
        from PySide6.QtWidgets import QDialog
        from ddm.settings_performance import SettingsProbe
        from ddm.settings_plugins import PluginRemovePrompt, PluginSettingsPage
        from ddm.ui import ActionButton, DisclosureButton, SelectControl, ToggleSwitch
        self.stack.enter_context(patch.object(PluginStorePage, 'open_catalog'))
        probe = SettingsProbe(self.root / 'plugin-settings-performance.jsonl')
        self.stack.callback(probe.stop)
        self.stack.enter_context(patch.object(PluginSettingsPage, '_installed_selection_changed',
                                              PluginSettingsPage._installed_selection_changed))
        probe.wrap(PluginSettingsPage, '_installed_selection_changed', trace_each=True)
        key = 'shared_controls'
        self.manager.install_zip(str(self.package(key, '1.0')))
        page = PluginSettingsPage(self.manager)
        prompt = PluginRemovePrompt('测试插件')
        try:
            store = page.store_page
            offers = [dict(id=key, name='已安装插件', version='2.0', available=True),
                      dict(id='new_plugin', name='新插件', version='1.0', available=True)]
            store.offers = offers
            store.show_offers(offers)
            page._show_update_notes(offers)
            page.resize(1000, 650)
            page.show()
            self.app.processEvents()
            for browser in (page.installed_browser, store.browser):
                for control in (browser.filter, browser.sort):
                    self.assertIsInstance(control, SelectControl)
                    changed = []
                    control.currentIndexChanged.connect(changed.append)
                    QTest.keyClick(control, Qt.Key_Down)
                    self.assertEqual(control.currentIndex(), 1)
                    self.assertEqual(changed[-1], 1)
                    control.setCurrentIndex(0)
                self.assertEqual(browser.search.objectName(), 'Search')
            card = page._installed_cards[key]
            check = page.checks[key]
            self.assertIsInstance(check, ToggleSwitch)
            self.assertEqual(check.text(), '启用')
            self.assertIn(key, check.accessibleName())
            self.assertTrue(check.accessibleDescription())
            labels = [label for label in card.findChildren(QLabel) if label.buddy() is check]
            self.assertEqual([label.text() for label in labels], ['启用'])
            self.assertTrue(labels[0].isVisible())
            states, toggled, page_changes = [], [], []
            check.stateChanged.connect(states.append)
            check.toggled.connect(toggled.append)
            page.changed.connect(lambda: page_changes.append(check.isChecked()))
            before = check.isChecked()
            QTest.keyClick(check, Qt.Key_Space)
            self.assertEqual(check.isChecked(), not before)
            self.assertEqual(states, [Qt.Checked.value if check.isChecked() else Qt.Unchecked.value])
            self.assertEqual(toggled, [not before])
            self.assertEqual(page_changes, [not before])
            self.assertIn('重启后生效', page.card_details[key][1].text())
            for control in (page.install_button, page.update_buttons[key], store.refresh,
                            *store.buttons.values(), prompt.cancel_button, prompt.delete_button):
                self.assertIsInstance(control, ActionButton)
            remove = next(button for button in card.findChildren(QPushButton) if button.text() == '删除')
            self.assertIsInstance(remove, ActionButton)
            self.assertIsInstance(page._detail_buttons[key], DisclosureButton)
            self.assertTrue(prompt.cancel_button.isDefault())
            self.assertFalse(prompt.delete_button.autoDefault())
            self.assertEqual(prompt.delete_button.objectName(), 'PrimaryButton')
            with patch('ddm.settings_plugins.QFileDialog.getOpenFileName', return_value=('', '')) as choose:
                page.install_button.click()
                choose.assert_called_once()
            with patch.object(store, 'refresh_catalog') as refresh:
                store.refresh.click()
                refresh.assert_called_once_with(force=True)
            with patch.object(store, 'install_offer') as install:
                page.update_buttons[key].click()
                store.buttons['new_plugin'].click()
                self.assertEqual(install.call_count, 2)
                install.assert_any_call(offers[0])
                install.assert_any_call(offers[1])
            with patch.object(page, '_remove') as delete:
                remove.click()
                delete.assert_called_once_with(key, card)
            prompt.cancel_button.click()
            self.assertEqual(prompt.result(), QDialog.DialogCode.Rejected)
            prompt.delete_button.click()
            self.assertEqual(prompt.result(), QDialog.DialogCode.Accepted)
        finally:
            prompt.deleteLater()
            store.stop()
            page.close()
            page.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

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
                raise online.requests.exceptions.ChunkedEncodingError('test connection lost')
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
                self.assertIn('文件未接收完整', notice._update_rows[key][1].failure.text())
                self.assertTrue(notice._update_rows[key][1].failure.isVisible())
                reason = notice._update_rows[key][1].failure
                self.assertGreaterEqual(reason.height(), reason.heightForWidth(reason.width()))
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
        page.resize(1000, 600)
        page.show()
        page._release_ready(dict(version='9.0', size=100))
        with patch.object(sys, 'frozen', True, create=True), patch.object(online, 'session', return_value=Session()), \
                patch.object(online, 'download', return_value='test.zip'), \
                patch.object(update_install, 'prepare', side_effect=ValueError('更新包版本与发布记录不一致')):
            page.download_update()
            self.wait_for(lambda: not page.jobs)
            self.assertEqual(page.download_state['phase'], 'failed')
            self.assertIn('更新包版本与发布记录不一致', page.download_progress.failure.text())
            self.assertTrue(page.download_progress.failure.isVisible())
            self.assertIn('更新包版本与发布记录不一致', page.status.text())
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
