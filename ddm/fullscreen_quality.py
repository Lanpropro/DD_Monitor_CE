"""Temporary Bilibili original-quality selection, independent of audio focus."""
import weakref


class FullscreenQuality:
    def __init__(self, window):
        self.window = weakref.proxy(window)
        self.saved = {}  # tile -> (room_id, requested quality before fullscreen)

    def active(self, tile):
        return (tile is not None and tile is self.window._fullscreen_tile
                and self.window.settings.get("fullscreen_original_quality", True)
                and str(tile.room.get("room_id") or "").isascii()
                and str(tile.room.get("room_id") or "").isdigit())

    def original(self, tile):
        previous = self.saved.get(tile)
        if previous and previous[0] == str(tile.room.get("room_id") or ""):
            return previous[1]
        return int(tile.quality)

    @staticmethod
    def original_quality(tile):
        # New Bilibili streams can advertise 2K 原画 as 25000 while 10000
        # means 1080P 高码率. Prefer the stream's named original-quality tier.
        originals = []
        for option in getattr(tile, "quality_options", []):
            if "原画" in f"{option.get('desc', '')} {option.get('label', '')}":
                qn = int(option.get("qn") or 0)
                if qn > 0:
                    originals.append(qn)
        return max(originals, default=10000)

    def change(self, tile, quality):
        if tile.quality == quality:
            return
        blocked = tile.blockSignals(True)
        try:
            tile.set_quality(quality)
        finally:
            tile.blockSignals(blocked)
        tile.room["quality"] = int(tile.quality)
        self.window._save_timer.start()
        if (tile.room.get("live") and not tile.paused
                and not self.window._closing):
            self.window.start_tile(tile)

    def restore(self, tile):
        room_id, quality = self.saved.pop(tile)
        if tile not in self.window.wall.tiles:
            return
        if str(tile.room.get("room_id") or "") != room_id:
            return  # A different room now occupies this slot.
        capture = self.window._capture_quality.get(tile)
        if capture and capture[0] == room_id:
            # Recording has priority; its normal completion will restore this value.
            self.window._capture_quality[tile] = (room_id, quality)
        else:
            self.change(tile, quality)

    def sync(self):
        target = self.window._fullscreen_tile
        for tile in list(self.saved):
            if (not self.active(tile) or tile not in self.window.wall.tiles
                    or self.saved[tile][0] != str(tile.room.get("room_id") or "")):
                self.restore(tile)
        if (not self.active(target) or target not in self.window.wall.tiles
                or target in self.window._capture_quality):
            return
        if target not in self.saved:
            self.saved[target] = (str(target.room["room_id"]), int(target.quality))
            self.change(target, self.original_quality(target))

    def capture_released(self, tile, room_id, quality):
        """Keep original quality if a recording stops while still fullscreen."""
        if self.active(tile) and str(tile.room.get("room_id") or "") == room_id:
            self.saved.setdefault(tile, (room_id, quality))
            return self.original_quality(tile)
        return quality
