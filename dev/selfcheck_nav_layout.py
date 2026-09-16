"""自查：关注列表拖动排序（含置顶约束）、布局菜单的两个子菜单切换。不联网。"""
import os
import sys
import time

from PySide6.QtCore import QMimeData, QPointF, Qt
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import layouts, theme  # noqa: E402
from ddm.widgets import (  # noqa: E402
    NAV_ITEM_GAP, NAV_ITEM_HEIGHT, LayoutPicker, Sidebar,
)

ROOMS = [{"room_id": f"100{index}", "uname": f"主播{index}", "title": f"房间{index}",
          "live": index % 2 == 0}
         for index in range(1, 6)]


def order(sidebar):
    return [str(item.room.get("room_id")) for item in sidebar.items()]


def settle(app, seconds):
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.03)


def drop_at(sidebar, room_id: str, y: float):
    mime = QMimeData()
    mime.setData("application/x-ddm-nav", str(room_id).encode("utf-8"))
    event = QDropEvent(QPointF(20, y), Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier)
    sidebar.list_box.dropEvent(event)


def main() -> None:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())

    sidebar = Sidebar([dict(room) for room in ROOMS])
    sidebar.setGeometry(-8000, -8000, 248, 700)
    sidebar.show()
    settle(app, 0.5)

    print("=== 1. 置顶后置顶的两个排在最上面 ===")
    sidebar.toggle_pin(sidebar.items()[2].room)      # 1003 置顶
    sidebar.toggle_pin(sidebar.items()[3].room)      # 1004 置顶
    print("  顺序:", order(sidebar), "置顶表:", sidebar.pinned)
    assert order(sidebar)[:2] == ["1003", "1004"]

    print("\n=== 2. 普通项拖不到置顶上方 ===")
    changed = sidebar.reorder_item("1001", 0)        # 想把 1001 拖到最上面
    print("  拖动结果:", changed, "顺序:", order(sidebar))
    assert order(sidebar)[0] == "1003" and order(sidebar)[1] == "1004"
    assert order(sidebar)[2] == "1001", "应该落在置顶区下面第一格"

    print("\n=== 3. 置顶项之间可以互相换顺序 ===")
    sidebar.reorder_item("1004", 0)
    print("  顺序:", order(sidebar), "置顶表:", sidebar.pinned)
    assert order(sidebar)[:2] == ["1004", "1003"]
    assert sidebar.pinned == ["1004", "1003"]

    print("\n=== 4. 置顶项拖不到下面（收回置顶区末尾）===")
    sidebar.reorder_item("1004", 5)
    print("  顺序:", order(sidebar), "置顶表:", sidebar.pinned)
    assert order(sidebar)[:2] == ["1003", "1004"], "置顶项只能落在置顶区里"
    assert order(sidebar)[2] == "1001", "普通项不会被推到置顶区"

    print("\n=== 5. 普通项之间可以排到末尾 ===")
    before = order(sidebar)
    sidebar.reorder_item("1001", len(before))
    print(f"  {before} -> {order(sidebar)}")
    assert order(sidebar)[-1] == "1001"
    assert order(sidebar)[:2] == ["1003", "1004"]

    print("\n=== 6. 列表真的接收拖动（模拟落点）===")
    assert sidebar.list_box.acceptDrops(), "列表容器要允许拖放"
    settle(app, 0.4)
    y = sidebar.list_box.content_height() + 10       # 落在所有卡片下面
    drop_at(sidebar, "1001", y)
    settle(app, 0.4)
    print(f"  落点 y={y:.0f} 之后顺序: {order(sidebar)}")
    assert order(sidebar)[-1] == "1001"
    assert order(sidebar)[:2] == ["1003", "1004"]

    print("\n=== 7. 抓起来拖动：卡片让位（空出一格）===")
    sidebar.show_drop_indicator("1001", 2)
    settle(app, 0.4)
    held = next(entry for entry in sidebar.items()
                if str(entry.room.get("room_id")) == "1001")
    others = [entry for entry in sidebar.items() if entry is not held]
    print(f"  被拖的卡片隐藏={not held.isVisible()}"
          f" 其余卡片位置={[entry.y() for entry in others]}"
          f" 列表高度={sidebar.list_box.minimumHeight()}")
    assert not held.isVisible(), "抓起来的那张要从列表里拿掉"
    pitch = NAV_ITEM_HEIGHT + NAV_ITEM_GAP
    assert others[1].y() >= others[0].y() + pitch - NAV_ITEM_GAP, "落点位置要空出一格"
    sidebar.show_drop_indicator(None, 0)
    settle(app, 0.4)
    print(f"  恢复后：全部可见={all(entry.isVisible() for entry in sidebar.items())}"
          f" 位置={[entry.y() for entry in sidebar.items()]}")
    assert all(entry.isVisible() for entry in sidebar.items())
    assert [entry.y() for entry in sidebar.items()] == [index * pitch
                                                       for index in range(5)]

    print("\n=== 8. 松手结算：列表内排序 / 列表外只放回去 ===")
    inside = sidebar.list_box.mapToGlobal(QPointF(20, sidebar.list_box.slot_height() * 1.2)
                                          .toPoint())
    before = order(sidebar)
    sidebar.finish_drag("1001", inside)
    settle(app, 0.4)
    print(f"  列表内松手：{before} -> {order(sidebar)}")
    assert order(sidebar)[:2] == ["1003", "1004"], "置顶区不能被顶掉"
    assert order(sidebar)[2] == "1001", "拖到列表里应该真的排到那个位置"

    sidebar.show_drop_indicator("1001", 3)
    settle(app, 0.3)
    outside = sidebar.list_box.mapToGlobal(QPointF(20, -400).toPoint())
    before = order(sidebar)
    sidebar.finish_drag("1001", outside)
    settle(app, 0.4)
    print(f"  列表外松手：{before} -> {order(sidebar)}"
          f" 全部可见={all(entry.isVisible() for entry in sidebar.items())}")
    assert order(sidebar) == before, "拖到列表外面不应该改顺序"
    assert all(entry.isVisible() for entry in sidebar.items()), "卡片要放回去"

    print("\n=== 9. 布局菜单：普通布局 / 弹幕布局两个按钮 ===")
    picker = LayoutPicker("dm_main3")
    picker.move(-8000, -8000)
    picker.show()
    settle(app, 0.5)
    tabs = list(picker._tabs)
    print(f"  子菜单: {tabs} 当前={picker.group()}")
    assert tabs == ["普通布局", "弹幕布局"]
    assert picker.group() == "弹幕布局", "当前布局在弹幕组里，默认应该停在这一栏"
    visible = [card.text() for card in picker._cards["弹幕布局"] if card.isVisible()]
    print(f"  弹幕布局可见: {len(visible)} 个 -> {visible[:3]} …")
    assert len(visible) == len(layouts.DANMAKU_LAYOUTS)
    assert not any(card.isVisible() for card in picker._cards["普通布局"])

    picker.set_group("普通布局")
    settle(app, 0.3)
    visible = [card.text() for card in picker._cards["普通布局"] if card.isVisible()]
    print(f"  切到普通布局：{len(visible)} 个可见，尺寸={picker.width()}x{picker.height()}"
          f"（切栏前后尺寸保持一致）")
    assert len(visible) == len(layouts.LAYOUTS)
    assert not any(card.isVisible() for card in picker._cards["弹幕布局"])
    assert picker._tabs["普通布局"].isChecked()

    chosen: list[str] = []
    picker.chosen.connect(chosen.append)
    picker._cards["普通布局"][0].click()
    print(f"  点第一个卡片 -> chosen={chosen}")
    assert chosen == [layouts.LAYOUTS[0]["id"]]

    picker.close()
    sidebar.close()
    print("\n全部通过")


if __name__ == "__main__":
    main()
    # 直接退出进程：Qt / VLC 在线程收尾时析构会偶发崩在退出瞬间（程序本体也是这么做的）
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
