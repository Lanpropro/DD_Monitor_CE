"""文件夹标题拖放：两种方向、自动折叠、点击保护、搜索及持久化。"""
import os
from pathlib import Path
import sys
from unittest.mock import patch

os.environ["DDM_NO_SAVE"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, Qt
from PySide6.QtGui import QDragEnterEvent, QDragMoveEvent, QDropEvent, QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from ddm import theme
from ddm.follow_folders import UNCLASSIFIED
from ddm.widgets import FOLDER_MIME, NAV_MIME, Sidebar


def main():
    app = QApplication([])
    app.setStyleSheet(theme.qss())
    rooms = [{"room_id": rid, "uname": rid, "live": False}
             for rid in ("1", "2", "huya:a", "3")]
    sidebar = Sidebar(rooms, auto_compact=False)
    sidebar.resize(248, 900)
    sidebar.show()
    first = sidebar.create_folder("分类甲")
    second = sidebar.create_folder("分类乙")
    sidebar.move_to_folder(["1"], first)
    sidebar.move_to_folder(["2"], second)
    smart = sidebar.create_folder("分类智能", rule={"status": "any", "platforms": ["huya"]})
    app.processEvents()
    changes = []
    sidebar.foldersChanged.connect(lambda: changes.append(sidebar.folder_state()))

    def order():
        return [folder["id"] for folder in sidebar.folders]

    def headers_only():
        assert all(folder["collapsed"] for folder in sidebar.folders)
        assert not sidebar.visible_items()
        assert all(item.isHidden() for item in sidebar.items())

    def simulate_drag(fid, target, point, *, cancel=False):
        source = sidebar._folder_buttons[fid]
        press = source.rect().center()
        QTest.mousePress(source, Qt.LeftButton, pos=press)
        endpoint = press + QPoint(QApplication.startDragDistance() + 3, 0)
        move = QMouseEvent(QEvent.MouseMove, QPointF(endpoint),
                           QPointF(source.mapToGlobal(endpoint)), Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
        before = order()
        previous = {folder["id"]: folder["collapsed"] for folder in sidebar.folders}

        def execute(actions):
            assert actions == Qt.MoveAction
            headers_only()
            mime = drag.return_value.setMimeData.call_args.args[0]
            assert bytes(mime.data(FOLDER_MIME)).decode() == fid
            assert not mime.hasFormat(NAV_MIME), "文件夹拖动不能变成卡片归类"
            if cancel:
                return Qt.IgnoreAction
            # 让 Qt 送真实拖入、移动和落下事件，验证按钮与空白区的接线。
            enter = QDragEnterEvent(point(), Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier)
            QApplication.sendEvent(target, enter)
            assert enter.isAccepted()
            moving = QDragMoveEvent(point(), Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier)
            QApplication.sendEvent(target, moving)
            assert moving.isAccepted() and not sidebar.list_box.folder_drop_indicator.isHidden()
            drop = QDropEvent(QPointF(point()), Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier)
            QApplication.sendEvent(target, drop)
            assert drop.isAccepted()
            return Qt.MoveAction

        with patch("ddm.widgets.QDrag") as drag, patch.object(sidebar, "begin_drag_scroll") as begin, \
                patch.object(sidebar, "end_drag_scroll") as end:
            drag.return_value.exec.side_effect = execute
            QApplication.sendEvent(source, move)
            drag.return_value.exec.assert_called_once()
            begin.assert_called_once()
            end.assert_called_once()
        QTest.mouseRelease(source, Qt.LeftButton, pos=source.rect().center())
        assert {folder["id"]: folder["collapsed"] for folder in sidebar.folders} == previous
        assert not sidebar._folders_folded_by_drag and not sidebar._folder_drag_previous
        assert not sidebar.list_box.folder_drop_indicator.isVisible()
        assert not sidebar.list_box._scroll_timer.isActive()
        assert not source.isDown(), "拖动结束不能留下按下状态或触发点击展开"
        if cancel:
            assert order() == before

    # 低于拖动阈值的操作仍是点击，不会抢走展开/收起。
    first_header = sidebar._folder_buttons[first]
    with patch("ddm.widgets.QDrag") as drag:
        QTest.mouseClick(first_header, Qt.LeftButton)
        assert sidebar.get_folder(first)["collapsed"]
        QTest.mouseClick(first_header, Qt.LeftButton)
        assert not sidebar.get_folder(first)["collapsed"]
        press = first_header.rect().center()
        QTest.mousePress(first_header, Qt.LeftButton, pos=press)
        endpoint = press + QPoint(1, 0)
        move = QMouseEvent(QEvent.MouseMove, QPointF(endpoint),
                           QPointF(first_header.mapToGlobal(endpoint)), Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
        QApplication.sendEvent(first_header, move)
        assert not any(folder["collapsed"] for folder in sidebar.folders)
        QTest.mouseRelease(first_header, Qt.LeftButton, pos=endpoint)
        assert sidebar.get_folder(first)["collapsed"]
        QTest.mouseClick(first_header, Qt.LeftButton)
        drag.assert_not_called()
    # 横屏：普通文件夹可以放到智能文件夹后面。
    smart_header = sidebar._folder_buttons[smart]
    QTest.mouseClick(smart_header, Qt.LeftButton)
    simulate_drag(first, smart_header, lambda: QPoint(10, smart_header.height() - 2))
    assert not sidebar.get_folder(first)["collapsed"] and sidebar.get_folder(smart)["collapsed"]
    assert order() == [second, smart, first, UNCLASSIFIED]
    assert sidebar.folder_for("1") == first and sidebar.folder_for("2") == second
    assert sidebar.folder_for("huya:a") == smart
    # 未分类也可拖到最前，结束后保持原展开状态，点击仍可正常收起/展开。
    target = sidebar._folder_buttons[second]
    simulate_drag(UNCLASSIFIED, target, lambda: QPoint(10, 1))
    assert order()[0] == UNCLASSIFIED
    QTest.mouseClick(sidebar._folder_buttons[UNCLASSIFIED], Qt.LeftButton)
    assert "3" not in [item.room["room_id"] for item in sidebar.visible_items()]
    QTest.mouseClick(sidebar._folder_buttons[UNCLASSIFIED], Qt.LeftButton)
    assert "3" in [item.room["room_id"] for item in sidebar.visible_items()]
    # 搜索状态下临时收起所有文件夹，放下后恢复搜索结果和原折叠状态。
    sidebar.search.setText("分类")
    simulate_drag(second, smart_header, lambda: QPoint(10, smart_header.height() - 2))
    assert all(not header.isHidden() for header in sidebar._folder_buttons.values())
    assert len(sidebar.visible_items()) == 4
    sidebar.search.clear()
    # 竖屏：窄标题条以左右坐标排序，并可放到列表的空白区末尾。
    sidebar.set_side("top")
    sidebar.resize(1200, 225)
    app.processEvents()
    simulate_drag(first, sidebar.list_box,
                  lambda: QPoint(sidebar.list_box.width() - 2, 10))
    assert order()[-1] == first
    # 智能文件夹同样可以向前拖；取消拖动也恢复原展开状态，不改变顺序。
    unclassified_header = sidebar._folder_buttons[UNCLASSIFIED]
    simulate_drag(smart, unclassified_header, lambda: QPoint(1, 10))
    assert order()[0] == smart
    QTest.mouseClick(sidebar._folder_buttons[first], Qt.LeftButton)
    simulate_drag(first, sidebar.list_box, lambda: QPoint(1, 10), cancel=True)
    QTest.mouseClick(sidebar._folder_buttons[first], Qt.LeftButton)
    simulate_drag(first, sidebar.list_box, lambda: QPoint(1, 10), cancel=True)
    before = order()
    sidebar.finish_folder_drag(first, sidebar.list_box.mapToGlobal(QPoint(-30, -30)))
    assert order() == before
    # 顺序与折叠状态均可恢复，未分类为空时仍不显示。
    snapshot = sidebar.folder_state()
    restored = Sidebar(rooms)
    restored.set_folders(snapshot)
    assert restored.folder_state() == snapshot
    assert {item.room["room_id"] for item in restored.visible_items()} == {
        item.room["room_id"] for item in sidebar.visible_items()}
    sidebar.move_to_folder(["3"], first)
    assert sidebar._folder_buttons[UNCLASSIFIED].isHidden()
    assert UNCLASSIFIED in order(), "隐藏的未分类仍需保留其保存的位置"
    assert changes
    restored.close()
    sidebar.close()
    print("PASS: folder title drag, both orientations, temporary collapse/restore/cancel, search, membership and persistence")


if __name__ == "__main__":
    main()
