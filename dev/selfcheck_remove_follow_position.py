"""Removing followed rooms must clear slots without moving the other streams."""
import os
from pathlib import Path
import sys

from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import app as app_module
from ddm.app import MainWindow
from selfcheck_layout_live_priority import SilentPoller, StubPlayer


class Player(StubPlayer):
    def __init__(self):
        super().__init__()
        self.released = False

    def release(self):
        self.released = True


def check(app, portrait):
    rooms = [{"room_id": str(1000 + i), "uname": f"Room {i}", "live": False}
             for i in range(6)]
    window = MainWindow(rooms, [dict(room) for room in rooms], layout_id="corner",
                        state={"settings": {"auto_quality": False}})
    window.resize(700, 1200) if portrait else window.resize(1400, 900)
    window.show()
    app.processEvents()
    window.start_tile = lambda tile: None
    tiles = list(window.wall.tiles)
    players = []
    for i, tile in enumerate(tiles):
        tile.volume = 10 + i
        tile.muted = bool(i % 2)
        tile.audio_channel = i % 3
        tile.sync_audio_ui()
        player = Player()
        players.append(player)
        window.players[tile] = player
    positions = [tile.geometry() for tile in tiles]
    audio = [(tile.volume, tile.muted, tile.audio_channel) for tile in tiles]
    original_rooms = [tile.room.get("room_id", "") for tile in tiles]
    stopped_recordings = []
    window.recorder.stop = lambda tile: stopped_recordings.append(tile)
    window._pending_capture[tiles[0]] = {"action": "record"}
    try:
        # Remove the main stream; keep its empty slot, all players and geometry after it.
        window.remove_room(rooms[0])
        app.processEvents()
        assert window.wall.tiles == tiles, "Removing a follow shifted the wall slots"
        assert [tile.geometry() for tile in tiles] == positions
        assert not tiles[0].room.get("room_id") and players[0].released
        assert tiles[0] not in window.players and tiles[0] not in window._pending_capture
        assert tiles[0] in stopped_recordings
        assert [tile.room.get("room_id", "") for tile in tiles[1:]] == original_rooms[1:]
        assert all(window.players[tile] is player and not player.released
                   for tile, player in zip(tiles[1:], players[1:]))
        assert [(tile.volume, tile.muted, tile.audio_channel) for tile in tiles] == audio
        assert all(room["room_id"] != original_rooms[0] for room in window.sidebar.rooms())
        saved = window.current_state()
        assert not saved["wall"][0].get("room_id"), "Saved wall must retain the empty first slot"
        # Batch deletion must also leave the original slots in place.
        window.remove_rooms([rooms[2], rooms[4]])
        app.processEvents()
        assert window.wall.tiles == tiles
        assert [tile.geometry() for tile in tiles] == positions
        assert all(not tiles[i].room.get("room_id") for i in (0, 2, 4))
        assert all(tiles[i].room["room_id"] == original_rooms[i] for i in (1, 3, 5))
        # Refill the first empty slot rather than append or displace the other streams.
        replacement = {"room_id": "2000", "uname": "Replacement", "live": False}
        window.add_to_wall(replacement)
        assert window.wall.tiles == tiles and tiles[0].room["room_id"] == "2000"
    finally:
        window.close()


def main():
    app_module.StatusPoller = app_module.StatsPoller = SilentPoller
    app = QApplication(sys.argv)
    check(app, False)
    check(app, True)
    print("Follow removal: landscape/portrait, stable slots, player cleanup, batch and refill passed")


if __name__ == "__main__":
    main()
