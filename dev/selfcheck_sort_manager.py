"""离线自检：关注卡片多选、整组移动和置顶边界。"""
import os
import sys

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from ddm import theme  # noqa: E402
from ddm.widgets import Sidebar  # noqa: E402


def main() -> None:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setStyleSheet(theme.qss())
    rooms = [{"room_id": room_id, "uname": room_id.upper()} for room_id in
             ("p1", "p2", "a", "b", "c", "d")]
    sidebar = Sidebar(rooms)
    sidebar.setGeometry(-8000, -8000, 248, 600)
    sidebar.show()
    app.processEvents()
    sidebar.apply_pins(["p1", "p2"])

    def order() -> list[str]:
        return [str(item.room["room_id"]) for item in sidebar.items()]

    def item(room_id: str):
        return next(entry for entry in sidebar.items()
                    if str(entry.room["room_id"]) == room_id)

    for room_id in ("p2", "b", "d"):
        QTest.mouseClick(item(room_id), Qt.LeftButton, Qt.ControlModifier)
    assert sidebar.selected_sort_ids() == ["p2", "b", "d"]
    assert all(item(room_id).property("sortSelected") for room_id in ("p2", "b", "d"))
    menu = item("b")._context_menu()
    next(action for action in menu.actions() if action.text() == "将选中的 3 张移到最前").trigger()
    assert order() == ["p2", "p1", "b", "d", "a", "c"]
    assert sidebar.pinned == ["p2", "p1"]
    assert sidebar.custom_order == order()
    next(action for action in item("b")._context_menu().actions()
         if action.text() == "将选中的 3 张移到最后").trigger()
    assert order() == ["p1", "p2", "a", "c", "b", "d"]

    QTest.mouseClick(item("a"), Qt.LeftButton)
    assert sidebar.selected_sort_ids() == []
    QTest.mouseClick(item("a"), Qt.LeftButton, Qt.ControlModifier)
    QTest.mouseClick(item("b"), Qt.LeftButton, Qt.ShiftModifier)
    assert sidebar.selected_sort_ids() == ["a", "c", "b"]
    sidebar.clear_sort_selection()

    QTest.mouseClick(item("b"), Qt.LeftButton, Qt.ControlModifier)
    QTest.mouseClick(item("d"), Qt.LeftButton, Qt.ControlModifier)
    assert sidebar.dragged_room_ids("b") == ["b", "d"]
    sidebar.show_drop_indicator("b", 2)
    assert item("b").isHidden() and item("d").isHidden()
    sidebar.finish_drag("b", sidebar.list_box.mapToGlobal(QPoint(10, 0)))
    assert order() == ["p1", "p2", "b", "d", "a", "c"]
    assert not item("b").isHidden() and not item("d").isHidden()
    assert sidebar.selected_sort_ids() == ["b", "d"]

    sidebar.clear_sort_selection()
    QTest.mouseClick(item("p2"), Qt.LeftButton, Qt.ControlModifier)
    QTest.mouseClick(item("b"), Qt.LeftButton, Qt.ControlModifier)
    assert sidebar.reorder_items(sidebar.selected_sort_ids(), 0)
    assert order() == ["p2", "p1", "b", "d", "a", "c"]
    assert sidebar.pinned == ["p2", "p1"]

    sidebar.search.setText("P")
    assert sidebar.selected_sort_ids() == []
    assert not any(action.text() == "管理排序…"
                   for action in sidebar.sort_button.menu().actions())

    sidebar.search.clear()
    sidebar.set_select_mode(True)
    QTest.mouseClick(item("a"), Qt.LeftButton)
    QTest.mouseClick(item("c"), Qt.LeftButton)
    assert sidebar.selected_sort_ids() == ["a", "c"]
    assert sidebar.dragged_room_ids("a") == ["a", "c"]
    assert item("a").property("sortSelected") and item("c").property("sortSelected")
    next(action for action in item("a")._context_menu().actions()
         if action.text() == "将选中的 2 张移到最前").trigger()
    assert order() == ["p2", "p1", "a", "c", "b", "d"]
    assert sidebar.selected_sort_ids() == ["a", "c"]
    sidebar.search.setText("A")
    assert sidebar.selected_sort_ids() == ["a"], "隐藏的勾选卡片不能被拖动"
    sidebar.search.clear()
    assert sidebar.selected_sort_ids() == ["a", "c"]
    sidebar.set_select_mode(False)
    assert sidebar.selected_sort_ids() == []
    sidebar.close()
    print("关注卡片多选、整组拖动、右键移动与置顶边界通过")


if __name__ == "__main__":
    main()
