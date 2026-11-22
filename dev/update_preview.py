"""Interactive update acceptance using production widgets and loopback downloads."""
import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DDM_NO_SAVE'] = '1'

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QHBoxLayout, QVBoxLayout, QWidget
from ddm.settings_pages import PAGE_INDEX
from ddm import app_update_ui, app_updates, config, online, theme, update_install
from ddm.app_updates import AppUpdates
from ddm.dialogs import SettingsDialog
from ddm.notification_center import NotificationButton
from ddm.plugins import PluginManager
from ddm.settings_control import SettingsControl
from ddm.ui import ActionButton, HintLabel, SelectControl, page_header
from update_preview_server import PreviewServer


class PreviewUpdates(AppUpdates):
    def restart_updates(self, page):
        self.host.confirmed += 1
        self.host.result.setText('已收到重启确认。验收窗口保留，未替换程序。')


class UpdatePreview(QWidget):
    def __init__(self, directory, server):
        super().__init__()
        self.directory, self.server = Path(directory), server
        self.settings = {'auto_update': True, 'notice_persist_updates': True}
        self._closing = False
        self._update_notice = self._app_update_page = self._plugin_downloads = None
        self.dialog = None
        self.confirmed = self.session = 0
        self.app_updates = PreviewUpdates(self)
        self.settings_control = SettingsControl(self)
        self.setWindowTitle('更新样式验收 · 本地测试')
        self.setObjectName('SettingsPage')
        self.resize(1100, 760)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(470, 32, 24, 24)
        layout.addLayout(page_header('更新样式验收',
            '在左上角通知点击下载，或打开设置。使用本地测试包；完成时仅演示重启确认。'))
        controls = QHBoxLayout()
        self.scenario = SelectControl(self)
        self.scenario.addItems(('正常下载（约20秒）', '慢速下载（约1分钟）',
                                '断流失败后重试', '校验失败后重试'))
        layout.addWidget(self.scenario)
        self.reset = ActionButton('重新开始', self)
        self.reset.clicked.connect(self.reset_session)
        controls.addWidget(self.reset)
        notice = ActionButton('显示更新通知', self)
        notice.clicked.connect(self._show_update_notice)
        controls.addWidget(notice)
        appearance = ActionButton('切换深浅色', self)
        appearance.clicked.connect(lambda: theme.apply('dark' if theme.is_light() else 'light'))
        controls.addWidget(appearance)
        controls.addStretch()
        layout.addLayout(controls)
        row = QHBoxLayout()
        software = ActionButton('打开软件更新页', self)
        software.clicked.connect(lambda: self.open_settings('updates'))
        plugins = ActionButton('打开插件页', self)
        plugins.clicked.connect(lambda: self.open_settings('plugins'))
        row.addWidget(software)
        row.addWidget(plugins)
        history = NotificationButton(self)
        row.addWidget(history)
        row.addStretch()
        layout.addLayout(row)
        self.sidebar = SimpleNamespace(notification_button=history, settings_button=software)
        self.result = HintLabel('选择场景后点“重新开始”；断流场景自动尝试三次，失败后点“重试”即可恢复。', self)
        layout.addWidget(self.result)
        layout.addStretch()
        self.reset_session()

    def reset_session(self):
        if (self._app_update_page and self._app_update_page.jobs) or (self._plugin_downloads and self._plugin_downloads.jobs):
            self.result.setText('当前仍在下载。完成后可重新开始，或关闭验收窗口结束本次测试。')
            return
        if self.dialog:
            self.dialog.reject()
        if self._update_notice:
            self._update_notice.dismiss(animate=False)
            self._update_notice.deleteLater()
            self._update_notice = None
        if self._app_update_page:
            self._app_update_page.stop()
            self._app_update_page.deleteLater()
            self._app_update_page = None
        if self._plugin_downloads:
            self._plugin_downloads.stop()
            self._plugin_downloads.deleteLater()
            self._plugin_downloads = None
        self.session += 1
        self.plugins = PluginManager(plugins_dir=str(self.directory / f'session-{self.session}' / 'plugins'), enabled=[])
        for key in ('preview_one', 'preview_two'):
            package = self.directory / ('old-' + key + '.zip')
            self.server.package(package, key, self.server.offer(key)['name'], '1.0', 1)
            self.plugins.install_zip(str(package))
        self.settings.pop('seen_update_versions', None)
        self.settings.pop('seen_update_entry_versions', None)
        self._available_update = dict(self.server.offer('app'), version='9.9.9')
        self._plugin_catalog_offers = [self.server.offer(key) for key in ('preview_one', 'preview_two')]
        self._set_plugin_updates(self._plugin_catalog_offers)
        self.server.scenario(self.scenario.currentIndex())
        self.result.setText('测试请求已就绪；可直接在通知下载，也可打开设置。')
        QTimer.singleShot(0, self._show_update_notice)

    def _show_update_notice(self):
        self.app_updates.show_update_notice()

    def _unread_app_update(self):
        return self.app_updates.unread_app_update()

    def _unread_plugin_updates(self):
        return self.app_updates.unread_plugin_updates()

    def _set_app_update(self, offer):
        self._available_update = offer

    def _set_plugin_updates(self, offers):
        self.app_updates.set_plugin_updates(offers)

    def _mark_updates(self):
        self.app_updates.mark_updates()

    def current_state(self):
        return {'settings': self.settings}

    def _get_update_page(self, settings):
        page = self.settings_control.get_update_page(settings)
        page.data_page.hide()
        if not (page.jobs or page.plan_path):
            page._release_ready(self._available_update)
        return page

    def open_settings(self, page='updates'):
        if self.dialog is None:
            dialog = self.dialog = SettingsDialog(self.settings, {}, self,
                plugin_manager=self.plugins, update_page_factory=self._get_update_page)
            for index in range(dialog.nav.count()):
                dialog.nav.item(index).setHidden(index not in (PAGE_INDEX['plugins'], PAGE_INDEX['updates']))
            def created(index, widget):
                if index == PAGE_INDEX['plugins']:
                    widget.store_page.set_downloads(self.app_updates.plugin_downloads())
                    widget.store_page._catalog_ready(self._plugin_catalog_offers)
            dialog.pageCreated.connect(created)
            dialog.updatesViewed.connect(self.app_updates.remember_updates)
            dialog.finished.connect(self._settings_finished)
            dialog.open()
        self.dialog.nav.setCurrentRow(PAGE_INDEX[page])
        if page == 'plugins':
            self.dialog.plugin_page.tabs.setCurrentIndex(1)
        self.dialog.raise_()

    def _settings_finished(self, result):
        dialog, self.dialog = self.dialog, None
        if result == SettingsDialog.Accepted:
            if dialog.restart_requested or (self._app_update_page and self._app_update_page.install_requested):
                self.app_updates.restart_updates(self._app_update_page)
                if self._app_update_page:
                    self._app_update_page.install_requested = False
        dialog.deleteLater()

    def prepare(self, archive, *args, **kwargs):
        plan = self.directory / 'preview-plan.json'
        plan.write_text('{}', encoding='utf-8')
        return str(plan)

    def closeEvent(self, event):
        self._closing = True
        if self.dialog:
            self.dialog.reject()
        if self._update_notice:
            self._update_notice.dismiss(animate=False)
        if self._app_update_page:
            self._app_update_page.stop()
        if self._plugin_downloads:
            self._plugin_downloads.stop()
        super().closeEvent(event)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--smoke', action='store_true')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='ddm-update-preview-') as temporary, ExitStack() as stack:
        stack.enter_context(patch.object(config, 'DATA_ROOT', temporary))
        stack.enter_context(patch.object(config, 'CONFIG_PATH', str(Path(temporary) / 'utils/config.json')))
        server = PreviewServer(temporary, unit=128 * 1024 if args.smoke else 4 * 1024 * 1024)
        stack.callback(server.stop)
        app = QApplication.instance() or QApplication([])
        theme.configure_appearance({'appearance_font': theme.danmaku_font_family()})
        theme.apply('dark')
        window = UpdatePreview(temporary, server)
        proxy = SimpleNamespace(frozen=True, executable=sys.executable, stderr=sys.stderr)
        stack.enter_context(patch.object(app_update_ui, 'sys', proxy))
        stack.enter_context(patch.object(app_updates, 'sys', proxy))
        stack.enter_context(patch.object(update_install, 'prepare', window.prepare))
        stack.enter_context(patch.object(update_install, 'discard_plan', lambda *args: None))
        stack.enter_context(patch.object(online, 'app_release', lambda *args: window._available_update))
        stack.enter_context(patch.object(online, 'release_notes', lambda *args: '本地更新样式验收'))
        stack.enter_context(patch.object(online, 'cached_plugin_catalog', lambda *args, **kwargs: window._plugin_catalog_offers))
        original_session = online.session
        def session():
            client = original_session()
            client.trust_env = False
            return client
        stack.enter_context(patch.object(online, 'session', session))
        window.show()
        if args.smoke:
            outcome = {'done': False, 'failed': False, 'started': False}
            timer = QTimer(window)
            def inspect():
                try:
                    if not outcome['started']:
                        window._update_notice.action.click()
                        outcome['started'] = True
                        return
                    page = window._app_update_page
                    downloads = window._plugin_downloads
                    if page.download_state.get('phase') == 'failed':
                        raise AssertionError(page.download_state)
                    if any(state['phase'] == 'failed' for state in downloads.states.values()):
                        raise AssertionError(downloads.states)
                    if not page.plan_path or downloads.jobs or page.jobs:
                        return
                    assert len(downloads.states) == 2 and all(state['phase'] == 'ready' for state in downloads.states.values())
                    window.open_settings('plugins')
                    assert window.dialog.plugin_page.needs_restart()
                    window.dialog.reject()
                    window.open_settings('updates')
                    assert window.dialog.update_page is page and page.download_progress.bar.value() == 100
                    window.dialog.reject()
                    window._update_notice._update_rows['app'][2].click()
                    assert window.confirmed == 1 and not window.plugins.plugins
                    assert not page.install_requested
                    outcome['done'] = True
                    print('PASS: loopback downloads, production notice/settings, staged plugins, confirmation without installation')
                    timer.stop()
                    window.close()
                except Exception:
                    import traceback
                    traceback.print_exc()
                    outcome['failed'] = True
                    timer.stop()
                    window.close()
            timer.timeout.connect(inspect)
            timer.start(50)
            QTimer.singleShot(15_000, lambda: window.close() if not outcome['done'] else None)
        result = app.exec()
        return int(not outcome['done'] or outcome['failed']) if args.smoke else result


if __name__ == '__main__':
    raise SystemExit(main())
