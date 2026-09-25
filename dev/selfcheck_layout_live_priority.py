"""缩小布局时优先保留开播格子，并保持每个位置的声音设置。"""
import os
import sys

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import app as app_module  # noqa: E402
from ddm.app import MainWindow  # noqa: E402


class SilentPoller(QThread):
    updated = Signal(dict)

    def __init__(self, room_ids, parent=None):
        super().__init__(parent)

    def run(self) -> None:
        pass


class StubPlayer:
    def __init__(self):
        self.volume = None
        self.muted = None
        self.channel = None

    def set_volume(self, value):
        self.volume = value

    def set_muted(self, value):
        self.muted = value

    def set_audio_channel(self, value):
        self.channel = value

    def reapply_audio_channel(self):
        pass

    def release(self):
        pass


def main() -> None:
    app_module.StatusPoller = SilentPoller
    app_module.StatsPoller = SilentPoller
    app = QApplication(sys.argv)
    rooms = [{"room_id": str(1000 + index), "uname": str(index), "live": False}
             for index in range(6)]
    window = MainWindow(rooms, [dict(room) for room in rooms], layout_id="corner",
                        state={"settings": {"auto_quality": False}})
    window.resize(1400, 900)
    window.show()
    app.processEvents()
    window.start_tile = lambda tile: None  # 本测试只验证选位，不连接直播接口
    original = list(window.wall.tiles)
    for index, tile in enumerate(original):
        tile.volume = 10 + index * 10
        tile.muted = index == 1
        tile.audio_channel = 2 if index == 1 else 1
        tile.sync_audio_ui()
    original[0].set_live(True)
    original[3].set_live(True)
    player = StubPlayer()
    window.players[original[3]] = player

    window._on_layout_changed("main2")
    app.processEvents()
    assert window.wall.visible_tiles() == [original[0], original[3], original[2]]
    assert window.wall.tiles[3] is original[1]
    assert (original[3].volume, original[3].muted, original[3].audio_channel) == (20, True, 2)
    assert (original[1].volume, original[1].muted, original[1].audio_channel) == (40, False, 1)
    assert (player.volume, player.muted, player.channel) == (20, True, 2)
    assert window.players[original[3]] is player

    window._on_layout_changed("corner")
    app.processEvents()
    assert len(window.wall.visible_tiles()) == 6
    order = list(window.wall.tiles)
    window._on_layout_changed("main2")
    app.processEvents()
    assert window.wall.tiles == order, "已可见的开播格子不应再被移动"
    window.close()
    print("缩小布局优先显示开播格子、声音设置留在原位置：通过")


if __name__ == "__main__":
    main()
