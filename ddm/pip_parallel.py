"""Temporary playback panes owned by the independent picture-in-picture wall."""

from PySide6.QtCore import QTimer

from .wall_widgets import WallGrid


class ParallelWall(WallGrid):
    def ensure_slots(self):
        """The floating composition only contains rooms selected in the picker."""


class ParallelPictureInPicture:
    def __init__(self, host, parent):
        self.host = host
        self.wall = ParallelWall([], parent=parent, prepare_room=host.room_placement.prepare_room)
        self.tiles = {}
        self.moved = {}
        self.room_ids = []
        self.primary = None

    def update(self, rooms, primary, window, wall_sources, move_wall_streams):
        self.room_ids = list(rooms)
        self.primary = primary
        for room_id in tuple(self.tiles):
            if (room_id not in rooms or room_id in self.moved and not move_wall_streams
                    or room_id in wall_sources and room_id not in self.moved):
                self.remove(room_id, window)
        for room_id, room in rooms.items():
            if room_id not in self.tiles:
                if room_id in wall_sources:
                    self.tiles[room_id] = self._move_to_window(room_id, wall_sources[room_id])
                    continue
                tile = self.wall._make_tile(dict(room, muted=True))
                tile.setProperty('pictureInPictureIndependent', True)
                tile.volumeChanged.connect(self.host._on_volume_changed)
                tile.muteToggled.connect(self.host._on_mute_changed)
                tile.audioChannelChanged.connect(self.host._on_audio_changed)
                tile.qualityChanged.connect(self.host._on_quality_changed)
                tile.reloadRequested.connect(self.host._on_reload)
                tile.pauseToggled.connect(self.host._on_pause_toggled)
                tile.codecSettingsRequested.connect(lambda t=tile: self.host._open_tile_codecs(t))
                tile.streamInfoRequested.connect(lambda t=tile: self.host._open_tile_stream_info(t))
                tile.liveCatchupToggled.connect(
                    lambda enabled, t=tile: self.host.stream_playback.set_live_catchup(t, enabled))
                self.tiles[room_id] = tile
        selected = [self.tiles[room_id] for room_id in self.room_ids]
        window.track_tiles(selected)
        return selected

    def _move_to_window(self, room_id, tile):
        host, wall = self.host, self.host.wall
        if host._fullscreen_tile is tile:
            host._exit_fullscreen()
        host._stop_tile(tile)
        index = wall.tiles.index(tile)
        slot = wall._make_tile({})
        wall.tiles.pop()
        wall.tiles[index] = slot
        wall.grid.removeWidget(tile)
        layer = tile.video_danmaku._quick_layer
        self.moved[room_id] = slot, tile.minimumSize(), tile.muted, layer
        tile.hide()
        tile.setProperty('pictureInPictureIndependent', True)
        tile.setParent(self.wall)
        self.wall.tiles.append(tile)
        if layer is not None:
            self.wall._quick_danmaku_requested = True
            tile.video_danmaku.attach_quick_layer(self.wall.ensure_quick_danmaku_layer())
        tile.set_muted(True)
        wall.relayout(force=True)
        return tile

    def _return_to_wall(self, room_id, tile):
        slot, minimum, muted, layer = self.moved.pop(room_id)
        host, wall = self.host, self.host.wall
        panes = wall.pane_danmaku
        if (slot not in wall.tiles or slot.room.get('room_id')
                or panes.cell_for_tile(slot) in panes.bindings() or host._tile_of(room_id) is not None):
            return False
        host._stop_tile(tile)
        self.wall.tiles.remove(tile)
        tile.hide()
        tile.set_muted(muted)
        tile.setProperty('pictureInPictureIndependent', False)
        tile.setProperty('pictureInPicture', False)
        tile.setMinimumSize(minimum)
        index = wall.tiles.index(slot)
        wall._drop_tile(slot)
        wall.tiles.insert(index, tile)
        tile.setParent(wall)
        tile.video_danmaku.attach_quick_layer(layer)
        wall.relayout(force=True)
        QTimer.singleShot(0, host, lambda: host.start_tile(tile) if (
            not host._closing and tile in wall.tiles and str(tile.room.get('room_id')) == room_id
            and tile not in host.players and tile not in host._resolvers) else None)
        return True

    def remove(self, room_id, window):
        tile = self.tiles.pop(room_id)
        window.forget_tile(tile)
        moved = room_id in self.moved
        if moved and self._return_to_wall(room_id, tile):
            return
        getattr(self.host, '_match_sync_saved', {}).pop(tile, None)
        getattr(self.host, '_match_sync_resume_pause', {}).pop(tile, None)
        dialog = self.host._stream_info_dialogs.get(tile)
        if dialog is not None:
            dialog.close()
        if moved:
            self.host._clear_tile_room(tile)
            if tile in self.host.recorder.sessions:
                tile.hide()
                self.wall.tiles.remove(tile)
                tile.setParent(self.host.wall)
                self.host._preset_retired_tiles.add(tile)
                return
        else:
            self.host._stop_tile(tile)
        self.wall._drop_tile(tile)

    def close(self, window):
        for room_id in tuple(self.tiles):
            self.remove(room_id, window)
