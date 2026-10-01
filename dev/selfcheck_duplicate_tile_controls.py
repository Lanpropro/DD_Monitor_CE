"""离线回归：同房间占两格时，暂停、刷新和关闭只操作信号来源格子。"""
import os
import sys
from unittest.mock import Mock, patch

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm.app import MainWindow  # noqa: E402


def main():
    app = QApplication(sys.argv)
    room = {"room_id": "1001", "uname": "duplicate-test", "live": True,
            "quality": 250, "muted": True, "volume": 42}
    with patch.object(MainWindow, "start_tile") as start, \
            patch.object(MainWindow, "refresh_status"), \
            patch.object(MainWindow, "refresh_stats"), \
            patch.object(MainWindow, "sync_danmaku"), \
            patch.object(MainWindow, "load_avatars_for"):
        window = MainWindow([dict(room)], [dict(room), dict(room)], layout_id="2x2",
                            state={"settings": {"preview_on_hover": False}})
        try:
            first, second = window.wall.tiles[:2]
            first_player, second_player = Mock(), Mock()
            window.players.update({first: first_player, second: second_player})
            QTest.mouseClick(second.pause_button, Qt.LeftButton)
            second_player.set_paused.assert_called_once_with(True)
            first_player.set_paused.assert_not_called()
            assert second.paused and not first.paused
            start.reset_mock()
            second.reloadRequested.emit(second.room)
            start.assert_called_once_with(second)
            QTest.mouseClick(second.close_button, Qt.LeftButton)
            assert first.room.get("room_id") == "1001"
            assert not second.room.get("room_id")
            second_player.release.assert_called_once()
            first_player.release.assert_not_called()
        finally:
            window.close()
            app.processEvents()
    print("重复直播间格子的暂停、刷新和关闭隔离：通过", flush=True)


if __name__ == "__main__":
    main()
