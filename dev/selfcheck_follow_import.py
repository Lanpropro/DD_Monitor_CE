"""关注导入：名称搜索、跨搜索勾选、目标文件夹与宿主保存链路。"""
import os
from pathlib import Path
import sys
from unittest.mock import patch

os.environ["DDM_NO_SAVE"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QPushButton
from ddm import bili, theme
from ddm.account_dialog import AccountPlatformDialog
from ddm.app import MainWindow
from ddm.dialogs import FollowImportDialog
from ddm.follow_folders import UNCLASSIFIED
from ddm.login import LoginWindow


ROOMS = [
    {"room_id": "1001", "uname": "测试主播", "live": True, "title": "Apex"},
    {"room_id": "huya:1002", "uname": "Apex Alice", "live": False, "title": "测试主播"},
    {"room_id": "douyu:1003", "uname": "APEX Bob", "live": True, "title": "赛事"},
]


def select_folder(dialog, folder_id):
    next(a for a in dialog.folder_button.menu().actions() if a.data() == folder_id).trigger()
    assert dialog.folder_id == folder_id
    assert sum(a.isChecked() for a in dialog.folder_button.menu().actions()) == 1


def click_button(dialog, text):
    button = next(b for b in dialog.findChildren(QPushButton) if b.text() == text)
    QTest.mouseClick(button, Qt.LeftButton)


def main():
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(theme.qss())
    folders = [{"id": "games", "name": "赛事", "type": "normal"},
               {"id": "smart", "name": "直播中", "type": "smart"},
               {"id": UNCLASSIFIED, "name": "未分类", "type": "unclassified"}]
    dialog = FollowImportDialog(ROOMS, {"1001"}, folders=folders)
    dialog.show()
    app.processEvents()
    assert "已在列表" in dialog.list.item(0).text()
    assert [a.text() for a in dialog.folder_button.menu().actions()] == ["未分类", "赛事"]
    assert dialog.folder_id == ""
    select_folder(dialog, "games")
    assert dialog.folder_button.text() == "赛事"

    dialog.search_edit.setText("测试主播")
    assert [dialog.list.item(i).isHidden() for i in range(3)] == [False, True, True]
    # 实际点击整行；只按名称匹配，不按直播标题匹配。
    app.processEvents()
    rect = dialog.list.visualItemRect(dialog.list.item(0))
    QTest.mouseClick(dialog.list.viewport(), Qt.LeftButton, pos=QPoint(120, rect.center().y()))
    assert dialog.selected() == [ROOMS[0]]
    dialog.search_edit.setText("  apex  ")
    assert [dialog.list.item(i).isHidden() for i in range(3)] == [True, False, False]
    click_button(dialog, "全选")
    assert dialog.selected() == ROOMS
    click_button(dialog, "全不选")
    assert dialog.selected() == [ROOMS[0]], "隐藏的勾选不应被搜索结果的批量操作清除"
    click_button(dialog, "只选直播中")
    assert dialog.selected() == [ROOMS[0], ROOMS[2]]
    assert "当前显示 2 个" in dialog.header.text() and "已勾选 2 个" in dialog.header.text()
    dialog.search_edit.setText("不存在")
    click_button(dialog, "全选")
    assert all(dialog.list.item(i).isHidden() for i in range(3))
    assert dialog.selected() == [ROOMS[0], ROOMS[2]] and "当前显示 0 个" in dialog.header.text()
    avatar = QPixmap(32, 32)
    avatar.fill(Qt.red)
    dialog.set_avatar("douyu:1003", avatar)
    assert not dialog.list.item(2).icon().isNull()
    dialog.search_edit.setFocus()
    QTest.keyClick(dialog.search_edit, Qt.Key_Return)
    assert dialog.isVisible() and dialog.result() == QDialog.Rejected, "搜索回车不能直接导入"
    dialog.search_edit.clear()
    assert all(not dialog.list.item(i).isHidden() for i in range(3))
    click_button(dialog, "全不选")
    assert not dialog.selected()
    select_folder(dialog, "")
    assert dialog.folder_button.text() == "未分类"
    dialog.close()
    empty = FollowImportDialog([], set())
    empty.search_edit.setText("主播")
    empty._check_all(True)
    assert not empty.selected() and len(empty.folder_button.menu().actions()) == 1
    empty.close()
    print("PASS: name-only search, case folding, visible-only bulk actions, retained checks/avatars, Enter and empty list")

    with patch("ddm.app.QTimer.singleShot"):
        window = MainWindow([], [], state={"plugins_enabled": []})
    first = window.sidebar.create_folder("已有分类")
    target = window.sidebar.create_folder("导入分类")
    window.sidebar.create_folder("直播中", rule={"status": "live", "platforms": []})
    window.sidebar.add_room(ROOMS[0])
    window.sidebar.move_to_folder(["1001"], first)
    window.sidebar.toggle_folder(target)
    def confirm(account):
        account._show_rooms(ROOMS)
        page = account.page
        assert [a.text() for a in page.folder_button.menu().actions()] == ["未分类", "已有分类", "导入分类"]
        select_folder(page, target)
        page.search_edit.setText("测试主播")
        page._check_all(True)
        page.search_edit.setText("apex")
        page._check_all(True)
        page.accept()
        assert account.rooms == ROOMS and account.folder_id == target
        return account.result()
    with patch.object(bili, "SESSION_DATA", ""), \
            patch.object(LoginWindow, "start_login"), \
            patch.object(window, "_start_avatar_loader"), \
            patch.object(window, "load_avatars_for"), patch.object(window, "_refresh_meta"):
        with patch.object(AccountPlatformDialog, "exec", confirm):
            window.open_import_follows()
            window.open_import_follows()
        assert len(window.sidebar.rooms()) == 3
        assert window.sidebar.folder_for("1001") == first, "重复导入不更改已有归属"
        assert window.sidebar.folder_for("huya:1002") == target
        assert window.sidebar.folder_for("douyu:1003") == target
        assert window.sidebar.get_folder(target)["collapsed"]
        assert window._save_timer.isActive()
        saved = next(f for f in window.current_state()["follow_folders"] if f["id"] == target)
        assert set(saved["rooms"]) == {"huya:1002", "douyu:1003"}
        new = dict(ROOMS[0], room_id="1004")
        window._import_selected_follows([new])
        assert window.sidebar.folder_for("1004") == UNCLASSIFIED
        gone = window.sidebar.create_folder("已删除")
        window.sidebar.delete_folder(gone)
        window._import_selected_follows([dict(new, room_id="1005")], folder_id=gone)
        assert window.sidebar.folder_for("1005") == UNCLASSIFIED
        with patch.object(AccountPlatformDialog, "exec", return_value=QDialog.Rejected), \
                patch.object(window, "_import_selected_follows") as imported:
            window.open_import_follows()
            imported.assert_not_called()
    window.close()
    print("PASS: shared account page passes target, cross-platform import, dedup, collapse, persistence, fallback and cancel")


if __name__ == "__main__":
    main()
