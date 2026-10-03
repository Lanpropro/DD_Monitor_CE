"""添加直播间：文件夹选择、输入验证、异步归类与默认未分类。"""
import os
from pathlib import Path
import sys
from unittest.mock import patch

os.environ["DDM_NO_SAVE"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog
from ddm import theme
from ddm.app import MainWindow
from ddm.dialogs import AddRoomDialog
from ddm.follow_folders import UNCLASSIFIED


class InfoFixture(QObject):
    resolved = Signal(dict)
    failed = Signal(str)
    finished = Signal()
    pending = []

    def __init__(self, room_id, parent=None, *, platform=None):
        super().__init__(parent)
        self.room_id = room_id

    def start(self):
        self.pending.append(self)

    def complete(self):
        self.resolved.emit({"room_id": self.room_id, "uname": self.room_id, "live": False})
        self.finished.emit()


def select(dialog, folder_id):
    next(action for action in dialog.folder_button.menu().actions() if action.data() == folder_id).trigger()
    assert dialog.folder_id == folder_id
    assert sum(action.isChecked() for action in dialog.folder_button.menu().actions()) == 1


def main():
    app = QApplication([])
    app.setStyleSheet(theme.qss())
    folders = [{"id": "a", "name": "赛事", "type": "normal"},
               {"id": "smart", "name": "未开播", "type": "smart"},
               {"id": UNCLASSIFIED, "name": "未分类", "type": "unclassified"}]
    dialog = AddRoomDialog(folders=folders)
    dialog.show()
    app.processEvents()
    assert [action.text() for action in dialog.folder_button.menu().actions()] == ["未分类", "赛事"]
    assert dialog.folder_id == "" and dialog.folder_button.text() == "未分类"
    select(dialog, "a")
    assert dialog.folder_button.text() == "赛事"
    dialog.edit.setText("无效输入")
    dialog.accept()
    assert not dialog.room_id and dialog.result() == QDialog.Rejected and dialog.isVisible()
    assert dialog.folder_id == "a"
    dialog.edit.setText("https://live.bilibili.com/1001?from=2")
    QTest.keyClick(dialog.edit, Qt.Key_Return)
    assert dialog.result() == QDialog.Accepted and dialog.room_id == "1001" and dialog.folder_id == "a"
    dialog.close()
    empty = AddRoomDialog()
    assert len(empty.folder_button.menu().actions()) == 1
    empty.close()
    platform = AddRoomDialog(folders=folders, room_id_resolver=lambda text: "huya:a")
    select(platform, "a")
    platform.edit.setText("https://www.huya.com/a")
    platform.accept()
    assert platform.room_id == "huya:a" and platform.folder_id == "a"
    platform.close()

    with patch.object(MainWindow, "refresh_status"), patch.object(MainWindow, "refresh_stats"):
        window = MainWindow([], [], state={"plugins_enabled": []})
    first = window.sidebar.create_folder("赛事")
    second = window.sidebar.create_folder("娱乐")
    window.sidebar.create_folder("智能", rule={"status": "any", "platforms": []})
    window.sidebar.toggle_folder(first)
    with patch("ddm.app.InfoResolver", InfoFixture), \
            patch.object(window.plugins, "platform_for", side_effect=lambda rid: object() if ":" in rid else None), \
            patch.object(window, "load_avatars_for"), patch.object(window, "add_to_wall"), \
            patch.object(window, "_normalize_room_input", side_effect=lambda value: value):
        # 实际添加窗口传递选中的文件夹；两个异步请求反向完成仍进入各自目标。
        def choose(dialog):
            assert [action.text() for action in dialog.folder_button.menu().actions()] == ["未分类", "赛事", "娱乐"]
            select(dialog, first)
            dialog.edit.setText("101")
            dialog.accept()
            return dialog.result()
        with patch.object(AddRoomDialog, "exec", choose):
            window.open_add_room()
        window._add_room_id("huya:a", folder_id=second)
        InfoFixture.pending[1].complete()
        InfoFixture.pending[0].complete()
        assert window.sidebar.folder_for("101") == first
        assert window.sidebar.folder_for("huya:a") == second
        assert window.sidebar.get_folder(first)["collapsed"], "添加到收起的文件夹不应更改其展开状态"
        assert "101" not in window.sidebar._folder_pending
        # 不选择文件夹、或查询期间目标被删除时，保留默认未分类。
        window._add_room_id("102")
        InfoFixture.pending[-1].complete()
        assert window.sidebar.folder_for("102") == UNCLASSIFIED
        gone = window.sidebar.create_folder("临时")
        window._add_room_id("103", folder_id=gone)
        window.sidebar.delete_folder(gone)
        InfoFixture.pending[-1].complete()
        assert window.sidebar.folder_for("103") == UNCLASSIFIED
        # 重复添加不重复查询，也不改变已有卡片归属；失败/取消不添加卡片。
        count = len(InfoFixture.pending)
        window._add_room_id("101", folder_id=second)
        assert len(InfoFixture.pending) == count and window.sidebar.folder_for("101") == first
        window._add_room_id("104", folder_id=first)
        InfoFixture.pending[-1].failed.emit("104")
        InfoFixture.pending[-1].finished.emit()
        assert "104" not in {room["room_id"] for room in window.sidebar.rooms()}
        with patch.object(AddRoomDialog, "exec", return_value=QDialog.Rejected):
            window.open_add_room()
        assert len(InfoFixture.pending) == count + 1
        saved = window.current_state()
        assert "101" in next(folder["rooms"] for folder in saved["follow_folders"] if folder["id"] == first)
        assert "huya:a" in next(folder["rooms"] for folder in saved["follow_folders"] if folder["id"] == second)
    window.close()
    print("PASS: add-room folder button, validation, both platform paths, concurrent results, fallback and persistence")


if __name__ == "__main__":
    main()
