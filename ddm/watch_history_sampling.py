"""Sample visible active playback into the existing watch-history model."""
import time


def tick_watch_history(host):
    now = time.monotonic()
    elapsed = now - host._watch_history_last_tick
    host._watch_history_last_tick = now
    history = host.sidebar.watch_history
    if host._closing or not history.enabled:
        return
    present = {str(tile.room.get("room_id")) for tile in host.wall.tiles
               if tile.room.get("room_id")}
    active = set()
    if host.isVisible() and not host.isMinimized():
        for tile in host.wall.visible_tiles():
            player = host.players.get(tile)
            if (tile.isVisible() and not tile.paused and player is not None
                    and player.state == "playing" and not player.paused):
                active.add(str(tile.room.get("room_id")))
    if history.sample(present, active, elapsed):
        host._save_timer.start()
