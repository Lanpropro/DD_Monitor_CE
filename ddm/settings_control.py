"""Settings entry, page wiring and application; the window owns sessions and state."""
from copy import deepcopy
import os
import sys
import time

from . import config as config_module
from .update_version import update_identity


class SettingsControl:
    def __init__(self, host):
        self.host = host

    def streamer_rooms(self):
        from .streamer_settings_catalog import room_choices
        return room_choices(self.host)

    def request_streamer_quality(self, room_id, reply):
        if getattr(self, '_streamer_catalog', None) is None:
            from .streamer_settings_catalog import StreamerSettingsCatalog
            self._streamer_catalog = StreamerSettingsCatalog(self.host)
        self._streamer_catalog.request(room_id, reply)

    def open_sidebar_settings(self):
        host = self.host
        if os.environ.get("DDM_SETTINGS_PROCESS") != "1":
            return host.open_settings()
        session = getattr(host, '_settings_host', None)
        if session is not None:
            session.sync()
        host._get_settings_process().open(host.settings, host.shortcuts, host._sc_preview_context(),
                                          streamer_rooms=self.streamer_rooms())
        return False

    def sc_preview_context(self):
        host = self.host
        from PySide6.QtCore import QPoint
        def surface(widget, events, presentation):
            cards = [{'message': event.get('message') or event.get('text') or '',
                      'collapsed': presentation.is_collapsed(event)} for event in events]
            return {'size': [max(1, widget.width()), max(1, widget.height())],
                    'cards': cards or [{'message': '', 'collapsed': False}]}

        panel = host.wall.danmaku
        context = {'panel': surface(panel.body.viewport(), panel.super_chats._events,
                                    panel.super_chats.presentation)}
        viewport = panel.body.viewport()
        origin = viewport.mapTo(panel, QPoint())
        context['panel'].update(outer_size=[max(1, panel.width()), max(1, panel.height())],
                                viewport_rect=[origin.x(), origin.y(), viewport.width(), viewport.height()])
        tile = host._fullscreen_tile or host.wall.danmaku_target_tile()
        if tile is not None:
            video = tile.video_danmaku
            context['video'] = surface(video, video.super_chat_overlay.chats,
                                       video.super_chat_overlay.presentation)
        return context

    def get_settings_process(self):
        host = self.host
        if getattr(host, "_settings_process", None) is None:
            from .settings_process import SettingsProcess
            host._settings_process = SettingsProcess(host)
            host._settings_process.saved.connect(host._remote_settings_saved)
            from .settings_autosave_apply import handle_request
            host._settings_process.autoSaveRequested.connect(lambda message: handle_request(host, message))
            host._settings_process.hostRequest.connect(host._settings_host_request)
            host._settings_process.closed.connect(host._close_settings_host)
            host._settings_process.occlusionChanged.connect(
                lambda: host.wall._quick_danmaku_layer.show()
                if not host._closing and host.wall._quick_danmaku_layer is not None else None)
            host._settings_process.failed.connect(lambda message: host._show_notice(
                "独立设置窗口未能启动；点击此通知使用原设置窗口", kind="error", on_click=host.open_settings))
        return host._settings_process

    def remote_settings_saved(self, changes):
        host = self.host
        if getattr(host, '_closing', False) or not any(changes.values()):
            return
        from types import SimpleNamespace
        dialog = SimpleNamespace(
            settings=lambda: changes.get("settings", {}),
            shortcuts=lambda: {**host.shortcuts, **changes.get("shortcuts", {})},
            enabled_plugins=lambda: host.plugins.enabled,
            _loaded_pages={}, restart_requested=False)
        before = (None if host.plugins.enabled is None else set(host.plugins.enabled),
                  dict(host.plugins._platform_owner), set(host.plugins._removed))
        host._apply_settings_dialog(dialog, before)

    def settings_host_request(self, message):
        host = self.host
        if getattr(host, '_closing', False):
            return
        if message['kind'] == 'streamer-quality':
            room_id, token = message.get('room_id'), message.get('token')
            client = host._settings_process
            if isinstance(room_id, str) and room_id and isinstance(token, str):
                def reply(options, error):
                    if client.visible and not client.closing:
                        client._send({'kind': 'streamer-quality-result', 'room_id': room_id,
                                      'token': token, 'options': options, 'error': error})
                self.request_streamer_quality(room_id, reply)
            return
        session = getattr(host, '_settings_host', None)
        if session is None:
            if message['kind'] not in ('host-page', 'host-general'):
                return
            from .settings_host import SettingsHost
            session = host._settings_host = SettingsHost(host, host._settings_process, message)
        session.handle(message)

    def close_settings_host(self):
        host = self.host
        session = getattr(host, '_settings_host', None)
        if session is not None:
            host._settings_host = None
            session.close()

    def get_update_page(self, settings):
        host = self.host
        if getattr(host, '_app_update_page', None) is None:
            from .online_ui import AppUpdatePage
            host._app_update_page = AppUpdatePage(settings, host)
            host._app_update_page.releaseChecked.connect(host._set_app_update)
            host._app_update_page.transferChanged.connect(host.app_updates.app_transfer_changed)
        page = host._app_update_page
        page.auto.setChecked(bool(settings.get('auto_update', False)))
        return page

    def create_settings_dialog(self, settings=None, shortcuts=None, *, dialog_class, hosted=False):
        host = self.host
        SettingsDialog = dialog_class
        seen = dict(host.settings.get('seen_update_entry_versions') or {})
        if host._available_update:
            seen['app'] = update_identity(host._available_update)
        seen.update({offer['id']: offer['version'] for offer in host._plugin_update_offers})
        if seen != (host.settings.get('seen_update_entry_versions') or {}):
            host.settings['seen_update_entry_versions'] = seen
            host._mark_updates()
            config_module.save(host.current_state())
        dialog = SettingsDialog(host.settings if settings is None else settings,
                                host.shortcuts if shortcuts is None else shortcuts, host,
                                plugin_manager=host.plugins, update_page_factory=host._get_update_page,
                                streamer_rooms=self.streamer_rooms(),
                                **({'hosted': True} if hosted else {}))
        from .settings_process import host_layout_context
        dialog.set_host_layout(**host_layout_context(host))

        def page_created(index, widget):
            key = dialog.PAGES[index][0]
            if key == 'danmaku':
                widget.sync_blocking(host.settings)
                widget.super_chat_placement.set_preview_context(host._sc_preview_context())
            elif key == 'plugins':
                widget.store_page.set_downloads(host.app_updates.plugin_downloads())
                widget.store_page.offersChanged.connect(host._set_plugin_updates)
                if host._plugin_catalog_offers:
                    widget.store_page._catalog_ready(host._plugin_catalog_offers)
            elif key == 'updates':
                if (host._available_update and not (widget.jobs or widget.plan_path)
                        and (not widget._checked or not widget.offer
                             or update_identity(widget.offer) != update_identity(host._available_update))):
                    widget._release_ready(host._available_update)
                    widget._busy(False)
        dialog.pageCreated.connect(page_created)
        def request_streamer_quality(room_id, token):
            from shiboken6 import isValid

            def reply(options, error):
                if isValid(dialog):
                    dialog.receive_streamer_quality(room_id, token, options, error)

            self.request_streamer_quality(room_id, reply)

        dialog.streamerQualityRequested.connect(request_streamer_quality)
        dialog.updatesViewed.connect(host._remember_updates)
        dialog.appearanceChanged.connect(host.set_appearance)
        dialog._mark_update_page('plugins', any(dialog.seen_versions.get(offer['id']) != offer['version']
                                                for offer in host._plugin_update_offers))
        dialog._mark_update_page('updates', bool(host._available_update and
                                                dialog.seen_versions.get('app') != update_identity(host._available_update)))
        from .settings_autosave_apply import bind_dialog
        bind_dialog(host, dialog)
        return dialog

    def open_settings(self, page: str = "general", *, dialog_class) -> bool:
        host = self.host
        SettingsDialog = dialog_class
        """一个窗口里选类别（常规 / 快捷键），和 Adobe 那类设置一样。"""
        started = time.perf_counter()
        plugins_before = (None if host.plugins.enabled is None else set(host.plugins.enabled),
                          dict(host.plugins._platform_owner), set(host.plugins._removed))
        dialog = host._create_settings_dialog()
        try:
            print(f"[设置耗时] 准备窗口 {(time.perf_counter() - started) * 1000:.1f}ms", file=sys.stderr, flush=True)
            for index, (key, _label) in enumerate(dialog.PAGES):
                if key == page:
                    dialog.nav.setCurrentRow(index)
                    break
            if page == "plugins":
                dialog.plugin_page.tabs.setCurrentIndex(1)
            if dialog.exec() != SettingsDialog.Accepted:
                return False
            return host._apply_settings_dialog(dialog, plugins_before)
        finally:
            dialog.deleteLater()

    def apply_plugin_selection(self, enabled_plugins):
        from .settings_performance import measure

        host = self.host
        manager = host.plugins
        before = manager.enabled
        after = None if enabled_plugins is None else set(enabled_plugins)
        manager.enabled = after

        def eligibility_changed(owner):
            return (before is None or owner in before) != (after is None or owner in after)

        if any(plugin.skin is not None and eligibility_changed(plugin.context.name)
               for plugin in manager.plugins):
            measure('SettingsControl.plugin_selection_skin', host.refresh_skin)
        if any(eligibility_changed(owner) for owner in manager._platform_owner.values()):
            measure('SettingsControl.plugin_selection_rooms', host._sync_platform_rooms)
        host.state['settings'] = dict(host.settings)
        state = measure('SettingsControl.plugin_selection_state', host.current_state)
        measure('SettingsControl.plugin_selection_save', config_module.save, state, raise_errors=True)

    def apply_settings_dialog(self, dialog, plugins_before, *, dialog_class):
        host = self.host
        SettingsDialog = dialog_class
        saved_at = time.perf_counter()
        appearance_before = {key: deepcopy(value) for key, value in host.settings.items()
                             if key.startswith('skin_') or key == 'appearance_mode'}
        codecs_before = {tile: host._codec_settings(tile) for tile in host.wall.tiles}
        updated_settings = dialog.settings()
        changed_keys = {key for key, value in updated_settings.items() if host.settings.get(key) != value}
        from .settings_material import DEFAULTS as MATERIAL_DEFAULTS, set_segment_motion
        from .appearance_preferences import DEFAULTS as APPEARANCE_DEFAULTS
        presentation_only = bool(changed_keys) and changed_keys <= (
            MATERIAL_DEFAULTS.keys() | APPEARANCE_DEFAULTS.keys()
            | {'notice_banner_enabled', 'tray_context_menu', 'windowed_transparent_controls'})
        host.settings.update(updated_settings)
        if 'windowed_transparent_controls' in changed_keys:
            for tile in host.wall.tiles:
                tile._layout_areas()
        if 'settings_segment_motion' in changed_keys:
            set_segment_motion(host, host.settings['settings_segment_motion'])
        if changed_keys & {"settings_glass_enabled", "settings_glass_opacity", "settings_no_shadows"}:
            from .notice_dialog import NoticeDialog
            for notice in host.findChildren(NoticeDialog):
                notice.set_material(host.settings)
        from . import theme
        if theme.configure_appearance(host.settings):
            theme.apply(host.settings['appearance_mode'])
        from .native_diagnostics import set_dump_enabled
        set_dump_enabled(host.settings.get("native_crash_dump", False))
        from .notification_center import NoticeRow
        from .online_ui import ResultNotice
        for notice in [*host.findChildren(NoticeRow), *host.findChildren(ResultNotice)]:
            if 'notice_banner_enabled' in changed_keys:
                from .room_artwork import style_room_notice
                style_room_notice(notice, notice.artwork)
            else:
                notice.update()
        for codec_dialog in host._codec_dialogs.values():
            codec_dialog.controls.set_defaults(config_module.codec_settings(host.settings))
        if not host.settings.get("auto_update", False):
            host._startup_update_timer.stop()
            update_page = getattr(host, '_app_update_page', None)
            downloads = getattr(host, '_plugin_downloads', None)
            if (host._update_notice is not None and not
                    ((update_page and update_page.download_state) or (downloads and downloads.states))):
                host._update_notice.dismiss()
        host._sync_fullscreen_audio()
        host.shortcuts = dialog.shortcuts()
        host._refresh_shortcuts()
        enabled_plugins = dialog.enabled_plugins()
        host.plugins.enabled = None if enabled_plugins is None else set(enabled_plugins)
        plugins_changed = (host.plugins.enabled, host.plugins._platform_owner, host.plugins._removed) != plugins_before
        appearance_after = {key: value for key, value in host.settings.items()
                            if key.startswith('skin_') or key == 'appearance_mode'}
        if appearance_after != appearance_before or plugins_changed:
            host.refresh_skin()
        print(f"[设置耗时] 应用控件和外观 {(time.perf_counter() - saved_at) * 1000:.1f}ms", file=sys.stderr, flush=True)
        if plugins_changed:
            host._sync_platform_rooms()
        host.state["settings"] = dict(host.settings)
        host.state.setdefault("ui", {})["shortcuts"] = dict(host.shortcuts)
        host._poll_timer.setInterval(host.poll_interval_ms())
        for player in host.players.values():
            player.freeze_watch = bool(host.settings.get("freeze_watch", True))
            player.set_volume_normalization(bool(host.settings.get("volume_normalization", False)), host.settings.get('volume_normalization_curve'))
        for tile in host.wall.tiles:
            if host._tile_codecs_changed(tile, codecs_before.get(tile, {})):
                host._restart_codec_tile(tile)
        if getattr(dialog, 'auto_saving', False) is True:
            config_module.save(host.current_state(), raise_errors=True)
        else:
            config_module.save(host.current_state())
        # 两个总开关改完要立刻生效：录制开关还可能停掉正在录的会话
        host._sync_recording_switch()
        host._sync_replay_scope()
        if not presentation_only or plugins_changed:
            host.apply_danmaku_settings()
        host.apply_preview_settings()
        print(f"[设置耗时] 保存并应用全部设置 {(time.perf_counter() - saved_at) * 1000:.1f}ms", file=sys.stderr, flush=True)
        print(f"[设置] {host.settings} 快捷键 {host.shortcuts}", file=sys.stderr, flush=True)
        update_page = dialog._loaded_pages.get(SettingsDialog.PAGE_INDEX['updates'])
        if getattr(update_page, "install_requested", False):
            host._update_plan = dialog.update_page.plan_path
            host.close()
        elif getattr(dialog, "restart_requested", False):
            host._restart_requested = True
            host.close()
        return True

    def set_appearance(self, mode: str) -> None:
        from PySide6.QtCore import QPoint
        from . import theme
        host = self.host
        host.settings["appearance_mode"] = theme.normalize_mode(mode)
        source = host.sender()
        page = getattr(source, 'appearance_page', None)
        if page is not None:
            if hasattr(host, '_theme_transition'):
                host._theme_transition.finish()
            theme.apply(host.settings["appearance_mode"])
        else:
            from .theme_transition import ThemeTransition
            if not hasattr(host, '_theme_transition'):
                host._theme_transition = ThemeTransition(host)
            button = host.sidebar.appearance_button
            host._theme_transition.change(host.settings["appearance_mode"], button.mapToGlobal(QPoint()))
        host._save_timer.start()

    def sidebar_card_mode_changed(self, enabled):
        host = self.host
        host.settings['sidebar_card_mode'] = enabled
        host.settings['sidebar_auto_compact'] = False
        host._save_timer.start()

    def set_skin(self, values):
        host = self.host
        active = host.plugins.active_skin()
        if active is not None and active['version'] == 1:
            host.refresh_skin()
            return
        host.settings.update(values)
        host.refresh_skin()
        config_module.save(host.current_state())

    def set_skin_parts(self, values):
        host = self.host
        from .skin_parts import validate_parts
        from pathlib import Path
        validate_parts(values, Path(config_module.data_root()) / 'utils' / 'skins')
        host.settings['skin_parts'] = deepcopy(values)
        host.refresh_skin()
        config_module.save(host.current_state())

    def apply_preview_settings(self) -> None:
        """关注列表样式与悬停预览开关。"""
        host = self.host
        before = host.sidebar.card_mode
        host.sidebar.set_folder_collapse_mode(host.settings.get('folder_collapse_mode', 'all'))
        host.sidebar.show_platform_logos = bool(host.settings.get("sidebar_platform_logos", True))
        host.sidebar._sync_count()
        host.sidebar.set_compact_background(
            bool(host.settings.get("sidebar_compact_background", True)))
        host.sidebar.set_compact_policy(
            bool(host.settings.get("sidebar_card_mode", True)),
            bool(host.settings.get("sidebar_auto_compact", True)),
            int(host.settings.get("sidebar_compact_threshold", 18)),
        )
        if host.sidebar.card_mode != before:
            host.hover_preview.stop()
        host.hover_preview.enabled = bool(host.settings.get("preview_on_hover", True))
        if not host.hover_preview.enabled:
            host.hover_preview.stop()
