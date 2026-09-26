"""离线自检：排序管理窗口批量移动、搜索与置顶区约束。"""
import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from ddm.sort_dialog import SortManagerDialog, move_selected  # noqa: E402
from ddm.widgets import Sidebar  # noqa: E402


def main() -> None:
    order = ["p1", "p2", "a", "b", "c", "d"]
    selected = {"p2", "b", "d"}
    assert move_selected(order, selected, "first", 2) == ["p2", "p1", "b", "d", "a", "c"]
    assert move_selected(order, selected, "last", 2) == ["p1", "p2", "a", "c", "b", "d"]
    assert move_selected(order, {"b", "c"}, "up", 2) == ["p1", "p2", "b", "c", "a", "d"]
    assert move_selected(order, {"b", "c"}, "down", 2) == ["p1", "p2", "a", "d", "b", "c"]

    app = QApplication.instance() or QApplication(sys.argv)
    rooms = [(room_id, room_id.upper()) for room_id in order]
    dialog = SortManagerDialog(rooms, ["p1", "p2"])
    dialog.search.setText("B")
    visible = [dialog.list.item(index).data(Qt.UserRole)
               for index in range(dialog.list.count())
               if not dialog.list.item(index).isHidden()]
    assert visible == ["b"], "搜索应只显示匹配卡片"
    dialog.search.clear()
    for index in range(dialog.list.count()):
        item = dialog.list.item(index)
        item.setSelected(item.data(Qt.UserRole) in {"b", "d"})
    dialog.move_buttons["first"].click()
    assert dialog.order_ids() == ["p1", "p2", "b", "d", "a", "c"]
    dialog.close()

    sidebar = Sidebar([{"room_id": room_id, "uname": name} for room_id, name in rooms])
    sidebar.apply_pins(["p1", "p2"])
    assert sidebar.apply_manual_order(["a", "p2", "d", "p1", "b", "c"])
    assert [str(item.room["room_id"]) for item in sidebar.items()] == \
        ["p2", "p1", "a", "d", "b", "c"]
    assert sidebar.pinned == ["p2", "p1"]
    assert sidebar.custom_order == ["p2", "p1", "a", "d", "b", "c"]
    sidebar.close()
    print("排序管理窗口：搜索、批量移动与置顶区约束通过")


if __name__ == "__main__":
    main()
