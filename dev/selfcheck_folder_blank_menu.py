"""关注栏空白处右键：创建两种文件夹，兼容空列表、过滤和两种方向。"""
import os
from pathlib import Path
import sys
from unittest.mock import patch

os.environ["DDM_NO_SAVE"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QPoint
from PySide6.QtGui import QContextMenuEvent
from PySide6.QtWidgets import QApplication, QDialog, QMenu
from ddm import theme
from ddm.widgets import Sidebar, SmartFolderDialog


def main():
    app = QApplication([])
    app.setStyleSheet(theme.qss())
    sidebar = Sidebar([], auto_compact=False)
    sidebar.resize(248, 750)
    sidebar.show()
    app.processEvents()

    def context(target, position):
        shown = []
        class ProbeMenu(QMenu):
            def exec(self, global_pos):
                shown.append(self)
                assert global_pos == target.mapToGlobal(position)
        event = QContextMenuEvent(QContextMenuEvent.Mouse, position, target.mapToGlobal(position))
        with patch("ddm.widgets.QMenu", ProbeMenu):
            QApplication.sendEvent(target, event)
        assert event.isAccepted() and len(shown) == 1
        return shown[0]

    def blank_menu(target, position):
        menu = context(target, position)
        assert [action.text() for action in menu.actions()] == ["新建文件夹…", "新建智能文件夹…"]
        return menu

    # 没有卡片时，提示文字上和侧栏边缘的空白处都可创建。
    blank_menu(sidebar.list_box.empty_hint, sidebar.list_box.empty_hint.rect().center())
    menu = blank_menu(sidebar, QPoint(1, 1))
    with patch("ddm.widgets.QInputDialog.getText", return_value=("赛事", True)):
        menu.actions()[0].trigger()
    ordinary = next(folder for folder in sidebar.folders if folder["name"] == "赛事")
    assert ordinary["type"] == "normal"
    snapshot = sidebar.folder_state()
    with patch("ddm.widgets.QInputDialog.getText", return_value=("", False)):
        menu.actions()[0].trigger()
    assert sidebar.folder_state() == snapshot
    menu = blank_menu(sidebar.list_box, sidebar.list_box.rect().bottomRight() - QPoint(1, 1))
    def choose(dialog):
        dialog.name_edit.setText("未开播虎牙")
        dialog.status_combo.setCurrentIndex(dialog.status_combo.findData("offline"))
        dialog.platform_checks["huya"].setChecked(True)
        return QDialog.Accepted
    with patch.object(SmartFolderDialog, "exec", choose):
        menu.actions()[1].trigger()
    smart = next(folder for folder in sidebar.folders if folder["name"] == "未开播虎牙")
    assert smart["type"] == "smart" and smart["rule"] == {
        "status": "offline", "platforms": ["huya"], "sources": [], "display": "move"}
    sidebar.add_room({"room_id": "1", "uname": "主播", "live": False})
    sidebar.move_to_folder(["1"], ordinary["id"])
    app.processEvents()
    # 卡片和文件夹标题保留各自的右键菜单，不会被空白菜单覆盖。
    item = sidebar.items()[0]
    assert "移入文件夹" in [action.text() for action in context(item, item.rect().center()).actions()]
    header = sidebar._folder_buttons[ordinary["id"]]
    assert "重命名文件夹…" in [action.text() for action in context(header, header.rect().center()).actions()]
    for side, collapsed in (("left", False), ("left", True), ("top", False)):
        sidebar.set_side(side)
        sidebar.set_collapsed(collapsed, animate=False)
        sidebar.resize(248, 900) if side == "left" else sidebar.resize(1200, 225)
        app.processEvents()
        blank_menu(sidebar.list_box, sidebar.list_box.rect().bottomRight() - QPoint(1, 1))
        sidebar.search.setText("不匹配的名称")
        assert not sidebar.visible_items()
        blank_menu(sidebar.list_box.empty_hint, sidebar.list_box.empty_hint.rect().center())
        sidebar.search.clear()
    sidebar.set_collapsed(True, animate=False)
    app.processEvents()
    blank_menu(sidebar._head_strip, sidebar._head_strip.rect().bottomRight() - QPoint(1, 1))
    sidebar.close()
    print("PASS: blank follow-bar context menu, both folder creations, empty/search/orientation and existing menus")


if __name__ == "__main__":
    main()
