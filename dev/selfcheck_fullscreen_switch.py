"""回归自检：进出全屏时格子的可见性与分批露面。

用户报「取消全屏的时候会卡顿一段时间」。4K 实测那条退出链路约 283 ms，其中
抓屏 + 建遮盖窗约 95 ms，剩下约 190 ms 是窗口样式切换 + 9 个格子的 VLC 原生
窗口重配 —— 一次做完主线程会僵住，盖在上面的过渡图也跟着"冻"在原地，看起来
就是卡住再突然一跳。

这一版把重配拆成几批（`WallPanel.reveal_tiles_staggered`），并让遮盖图淡出。
这里钉住拆分本身的正确性：布局一次算好、格子分批显示、最后**一个都不能少**、
反复进出也不许漏状态。

遮盖窗那几步在离屏/无交互桌面下拿不到截图（`_grab_fullscreen_frame` 返回 None），
所以本自检把它 patch 掉，只验它拿不到图时能安全降级。
"""
import os
import sys
import time
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import config as config_module  # noqa: E402
from ddm import theme  # noqa: E402
from ddm.app import MainWindow  # noqa: E402

ROOMS = [{"room_id": f"98{index:02d}", "uname": f"主播{index}", "title": "t",
          "live": True, "muted": True, "volume": 40, "quality": 250}
         for index in range(1, 10)]


def settle(app, seconds: float = 0.3) -> None:
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


def main() -> None:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())
    settings = dict(config_module.DEFAULT_SETTINGS)
    window = MainWindow([dict(room) for room in ROOMS],
                        [dict(room) for room in ROOMS],
                        layout_id="3x3", state={"settings": dict(settings)})
    window.setGeometry(-9000, -9000, 1200, 700)
    window.show()
    settle(app, 0.5)
    # 遮盖窗那一步在无人值守时拿不到截图，而且它会盖住真实桌面 —— 整个 patch 掉
    hold = patch.object(MainWindow, "_hold_fullscreen_frame", lambda _self: None)
    try:
        tiles = list(window.wall.tiles)
        for tile in tiles:
            tile.room["live"] = True
            tile.stream_url = "https://example.invalid/live.flv"
        print(f"画面墙格子 {len(tiles)} 个")

        print("\n=== 1. 进入全屏：只留目标格子 ===")
        target = tiles[4]
        with hold:
            window._on_fullscreen(target)          # noqa: SLF001
        settle(app, 0.2)
        visible = window.wall.visible_tiles()
        print(f"  全屏中可见格子={len(visible)}（该 1）")
        assert visible == [target], f"全屏时只该显示目标格子，实际 {visible}"
        assert window._fullscreen_tile is target      # noqa: SLF001

        print("\n=== 2. 退出全屏：分批露面，刚退出来那格立刻回来 ===")
        with hold:
            window._exit_fullscreen()              # noqa: SLF001
        pending = list(window.wall._pending_reveal)   # noqa: SLF001
        visible_now = window.wall.visible_tiles()
        print(f"  退出当帧：可见={len(visible_now)} 排队={len(pending)}")
        assert target.isVisible(), "刚退出来的那一格要立刻显示（视线在它身上）"
        assert target not in pending, "first 不该被排进等待队列"
        assert pending, "其余格子该排进等待队列，等后面几帧再露面"
        assert len(visible_now) < len(tiles), \
            f"不该在退出当帧就把 {len(tiles)} 格全显示 —— 那就白拆了"
        assert window.wall._defer_show, "分批期间该处在「延迟显示」状态"  # noqa: SLF001

        print("\n=== 3. 分批跑完：一个都不许少 ===")
        settle(app, 0.8)
        visible = window.wall.visible_tiles()
        print(f"  最终可见={len(visible)}/{len(tiles)}　"
              f"排队剩={len(window.wall._pending_reveal)}　"    # noqa: SLF001
              f"defer={window.wall._defer_show}")               # noqa: SLF001
        assert len(visible) == len(tiles), f"分批跑完该全部显示，实际 {len(visible)}"
        assert window.wall._pending_reveal == [], "排队该清空"       # noqa: SLF001
        assert not window.wall._defer_show, "分批结束后要复位"        # noqa: SLF001

        print("\n=== 4. 反复进出：状态每次都要收敛 ===")
        for index in range(3):
            with hold:
                window._on_fullscreen(tiles[index])    # noqa: SLF001
                settle(app, 0.15)
                window._exit_fullscreen()              # noqa: SLF001
            settle(app, 0.8)
            visible = window.wall.visible_tiles()
            assert len(visible) == len(tiles), \
                f"第 {index + 1} 轮进出后格子没回全：{len(visible)}"
            assert not window.wall._defer_show and not window.wall._pending_reveal
        print("  3 轮进出后格子数与状态都对")

        print("\n=== 5. 分批没跑完就再进全屏：不许留残留 ===")
        with hold:
            window._on_fullscreen(tiles[0])            # noqa: SLF001
            settle(app, 0.15)
            window._exit_fullscreen()                  # noqa: SLF001
        # 故意不等那几批跑完，直接又进全屏
        with hold:
            window._on_fullscreen(tiles[1])            # noqa: SLF001
        print(f"  又进全屏后：排队={len(window.wall._pending_reveal)}　"   # noqa: SLF001
              f"defer={window.wall._defer_show}")                        # noqa: SLF001
        assert window.wall._pending_reveal == [], "重新进入全屏要把排队清掉"  # noqa: SLF001
        assert not window.wall._defer_show
        with hold:
            window._exit_fullscreen()                  # noqa: SLF001
        settle(app, 0.8)
        visible = window.wall.visible_tiles()
        print(f"  再退出来：可见={len(visible)}/{len(tiles)}")
        assert len(visible) == len(tiles), f"最后仍要全部回来，实际 {len(visible)}"

        print("\n=== 6. 拿不到截图时遮盖子系统的安全降级 ===")
        assert window._fullscreen_cover is None, "自检里 patch 过，不该有遮盖窗"  # noqa: SLF001
        window._release_fullscreen_frame()     # noqa: SLF001
        window._start_fullscreen_fade()        # noqa: SLF001
        window._clear_fullscreen_cover()       # noqa: SLF001
        print("  cover 为 None 时 release / fade / clear 三个入口都安全返回")
    finally:
        window.close()
        settle(app, 0.25)
    print("\n全部通过")


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
