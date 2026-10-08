"""启动更新开关、非模态悬浮提示、跳转、十秒消失和关闭收尾。"""
from contextlib import ExitStack
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from unittest.mock import patch

os.environ['DDM_NO_SAVE'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication, QMessageBox
from ddm import app as app_module, config, online, plugin_updates, theme
from ddm.dialogs import SettingsDialog
from selfcheck_online_ui import Session


def settle(app, window):
    end = time.monotonic() + 5
    while (window._startup_update_task is not None or window._startup_plugin_task is not None) and time.monotonic() < end:
        app.processEvents()
        QTest.qWait(10)
    app.processEvents()
    assert window._startup_update_task is None
    assert window._startup_plugin_task is None


def main():
    app = QApplication([])
    app.setStyleSheet(theme.qss())
    offer = {'version': '0.3.1', 'notes': '# 更新说明\n\n修复内容'}
    with ExitStack() as stack:
        temporary = stack.enter_context(tempfile.TemporaryDirectory(prefix='ddm-update-notice-'))
        stack.enter_context(patch.object(config, 'REPO', temporary))
        stack.enter_context(patch.object(online, 'session', return_value=Session()))
        stack.enter_context(patch.object(online, 'cached_plugin_catalog', return_value=[]))
        for method in ('refresh_status', 'refresh_stats', 'refresh_account', 'load_room_avatars',
                       'load_cached_covers', 'load_cached_avatars', 'start_all'):
            stack.enter_context(patch.object(app_module.MainWindow, method))
        modal = stack.enter_context(patch.object(QMessageBox, 'information'))
        (Path(temporary) / 'RELEASE-v0.3.md').write_text('# 当前版本说明', encoding='utf-8')
        disabled = app_module.MainWindow([], [], state={'plugins_enabled': []})
        with patch.object(online, 'app_release') as check:
            assert disabled._startup_update_timer.isActive() == bool(disabled.plugins.catalog())
            disabled._check_startup_update()
            check.assert_not_called()
        disabled.close()
        window = app_module.MainWindow([], [], state={'plugins_enabled': [], 'settings': {'auto_update': True}})
        window.show()
        app.processEvents()
        assert window._startup_update_timer.isActive()
        with patch.object(online, 'app_release', return_value=offer) as check, \
                patch.object(online, 'download') as download:
            window._startup_update_timer.timeout.emit()
            settle(app, window)
            notice = window._update_notice
            assert notice and notice.isVisible()
            assert notice.windowModality() == Qt.NonModal and notice.isWindow()
            assert notice.testAttribute(Qt.WA_ShowWithoutActivating)
            assert notice.windowFlags() & Qt.WindowDoesNotAcceptFocus
            assert notice.timer.interval() == 10_000 and notice.timer.isActive()
            image = notice.grab().toImage()
            assert image.pixelColor(0, 0).alpha() < 50 and image.pixelColor(20, 50).alpha() > 240, \
                'floating notice must have a painted body and transparent rounded corners'
            window._check_startup_update()
            assert check.call_count == 1, 'startup check must run once'
            download.assert_not_called()
        opened = []
        class InspectDialog(SettingsDialog):
            def exec(self):
                opened.append((self.nav.currentRow(), self.update_page.offer, self.update_page.auto.isChecked()))
                self.reject()
                return self.result()
        with patch.object(app_module, 'SettingsDialog', InspectDialog):
            QTest.mouseClick(notice.action, Qt.LeftButton)
        assert opened == [(5, offer, True)] and not notice.isVisible()
        assert not notice.timer.isActive() and window.settings['auto_update']
        assert window.sidebar.settings_button._update_dot.isHidden()
        assert window.settings['seen_update_versions']['app'] == offer['version']
        window._startup_update_ready((None, offer))
        assert not notice.isVisible(), 'viewed app version must not notify again'
        # 手动检查发现没有新版时，清除本体标记。
        window._set_app_update(None)
        assert window.sidebar.settings_button._update_dot.isHidden()
        window._set_app_update(offer)
        # 真正经过十秒，未点击的提醒自动消失，不执行下载或跳转。
        activated = QSignalSpy(notice.activated)
        notice.show_offer(offer)
        old_position = notice.pos()
        window.move(window.x() + 25, window.y() + 25)
        app.processEvents()
        assert notice.pos() != old_position
        QTest.qWait(10_400)
        assert not notice.isVisible() and activated.count() == 0
        class DisableDialog(SettingsDialog):
            def exec(self):
                self.update_page.auto.setChecked(False)
                self.confirm_button.click()
                return self.result()
        with patch.object(app_module, 'SettingsDialog', DisableDialog), patch.object(config, 'save') as save:
            assert window.open_settings('updates')
            assert not window.settings['auto_update'] and save.called
            assert window.current_state()['settings']['auto_update'] is False
        window.close()
        latest = app_module.MainWindow([], [], state={'plugins_enabled': [], 'settings': {'auto_update': True}})
        with patch.object(online, 'app_release', return_value=None):
            latest._check_startup_update()
            settle(app, latest)
            assert latest._update_notice is None
        latest.close()
        # 本体自动检查关闭时，已安装插件仍可在启动检查后提示。
        plugins_window = app_module.MainWindow([], [], state={'plugins_enabled': [], 'settings': {'auto_update': False}})
        plugins_window.show()
        plugin_offer = {'id': 'domestic_live', 'name': '国内平台', 'description': '测试',
                        'version': '2.0', 'available': True}
        installed = [{'id': 'domestic_live', 'version': '1.0', 'name': '国内平台',
                      'description': '测试', 'enabled': False, 'status': '未启用', 'reason': ''}]
        with patch.object(plugins_window.plugins, 'catalog', return_value=installed), \
                patch.object(online, 'cached_plugin_catalog', return_value=[plugin_offer]), \
                patch.object(online, 'app_release') as app_check:
            plugins_window._check_startup_update()
            settle(app, plugins_window)
            app_check.assert_not_called()
            assert plugins_window._plugin_update_offers == [plugin_offer]
            assert not plugins_window.sidebar.settings_button._update_dot.isHidden()
            assert plugins_window.sidebar.settings_button._update_dot.x() > plugins_window.sidebar.settings_button.width() // 2
            class GeneralInspectDialog(SettingsDialog):
                def exec(self):
                    assert self.nav.item(4).data(Qt.UserRole + 1)
                    self.reject()
                    return self.result()
            with patch.object(app_module, 'SettingsDialog', GeneralInspectDialog):
                plugins_window.open_settings()
            assert plugins_window.sidebar.settings_button._update_dot.isHidden()
            assert plugins_window._unread_plugin_updates(), 'entering general settings only acknowledges the entry dot'
            plugin_notice = plugins_window._update_notice
            assert plugin_notice.isVisible() and '插件可更新' in plugin_notice.title.text()
            plugin_notice._motion.stop()
            plugin_notice._progress = 1.0
            plugin_notice.reposition()
            assert abs(plugin_notice.x() - (plugins_window.x() + (plugins_window.width() - plugin_notice.width()) // 2)) < 5
            plugin_opened = []
            class PluginInspectDialog(SettingsDialog):
                def exec(self):
                    plugin_opened.append((self.nav.currentRow(), self.plugin_page.tabs.currentIndex()))
                    self.reject()
                    return self.result()
            with patch.object(app_module, 'SettingsDialog', PluginInspectDialog):
                plugin_notice.action.click()
            assert plugin_opened == [(4, 1)] and not plugin_notice.isVisible()
            assert plugins_window.sidebar.settings_button._update_dot.isHidden()
            assert plugins_window.settings['seen_update_versions']['domestic_live'] == '2.0'
            plugins_window._startup_plugins_ready((None, [plugin_offer]))
            assert not plugin_notice.isVisible(), 'viewed plugin version must not notify again'
            plugin_offer = dict(plugin_offer, version='2.1')
            plugins_window._set_plugin_updates([plugin_offer])
            # 两种更新独立管理，清除本体更新不能抹掉插件红点。
            plugins_window._set_app_update(offer)
            plugins_window._set_app_update(None)
            assert not plugins_window.sidebar.settings_button._update_dot.isHidden()
            dialog = SettingsDialog(plugins_window.settings, {}, plugins_window, plugin_manager=plugins_window.plugins)
            dialog.plugin_page.store_page._catalog_ready([plugin_offer])
            assert dialog.nav.item(4).data(Qt.UserRole + 1)
            assert not dialog._plugin_update_dot.isHidden()
            dialog.update_page._release_ready(offer)
            assert dialog.nav.item(5).data(Qt.UserRole + 1)
            dialog.update_page._release_ready(None)
            assert not dialog.nav.item(5).data(Qt.UserRole + 1)
            with patch.object(plugin_updates, 'pending_versions', return_value={'domestic_live': '2.1'}):
                dialog.plugin_page.store_page._catalog_ready([plugin_offer])
                plugins_window._set_plugin_updates([plugin_offer])
                assert not dialog.nav.item(4).data(Qt.UserRole + 1)
                assert dialog._plugin_update_dot.isHidden()
                assert plugins_window.sidebar.settings_button._update_dot.isHidden()
            # 未安装或版本相同的插件不应产生红点。
            plugins_window._set_plugin_updates([dict(plugin_offer, version='1.0'),
                                               dict(plugin_offer, id='global_live')])
            assert not plugins_window._plugin_update_offers
            dialog.seen_versions.pop('domestic_live', None)
            dialog.plugin_page.store_page._catalog_ready([plugin_offer])
            assert dialog.nav.item(4).data(Qt.UserRole + 1)
            dialog.nav.setCurrentRow(4)
            assert not dialog.nav.item(4).data(Qt.UserRole + 1)
            assert dialog._plugin_update_dot.isHidden()
            assert dialog.plugin_page.store_page.buttons['domestic_live']._update_dot.isHidden()
            assert dialog.plugin_page.store_page.buttons['domestic_live'].property('storeEnabled')
            dialog.reject()
        plugins_window.close()
        closing = app_module.MainWindow([], [], state={'plugins_enabled': [], 'settings': {'auto_update': True}})
        started = threading.Event()
        def pending(*args):
            started.set()
            while not closing._startup_update_task.isInterruptionRequested():
                time.sleep(0.01)
            return offer
        with patch.object(online, 'app_release', side_effect=pending):
            closing._check_startup_update()
            assert started.wait(2)
            closing.close()
            settle(app, closing)
            assert closing._update_notice is None, 'late results after closing must not show a notice'
        modal.assert_not_called()
    print('PASS: independent app/plugin badges, pending and uninstalled exclusions, centered startup notice, page routing, ten-second dismissal and safe shutdown')


if __name__ == '__main__':
    main()
