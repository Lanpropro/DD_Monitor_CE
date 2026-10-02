"""联网验收：按房间实际档位逐个切换，核对 VLC 尺寸、菜单和保存值。"""
import os
from pathlib import Path
import re
import sys
import time
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
os.environ["DDM_NO_SAVE"] = "1"
os.environ.setdefault("PYTHON_VLC_LIB_PATH", str(REPO / "libvlc.dll"))
from PySide6.QtWidgets import QApplication  # noqa: E402
from ddm import config, theme  # noqa: E402
from ddm.app import MainWindow  # noqa: E402
from selfcheck_platform_preview_live import wait_for, stats, relay_stopped  # noqa: E402


def main():
    room_id = sys.argv[1]
    app = QApplication([])
    app.setStyleSheet(theme.qss())
    state = {"plugins_enabled": ["huya_watch", "global_live"], "settings": {"auto_quality": True,
             "preview_on_hover": False, "recording_enabled": False,
             "recording_replay_enabled": False, "freeze_watch": False}}
    with patch("ddm.app.QTimer.singleShot"):
        window = MainWindow([], [], state=state, layout_id="corner")
    window.resize(1000, 700)
    window.show()
    window._poll_timer.stop()
    window._stats_timer.stop()
    try:
        platform = window.plugins.platform_for(room_id)
        room = platform.room_info(room_id).as_dict()
        assert room["live"]
        tile = window.wall.tiles[0]
        tile.set_room(room)
        tile.set_muted(True)
        window.start_tile(tile)
        wait_for(app, lambda: tile in window.players and stats(window.players[tile]).displayed_pictures > 30)
        options = list(tile.quality_options)
        assert options == platform.room_quality_options(room_id) and options
        for option in options:
            qn = option["qn"]
            if tile.actual_quality != qn:
                previous = window.players[tile]._relay
                tile.set_quality(qn)
                wait_for(app, lambda: tile not in window._resolvers and window.players[tile]._relay is not previous
                         and stats(window.players[tile]).displayed_pictures > 30)
                relay_stopped(previous)
            player = window.players[tile]
            before = stats(player).displayed_pictures
            wait_for(app, lambda: stats(player).displayed_pictures > before + 60, 15)
            width, height = player.player.video_get_size(0)
            assert width > 0 and height > 0 and tile.quality == tile.actual_quality
            actual = next(item for item in options if item["qn"] == tile.actual_quality)
            resolution = re.search(r"\b(\d+)x(\d+)\b", actual["desc"])
            if resolution:
                assert (width, height) == tuple(map(int, resolution.groups())), (
                    room_id, actual["desc"], width, height)
            assert tile._quality_text() == actual.get("label", actual["desc"])
            window.apply_quality_policy(restart=False)
            assert tile.quality == actual["qn"]
            saved = window.current_state()
            _, wall = config.build_rooms(saved)
            assert wall[0]["quality"] == actual["qn"]
            print(f"PASS: {room_id} request {option['desc']} => actual {actual['desc']}, "
                  f"{width}x{height}, native qn={tile.actual_quality}, "
                  "continuous frames, exact menu, saved choice, no Bili auto override", flush=True)
        relay = window.players[tile]._relay
    finally:
        window.close()
        app.processEvents()
    relay_stopped(relay)


if __name__ == "__main__":
    main()
