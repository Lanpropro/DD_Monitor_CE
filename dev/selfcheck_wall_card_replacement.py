"""替换格子时同步关注卡片的上墙边框与当前选择，覆盖重复房间和横竖屏。"""
import os
from pathlib import Path
import sys
from unittest.mock import patch

os.environ["DDM_NO_SAVE"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from ddm import app as app_module, theme
from ddm.app import MainWindow
from selfcheck_layout_live_priority import SilentPoller


def check(app, portrait):
    rooms = [{"room_id": str(710001 + i), "uname": f"Test {i}", "live": True}
             for i in range(3)]
    window = MainWindow(rooms, [dict(rooms[0])], layout_id="main2",
                        state={"plugins_enabled": [], "settings": {"auto_quality": False}})
    window.resize(700, 1100) if portrait else window.resize(1400, 900)
    window.show()
    app.processEvents()
    cards = {str(item.room["room_id"]): item for item in window.sidebar.items()}
    target = window.wall.tiles[0]
    try:
        window._on_tile_clicked(target.room)
        window._on_room_dropped(target, rooms[1]["room_id"])
        assert not cards[rooms[0]["room_id"]].property("onWall")
        assert not cards[rooms[0]["room_id"]].property("selected"), "replaced room retains its selected blue background"
        assert cards[rooms[1]["room_id"]].property("onWall")
        assert cards[rooms[1]["room_id"]].property("selected")
        assert window.sidebar._head_strip._on_wall_ids == {rooms[1]["room_id"]}

        # 同一主播仍在另一个格子时，只清选择，不清其上墙标记。
        second = window.wall.tiles[1]
        second.set_room(dict(rooms[1]))
        window._refresh_meta()
        window._on_room_dropped(target, rooms[2]["room_id"])
        assert cards[rooms[1]["room_id"]].property("onWall")
        assert not cards[rooms[1]["room_id"]].property("selected")
        assert cards[rooms[2]["room_id"]].property("onWall")
        assert cards[rooms[2]["room_id"]].property("selected")
        # 格子交换及从另一格拖回时，选择也跟随聚焦位置的新房间。
        window._on_tile_swapped(second.room["room_id"], target)
        assert cards[rooms[1]["room_id"]].property("selected")
        assert not cards[rooms[2]["room_id"]].property("selected")
        window._on_room_dropped(target, rooms[2]["room_id"])
        assert cards[rooms[2]["room_id"]].property("selected")
        assert not cards[rooms[1]["room_id"]].property("selected")
        window._on_close_tile(target.room)
        assert not cards[rooms[2]["room_id"]].property("onWall")
        assert not cards[rooms[2]["room_id"]].property("selected")
        assert cards[rooms[1]["room_id"]].property("onWall")

        # 未聚焦任何格子时，刷新占用状态不应取消用户单独点击的关注卡片。
        window._on_tile_clicked(rooms[0])
        window._refresh_meta()
        assert cards[rooms[0]["room_id"]].property("selected")
    finally:
        window.close()


def main():
    app = QApplication([])
    app.setStyleSheet(theme.qss())
    with patch.object(app_module, "StatusPoller", SilentPoller), \
            patch.object(app_module, "StatsPoller", SilentPoller), \
            patch.object(MainWindow, "start_tile"):
        check(app, False)
        check(app, True)
    print("PASS: replaced/closed focused rooms clear stale blue selection; duplicate-room wall marks and independent card selection remain correct in both orientations")


if __name__ == "__main__":
    main()
