"""Startup update checks and notifications; the window owns tasks, offers and UI."""
import sys

from . import config as config_module
from . import version as version_module
from .update_version import release_label, running_revision, update_identity


class AppUpdates:
    def __init__(self, host):
        self.host = host

    def plugin_downloads(self):
        host = self.host
        if getattr(host, '_plugin_downloads', None) is None:
            from .plugin_downloads import PluginDownloads
            host._plugin_downloads = PluginDownloads(host.plugins, host)
            host._plugin_downloads.changed.connect(self._plugin_transfer_changed)
            host._plugin_downloads.installed.connect(lambda result: host._set_plugin_updates(
                host._plugin_catalog_offers))
        return host._plugin_downloads

    def _plugin_transfer_changed(self, key):
        host = self.host
        if host._update_notice is None or key not in host._update_notice._update_rows:
            host._show_update_notice()
        if host._update_notice is not None:
            host._update_notice.set_transfer(key, self.plugin_downloads().states[key])

    def app_transfer_changed(self, state):
        host = self.host
        if host._update_notice is None or 'app' not in host._update_notice._update_rows:
            host._show_update_notice()
        if host._update_notice is not None:
            host._update_notice.set_transfer('app', state)

    def start_notice_update(self, key):
        host = self.host
        if host._closing:
            return
        page = host._get_update_page(host.settings) if key == 'app' else getattr(host, '_app_update_page', None)
        if key == 'app':
            if not page.jobs and not page.plan_path and host._available_update:
                page._release_ready(host._available_update)
            if page.plan_path:
                downloads = getattr(host, '_plugin_downloads', None)
                if page.jobs or (downloads and downloads.jobs):
                    return
                self.restart_updates(page)
            else:
                page.download_update()
        else:
            downloads = self.plugin_downloads()
            if downloads.states.get(key, {}).get('phase') == 'ready':
                if downloads.jobs or (page is not None and page.jobs):
                    return
                self.restart_updates(page)
            else:
                offer = next((entry for entry in host._plugin_update_offers if entry['id'] == key), None)
                if offer:
                    downloads.start(offer)

    def download_notice_updates(self):
        host = self.host
        if host._closing:
            return
        host._show_update_notice()
        if host._update_notice is not None:
            host._update_notice._open()

    def restart_updates(self, page):
        """Reuse the settings save handshake before closing an open settings session."""
        host = self.host
        app_ready = page is not None and bool(page.plan_path)
        session = getattr(host, '_settings_host', None)
        if session is not None:
            if app_ready:
                session.dialog.update_page.install_requested = True
            else:
                session.dialog.plugin_page._files_changed = True
            session.client._send({'kind': 'host-request-save'})
            return
        from PySide6.QtWidgets import QApplication
        from .dialogs import SettingsDialog
        dialog = QApplication.activeModalWidget()
        if isinstance(dialog, SettingsDialog) and dialog.parentWidget() is host:
            if app_ready:
                dialog.update_page.install_requested = True
            else:
                dialog.plugin_page._files_changed = True
            dialog._save()
            return
        if app_ready:
            page.install_requested = True
            host._update_plan = page.plan_path
        else:
            host._restart_requested = True
        host.close()

    def check_startup_update(self) -> None:
        host = self.host
        host._check_startup_plugins()
        if host._closing or host._startup_update_checked or not host.settings.get("auto_update", False):
            return
        from . import online
        from .online_ui import OnlineTask
        host._startup_update_checked = True
        def check(cancelled, progress):
            with online.session() as client:
                return online.app_release(client, version_module.VERSION,
                    running_revision(config_module.REPO))
        task = OnlineTask(check, None, host)
        host._startup_update_task = task
        task.succeeded.connect(host._startup_update_ready)
        task.failed.connect(host._startup_update_failed)
        task.finished.connect(host._startup_update_finished)
        task.start()

    def startup_update_ready(self, payload) -> None:
        host = self.host
        offer = payload[1]
        if host._closing or not host.settings.get("auto_update", False) or not offer:
            return
        host._set_app_update(offer)
        host._show_update_notice()

    def set_app_update(self, offer):
        host = self.host
        host._available_update = offer
        host._mark_updates()

    def set_plugin_updates(self, offers):
        host = self.host
        from .online_ui import plugin_update_offers
        host._plugin_catalog_offers = list(offers)
        host._plugin_update_offers = plugin_update_offers(host.plugins, offers)
        host._mark_updates()

    def mark_updates(self):
        host = self.host
        from .online_ui import set_update_dot
        seen = host.settings.get('seen_update_entry_versions') or {}
        offer = host._unread_app_update()
        active = bool((offer and seen.get('app') != update_identity(offer)) or any(
            seen.get(entry['id']) != entry['version'] for entry in host._unread_plugin_updates()))
        set_update_dot(host.sidebar.settings_button, active)
        host.sidebar.settings_button.setToolTip('有新版本，打开设置查看' if active else '打开设置')

    def unread_app_update(self):
        host = self.host
        seen = host.settings.get('seen_update_versions') or {}
        return host._available_update if (host._available_update
            and seen.get('app') != update_identity(host._available_update)) else None

    def unread_plugin_updates(self):
        host = self.host
        seen = host.settings.get('seen_update_versions') or {}
        return [offer for offer in host._plugin_update_offers
                if seen.get(offer['id']) != offer['version']]

    def remember_updates(self, versions):
        host = self.host
        host.settings['seen_update_versions'] = dict(versions)
        host._mark_updates()
        config_module.save(host.current_state())

    def check_startup_plugins(self):
        host = self.host
        if host._closing or host._startup_plugin_checked:
            return
        host._startup_plugin_checked = True
        if not host.plugins.catalog():
            return
        from pathlib import Path
        from . import online
        from .online_ui import OnlineTask
        path = Path(config_module.data_root()) / 'cache' / 'plugin-catalog.json'
        def check(cancelled, progress):
            with online.session() as client:
                return online.cached_plugin_catalog(client, version_module.VERSION, path)
        task = OnlineTask(check, None, host)
        host._startup_plugin_task = task
        task.succeeded.connect(host._startup_plugins_ready)
        task.failed.connect(host._startup_update_failed)
        task.finished.connect(host._startup_plugins_finished)
        task.start()

    def startup_plugins_ready(self, payload):
        host = self.host
        if host._closing:
            return
        host._set_plugin_updates(payload[1])
        if host._unread_plugin_updates():
            host._show_update_notice()

    def startup_plugins_finished(self):
        host = self.host
        task = host.sender()
        if task is host._startup_plugin_task:
            host._startup_plugin_task = None
        task.deleteLater()

    def show_update_notice(self):
        host = self.host
        from .online_ui import UpdateNotice
        page = getattr(host, '_app_update_page', None)
        downloads = getattr(host, '_plugin_downloads', None)
        app_offer = host._available_update if page is not None and page.download_state else host._unread_app_update()
        plugin_offers = {offer['id']: offer for offer in host._unread_plugin_updates()}
        if downloads is not None:
            plugin_offers.update(downloads.offers)
        plugin_offers = list(plugin_offers.values())
        if not app_offer and not plugin_offers:
            return
        if host._update_notice is None:
            host._update_notice = UpdateNotice(host)
            host._update_notice.activated.connect(lambda: host.open_settings(
                "updates" if "app" in host._update_notice._update_rows else "plugins"))
            host._update_notice.updateRequested.connect(self.start_notice_update)
        host._update_notice.show_offer(app_offer or {'version': ''},
            persistent=host.settings.get('notice_persist_updates', True))
        parts = []
        if app_offer:
            parts.append('软件有新版 v' + release_label(app_offer))
        if plugin_offers:
            parts.append(f'{len(plugin_offers)} 个插件可更新')
        entries = ([dict(key='app', title='软件 v' + release_label(app_offer),
                         enabled=bool(getattr(sys, 'frozen', False)),
                         hint='' if getattr(sys, 'frozen', False) else '源码版请通过仓库更新')]
                   if app_offer else [])
        entries.extend(dict(key=offer['id'], title=offer['name'] + ' v' + offer['version'])
                       for offer in plugin_offers)
        host._update_notice.set_updates(entries)
        if page is not None and page.download_state:
            host._update_notice.set_transfer('app', page.download_state)
        if downloads is not None:
            for key, state in downloads.states.items():
                host._update_notice.set_transfer(key, state)
        center = host.sidebar.notification_button.center
        entry = center.add(' · '.join(parts), kind='update',
            callback=self.download_notice_updates,
            action='下载更新',
            secondary_callback=lambda page='updates' if app_offer else 'plugins': host.open_settings(page),
            secondary_action='查看设置详情', key=('update', update_identity(app_offer) if app_offer else '',
                tuple(sorted((offer['id'], offer['version']) for offer in plugin_offers))))
        host._update_notice.track_history((center, entry))

    def startup_update_failed(self, payload) -> None:
        host = self.host
        if not host._closing:
            print(f"[更新检查] {payload[1]}", file=sys.stderr, flush=True)

    def startup_update_finished(self) -> None:
        host = self.host
        task = host.sender()
        if task is host._startup_update_task:
            host._startup_update_task = None
        task.deleteLater()
