"""回归自检：关注栏拖动卡片时的「贴边自动滚」，上下两个方向都要能用。

以前只有「往上」能滚：判据用的是 RoomListBox 的**内容高度**（它是
``scroll.setWidget()`` 的内容 widget，40 个关注时 5200px），而视口只有 517px，
于是「往下」的判据 ``y > 内容高 - 28`` 在视口里永远够不着 —— 往下滚等于没有，
卡片拖不到看不见的位置。

这里钉住三件事：
1. 光标贴到**视口**下边缘 / 上边缘，分别触发往下 / 往上滚；
2. 越贴边滚得越快，而且每一拍真的会推动滚动条；
3. 中间不滚、拖动结束要停表（不然松手后还在滚）。

不联网、不弹窗：只构造窗口，直接调 auto_scroll / _scroll_tick 看效果。
"""
import os
import sys
import time

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import theme  # noqa: E402
from ddm.app import MainWindow  # noqa: E402

ROOMS = [{"room_id": str(1000 + i), "uname": f"主播{i}", "title": "标题", "live": True,
          "muted": True, "volume": 42, "quality": 250} for i in range(40)]


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
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())
    window = MainWindow([dict(room) for room in ROOMS], [], layout_id="1x1")
    window.setGeometry(-9000, -9000, 1400, 800)
    window.show()
    settle(app, 1.0)

    area = window.sidebar.scroll
    box = window.sidebar.list_box
    viewport = area.viewport()
    bar = area.verticalScrollBar()

    print("=== 0. 前提：内容比视口长，滚动条有得滚 ===")
    print(f"  视口高={viewport.height()} 内容高={box.height()} "
          f"滚动范围 0~{bar.maximum()}")
    assert viewport.height() < box.height(), "自检要有比视口长的列表才有意义"
    assert bar.maximum() > 0, "滚动条得能滚"

    def global_at(y: int) -> QPoint:
        return viewport.mapToGlobal(QPoint(max(1, viewport.width() // 2), y))

    print("\n=== 1. 贴视口下边缘 -> 往下滚（以前永远不触发）===")
    near_bottom = global_at(viewport.height() - 5)
    box.auto_scroll(near_bottom)
    print(f"  auto_scroll(视口下边缘-5) -> dir={box._scroll_dir}")     # noqa: SLF001
    assert box._scroll_dir == 1, "拖到视口下边缘必须往下滚"
    content_y = box.mapFromGlobal(near_bottom).y()
    print(f"  同一位置的内容坐标 y={content_y}，老判据要 y>{box.height() - 28}"
          f" -> 够不着，这就是根因")
    assert content_y < box.height() - 28, "老算法在这个位置确实触发不了"

    print("\n=== 2. 每一拍真的推动滚动条，而且越贴边越快 ===")
    before = bar.value()
    box._scroll_tick()                                     # noqa: SLF001
    after = bar.value()
    print(f"  往下：{before} -> {after}（步长≈{box._scroll_step:.0f}px）")
    assert after > before, "往下滚要真的把滚动条推下去"

    box.auto_scroll(global_at(viewport.height() - 2))      # 贴死边缘
    fast = box._scroll_step                                # noqa: SLF001
    box.auto_scroll(global_at(viewport.height() - box.SCROLL_EDGE + 2))   # 刚进边缘带
    slow = box._scroll_step                                # noqa: SLF001
    print(f"  贴死={fast:.0f}px/拍  刚进带={slow:.0f}px/拍")
    assert fast > slow, "越贴边应该滚得越快"

    print("\n=== 3. 贴视口上边缘 -> 往上滚 ===")
    box.auto_scroll(global_at(5))
    print(f"  auto_scroll(视口上边缘+5) -> dir={box._scroll_dir}")      # noqa: SLF001
    assert box._scroll_dir == -1
    before = bar.value()
    box._scroll_tick()                                     # noqa: SLF001
    print(f"  往上：{before} -> {bar.value()}")
    assert bar.value() < before, "往上滚要真的把滚动条收回去"

    print("\n=== 4. 中间不滚，且定时器停掉 ===")
    box.auto_scroll(global_at(viewport.height() // 2))
    print(f"  视口中间 -> dir={box._scroll_dir} 定时器={box._scroll_timer.isActive()}")  # noqa: SLF001
    assert box._scroll_dir == 0
    assert not box._scroll_timer.isActive(), "不滚了必须停表"          # noqa: SLF001

    print("\n=== 5. 端到端：hover_drag 传全局坐标，自动滚生效 ===")
    window.sidebar.hover_drag("1003", global_at(viewport.height() - 3))
    print(f"  hover_drag(视口下边缘) -> dir={box._scroll_dir}")        # noqa: SLF001
    assert box._scroll_dir == 1, "拖动回调必须传全局坐标，否则又回到老 bug"
    assert box._scroll_timer.isActive()                               # noqa: SLF001
    window.sidebar.end_drag()
    print(f"  拖动结束 -> dir={box._scroll_dir} 定时器={box._scroll_timer.isActive()}")  # noqa: SLF001
    assert box._scroll_dir == 0 and not box._scroll_timer.isActive(), \
        "松手/取消之后不能再滚"

    window.close()
    settle(app, 0.3)
    print("\n全部通过")


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
