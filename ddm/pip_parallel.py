"""Temporary playback panes owned by the independent picture-in-picture wall."""

from .wall_widgets import WallGrid


class ParallelWall(WallGrid):
    def ensure_slots(self):
        """The floating composition only contains rooms selected in the picker."""


class ParallelPictureInPicture:
    def __init__(self, host, parent):
        self.host = host
        self.wall = ParallelWall([], parent=parent, prepare_room=host.room_placement.prepare_room)
        self.tiles = {}
        self.room_ids = []
        self.primary = None

    def update(self, rooms, primary, window):
        self.room_ids = list(rooms)
        self.primary = primary
        for room_id in tuple(self.tiles):
            if room_id not in rooms:
                self.remove(room_id, window)
        for room_id, room in rooms.items():
            if room_id not in self.tiles:
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
                self.tiles[room_id] = tile
        selected = [self.tiles[room_id] for room_id in self.room_ids]
        window.track_tiles(selected)
        return selected

    def remove(self, room_id, window):
        tile = self.tiles.pop(room_id)
        window.forget_tile(tile)
        getattr(self.host, '_match_sync_saved', {}).pop(tile, None)
        getattr(self.host, '_match_sync_resume_pause', {}).pop(tile, None)
        dialog = self.host._stream_info_dialogs.get(tile)
        if dialog is not None:
            dialog.close()
        self.host._stop_tile(tile)
        self.wall._drop_tile(tile)

    def close(self, window):
        for room_id in tuple(self.tiles):
            self.remove(room_id, window)
