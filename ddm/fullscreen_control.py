"""Main window fullscreen control; window remains the only state and Qt lifetime owner."""
from copy import deepcopy
import sys
import time
from . import layouts
from .auto_quality import AUTO_QUALITY
from .tile_widgets import Tile


class FullscreenControl:
    def __init__(self, host):
        self.host = host

    def report_fullscreen_cost(self, action: str, started: float, covered: float,
                                switched: float, done: float) -> None:
        """打一行分段耗时。

        记录窗口样式与格子布局的耗时；实时视频在切换期间保持播放。
        有这几个数，下次再觉得卡就知道该动哪一段，而不是从头猜。
        """
        host = self.host
        print(f"[全屏] {action} {(done - started) * 1000:.0f} ms"
              f"（准备 {(covered - started) * 1000:.0f}"
              f" / 切换 {(switched - covered) * 1000:.0f}"
              f" / 布局 {(done - switched) * 1000:.0f}）",
              file=sys.stderr, flush=True)

    def sync_fullscreen_audio(self) -> None:
        host = self.host
        if host._fullscreen_tile is not None and host.settings.get("fullscreen_solo_audio", True):
            for tile in host.wall.tiles:
                host._fullscreen_audio_saved.setdefault(tile, bool(tile.muted))
                muted = tile is not host._fullscreen_tile
                if tile.muted != muted:
                    tile.set_muted(muted)
        else:
            saved, host._fullscreen_audio_saved = host._fullscreen_audio_saved, {}
            for tile, muted in saved.items():
                if tile in host.wall.tiles and tile.muted != muted:
                    tile.set_muted(muted)

    def upgrade_fullscreen_quality(self, tile: Tile) -> bool:
        host = self.host
        if (tile.quality == AUTO_QUALITY or tile in host._capture_quality
                or getattr(tile, "quality_locked", False)):
            return False
        # 平台档位按画质从高到低排列，编号大小不代表跨平台的清晰度。
        highest = next((int(item["qn"]) for item in tile.quality_options
                        if int(item["qn"]) != AUTO_QUALITY), 10000)
        if tile.quality == highest:
            return False
        tile.set_quality(highest)
        return True

    def on_fullscreen(self, tile: Tile) -> None:
        host = self.host
        host.picture_in_picture.restore()
        if tile not in host.wall.tiles or not tile.room.get("room_id"):
            return
        host._cancel_interactive_resize()
        if host._fullscreen_tile is None and host.wall.layout_id in layouts.BY_ID:
            host._room_preset_fullscreen_layout = deepcopy(host.room_preset_snapshot()["layout"])
        if host._fullscreen_tile is tile:
            host._exit_fullscreen()
            return
        if host._fullscreen_tile is not None:
            return
        started = time.perf_counter()
        covered = time.perf_counter()
        print(f"[全屏音频] 进入原格子={host.wall.tiles.index(tile)+1} "
              f"房间={tile.room.get('room_id', '')} 音量={tile.volume} "
              f"声道={tile.audio_channel} 静音={tile.muted}", file=sys.stderr, flush=True)
        host._fullscreen_tile = tile
        if host.settings.get('notice_hide_fullscreen', False):
            for notice in tuple(getattr(host, '_notices', [])):
                notice.dismiss(animate=False)
        host._sync_input_shortcuts()
        host._sync_fullscreen_audio()
        host._fullscreen_presentation.enter(tile)
        tile.fullscreen_button.setToolTip("退出全屏（F / Esc）")
        host._refresh_shortcuts()
        host.sync_danmaku()
        finished = time.perf_counter()
        host._fullscreen_cursor.start()
        host._upgrade_fullscreen_quality(tile)
        print(f"[全屏音频] 展开后音量={tile.volume} 声道={tile.audio_channel} "
              f"静音={tile.muted}", file=sys.stderr, flush=True)
        host._report_fullscreen_cost("进入全屏", started, covered, finished, finished)

    def exit_fullscreen(self) -> None:
        host = self.host
        host._fullscreen_cursor.stop()
        tile = host._fullscreen_tile
        if tile is None:
            return
        started = time.perf_counter()
        covered = time.perf_counter()
        host._fullscreen_presentation.leave()
        switched = time.perf_counter()
        host._fullscreen_tile = None
        host.refresh_theme()
        host._refresh_shortcuts()
        host._sync_fullscreen_audio()
        host.sync_danmaku()
        laid_out = time.perf_counter()
        tile.fullscreen_button.setToolTip("全屏查看这一路（F）")
        host._refresh_meta()
        host._report_fullscreen_cost("退出全屏", started, covered, switched, laid_out)
