"""Followed room collection, asynchronous add/remove and platform activation; original window owns state."""


class RoomCatalog:
    def __init__(self, host):
        self.host = host

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
        for key in ("import_order", "custom_order"):
            getattr(host.sidebar, "set_" + key)(saved[key])
        host.sidebar.apply_pins(saved["pinned"])
        host.sidebar.set_folders(saved.get("follow_folders") or [])
        for index, room in enumerate(wall):
            if index >= len(host.wall.tiles):
                host.wall.add_room(room)
                continue
            tile = host.wall.tiles[index]
            if str(tile.room.get("room_id") or "") == str(room.get("room_id") or ""):
                continue
            if tile is host._fullscreen_tile:
                host._exit_fullscreen()
            host.recorder.stop(tile)
            host._pending_capture.pop(tile, None)
            host._stop_tile(tile)
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

    def open_add_room(self, *, dialog_type) -> None:
        host = self.host
        AddRoomDialog = dialog_type
        dialog = AddRoomDialog(host, room_id_resolver=host._normalize_room_input,
                               folders=host.sidebar.folder_state(),
                               folder_creator=host.sidebar.create_folder)
        hints = [hint for p in host.plugins.platforms.values()
                 if (hint := getattr(p, "room_input_hint", ""))]
        if hints:
            dialog.hint.setText("支持 B 站房间号；" + "；".join(hints))
        if dialog.exec() != AddRoomDialog.Accepted:
            return
        host._add_room_id(dialog.room_id, folder_id=dialog.folder_id)

    def add_room_id(self, room_id: str, *, folder_id: str = "", resolver_type) -> None:
        from PySide6.QtWidgets import QMessageBox
        host = self.host
        InfoResolver = resolver_type
        from .room_input import is_bili_short_url
        short_link = is_bili_short_url(room_id)
        if any(str(room.get("room_id")) == room_id for room in host.sidebar.rooms()):
            print(f"房间 {room_id} 已在关注列表里")
            return
        platform = host.plugins.platform_for(room_id)
        if ":" in room_id and not short_link:
            if platform is None:
                QMessageBox.warning(host, "添加直播间", "请启用对应的平台插件并重启")
                return
            resolver = InfoResolver(room_id, host, platform=platform)
            resolver.resolved.connect(lambda room: host._on_room_added(room, folder_id=folder_id)
                                      if not host._closing else None)
            resolver.failed.connect(lambda _rid, r=resolver: host._on_platform_room_failed(
                r, platform, room_id, folder_id=folder_id))
            resolver.finished.connect(lambda r=resolver: host._platform_info_running.discard(r))
            resolver.finished.connect(resolver.deleteLater)
            host._platform_info_running.add(resolver)
            resolver.start()
            return
        print(f"正在查询房间 {room_id} ...")
        resolver = InfoResolver(room_id, host)
        resolver.resolved.connect(lambda room: host._on_room_added(room, folder_id=folder_id))
        if short_link:
            resolver.failed.connect(lambda _rid: QMessageBox.warning(
                host, "添加直播间", "分享链接解析失败，请确认是直播间链接并检查网络后重试")
                if not host._closing else None)
        else:
            resolver.failed.connect(lambda rid: print(f"房间 {rid} 查询失败"))
        resolver.finished.connect(lambda r=resolver: host._platform_info_running.discard(r))
        resolver.finished.connect(resolver.deleteLater)
        host._platform_info_running.add(resolver)
        resolver.start()

    def on_platform_room_failed(self, resolver, platform, room_id, *, folder_id=""):
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
                host._add_room_id(canonical, folder_id=folder_id)
            return
        QMessageBox.warning(host, "添加直播间", "平台房间获取失败\n\n" + (
            getattr(resolver, "error_message", "") or "请检查房间链接或稍后重试"))

    def on_room_added(self, room: dict, *, folder_id: str = "", max_tiles) -> None:
        host = self.host
        MAX_TILES = max_tiles
        if host._closing:
            return
        if host.sidebar.add_room(room):
            if folder_id:
                host.sidebar.move_to_folder([str(room.get("room_id"))], folder_id)
            host.load_avatars_for([room])       # 新加的房间立刻显示头像
            from .online_ui import show_result
            show_result(host, "已添加 " + str(room.get("uname") or room.get("room_id")), rooms=[room])
        status = "直播中" if room.get("live") else "未开播"
        print(f"已添加 {room.get('uname')}（{status}）")
        if len(host.wall.tiles) < MAX_TILES:
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
