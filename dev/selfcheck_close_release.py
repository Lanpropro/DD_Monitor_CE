"""回归自检：关窗释放播放器后，迟到的取流回调不能再碰已经释放的实例。

来源是一次真机崩溃（`logs/ddm-2026-09-18.log`，对应 `444b1e4` 那版代码）：

    File "ddm/app.py", line 601, in <lambda>
        self._play_on(t, url, qn, profile, options, headers=resolver.headers))
    File "ddm/app.py", line 621, in _play_on
        player.set_volume(int(tile.volume))
    OSError: exception: access violation writing 0x0000000000000024

`vlc.MediaPlayer.release()` 只是把底层实例还回去，Python 包装还留在
`self.players` 里；而 `resolver.resolved` 是队列连接，关窗之后它还会再投递
一次，`_play_on` 就从表里拿到那个已经释放的实例 → 野指针。

这里钉住两条不变量：
1. `closeEvent()` 走完之后 `players` / `_resolvers` 必须是空的；
2. 关窗之后再来的取流回调（`start_tile` / `_play_on`）不许再拉起播放器。

不联网：不开真流，只建一个播放器对象验证生命周期。
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
from ddm.player import TilePlayer  # noqa: E402

ROOMS = [{"room_id": "7101", "uname": "主播甲", "title": "房间甲", "live": True,
          "muted": True, "volume": 42, "quality": 250}]


class SilentPoller(QThread):
    updated = Signal(dict)

    def __init__(self, room_ids, parent=None):
        super().__init__(parent)
        self.room_ids = list(room_ids)

    def run(self) -> None:
        return


def boom(room_id, quality=250, **_kwargs):        # noqa: ANN001, ANN201
    raise RuntimeError("selfcheck：不联网")


def settle(app, seconds: float) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
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

    print("=== 1. 关窗前：格子上有一个真播放器 ===")
    window = MainWindow([dict(room) for room in ROOMS], [dict(room) for room in ROOMS],
                        layout_id="1x1")
    window.setGeometry(-9000, -9000, 900, 600)
    window.show()
    settle(app, 1.0)
    tile = window.wall.tiles[0]
    player = TilePlayer(tile.video, window)
    player.set_volume(42)                     # 释放前是能用的
    window.players[tile] = player
    print(f"  格子={tile.room.get('uname')} 播放器已挂上：{len(window.players)} 个")
    assert window.players.get(tile) is player
    assert not getattr(window, "_closing", False), "关窗标记一开始必须是 False"

    print("\n=== 2. 关窗：release 之后表要清空 ===")
    window.close()
    settle(app, 0.4)
    print(f"  关窗后：_closing={getattr(window, '_closing', False)} "
          f"players={len(window.players)} "
          f"resolvers={len(window._resolvers)} 播放器已释放={player._released}")
    assert player._released, "关窗时播放器要真的被释放"
    assert not window.players, \
        "关窗后 players 必须清空，否则迟到的取流回调会拿到已释放的实例"
    assert not window._resolvers, "关窗后取流线程表也要清空"
    assert getattr(window, "_closing", False), "closeEvent 必须钉住关窗状态"

    print("\n=== 3. 关窗后迟到的取流回调：不许再拉起播放器 ===")
    # 这两条就是日志里那次崩溃的入口：resolved 在关窗之后才被投递
    window.start_tile(tile)
    window._play_on(tile, "http://127.0.0.1:9/none.flv")      # noqa: SLF001
    window._on_resolve_failed(tile, "迟到的失败")              # noqa: SLF001
    settle(app, 0.4)
    print(f"  回调之后：players={len(window.players)} resolvers="
          f"{len(window._resolvers)} 状态={tile.status_label.text()!r}")
    assert not window.players, "关窗后不能再建播放器（那就是野指针的来源）"
    assert not window._resolvers, "关窗后不能再起取流线程"

    print("\n=== 4. 正常关窗 + 反复关（release 幂等）===")
    window2 = MainWindow([dict(room) for room in ROOMS],
                         [dict(room) for room in ROOMS], layout_id="1x1")
    window2.setGeometry(-9000, -9000, 900, 600)
    window2.show()
    settle(app, 0.8)
    player2 = TilePlayer(window2.wall.tiles[0].video, window2)
    window2.players[window2.wall.tiles[0]] = player2
    window2.close()
    window2.close()                            # 重复关窗不能崩
    settle(app, 0.3)
    assert not window2.players
    print("  重复关窗无异常")

    print("\n全部通过")


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
