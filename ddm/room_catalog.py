"""Followed room collection, asynchronous add/remove and platform activation; original window owns state."""


class RoomCatalog:
    def __init__(self, host):
        self.host = host
        self._add_panel = None
        self._add_target = None
        ui = getattr(host, 'state', {}).get('ui') or {}
        self.followed_live_only = ui.get('room_add_followed_live_only') is True

    def sync_platform_rooms(self) -> None:
        from . import config as config_module
        host = self.host
        host.hover_preview.cancel()
        active = {kind for kind, owner in host.plugins._platform_owner.items()
                  if owner not in host.plugins._removed and
                  (host.plugins.enabled is None or owner in host.plugins.enabled)}
        saved = config_module.sync_platform_rooms(host.current_state(), active)
        host.state["suspended_platform_rooms"] = saved["suspended_platform_rooms"]
        rooms, wall = config_module.build_rooms(saved)
        followed = {room["room_id"] for room in rooms}
        for room in host.sidebar.rooms():
            if room["room_id"] not in followed:
                host.sidebar.remove_room(room)
        for room in rooms:
            if not any(item["room_id"] == room["room_id"] for item in host.sidebar.rooms()):
                host.sidebar.add_room(room)
        host.sidebar.items_control.refresh_room_card_branding(host.plugins)
        for key in ("import_order", "custom_order"):
            getattr(host.sidebar, "set_" + key)(saved[key])
        host.sidebar.apply_pins(saved["pinned"])
        host.sidebar.set_folders(saved.get("follow_folders") or [])
        for index, room in enumerate(wall):
            if index >= len(host.wall.tiles):
                host.wall.add_room(host.room_placement.prepare_wall_entry(room))
                continue
            tile = host.wall.tiles[index]
            if str(tile.room.get("room_id") or "") == str(room.get("room_id") or ""):
                continue
            if tile is host._fullscreen_tile:
                host._exit_fullscreen()
            host.recorder.stop(tile)
            host._pending_capture.pop(tile, None)
            host._stop_tile(tile)
            room = host.room_placement.prepare_wall_entry(room)
            tile.set_volume(room["volume"])
            tile.set_audio_channel(room["audio_channel"])
            tile.set_muted(room["muted"])
            tile.set_room(room)
        host._refresh_meta()

    def room_dict(self, room_id: str) -> dict | None:
        from . import bili
        host = self.host
        room_id = str(room_id)
        for room in host.sidebar.rooms():
            if str(room.get("room_id")) == room_id:
                return room
        return bili.room_info(room_id) if room_id.isdigit() else None

    def open_add_room(self, *, dialog_type=None, target_tile=None, resolver_type=None) -> None:
        from .bili import InfoResolver
        from .room_add_panel import RoomAddPanel
        host = self.host
        if self._add_panel is None:
            self._add_panel = RoomAddPanel(host.sidebar)
            self._add_panel.submitted.connect(self._submit_inline)
            self._add_panel.followed_requested.connect(self._load_followed)
            self._add_panel.followed_selected.connect(self._select_followed)
            self._add_panel.preset_selected.connect(self._select_preset)
            self._add_panel.followed.live_only.setChecked(self.followed_live_only)
            self._add_panel.followed.live_only.toggled.connect(self._remember_followed_live_only)
        if not self._add_panel.busy:
            self._add_target = target_tile
            self._add_resolver_type = resolver_type or InfoResolver
        hints = [getattr(platform, 'room_input_hint', '') for platform in host.plugins.platforms.values()]
        self._add_panel.entry.setToolTip('房间号或直播间链接，每行一个；Ctrl+Enter 添加'
                                       + ''.join('；' + hint for hint in hints if hint))
        self._add_panel.set_file_filters([platform.room_input_file_filter
            for platform in host.plugins.platforms.values() if getattr(platform, 'room_input_file_filter', '')])
        presets = []
        for platform in host.plugins.platforms.values():
            provider = getattr(platform, 'room_input_presets', None)
            if callable(provider):
                presets.extend(room.as_dict() for room in provider())
        self._add_panel.set_presets(presets)
        target = self._add_target
        self._add_panel.open(can_choose_followed=target is not None,
                             focus_on_close=target.add_room_button if target is not None else None)

    def _load_followed(self):
        occupied = {str(tile.room.get('room_id') or '') for tile in self.host.wall.tiles}
        self._add_panel.followed.load(occupied)

    def _remember_followed_live_only(self, checked):
        self.followed_live_only = checked
        self.host._save_timer.start()

    def _select_preset(self, room, folder_id):
        host, panel = self.host, self._add_panel
        if host._closing or panel.busy:
            return
        if getattr(host, '_follow_import_timer', None) is not None:
            panel.show_error('正在导入关注，请稍后重试')
            return
        if any(item['room_id'] == room['room_id'] for item in host.sidebar.rooms()):
            panel.show_error(f'{room["uname"]} 已在关注列表')
            return
        panel.error.hide()
        panel.fit_to_search()
        host._import_selected_follows([room], folder_id=folder_id, on_complete=self._load_followed
                                      if panel.followed_toggle.isChecked() else None)

    def _select_followed(self, room_id):
        host, panel, target = self.host, self._add_panel, self._add_target
        if host._closing or panel.busy or target is None:
            return
        if target not in host.wall.visible_tiles() or target.room.get('room_id'):
            panel.show_error('原空格已不可用，请从其他空格重新打开')
            return
        if host._tile_of(room_id) is not None:
            self._load_followed()
            panel.show_error('该关注主播已在画面墙上')
            return
        room = next((room for room in host.sidebar.rooms() if str(room.get('room_id')) == room_id), None)
        if room is None:
            self._load_followed()
            panel.show_error('该主播已从关注列表移除')
            return
        host._on_room_added(dict(room), target_tile=target)
        panel.close_editor()
        self._add_target = None

    def _submit_inline(self, text, folder_id):
        from .room_add_input import normalize_room_lines, normalize_room_text
        panel, host = self._add_panel, self.host
        if panel.busy or host._closing:
            return
        try:
            rooms = normalize_room_lines(text, lambda line: normalize_room_text(line, host._normalize_room_input))
        except ValueError as error:
            panel.show_error(str(error))
            return
        target = self._add_target
        panel.set_busy(True)
        if len(rooms) == 1:
            self.add_room_id(rooms[0], folder_id=folder_id, target_tile=target,
                             resolver_type=self._add_resolver_type, on_complete=self._complete_inline)
        else:
            from .room_add_batch import RoomAddBatch
            RoomAddBatch(host, rooms, folder_id, target_tile=target,
                         resolver_type=self._add_resolver_type, on_complete=self._complete_batch).start()

    def _complete_inline(self, success, message=''):
        if self.host._closing:
            return
        panel = self._add_panel
        panel.set_busy(False)
        if success:
            panel.entry.clear()
            panel.close_editor()
            self._add_target = None
        else:
            panel.show_error(message)

    def _complete_batch(self, batch):
        if batch.failures:
            self._add_panel.entry.setPlainText('\n'.join(room_id for room_id, _reason in batch.failures))
            message = '\n'.join(f'{room_id}：{reason}' for room_id, reason in batch.failures)
            self._complete_inline(False, message)
        else:
            self._complete_inline(True)

    def add_room_id(self, room_id: str, *, folder_id: str = "", resolver_type, target_tile=None, on_complete=None) -> None:
        from PySide6.QtWidgets import QMessageBox
        host = self.host
        InfoResolver = resolver_type
        from .room_input import bili_profile_uid, is_bili_short_url
        def added(room):
            if host._closing:
                return
            host._on_room_added(room, folder_id=folder_id, target_tile=target_tile)
            if on_complete is not None:
                on_complete(True, '')
        short_link = is_bili_short_url(room_id)
        profile_link = bool(bili_profile_uid(room_id))
        existing = next((room for room in host.sidebar.rooms() if str(room.get("room_id")) == room_id), None)
        if existing is not None:
            if target_tile is not None:
                host._on_room_added(existing, folder_id=folder_id, target_tile=target_tile)
            if on_complete is not None:
                on_complete(True, '')
            print(f"房间 {room_id} 已在关注列表里")
            return
        platform = host.plugins.platform_for(room_id)
        if callable(getattr(platform, 'room_list', None)):
            from .room_list_import import RoomListImport
            def list_added(_added, _skipped, message):
                if on_complete is not None:
                    on_complete(not message, message)
                elif message:
                    QMessageBox.warning(host, '导入频道', message)
            RoomListImport(host, platform.room_list, room_id, folder_id=folder_id,
                           target_tile=target_tile, on_complete=list_added).start()
            return
        if ":" in room_id and not (short_link or profile_link):
            if platform is None:
                if on_complete is not None:
                    on_complete(False, '请启用对应的平台插件并重启')
                else:
                    QMessageBox.warning(host, "添加直播间", "请启用对应的平台插件并重启")
                return
            resolver = InfoResolver(room_id, host, platform=platform)
            resolver.resolved.connect(added)
            resolver.failed.connect(lambda _rid, r=resolver: self.on_platform_room_failed(
                r, platform, room_id, folder_id=folder_id, target_tile=target_tile, on_complete=on_complete)
                if on_complete is not None else host._on_platform_room_failed(
                    r, platform, room_id, folder_id=folder_id, target_tile=target_tile))
            resolver.finished.connect(lambda r=resolver: host._platform_info_running.discard(r))
            resolver.finished.connect(resolver.deleteLater)
            host._platform_info_running.add(resolver)
            resolver.start()
            return
        print(f"正在查询房间 {room_id} ...")
        resolver = InfoResolver(room_id, host)
        resolver.resolved.connect(added)
        if on_complete is not None:
            resolver.failed.connect(lambda _rid, r=resolver: on_complete(False,
                getattr(r, 'error_message', '') or '房间查询失败，请检查链接、网络或登录状态')
                if not host._closing else None)
        elif short_link or profile_link:
            resolver.failed.connect(lambda _rid, r=resolver: QMessageBox.warning(
                host, "添加直播间", (getattr(r, 'error_message', '') or
                ('个人主页直播间查询失败，请稍后重试' if profile_link else
                 '分享链接解析失败，请确认是直播间链接并检查网络后重试')))
                if not host._closing else None)
        else:
            resolver.failed.connect(lambda rid: print(f"房间 {rid} 查询失败"))
        resolver.finished.connect(lambda r=resolver: host._platform_info_running.discard(r))
        resolver.finished.connect(resolver.deleteLater)
        host._platform_info_running.add(resolver)
        resolver.start()

    def on_platform_room_failed(self, resolver, platform, room_id, *, folder_id="", target_tile=None, on_complete=None):
        from PySide6.QtWidgets import QDialog, QMessageBox
        host = self.host
        if host._closing:
            return
        if (getattr(resolver, "browser_verification", False) is True
                and platform.kind == "douyin" and getattr(platform, "room_browser_init_script", "")):
            from .profile_room import ProfileRoomDialog
            dialog = ProfileRoomDialog(platform, "", host, room_id=room_id)
            result = dialog.exec()
            canonical = dialog.room_id
            dialog.deleteLater()
            if result == QDialog.Accepted and canonical and not host._closing:
                if on_complete is not None:
                    self.add_room_id(canonical, folder_id=folder_id, target_tile=target_tile,
                                     resolver_type=type(resolver), on_complete=on_complete)
                else:
                    host._add_room_id(canonical, folder_id=folder_id, target_tile=target_tile)
            elif on_complete is not None:
                on_complete(False, '验证已取消，可重新添加')
            return
        if on_complete is not None:
            on_complete(False, getattr(resolver, 'error_message', '') or '平台房间获取失败，请检查链接或登录状态')
            return
        QMessageBox.warning(host, "添加直播间", "平台房间获取失败\n\n" + (
            getattr(resolver, "error_message", "") or "请检查房间链接或稍后重试"))

    def on_room_added(self, room: dict, *, folder_id: str = "", max_tiles, target_tile=None, notify=True) -> None:
        host = self.host
        if host._closing:
            return
        if host.sidebar.add_room(room):
            if folder_id:
                host.sidebar.move_to_folder([str(room.get("room_id"))], folder_id)
            host.load_avatars_for([room])       # 新加的房间立刻显示头像
            from .online_ui import show_result
            if notify:
                show_result(host, "已添加 " + str(room.get("uname") or room.get("room_id")), rooms=[room])
        status = "直播中" if room.get("live") else "未开播"
        print(f"已添加 {room.get('uname')}（{status}）")
        if (target_tile in host.wall.tiles and not target_tile.room.get('room_id')
                and host._tile_of(str(room.get('room_id'))) is None):
            host.room_placement.drop_room(target_tile, str(room['room_id']), room=room)
        else:
            host.add_to_wall(room)
        host._refresh_meta()
        host._save_timer.start()

    def remove_room(self, room: dict) -> None:
        from . import plugins as plugin_api
        host = self.host
        if host.hover_preview._room_id() == str(room.get("room_id")):
            host.hover_preview.cancel()
        tile = host._tile_of(str(room.get("room_id")))
        if tile is not None:
            host.plugins.emit(plugin_api.EVENT_TILE_REMOVED, tile=tile,
                              room=dict(tile.room or {}))
            host._pending_capture.pop(tile, None)
            host.recorder.stop(tile)
            host._stop_tile(tile)
            host.wall.remove_room(tile.room)
            if tile not in host.recorder.sessions:
                host._restore_capture_quality(tile)
        host.sidebar.remove_room(room)
        host._refresh_meta()
        print(f"已移除 {room.get('uname')}")

    def remove_rooms(self, rooms: list) -> None:
        host = self.host
        for room in rooms:
            host.remove_room(room)
        print(f"多选删除完成，共 {len(rooms)} 个")
