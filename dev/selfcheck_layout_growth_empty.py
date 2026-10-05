"""扩展布局只补空格：包括保存的隐藏房间、横竖切换和弹幕布局。"""
import os
from pathlib import Path
import sys
from unittest.mock import patch

os.environ["DDM_NO_SAVE"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from ddm import config
from ddm.app import MainWindow


def main():
    app = QApplication([])
    rooms = [{"room_id": str(1000 + i), "uname": str(i), "live": True,
              "volume": 10 + i, "muted": bool(i % 2), "audio_channel": i % 5}
             for i in range(9)]
    state = {"plugins_enabled": [], "settings": {"auto_quality": False,
             "recording_enabled": False, "recording_replay_enabled": False,
             "danmaku_enabled": False, "preview_on_hover": False}}
    with patch("ddm.app.QTimer.singleShot"), patch.object(MainWindow, "sync_danmaku"), \
            patch.object(MainWindow, "refresh_status"), patch.object(MainWindow, "refresh_stats"), \
            patch.object(MainWindow, "start_tile") as start:
        for layout in ("2x2", "dm_main3", "portrait_main2", "resize"):
            window = MainWindow([dict(room) for room in rooms], [dict(room) for room in rooms],
                                layout_id="1x1", state=state)
            window.resize(1200, 800)
            window.show()
            app.processEvents()
            first = window.wall.tiles[0]
            first.room["live"] = False  # 其余隐藏房间在播，也不能自动替换当前未开播位置。
            audio = (first.volume, first.muted, first.audio_channel)
            start.reset_mock()
            try:
                if layout == "resize":
                    window._layout_by_orientation["portrait"] = "portrait_main2"
                    window.resize(500, 1000)
                else:
                    window._on_layout_changed(layout)
                app.processEvents()
                assert window.wall.tiles[0] is first and first.room["room_id"] == "1000", layout
                assert (first.volume, first.muted, first.audio_channel) == audio
                assert all(not tile.room.get("room_id") for tile in window.wall.tiles[1:]), layout
                assert start.call_count == 0, "扩展布局不能给隐藏直播间起流"
                assert len(window.sidebar.rooms()) == 9
                saved = window.current_state()
                _, restored = config.build_rooms(saved)
                assert restored[0]["room_id"] == "1000"
                assert all(not room.get("room_id") for room in restored[1:])
                # 再扩展到十六分，同样不回填；只在用户显式拖入时添加。
                window._on_layout_changed("4x4")
                app.processEvents()
                assert len(window.wall.visible_tiles()) == 16
                assert all(not tile.room.get("room_id") for tile in window.wall.tiles[1:])
                empty = window.wall.tiles[1]
                window._on_room_dropped(empty, "1001")
                assert empty.room["room_id"] == "1001"
                assert start.call_args.args[0] is empty
            finally:
                window.close()
                app.processEvents()
    print("PASS: growing layouts and orientation changes keep new slots empty, preserve the current room/audio and allow explicit drops")


if __name__ == "__main__":
    main()
