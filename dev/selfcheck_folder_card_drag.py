"""文件夹内卡片拖动：实时让位、稳定落点、取消恢复与排序持久化。"""
import os
from pathlib import Path
import sys

os.environ["DDM_NO_SAVE"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from ddm import theme
from ddm.widgets import NAV_MIME, Sidebar


def settle():
    QTest.qWait(190)


def main():
    app = QApplication([])
    app.setStyleSheet(theme.qss())
    for side, card_mode, collapsed, smart in (
            ("left", True, False, False), ("left", False, False, False),
            ("left", True, True, False), ("top", True, False, False),
            ("top", False, False, False), ("left", True, False, True)):
        rooms = [{"room_id": rid, "uname": rid, "live": False} for rid in
                 ("a", "b", "c", "d", "huya:x", "huya:y", "douyu:u")]
        sidebar = Sidebar(rooms, card_mode=card_mode, auto_compact=False)
        sidebar.resize(248, 1100)
        folder = sidebar.create_folder("当前分类", rule={"status": "any", "platforms": ["bilibili"]}
                                       if smart else None)
        other = sidebar.create_folder("其他分类")
        if not smart:
            sidebar.move_to_folder(["a", "b", "c", "d"], folder)
        sidebar.move_to_folder(["huya:x", "huya:y"], other)
        sidebar.set_side(side)
        if side == "top":
            sidebar.resize(1400, sidebar.height())
        sidebar.set_collapsed(collapsed, animate=False)
        sidebar.show()
        app.processEvents()
        box = sidebar.list_box
        items = {str(item.room["room_id"]): item for item in sidebar.items()}
        changes = []
        sidebar.orderChanged.connect(lambda: changes.append(True))

        def order():
            return [str(item.room["room_id"]) for item in sidebar.items()]

        def pos(rid):
            return items[rid].x() if box.horizontal else items[rid].y()

        def point(rid, fraction=.25):
            item = items[rid]
            return item.pos() + (QPoint(round(item.width() * fraction), item.height() // 2)
                                 if box.horizontal else
                                 QPoint(item.width() // 2, round(item.height() * fraction)))

        def hover(rid, local):
            mime = QMimeData()
            mime.setData(NAV_MIME, rid.encode())
            enter = QDragEnterEvent(local, Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier)
            QApplication.sendEvent(box, enter)
            moving = QDragMoveEvent(local, Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier)
            QApplication.sendEvent(box, moving)
            assert enter.isAccepted() and moving.isAccepted()
            box.set_scroll_dir(0)
            return mime

        def drop(mime, local):
            event = QDropEvent(QPointF(local), Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier)
            QApplication.sendEvent(box, event)
            assert event.isAccepted()
            settle()

        try:
            initial = order()
            saved = list(sidebar.custom_order)
            locations = {rid: pos(rid) for rid in items}
            headers = {fid: button.pos() for fid, button in sidebar._folder_buttons.items()}
            step = locations["b"] - locations["a"]
            target = point("a")
            sidebar.show_drop_indicator("d", items["d"]._index_in_host())
            mime = hover("d", target)
            assert items["d"].isHidden()
            # 真 Qt 动画的中间帧应向下/右移动，而非只在松手时突变。
            box._animations[items["a"]].setCurrentTime(75)
            assert locations["a"] < pos("a") < locations["a"] + step
            settle()
            assert all(pos(rid) == locations[rid] + step for rid in ("a", "b", "c"))
            assert order() == initial and sidebar.custom_order == saved and not changes
            assert all(button.pos() == headers[fid] for fid, button in sidebar._folder_buttons.items())
            assert all(pos(rid) == locations[rid] for rid in ("huya:x", "huya:y", "douyu:u"))
            # 光标不动而卡片已移动，落点不能因此来回跳。
            for _ in range(3):
                hover("d", target)
                settle()
                assert pos("a") == locations["a"] + step
            drop(mime, target)
            assert order() == ["d", "a", "b", "c", "huya:x", "huya:y", "douyu:u"]
            assert len(changes) == 1 and not items["d"].isHidden()
            assert sidebar.custom_order[:4] == ["d", "a", "b", "c"]
            # drop 后的兜底结算应保持同一顺序。
            sidebar.finish_drag("d", box.mapToGlobal(target))
            assert len(changes) == 1

            sidebar.set_custom_order(initial)
            changes.clear()
            target = point("d", .75)
            mime = hover("a", target)
            settle()
            assert all(pos(rid) == locations[rid] - step for rid in ("b", "c", "d"))
            drop(mime, target)
            assert order()[:4] == ["b", "c", "d", "a"]

            sidebar.set_custom_order(initial)
            changes.clear()
            # 连续反向拖动/立即取消，要中断正在运行的让位动画。
            hover("d", point("a"))
            sidebar.end_drag()
            settle()
            assert all(pos(rid) == locations[rid] and not items[rid].isHidden() for rid in items)
            assert order() == initial and not changes
            hover("d", point("a"))
            settle()
            sidebar.finish_drag("d", box.mapToGlobal(QPoint(-20, -20)))
            settle()
            assert all(pos(rid) == locations[rid] and not items[rid].isHidden() for rid in items)
            assert order() == initial and not changes

            sidebar.toggle_folder(other)
            hover("d", point("a"))
            settle()
            assert items["huya:x"].isHidden() and items["huya:y"].isHidden()
            assert sidebar._folder_buttons[other].pos() == headers[other]
            sidebar.end_drag()
            sidebar.toggle_folder(other)
            settle()

            sidebar.select_sort_item("b", Qt.ControlModifier)
            sidebar.select_sort_item("d", Qt.ControlModifier)
            hover("b", point("a"))
            settle()
            assert items["b"].isHidden() and items["d"].isHidden()
            assert pos("a") == locations["a"] + step * 2
            assert pos("c") == locations["c"] + step
            sidebar.end_drag()
            sidebar.clear_sort_selection()
            settle()

            sidebar.apply_pins(["a", "b"])
            hover("d", point("a"))
            settle()
            assert pos("a") == locations["a"] and pos("b") == locations["b"]
            assert pos("c") == locations["c"] + step
            sidebar.end_drag()
            sidebar.apply_pins([])
            # 搜索隐藏前两张后，抓起第三张不能误用完整列表下标而跳到末尾。
            items["c"].room["uname"] = items["d"].room["uname"] = "keep"
            sidebar.search.setText("keep")
            app.processEvents()
            filtered_pos = pos("d")
            assert items["c"]._index_in_host() == 0
            sidebar.show_drop_indicator("c", items["c"]._index_in_host())
            settle()
            assert pos("d") == filtered_pos
            target = point("d", .75)
            mime = hover("c", target)
            settle()
            drop(mime, target)
            assert order()[:4] == ["a", "b", "d", "c"]
            assert sidebar.folder_for("c") == sidebar.folder_for("d") == folder
            restored = Sidebar(sidebar.rooms(), auto_compact=False)
            restored.set_folders(sidebar.folder_state())
            restored.set_custom_order(sidebar.custom_order)
            assert [r["room_id"] for r in restored.rooms()][:4] == ["a", "b", "d", "c"]
            restored.close()
        finally:
            sidebar.close()
        print(f"PASS: {side}, card={card_mode}, collapsed={collapsed}, smart={smart}")
    print("PASS: animated folder card previews, fixed drop targets, cancellation, group/pin/filter boundaries and persistence")


if __name__ == "__main__":
    main()
