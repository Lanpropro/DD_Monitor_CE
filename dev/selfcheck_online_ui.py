"""商店实际下载安装/升级、后台任务关闭、版本页和录制退出接入。"""
import json
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from unittest.mock import patch
import zipfile

os.environ['DDM_NO_SAVE'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtTest import QTest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QTimer, Qt
from PySide6.QtWidgets import QApplication, QFrame, QLabel
from ddm import app as app_module, config, online, theme, update_install
from ddm.dialogs import PluginRemovePrompt, SettingsDialog
from ddm.online_ui import OnlinePage, PluginStorePage
from ddm.version import VERSION, VERSION_TAG
from ddm.plugins import PluginManager, read_manifest


def check_store_scroll(app, root):
    from types import SimpleNamespace
    entries = [dict(id=key, name=name, description=description, version='1.0', enabled=True,
                    status='已加载', reason='') for key, (name, description) in online.KNOWN_PLUGINS.items()]
    manager = SimpleNamespace(catalog=lambda: [dict(entry) for entry in entries], enabled=None,
                              plugins_dir=str(root / 'scroll-plugins'), _removed=set())
    offers = [dict(entry, version='1.1', available=True, notes='\n'.join(['更新说明，保留阅读位置'] * 18))
              for entry in entries]
    offers.extend(dict(id=f'scroll_{index}', name=f'浏览测试 {index}', description='紧凑插件说明',
                       version='1.0', available=True) for index in range(24))
    with patch.object(PluginStorePage, 'open_catalog'):
        dialog = SettingsDialog({}, {}, plugin_manager=manager)
        dialog.nav.setCurrentRow(SettingsDialog.PAGE_INDEX['plugins'])
        dialog.plugin_page.tabs.setCurrentIndex(1)
        store = dialog.plugin_page.store_page
        store.offers = offers
        store.show_offers(offers)
        dialog.show()
        app.processEvents()
        scroll = store.scroll
        bar = scroll.verticalScrollBar()
        button = store.buttons[offers[1]['id']]
        button.setFocus()
        app.processEvents()
        scroll.ensureWidgetVisible(button)
        app.processEvents()
        assert bar.maximum() > 500
        task = SimpleNamespace(key=offers[1]['id'], percent=0)
        def start(operation, callback, key=None):
            store.jobs.append(task)
            store.busyChanged.emit(True)
        try:
            with patch.object(store, 'start', start), patch('ddm.online_ui.show_result'):
                QTest.mousePress(button, Qt.LeftButton)
                app.processEvents()
                before = bar.value()
                QTest.mouseRelease(button, Qt.LeftButton)
                app.processEvents()
                assert bar.value() == before, ('Download start moved scroll', before, bar.value(), button.hasFocus(), app.focusWidget())
                bar.setValue(min(bar.maximum(), before + 40))  # Reading another card during download remains possible.
                before = bar.value()
                with patch.object(store, 'sender', return_value=task):
                    store._progress(50)
                app.processEvents()
                assert bar.value() == before, 'Download progress moved scroll'
                store.jobs.clear()
                store.busyChanged.emit(False)
                store._installed((offers[1]['id'], False))
                app.processEvents()
                assert bar.value() == before, 'Install completion moved scroll'
            page = dialog.plugin_page
            plugin_id = entries[0]['id']
            card = page.cards.itemAt(0).widget()
            with patch.object(manager, 'remove_plugin', create=True) as remove:
                def cancel(prompt):
                    text = '\n'.join(label.text() for label in prompt.findChildren(QLabel))
                    assert entries[0]['name'] in text and plugin_id not in text
                    return PluginRemovePrompt.Rejected
                with patch.object(PluginRemovePrompt, 'exec', cancel):
                    page._remove(plugin_id, card)
                remove.assert_not_called()
                assert plugin_id in page.checks
                with patch.object(PluginRemovePrompt, 'exec', return_value=PluginRemovePrompt.Accepted):
                    page._remove(plugin_id, card)
                remove.assert_called_once_with(plugin_id)
                assert plugin_id not in page.checks
        finally:
            store.jobs.clear()
            dialog.close()
            dialog.deleteLater()
            app.processEvents()


def check_store_browser(app, root):
    from types import SimpleNamespace
    offers = [dict(id=f'browser_{index:03d}', name=f'插件 {63-index:02d}', version='1.1',
                   description='直播辅助 ' + ('录制工具' if index % 2 else '弹幕工具') + ' 长说明' * 30,
                   author='Alice' if index % 2 else 'Bob', available=True,
                   notes='\n'.join(f'完整更新说明 {line}' for line in range(60))) for index in range(64)]
    entries = [dict(offer, version='1.0', enabled=True, status='已加载', reason='') for offer in offers[:3]]
    offers[1]['version'] = '1.0'
    offers[2].update(available=False, reason='需要新版主程序')
    offers[62].update(name='插件 99 ' + '很长的插件名称' * 30, author='Bob' * 60)
    manager = SimpleNamespace(catalog=lambda: entries, enabled=None,
                              plugins_dir=str(root / 'browser-plugins'), _removed=set())
    for mode in ('dark', 'light'):
        theme.apply(mode)
        with patch.object(PluginStorePage, 'open_catalog'):
            page = PluginStorePage(manager)
            page.show_offers(offers)
            page.resize(540, 560)
            page.show()
            app.processEvents()
            assert page.count.text() == '64 / 64 个插件'
            assert page.scroll.horizontalScrollBar().maximum() == 0
            assert all(card.height() < 112 for card in page._offer_cards.values())
            page.resize(400, 560)
            app.processEvents()
            assert page.scroll.horizontalScrollBar().maximum() == 0, 'Long titles/authors must not widen the plugin list'
            page.resize(540, 560)
            app.processEvents()
            position = page.search.mapTo(page, QPoint()).y()
            page.scroll.verticalScrollBar().setValue(400)
            app.processEvents()
            assert page.search.mapTo(page, QPoint()).y() == position, 'Search must remain above the scrolling list'
            page.search.setText('ALICE 录制')
            assert page.count.text() == '32 / 64 个插件'
            page.search.clear()
            page.filter.setCurrentIndex(3)
            assert page.count.text() == '1 / 64 个插件'
            assert page.cards.itemAt(0).widget() is page._offer_cards['browser_000']
            page.filter.setCurrentIndex(2)
            assert page.count.text() == '3 / 64 个插件'
            page.filter.setCurrentIndex(1)
            assert page.count.text() == '61 / 64 个插件'
            page.filter.setCurrentIndex(0)
            page.sort.setCurrentIndex(1)
            assert page.cards.itemAt(0).widget() is page._offer_cards['browser_063']
            page.sort.setCurrentIndex(2)
            assert page.cards.itemAt(0).widget() is page._offer_cards['browser_000']
            button = page.buttons['browser_000']
            details = page.show_details(offers[0])
            app.processEvents()
            assert '完整更新说明 59' in details.document.toPlainText()
            with patch.object(page, 'install_offer') as install:
                details.action.click()
                install.assert_called_once_with(offers[0])
            page.jobs.append(SimpleNamespace(key='browser_000', percent=35))
            page._busy(True)
            assert not details.action.isEnabled() and '35%' in details.action.text()
            page.search.setText('没有这样的插件')
            assert page.empty.isVisible() and page.count.text() == '0 / 64 个插件'
            assert page.buttons['browser_000'] is button, 'Filtering must retain the active installation control'
            page.search.clear()
            page.jobs.clear()
            page._busy(False)
            page.show_offers([dict(offers[0], version='1.2')])
            assert not details.action.isEnabled() and details.action.text() == '目录已更新'
            details.reject()
            page.show_offers(offers[:1])
            app.processEvents()
            assert page.count.text() == '1 / 1 个插件'
            page.close()
            page.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    theme.apply('dark')
    print('PASS: compact catalog, fixed search, status filters, ordering, full details and active-download identity')


def check_plugin_page_boundaries(app, root):
    from types import SimpleNamespace
    entries = [dict(id=f'boundary_{index}', name=f'插件 {index}', version='1.0',
                    description='很长的插件说明 ' * 20, enabled=True, status='已加载', reason='')
               for index in range(12)]
    manager = SimpleNamespace(catalog=lambda: entries, enabled=None,
                              plugins_dir=str(root / 'boundary-plugins'), _removed=set())
    with patch.object(PluginStorePage, 'open_catalog'):
        dialog = SettingsDialog({}, {}, plugin_manager=manager)
        dialog.nav.setCurrentRow(SettingsDialog.PAGE_INDEX['plugins'])
        page = dialog.plugin_page.store_page
        page.offers = [dict(entry, available=True) for entry in entries]
        page.show_offers(page.offers)
        dialog.plugin_page.tabs.setCurrentIndex(1)
        dialog.show()
        QTest.qWait(180)
        def bounds(widget):
            return widget.rect().translated(dialog.mapFromGlobal(widget.mapToGlobal(QPoint())))
        assert bounds(page).contains(bounds(page.refresh)), 'Refresh must stay inside the store toolbar, clear of the tab edge'
        assert not bounds(page.search).intersects(bounds(page.refresh)), 'Search and refresh must not overlap'
        assert bounds(page.search).top() > bounds(dialog.plugin_page.tabs.tabBar()).bottom()
        assert bounds(page.scroll).bottom() <= dialog.height() - 8, 'List must remain inside the settings shell'
        assert dialog.height() - bounds(page.scroll).bottom() < 45, 'List should use the removed footer space'
        page.scroll.verticalScrollBar().setValue(page.scroll.verticalScrollBar().maximum())
        app.processEvents()
        assert bounds(page.cards.itemAt(page.cards.count()-1).widget()).bottom() <= bounds(page.scroll.viewport()).bottom() - 8
        dialog.close()
        dialog.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    print('PASS: plugin toolbar and list fit the shell without a save footer')


def check_installed_browser(app, root):
    from types import SimpleNamespace
    entries = [dict(id=f'installed_{index:02d}', name=f'插件 {15-index:02d}', version='1.0',
                    description='完整说明 ' * 60, enabled=index % 2 == 0,
                    status='已加载' if index % 2 == 0 else '未启用', reason='') for index in range(16)]
    entries[0].update(name='长名称' * 60, status='加载失败', reason='完整失败原因 ' * 80)
    offers = [dict(entry, version='1.1', author='Alice' if index % 2 else 'Bob' * 60,
                   available=True, notes='完整更新记录末尾') for index, entry in enumerate(entries[:3])]
    manager = SimpleNamespace(catalog=lambda: [dict(entry) for entry in entries], enabled=None,
                              plugins_dir=str(root / 'installed-browser'), _removed=set())
    for mode in ('dark', 'light'):
        theme.apply(mode)
        app.setStyleSheet(theme.qss())
        with patch.object(PluginStorePage, 'open_catalog'):
            dialog = SettingsDialog({}, {}, plugin_manager=manager)
            dialog.nav.setCurrentRow(SettingsDialog.PAGE_INDEX['plugins'])
            page = dialog.plugin_page
            store = page.store_page
            store.offers = offers
            store.show_offers(offers)
            store.offersChanged.emit(offers)
            browser = page.installed_browser
            dialog.show()
            QTest.qWait(180)
            assert browser.count.text() == '16 / 16 个插件'
            assert page.installed_scroll.horizontalScrollBar().maximum() == 0
            assert all(card.height() < 130 for card in page._installed_cards.values())
            browser.search.setText('ALICE 完整说明')
            assert browser.count.text() == '1 / 16 个插件'
            browser.search.clear()
            browser.filter.setCurrentIndex(1)
            assert browser.count.text() == '8 / 16 个插件'
            check = page.checks['installed_00']
            check.setChecked(False)
            assert browser.count.text() == '7 / 16 个插件' and page.needs_restart()
            browser.filter.setCurrentIndex(2)
            assert browser.count.text() == '9 / 16 个插件'
            assert page.checks['installed_00'] is check and not check.isChecked()
            assert '重启后生效' in page.card_details['installed_00'][1].text()
            check.setChecked(True)
            assert not page.needs_restart() and dialog.confirm_button.isHidden()
            browser.filter.setCurrentIndex(3)
            assert browser.count.text() == '3 / 16 个插件'
            browser.filter.setCurrentIndex(0)
            browser.sort.setCurrentIndex(1)
            assert page.cards.itemAt(0).widget() is page._installed_cards['installed_15']
            browser.sort.setCurrentIndex(2)
            assert page.cards.itemAt(0).widget() is page._installed_cards['installed_02']
            details = page._show_installed_details('installed_00')
            assert entries[0]['reason'] in details.document.toPlainText()
            assert '完整更新记录末尾' in details.document.toPlainText()
            with patch.object(store, 'install_offer') as install:
                details.action.click()
                install.assert_called_once_with(offers[0])
            store.jobs.append(SimpleNamespace(key='installed_00', percent=45))
            store._busy(True)
            assert not details.action.isEnabled() and '45%' in details.action.text()
            store.jobs.clear()
            store._busy(False)
            details.reject()
            offline = page._show_installed_details('installed_15')
            assert not offline.action.isEnabled() and offline.action.text() == '暂无更新'
            offline.reject()
            browser.search.setText('没有匹配的插件')
            assert page.empty.isVisible() and browser.count.text() == '0 / 16 个插件'
            hidden_card = page._installed_cards['installed_00']
            page.checks['installed_01'].setChecked(True)
            page._store_installed('installed_02')
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            import shiboken6
            assert not shiboken6.isValid(hidden_card), 'Rebuild must also remove filtered-out cards'
            assert page.checks['installed_01'].isChecked(), 'Rebuild must retain unsaved choices'
            browser.search.clear()
            browser.sort.setCurrentIndex(0)
            for width in (900, 720):
                dialog.resize(width, 680)
                QTest.qWait(120)
                assert page.installed_scroll.horizontalScrollBar().maximum() == 0
                search_y = browser.search.mapTo(dialog, QPoint()).y()
                bar = page.installed_scroll.verticalScrollBar()
                bar.setValue(bar.maximum())
                app.processEvents()
                assert browser.search.mapTo(dialog, QPoint()).y() == search_y
                last = page.cards.itemAt(page.cards.count()-1).widget()
                assert last.mapTo(page.installed_scroll.viewport(), QPoint()).y() + last.height() <= page.installed_scroll.viewport().height() - 8
                assert page.installed_scroll.mapTo(dialog, QPoint()).y() + page.installed_scroll.height() <= dialog.height() - 8
            browser.search.setText('没有匹配的插件')
            with patch.object(manager, 'remove_plugin', create=True), patch.object(PluginRemovePrompt, 'exec', return_value=PluginRemovePrompt.Accepted):
                page._remove('installed_15', page._installed_cards['installed_15'])
            assert 'installed_15' not in page._installed_entries
            assert browser.count.text() == '0 / 15 个插件'
            dialog.close()
            dialog.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    theme.apply('dark')
    app.setStyleSheet(theme.qss())
    print('PASS: installed search, filters, selection retention, details, updates, rebuild, deletion and layout bounds')


def check_remove_prompt(app):
    for mode in ('dark', 'light'):
        theme.apply(mode)
        for action, result in (('cancel', PluginRemovePrompt.Rejected),
                               ('escape', PluginRemovePrompt.Rejected),
                               ('close', PluginRemovePrompt.Rejected),
                               ('enter', PluginRemovePrompt.Rejected),
                               ('delete', PluginRemovePrompt.Accepted)):
            prompt = PluginRemovePrompt('国内直播平台')
            assert prompt.minimumWidth() == 440
            assert prompt.windowTitle() == '删除插件'
            assert any('国内直播平台' in label.text() for label in prompt.findChildren(QLabel))
            assert prompt.cancel_button.text() == '取消' and prompt.cancel_button.isDefault()
            assert prompt.delete_button.text() == '删除'
            assert prompt.cancel_button.objectName() == 'IconButton'
            assert prompt.delete_button.objectName() == 'PrimaryButton'
            if action in ('escape', 'enter'):
                key = Qt.Key_Escape if action == 'escape' else Qt.Key_Return
                QTimer.singleShot(0, lambda prompt=prompt, key=key: QTest.keyClick(prompt, key))
            elif action == 'close':
                QTimer.singleShot(0, prompt.close)
            else:
                button = prompt.cancel_button if action == 'cancel' else prompt.delete_button
                QTimer.singleShot(0, button.click)
            assert prompt.exec() == result
            prompt.deleteLater()
            app.processEvents()
    theme.apply('dark')


class Session:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


def settle(app, page):
    deadline = time.monotonic() + 8
    while page.jobs and time.monotonic() < deadline:
        app.processEvents()
        QTest.qWait(10)
    app.processEvents()
    assert not page.jobs, 'background operation must finish'


def check_download_reopen(app, root):
    from types import SimpleNamespace
    for hosted in (False, True):
        started, release = threading.Event(), threading.Event()
        messages = []
        with patch.object(app_module.QTimer, 'singleShot'):
            window = app_module.MainWindow([], [], state={'plugins_enabled': [], 'settings': {'close_behavior': 'exit'}})
        if hosted:
            window._settings_process = SimpleNamespace(_send=messages.append, stop=lambda: None)
        plan = str(root / 'retained-update-plan.json')
        offer = {'version': '9.0', 'notes': 'New release'}

        def open_dialog():
            if hosted:
                window._settings_host_request({'kind': 'host-general', 'settings': window.settings,
                                               'shortcuts': window.shortcuts})
                dialog = window._settings_host.dialog
            else:
                dialog = window._create_settings_dialog()
            dialog.nav.setCurrentRow(SettingsDialog.PAGE_INDEX['updates'])
            return dialog

        def close_dialog(dialog):
            if hosted:
                window._close_settings_host()
            else:
                dialog.reject()
                dialog.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            app.processEvents()

        def download(_offer, destination, _client, cancelled, progress):
            progress(25, 100)
            started.set()
            while not release.wait(.01):
                if cancelled():
                    raise InterruptedError('Download interrupted on settings close')
            return str(destination)

        try:
            with patch.object(sys, 'frozen', True, create=True), \
                    patch.object(online, 'session', return_value=Session()), \
                    patch.object(online, 'download', side_effect=download) as downloading, \
                    patch.object(update_install, 'prepare', return_value=plan), \
                    patch.object(update_install, 'discard_plan') as discard:
                first = open_dialog()
                page = first.update_page
                page._release_ready(offer)
                page.action.click()
                assert started.wait(2)
                app.processEvents()
                assert '25%' in page.status.text()
                close_dialog(first)
                assert not page.stopping and len(page.jobs) == 1, 'Closing settings must keep the download'
                second = open_dialog()
                assert second.update_page is page and '25%' in page.status.text()
                assert not second.confirm_button.isEnabled(), 'Reopened settings must reflect the busy task'
                assert not page.action.isEnabled()
                close_dialog(second)
                release.set()
                settle(app, page)
                assert page.plan_path == plan, 'Download must finish while settings is closed'
                third = open_dialog()
                assert third.update_page is page and page.action.text() == '重启并更新'
                assert third.confirm_button.isEnabled()
                downloading.assert_called_once()
                discard.assert_not_called()
                page.action.click()
                assert page.install_requested
                if hosted:
                    assert sum(m['kind'] == 'host-request-save' for m in messages) == 1
                    window._close_settings_host()
                else:
                    assert third.result() == SettingsDialog.Accepted
                    third.deleteLater()
        finally:
            release.set()
            window._close_settings_host()
            window.close()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            app.processEvents()
    print('PASS: same download/progress and prepared update after closing/reopening normal and hosted settings')
    with patch.object(app_module.QTimer, 'singleShot'):
        window = app_module.MainWindow([], [], state={'plugins_enabled': [], 'settings': {'close_behavior': 'exit'}})
    page = window._get_update_page({})
    started, interrupted = threading.Event(), threading.Event()
    def wait_for_exit(cancelled, progress):
        started.set()
        while not cancelled():
            time.sleep(.01)
        interrupted.set()
    page.start(wait_for_exit, lambda _result: None)
    assert started.wait(2)
    window.close()
    settle(app, page)
    assert interrupted.wait(2) and page.stopping, 'Application exit must stop a hidden update task'


def main():
    app = QApplication([])
    app.setStyleSheet(theme.qss())
    check_remove_prompt(app)
    ui_thread = threading.get_ident()
    with tempfile.TemporaryDirectory(prefix='ddm-online-ui-') as temporary, patch.object(config, 'REPO', temporary):
        root = Path(temporary)
        check_store_browser(app, root)
        check_plugin_page_boundaries(app, root)
        check_installed_browser(app, root)
        check_download_reopen(app, root)
        check_store_scroll(app, root)
        (root / f'RELEASE-{VERSION_TAG}.md').write_text('# 当前版本说明\n\n- 已完成的功能', encoding='utf-8')
        archive = root / 'plugin.zip'
        def write_package(version):
            with zipfile.ZipFile(archive, 'w') as package:
                package.writestr('global_live/plugin.json', json.dumps({
                    'id': 'global_live', 'name': '海外直播平台', 'description': 'Twitch / YouTube',
                    'version': version, 'min_app_version': '0.3'}))
                package.writestr('global_live/plugin.py', "raise RuntimeError('must not load before restart')")
        write_package('1.0')
        manager = PluginManager(plugins_dir=str(root / 'plugins'), enabled=[])
        saves = []
        manager._save_settings = lambda: saves.append(threading.get_ident())
        dialog = SettingsDialog({}, {}, plugin_manager=manager)
        dialog.show()
        assert dialog.nav.item(SettingsDialog.PAGE_INDEX['updates']).text() == '软件更新'
        dialog.nav.setCurrentRow(SettingsDialog.PAGE_INDEX['updates'])
        assert dialog.reset_button.isHidden()
        page = dialog.plugin_page.store_page
        offers = [{'id': 'global_live', 'name': '海外直播平台', 'description': 'Twitch / YouTube',
                   'version': '1.0', 'available': True,
                   'url': f'https://github.com/{online.PLUGIN_REPOSITORY}/releases/download/v1.0/global_live-1.0.zip',
                   'size': archive.stat().st_size, 'sha256': hashlib.sha256(archive.read_bytes()).hexdigest()}]
        with patch.object(online, 'session', return_value=Session()), \
                patch.object(online, 'plugin_catalog', return_value=offers) as catalog, \
                patch.object(online, 'download', return_value=str(archive)):
            dialog.nav.setCurrentRow(SettingsDialog.PAGE_INDEX['plugins'])
            assert not page.refresh.isVisible()
            dialog.plugin_page.tabs.setCurrentIndex(1)
            settle(app, page)
            assert page.refresh.isVisible()
            assert page.browser.isAncestorOf(page.refresh)
            assert not page.search.geometry().intersects(page.refresh.geometry())
            bar = dialog.plugin_page.tabs.tabBar()
            tab_rect = bar.tabRect(1)
            tab_image = bar.grab().toImage()
            assert tab_image.pixelColor(tab_rect.topLeft()) != tab_image.pixelColor(
                tab_rect.topLeft() + QPoint(5, tab_rect.height() // 2)), 'selected tab corners must actually be rounded'
            original_button = page.buttons['global_live']
            dialog.plugin_page.tabs.setCurrentIndex(0)
            assert not page.refresh.isVisible()
            dialog.plugin_page.tabs.setCurrentIndex(1)
            settle(app, page)
            assert catalog.call_count == 1 and page.buttons['global_live'] is original_button
            page.refresh.click()
            settle(app, page)
            assert page.buttons['global_live'] is original_button, 'unchanged catalog must preserve displayed cards'
            assert page.buttons['global_live'].text() == '安装'
            page.buttons['global_live'].click()
            assert not dialog.confirm_button.isEnabled()
            settle(app, page)
            assert manager.enabled == {'global_live'} and saves == [ui_thread]
            assert dialog.plugin_page.checks['global_live'].isChecked()
            assert dialog.confirm_button.text() == '重启以应用'
            assert page.buttons['global_live'].text() == '已安装'
            assert not manager.plugins
            # 同 ID 更新暂存，原插件文件和禁用选择保留。
            dialog.plugin_page.checks['global_live'].setChecked(False)
            manager.enabled.clear()
            write_package('1.1')
            offers[0]['version'] = '1.1'
            page.refresh.click()
            settle(app, page)
            assert page.buttons['global_live'].text() == '更新'
            details = dialog.plugin_page._show_installed_details('global_live')
            assert details.action.text() == '更新' and details.action.isEnabled()
            details.action.click()
            settle(app, page)
            assert page.buttons['global_live'].text() == '待重启'
            assert details.action.text() == '待重启' and not details.action.isEnabled()
            details.reject()
            assert read_manifest(str(root / 'plugins' / 'global_live'), 'global_live')['version'] == '1.0'
            assert not dialog.plugin_page.checks['global_live'].isChecked()
            assert manager.enabled == set()
            cached_dialog = SettingsDialog({}, {}, plugin_manager=manager)
            cached_dialog.show()
            count = catalog.call_count
            cached_dialog.nav.setCurrentRow(SettingsDialog.PAGE_INDEX['plugins'])
            cached_dialog.plugin_page.tabs.setCurrentIndex(1)
            settle(app, cached_dialog.plugin_page.store_page)
            assert catalog.call_count == count + 1, 'first store entry must revalidate the persisted catalog'
            assert cached_dialog.plugin_page.store_page.buttons['global_live'].text() == '待重启'
            cached_dialog.plugin_page.tabs.setCurrentIndex(0)
            cached_dialog.plugin_page.tabs.setCurrentIndex(1)
            settle(app, cached_dialog.plugin_page.store_page)
            assert catalog.call_count == count + 1, 'tab switching must not repeatedly query the network'
            cached_dialog.close()
        update = dialog.update_page
        assert update.auto.isEnabled() and not update.auto.isChecked()
        assert '当前版本说明' in update.notes.toPlainText()
        with patch.object(online, 'app_release') as check, patch.object(online, 'download') as download:
            update.auto.click()
            assert dialog.settings()['auto_update'] is True
            check.assert_not_called()
            download.assert_not_called()
        offer = {'version': '0.3.1', 'notes': '修复内容', 'release_url': 'https://github.com/Lanpropro/DD_Monitor_CE/releases'}
        with patch.object(online, 'session', return_value=Session()), \
                patch.object(online, 'app_release', return_value=offer):
            update.check.click()
            settle(app, update)
            assert not update.action.isEnabled(), 'source checkout must not replace itself with EXE'
            assert update.notes.toPlainText() == '修复内容'
            assert update.notes_title.text() == '新版 0.3.1 更新说明'
        hotfix = dict(offer, version=VERSION, revision=1)
        dialog.nav.setCurrentRow(SettingsDialog.PAGE_INDEX['updates'])
        update._release_ready(hotfix)
        assert '热修复' in update.status.text() and '热修复' in update.notes_title.text()
        assert VERSION in update.status.text() and VERSION+'.1' not in update.status.text()
        from ddm.update_version import update_identity
        assert dialog.settings()['seen_update_versions']['app'] == update_identity(hotfix)
        update._release_ready(offer)
        dialog.nav.setCurrentRow(SettingsDialog.PAGE_INDEX['plugins'])
        # 已安装和商店卡片共用玻璃表面，区别于页面和旧的不透明灰底。
        from ddm.ui import SettingsSurface
        for tab in (0, 1):
            dialog.plugin_page.tabs.setCurrentIndex(tab)
            app.processEvents()
            card = next(card for card in dialog.plugin_page.tabs.currentWidget().findChildren(QFrame)
                        if card.objectName() == 'PluginCard' and card.isVisible())
            capture = dialog.grab().toImage()
            card_pixel = card.mapTo(dialog, QPoint(20, 5))
            page_pixel = dialog.plugin_page.mapTo(dialog, QPoint(2, 2))
            assert isinstance(card, SettingsSurface)
            assert capture.pixelColor(card_pixel) != capture.pixelColor(page_pixel), 'plugin card material must be visible'
            assert capture.pixelColor(card_pixel) != theme.qcolor(theme.CONTENT), 'plugin card must use translucent material'
        stage = root / 'stage'
        stage.mkdir()
        plan_path = stage / 'update-plan.json'
        plan_path.write_text(json.dumps({'stage': str(stage), 'new_exe': 'DD监控室CE-v0.3.1.exe'}), encoding='utf-8')
        with patch.object(sys, 'frozen', True, create=True), \
                patch.object(online, 'session', return_value=Session()), \
                patch.object(online, 'download', return_value=str(archive)), \
                patch('ddm.online_ui.update_install.prepare', return_value=str(plan_path)):
            update._busy(False)
            update.action.click()
            settle(app, update)
            assert update.action.text() == '重启并更新'
            update.action.click()
            assert update.install_requested and dialog.result() == SettingsDialog.Accepted
            (root / update_install.RESULT).write_text(json.dumps({'message': '软件更新完成'}), encoding='utf-8')
            auto_dialog = SettingsDialog({'auto_update': True}, {}, plugin_manager=manager)
            auto_dialog.show()
            automatic = auto_dialog.update_page
            assert automatic.auto.isChecked()
            assert automatic.status.text() == '软件更新完成'
            assert automatic.action.text() == '请先检查更新' and not automatic.action.isEnabled()
            app.processEvents()
            pixel = lambda: automatic.action.grab().toImage().pixelColor(10, automatic.action.height() // 2)
            assert pixel() != theme.qcolor(theme.ACCENT), 'Unavailable update must not look like an active blue button'
            automatic._release_ready(offer)
            assert automatic.action.isEnabled() and automatic.action.text() == '下载更新'
            assert pixel() == theme.qcolor(theme.ACCENT)
            automatic._release_ready(None)
            assert not automatic.action.isEnabled() and automatic.action.text() == '已是最新版本'
            with patch.object(online, 'app_release', return_value=None), \
                    patch.object(online, 'release_notes', side_effect=online.requests.HTTPError('offline')), \
                    patch.object(online, 'download') as download:
                automatic.check.click()
                settle(app, automatic)
                assert '当前版本说明' in automatic.notes.toPlainText()
                assert automatic.notes_title.text() == f'当前版本 {VERSION} 更新说明'
                assert automatic.auto.isEnabled() and not automatic.action.isEnabled()
                assert automatic.action.text() == '已是最新版本'
                download.assert_not_called()
            with patch.object(online, 'app_release', return_value=None), \
                    patch.object(online, 'release_notes', return_value='# 发布后修改的当前版本说明'):
                automatic.check.click()
                settle(app, automatic)
                assert automatic.notes.toPlainText() == '发布后修改的当前版本说明'
            with patch.object(online, 'app_release', side_effect=OSError('offline')), \
                    patch.object(online, 'download') as download:
                automatic.check.click()
                settle(app, automatic)
                assert 'offline' in automatic.status.text() and automatic.auto.isEnabled()
                assert automatic.action.text() == '请先检查更新' and automatic.check.isEnabled()
                assert '当前版本说明' in automatic.notes.toPlainText(), 'network failure must preserve current notes'
                download.assert_not_called()
            with patch.object(online, 'app_release', return_value=dict(offer, notes='# 新版\n\n- 修复内容')), \
                    patch.object(online, 'download', return_value=str(archive)) as download:
                automatic.check.click()
                assert not auto_dialog.confirm_button.isEnabled()
                settle(app, automatic)
                download.assert_not_called()
                with patch.object(online, 'download', side_effect=OSError('download failed')):
                    automatic.action.click()
                    settle(app, automatic)
                    assert 'download failed' in automatic.status.text()
                    assert automatic.action.isEnabled() and automatic.action.text() == '下载更新'
                    assert not automatic.plan_path
                automatic.action.click()
                settle(app, automatic)
                download.assert_called_once()
                assert automatic.plan_path == str(plan_path)
                assert automatic.action.text() == '重启并更新'
                assert not automatic.install_requested and automatic.auto.isEnabled()
                assert '新版' in automatic.notes.toPlainText() and '# 新版' not in automatic.notes.toPlainText()
                automatic.action.click()
                assert automatic.install_requested and auto_dialog.result() == SettingsDialog.Accepted
            auto_dialog.close()
        with patch.object(app_module.QProcess, 'startDetached', return_value=(True, 123)) as launch:
            assert app_module._launch_update(str(plan_path))
            launch.assert_called_once_with(str(stage / 'DD监控室CE-v0.3.1.exe'),
                                           ['--apply-update', str(plan_path)], str(stage))
        dialog.close()
        # 更新按钮复用正常关闭流程，录制必须收尾，不能跳过保存。
        class InstallDialog(SettingsDialog):
            def exec(self):
                self.update_page.plan_path = str(plan_path)
                self.update_page.install_requested = True
                self.confirm_button.click()
                return self.result()
        with patch.object(app_module.MainWindow, 'refresh_status'), \
                patch.object(app_module.MainWindow, 'refresh_stats'), \
                patch.object(app_module, 'SettingsDialog', InstallDialog), patch.object(config, 'save') as save:
            window = app_module.MainWindow([], [], state={'plugins_enabled': [], 'settings': {'close_behavior': 'exit'}})
            shutdown = window.recorder.shutdown
            with patch.object(window.recorder, 'shutdown', wraps=shutdown) as finish:
                assert window.open_settings('updates')
                assert window._closing and window._update_plan == str(plan_path)
                assert not window._restart_requested and save.called
                finish.assert_called_once()
        # 下载取消后等待工作线程退出，避免销毁仍运行的 QThread。
        standalone = OnlinePage()
        started = threading.Event()
        def wait_for_cancel(cancelled, progress):
            started.set()
            while not cancelled():
                time.sleep(0.01)
            return None
        called = []
        standalone.start(wait_for_cancel, called.append)
        assert started.wait(2)
        standalone.stop()
        settle(app, standalone)
        assert not called
        standalone.close()
        store = PluginStorePage(manager)
        store.resize(600, 400)
        credit_offer = {'id': 'bili_live', 'name': 'B站直播互动', 'description': '发送弹幕、表情和礼物',
                        'version': '1.0', 'available': True, 'author': 'reon-nynes'}
        store.show_offers([credit_offer])
        store.show(); app.processEvents()
        card = store.cards.itemAt(0).widget()
        credit = card.findChild(QLabel, 'PluginAuthor')
        assert credit is not None and credit.text() == '@reon-nynes'
        assert credit.textFormat() == Qt.PlainText
        where = credit.mapTo(card, QPoint(0, 0))
        assert where.x() > card.width() / 2 and where.y() > card.height() / 2
        assert card.rect().contains(credit.mapTo(card, credit.rect().bottomRight()))
        store.show_offers([{k: v for k, v in credit_offer.items() if k != 'author'}])
        assert store.cards.itemAt(0).widget().findChild(QLabel, 'PluginAuthor') is None
        store.close()
    print('PASS: store install/update, UI-thread saves, independent software update, cancel, restart and recording shutdown')


if __name__ == '__main__':
    main()
