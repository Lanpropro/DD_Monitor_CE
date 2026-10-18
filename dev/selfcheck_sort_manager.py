"""离线自检：关注卡片多选、整组移动和置顶边界。"""
import os
import sys

from PySide6.QtCore import QEvent, QPoint, Qt
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
    for side in ("left", "top", "left", "top", "left"):
        sidebar.set_side(side)
        app.processEvents()
        button = sidebar.batch_button
        assert button.text() == "" and button._icon_mode
        assert button.accessibleName() == "多选直播间"
        if side == "left":
            assert button.parentWidget() is sidebar.status_row
            box = sidebar.status_row.layout()
            assert box.indexOf(button) == box.indexOf(sidebar.sort_button) + 1
            assert sidebar._header_row.layout().indexOf(button) == -1
            assert button.size().width() == button.size().height() == 22
        QTest.mouseClick(button, Qt.LeftButton)
        assert sidebar.select_mode and button.isChecked()
        assert sidebar.account_row.isHidden() and sidebar.tool_row.isHidden()
        assert sidebar.normal_bar.isHidden() and not sidebar.batch_bar.isHidden()
        card = sidebar.items()[0]
        assert card._layout.indexOf(card.check) == -1
        check_center = card.check.geometry().center() - card.pos()
        assert check_center.y() == card.height() // 2 - 1
        assert check_center.x() == card.width() - 13
        assert card.mask().isEmpty(), '圆弧不能退回有锯齿的整数区域遮罩'
        assert card.graphicsEffect() is not None
        QTest.mouseClick(card.check, Qt.LeftButton)
        assert card.is_checked()
        sidebar.set_select_mode(False)
        assert not button.isChecked()
        assert not sidebar.account_row.isHidden() and not sidebar.tool_row.isHidden()
        assert card.mask().isEmpty() and card.check.isHidden() and not card.is_checked()
    sidebar.set_select_mode(True)
    for side in ('top', 'left', 'top', 'left'):
        sidebar.set_side(side)
        app.processEvents()
        assert sidebar.select_mode and sidebar.account_row.isHidden()
        assert sidebar.tool_row.isHidden() and sidebar.normal_bar.isHidden()
        assert not sidebar.batch_bar.isHidden()
        for card in sidebar.items():
            assert card.mask().isEmpty() and card.graphicsEffect() is not None
            assert card.check.geometry().center().x() - card.x() == card.width() - 13
    sidebar.set_select_mode(False)
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
    sidebar.finish_drag("b", sidebar.list_box.mapToGlobal(QPoint(10, item("p1").y())))
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
    assert item('c').check.isHidden(), '筛选隐藏卡片时，凹口上的勾选也必须隐藏'
    sidebar.search.clear()
    assert sidebar.selected_sort_ids() == ["a", "c"]
    sidebar.set_select_mode(False)
    assert sidebar.selected_sort_ids() == []
    sidebar.set_select_mode(True)
    removed = item('d')
    check = removed.check
    sidebar.remove_room(removed.room)
    assert check.isHidden()
    app.sendPostedEvents(None, QEvent.DeferredDelete)
    app.sendPostedEvents(None, QEvent.DeferredDelete)
    from shiboken6 import isValid
    assert not isValid(check), '删除卡片不能遗留独立勾选控件'
    sidebar.close()
    print("关注卡片多选、整组拖动、右键移动与置顶边界通过")


if __name__ == "__main__":
    main()
