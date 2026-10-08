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
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QFrame
from ddm import app as app_module, config, online, theme
from ddm.dialogs import SettingsDialog
from ddm.online_ui import OnlinePage
from ddm.version import VERSION, VERSION_TAG
from ddm.plugins import PluginManager, read_manifest


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


def main():
    app = QApplication([])
    app.setStyleSheet(theme.qss())
    ui_thread = threading.get_ident()
    with tempfile.TemporaryDirectory(prefix='ddm-online-ui-') as temporary, patch.object(config, 'REPO', temporary):
        root = Path(temporary)
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
        assert dialog.nav.item(5).text() == '软件更新'
        dialog.nav.setCurrentRow(5)
        assert dialog.reset_button.isHidden()
        page = dialog.plugin_page.store_page
        offers = [{'id': 'global_live', 'name': '海外直播平台', 'description': 'Twitch / YouTube',
                   'version': '1.0', 'available': True,
                   'url': f'https://github.com/{online.PLUGIN_REPOSITORY}/releases/download/v1.0/global_live-1.0.zip',
                   'size': archive.stat().st_size, 'sha256': hashlib.sha256(archive.read_bytes()).hexdigest()}]
        with patch.object(online, 'session', return_value=Session()), \
                patch.object(online, 'plugin_catalog', return_value=offers) as catalog, \
                patch.object(online, 'download', return_value=str(archive)):
            dialog.nav.setCurrentRow(4)
            assert page.refresh.isHidden()
            dialog.plugin_page.tabs.setCurrentIndex(1)
            settle(app, page)
            assert page.refresh.isVisible()
            assert page.refresh.y() < dialog.plugin_page.tabs.tabBar().height()
            assert page.refresh.x() > dialog.plugin_page.tabs.tabBar().width()
            bar = dialog.plugin_page.tabs.tabBar()
            tab_rect = bar.tabRect(1)
            tab_image = bar.grab().toImage()
            assert tab_image.pixelColor(tab_rect.topLeft()) != tab_image.pixelColor(
                tab_rect.topLeft() + QPoint(5, tab_rect.height() // 2)), 'selected tab corners must actually be rounded'
            original_button = page.buttons['global_live']
            dialog.plugin_page.tabs.setCurrentIndex(0)
            assert page.refresh.isHidden()
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
            assert dialog.confirm_button.text() == '保存并重启'
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
            page.buttons['global_live'].click()
            settle(app, page)
            assert page.buttons['global_live'].text() == '待重启'
            assert read_manifest(str(root / 'plugins' / 'global_live'), 'global_live')['version'] == '1.0'
            assert not dialog.plugin_page.checks['global_live'].isChecked()
            assert manager.enabled == set()
            cached_dialog = SettingsDialog({}, {}, plugin_manager=manager)
            cached_dialog.show()
            count = catalog.call_count
            cached_dialog.nav.setCurrentRow(4)
            cached_dialog.plugin_page.tabs.setCurrentIndex(1)
            settle(app, cached_dialog.plugin_page.store_page)
            assert catalog.call_count == count, 'reopening settings must reuse the persisted catalog'
            assert cached_dialog.plugin_page.store_page.buttons['global_live'].text() == '待重启'
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
        # 已安装和商店的卡片都应使用页面底色，而不是独立的灰底。
        for tab in (0, 1):
            dialog.plugin_page.tabs.setCurrentIndex(tab)
            app.processEvents()
            card = next(card for card in dialog.plugin_page.tabs.currentWidget().findChildren(QFrame)
                        if card.objectName() == 'PluginCard' and card.isVisible())
            capture = dialog.grab().toImage()
            card_pixel = card.mapTo(dialog, QPoint(20, 5))
            page_pixel = dialog.plugin_page.mapTo(dialog, QPoint(2, 2))
            assert capture.pixelColor(card_pixel) == capture.pixelColor(page_pixel), 'plugin gray card fill must be removed'
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
            auto_dialog = SettingsDialog({'auto_update': True}, {}, plugin_manager=manager)
            auto_dialog.show()
            automatic = auto_dialog.update_page
            assert automatic.auto.isChecked()
            with patch.object(online, 'app_release', return_value=None), \
                    patch.object(online, 'download') as download:
                automatic.check.click()
                settle(app, automatic)
                assert '当前版本说明' in automatic.notes.toPlainText()
                assert automatic.notes_title.text() == f'当前版本 {VERSION} 更新说明'
                assert automatic.auto.isEnabled() and not automatic.action.isEnabled()
                download.assert_not_called()
            with patch.object(online, 'app_release', side_effect=OSError('offline')), \
                    patch.object(online, 'download') as download:
                automatic.check.click()
                settle(app, automatic)
                assert 'offline' in automatic.status.text() and automatic.auto.isEnabled()
                assert '当前版本说明' in automatic.notes.toPlainText(), 'network failure must preserve current notes'
                download.assert_not_called()
            with patch.object(online, 'app_release', return_value=dict(offer, notes='# 新版\n\n- 修复内容')), \
                    patch.object(online, 'download', return_value=str(archive)) as download:
                automatic.check.click()
                assert not auto_dialog.confirm_button.isEnabled()
                settle(app, automatic)
                download.assert_not_called()
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
            window = app_module.MainWindow([], [], state={'plugins_enabled': []})
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
    print('PASS: store install/update, UI-thread saves, independent software update, cancel, restart and recording shutdown')


if __name__ == '__main__':
    main()
