"""回归自检：布局变小后，放不下的格子必须**停播**，不能只是隐藏还在出声。

用户报的现象：从 9 格布局（3x3）换成 6 格（3x2）之后，消失的那 3 个格子还在响
—— 因为 ``WallGrid.relayout()`` 对放不下的格子只做 ``setVisible(False)``，播放器
一步没停（``app._sync_tile_playback()`` 就是补这一刀）。

不联网：取流接口打桩成抛异常，播放器用只记「有没有被 release」的替身。
"""
import os
import sys
import time

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import bili, theme  # noqa: E402
from ddm import app as app_module  # noqa: E402
from ddm.app import MainWindow  # noqa: E402

ROOMS = [{"room_id": str(1000 + i), "uname": f"主播{i}", "title": "标题",
          "live": True, "muted": True, "volume": 42, "quality": 250}
         for i in range(9)]


class SilentPoller(QThread):
    updated = Signal(dict)

    def __init__(self, room_ids, parent=None):
        super().__init__(parent)
        self.room_ids = list(room_ids)

    def run(self) -> None:
        return


class StubPlayer:
    """替身播放器：只记「有没有被 release」。"""

    def __init__(self):
        self.released = False

    def release(self) -> None:
        self.released = True


def boom(*_args, **_kwargs):
    raise RuntimeError("selfcheck：不联网")


def settle(app, seconds: float) -> None:
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.03)


def main() -> None:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass
    bili.play_url = boom
    app_module.StatusPoller = SilentPoller
    app_module.StatsPoller = SilentPoller
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())

    print("=== 1. 9 格布局：9 个格子都摆得下 ===")
    window = MainWindow([dict(room) for room in ROOMS],
                        [dict(room) for room in ROOMS], layout_id="3x3")
    window.setGeometry(-9000, -9000, 1400, 800)
    window.show()
    settle(app, 0.8)
    stubs = {}
    for tile in window.wall.tiles:
        stubs[tile] = StubPlayer()
        window.players[tile] = stubs[tile]
    print(f"  可见={len(window.wall.visible_tiles())} "
          f"隐藏={window.wall.hidden_count()} players={len(window.players)}")
    assert len(window.wall.visible_tiles()) == 9 and window.wall.hidden_count() == 0

    print("\n=== 2. 切成 6 格（3x2）：消失的 3 个格子必须停播 ===")
    window._on_layout_changed("3x2")           # noqa: SLF001
    settle(app, 0.6)
    hidden = [tile for tile in window.wall.tiles if not tile.isVisible()]
    print(f"  可见={len(window.wall.visible_tiles())} 隐藏={len(hidden)} "
          f"players={len(window.players)}")
    assert len(hidden) == 3, f"3x3 -> 3x2 应该刚好藏起 3 个，实际 {len(hidden)}"
    for tile in hidden:
        assert stubs[tile].released, "藏起来的格子必须停播，否则还在出声"
        assert tile not in window.players, "停播的格子要从 players 表里摘掉"
    assert len(window.players) == 6, f"应该只剩 6 路在播，实际 {len(window.players)}"

    print("\n=== 3. 切回 9 格：重新显示的格子要重新接上 ===")
    started = []
    original_start = window.start_tile
    window.start_tile = lambda target: started.append(target)
    window._on_layout_changed("3x3")           # noqa: SLF001
    settle(app, 0.6)
    window.start_tile = original_start
    print(f"  可见={len(window.wall.visible_tiles())} 重新起播={len(started)}")
    assert window.wall.hidden_count() == 0
    assert len(started) == 3, f"重新露出来的 3 个格子要重新起播，实际 {len(started)}"

    window.close()
    settle(app, 0.3)
    print("\n全部通过")


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
