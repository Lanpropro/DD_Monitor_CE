"""Startup update checks and notifications; the window owns tasks, offers and UI."""
import sys

from . import config as config_module
from . import version as version_module
from .update_version import installed_revision, release_label, update_identity


class AppUpdates:
    def __init__(self, host):
        self.host = host

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
                    installed_revision(config_module.REPO, version_module.VERSION))
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
        app_offer = host._unread_app_update()
        plugin_offers = host._unread_plugin_updates()
        if not app_offer and not plugin_offers:
            return
        if host._update_notice is None:
            host._update_notice = UpdateNotice(host)
            host._update_notice.activated.connect(lambda: host.open_settings(
                "updates" if host._unread_app_update() else "plugins"))
        host._update_notice.show_offer(app_offer or {'version': ''},
            persistent=host.settings.get('notice_persist_updates', True))
        parts = []
        if app_offer:
            parts.append('软件有新版 v' + release_label(app_offer))
        if plugin_offers:
            parts.append(f'{len(plugin_offers)} 个插件可更新')
        host._update_notice.title.setText(' · '.join(parts))
        center = host.sidebar.notification_button.center
        entry = center.add(' · '.join(parts), kind='update',
            callback=lambda: host.open_settings('updates' if host._unread_app_update() else 'plugins'),
            action='查看更新', key=('update', update_identity(app_offer) if app_offer else '',
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
