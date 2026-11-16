"""Room-combination coordination; the window owns saved state, tiles and services."""
from copy import deepcopy

from . import config as config_module
from . import layouts, room_presets


class RoomPresetController:
    def __init__(self, host):
        self.host = host

    def snapshot(self):
        host = self.host
        wall = host.wall
        identifier = wall.layout_id
        if identifier == "corner":
            ratios = wall.corner_ratios()
        else:
            ratios = deepcopy(wall._layout_ratios.get(identifier, {}))
            # Defaults such as portrait 16:9 depend on the viewport; freeze their current proportions.
            for (key, _index), (_node, _area, sizes) in wall._preset_dividers.items():
                ratios.setdefault(key, [size / sum(sizes) for size in sizes])
        custom = wall.pane_danmaku.custom
        dm = None if custom else (layouts.danmaku_cell(identifier) if
            layouts.is_portrait_layout(identifier) else wall._danmaku_cell)
        pane_layout = dict(id=identifier, ratios=ratios, danmaku_cell=dm)
        if custom:
            cells = wall.pane_danmaku.cell_tiles()
            pane_layout["panels"] = [dict(cell=cell, source=None if tile is None else
                next((index for index, item in cells.items() if item is tile), -1))
                for cell, tile in sorted(wall.pane_danmaku.bindings().items())]
        order = [cell for cell in range(layouts.capacity(identifier)) if cell != dm]
        saved_layout = (host._room_preset_fullscreen_layout if host._fullscreen_tile is not None else None)
        return room_presets.validate({"layout": deepcopy(saved_layout) if saved_layout else pane_layout,
            "slots": [dict(cell=cell, room_id=str(tile.room.get("room_id") or ""),
                           label=str(tile.room.get("uname") or tile.room.get("room_id") or "空位"),
                           volume=int(tile.volume), audio_channel=int(tile.audio_channel),
                           muted=host._fullscreen_audio_saved.get(tile, bool(tile.muted)))
                      for cell, tile in zip(order, wall.tiles)]})


    def save(self, name, preset_id=None):
        host = self.host
        from uuid import uuid4
        name = str(name).strip()
        if not name:
            raise ValueError("请输入组合名称")
        if host.room_presets["version"] != 1:
            raise ValueError("组合数据版本暂不支持")
        items = host.room_presets["items"]
        if any(item.get("name") == name and item.get("id") != preset_id for item in items):
            raise ValueError("已有同名组合")
        snapshot = host.room_preset_snapshot()
        record = dict(snapshot, id=preset_id or uuid4().hex, name=name)
        if preset_id:
            index = next((i for i, item in enumerate(items) if item.get("id") == preset_id), None)
            if index is None:
                raise ValueError("该组合已不存在")
            items[index] = record
        else:
            items.append(record)
        host._active_room_preset_id = record["id"]
        host._save_timer.start()
        return record["id"]


    def rename(self, preset_id, name):
        host = self.host
        name = str(name).strip()
        if not name:
            raise ValueError("请输入组合名称")
        if any(item.get("name") == name and item.get("id") != preset_id
               for item in host.room_presets["items"]):
            raise ValueError("已有同名组合")
        for item in host.room_presets["items"]:
            if item.get("id") == preset_id:
                item["name"] = name
                host._save_timer.start()
                return
        raise ValueError("该组合已不存在")


    def delete(self, preset_id):
        host = self.host
        host.room_presets["items"] = [item for item in host.room_presets["items"]
                                     if item.get("id") != preset_id]
        if host._active_room_preset_id == preset_id:
            host._active_room_preset_id = ""
        host._save_timer.start()


    def apply(self, preset_id):
        host = self.host
        host.picture_in_picture.restore()
        if host._closing:
            return False
        if host.room_presets["version"] != 1:
            raise ValueError("组合数据版本暂不支持")
        record = next((item for item in host.room_presets["items"] if item.get("id") == preset_id), None)
        snapshot = room_presets.validate(record)
        if room_presets.same(snapshot, host.room_preset_snapshot()):
            if host._active_room_preset_id != preset_id:
                host._active_room_preset_id = preset_id
                host._save_timer.start()
            return True
        host._cancel_interactive_resize()
        slots = snapshot["slots"]
        available = list(host.wall.tiles)
        assigned = []
        # Reserve matching live players before taking spare/empty tiles for new rooms.
        for slot in slots:
            tile = next((tile for tile in available if slot["room_id"] and
                         str(tile.room.get("room_id") or "") == slot["room_id"]), None)
            assigned.append(tile)
            if tile is not None:
                available.remove(tile)
        for index, tile in enumerate(assigned):
            if tile is None:
                spare = next((item for item in available if item not in host.recorder.sessions), None)
                if spare is not None:
                    available.remove(spare)
                    assigned[index] = spare
        keeping = {tile for tile, slot in zip(assigned, slots) if tile is not None
                   and str(tile.room.get("room_id") or "") == slot["room_id"]}
        affected = [tile for tile, session in host.recorder.sessions.items()
                    if tile not in keeping and session.recording and not session.stopping]
        affected += [tile for tile, recording in host._pending_capture.items()
                     if tile not in keeping and recording and tile not in affected]
        if affected:
            from PySide6.QtWidgets import QMessageBox
            names = "、".join(str(tile.room.get("uname") or tile.room.get("room_id")) for tile in affected)
            if QMessageBox.question(host, "恢复直播间组合", f"将结束以下直播间的录制后恢复组合：\n{names}\n是否继续？",
                                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
                return False
        if host._fullscreen_tile is not None:
            host._exit_fullscreen()
        host.hover_preview.cancel()
        host.wall._cancel_border_drag()
        host._pending_layout = ""
        host._applying_room_preset = True
        try:
            for tile in list(host.wall.tiles):
                if tile not in keeping:
                    host._clear_tile_room(tile)
            for index, tile in enumerate(assigned):
                if tile is None:
                    assigned[index] = host.wall._make_tile({})
            for tile in list(host.wall.tiles):
                if tile not in assigned:
                    if tile in host.recorder.sessions:
                        # ffmpeg may still be finishing; its completion signal needs a live tile.
                        tile.hide()
                        host._preset_retired_tiles.add(tile)
                    else:
                        host.wall._drop_tile(tile)
            host.wall.tiles = assigned
            identifier = snapshot["layout"]["id"]
            portrait = layouts.is_portrait_layout(identifier)
            previous_orientation, previous_layout = host.orientation, host.wall.layout_id
            host.wall.pane_danmaku.settings.pop(identifier, None)
            if "panels" in snapshot["layout"]:
                by_cell = {slot["cell"]: tile for slot, tile in zip(slots, assigned)}
                host.wall.pane_danmaku.settings[identifier] = {item["cell"]:
                    None if item["source"] is None else by_cell.get(item["source"], -1)
                    for item in snapshot["layout"]["panels"]}
            host.wall.set_layout(identifier, relayout=False)
            host.wall._danmaku_cell = snapshot["layout"]["danmaku_cell"]
            if identifier == "corner":
                host.wall.restore_corner_ratios(snapshot["layout"]["ratios"])
            else:
                host.wall._layout_ratios[identifier] = deepcopy(snapshot["layout"]["ratios"])
            if portrait != (host.orientation == "portrait"):
                host._reshape_window(portrait)
                if previous_orientation:
                    host._layout_by_orientation[previous_orientation] = previous_layout
            host.orientation = "portrait" if portrait else "landscape"
            host.sidebar.set_collapsed(False, animate=False)
            host._build_arrangement(host.orientation)
            host.state.setdefault("ui", {})[f"layout_{host.orientation}"] = identifier
            host._layout_by_orientation[host.orientation] = identifier
            starting = []
            for tile, slot in zip(assigned, slots):
                rid = slot["room_id"]
                if tile not in keeping:
                    known = next((room for room in host.sidebar.rooms()
                                  if str(room.get("room_id")) == rid), None)
                    if known is None:
                        _, placeholders = config_module.build_rooms({"wall": [slot]})
                        known = placeholders[0]
                        if rid:
                            known["uname"] = slot["label"] or f"房间 {rid}"
                    tile.set_room(host._prepare_room(dict(known)))
                    if rid:
                        starting.append(tile)
                # These setters normally emit individual player updates; apply the whole sound state first.
                blocked = tile.blockSignals(True)
                try:
                    tile.set_volume(slot["volume"])
                    tile.set_audio_channel(slot["audio_channel"])
                    tile.set_muted(slot["muted"])
                finally:
                    tile.blockSignals(blocked)
                player = host.players.get(tile)
                if player is not None:
                    player.set_volume(tile.volume)
                    player.set_audio_channel(tile.audio_channel)
                    player.set_muted(tile.muted)
            host.wall.relayout(force=True)
            host.sidebar.set_layout_name(identifier)
            for tile in starting:
                if tile.isVisible() and (tile.room.get("live") or (":" in str(tile.room.get("room_id")) and
                        host.plugins.platform_for(str(tile.room["room_id"])) is None)):
                    host.start_tile(tile)
                else:
                    tile.set_status("未开播" if tile.room.get("live_known", True) else "等待刷新直播状态")
            host._active_room_preset_id = preset_id
            host._refresh_meta()
            host._save_timer.start()
        finally:
            host._applying_room_preset = False
        host.refresh_status(force=True)
        return True
