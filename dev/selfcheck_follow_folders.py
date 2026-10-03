"""关注文件夹：跨平台归类、折叠搜索、菜单、布局和持久化。"""
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

os.environ["DDM_NO_SAVE"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QMimeData, QPointF, Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QApplication
from ddm import config, theme
from ddm.widgets import NAV_MIME, Sidebar


def main():
    app = QApplication([])
    app.setStyleSheet(theme.qss())
    rooms = [{"room_id": key, "uname": name} for key, name in
             (("1", "主播甲"), ("huya:a", "主播乙"), ("2", "主播丙"))]
    sidebar = Sidebar(rooms, auto_compact=False)
    sidebar.resize(248, 750)
    sidebar.show()
    changes = []
    sidebar.foldersChanged.connect(lambda: changes.append(True))
    folder_id = sidebar.create_folder("赛事")
    assert folder_id
    assert not sidebar.create_folder("  ")
    assert not sidebar.create_folder("赛事")
    entries = {item.room["room_id"]: item for item in sidebar.items()}
    sidebar.select_sort_item("1", Qt.ControlModifier)
    sidebar.select_sort_item("huya:a", Qt.ControlModifier)
    menu = entries["1"]._context_menu()
    folder_menu = next(action.menu() for action in menu.actions() if action.text() == "移入文件夹")
    next(action for action in folder_menu.actions() if action.text() == "赛事").trigger()
    assert sidebar.folder_for("1") == sidebar.folder_for("huya:a") == folder_id
    assert set(sidebar.rooms()[i]["room_id"] for i in range(3)) == {"1", "2", "huya:a"}
    app.processEvents()
    header = sidebar._folder_buttons[folder_id]
    assert header.toolButtonStyle() == Qt.ToolButtonTextBesideIcon
    assert "赛事" in header.text()
    header.click()
    assert [item.room["room_id"] for item in sidebar.visible_items()] == ["2"]
    assert entries["1"].isHidden() and entries["huya:a"].isHidden()
    sidebar.set_select_mode(True)
    assert not sidebar.selected_sort_ids(), "折叠后的隐藏选择不能参与批量操作"
    sidebar.set_select_mode(False)
    sidebar.search.setText("主播乙")
    assert [item.room["room_id"] for item in sidebar.visible_items()] == ["huya:a"]
    sidebar.search.clear()
    assert entries["huya:a"].isHidden(), "清空搜索应恢复文件夹折叠"
    sidebar.search.setText("赛事")
    assert {item.room["room_id"] for item in sidebar.visible_items()} == {"1", "huya:a"}
    sidebar.search.clear()
    with patch("ddm.widgets.QInputDialog.getText", return_value=("比赛直播", True)):
        next(action for action in header._context_menu().actions()
             if action.text() == "重命名文件夹…").trigger()
    assert sidebar.folders[0]["name"] == "比赛直播"
    header.click()
    sidebar.set_select_mode(True)
    entries["1"].check.setChecked(True)
    header.click()
    assert not entries["1"].is_checked(), "折叠后应清除隐藏卡片的批量选择"
    sidebar.set_select_mode(False)
    snapshot = sidebar.folder_state()
    snapshot[0]["name"] = "外部副本"
    assert sidebar.folders[0]["name"] == "比赛直播"
    snapshot = sidebar.folder_state()
    restored = Sidebar(rooms)
    restored.set_folders(snapshot)
    assert restored.folder_state() == snapshot
    assert restored.folder_for("huya:a") == folder_id
    restored.close()
    header.click()
    # Qt 实际拖放事件与松手后的补结算都能将外层卡片归入文件夹。
    mime = QMimeData()
    mime.setData(NAV_MIME, b"2")
    enter = QDragEnterEvent(header.rect().center(), Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(header, enter)
    drop = QDropEvent(QPointF(header.rect().center()), Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(header, drop)
    assert drop.isAccepted() and sidebar.folder_for("2") == folder_id
    sidebar.move_to_folder(["2"], "")
    sidebar.finish_drag("2", header.mapToGlobal(header.rect().center()))
    assert sidebar.folder_for("2") == folder_id
    sidebar.move_to_folder(["2"], "")
    landscape_thickness = header.height()
    for side, collapsed in (("left", False), ("left", True), ("top", False), ("left", False)):
        sidebar.set_side(side)
        sidebar.set_collapsed(collapsed, animate=False)
        app.processEvents()
        rects = [item.geometry() for item in sidebar.visible_items()] + [header.geometry()]
        assert all(not a.intersects(b) for i, a in enumerate(rects) for b in rects[i + 1:]), (side, rects)
        if side == "top":
            assert header.width() == landscape_thickness, "竖屏文件夹应为横屏标题条旋转后的窄条"
            assert header.height() == entries["1"].height()
            header.click()
            assert entries["1"].isHidden() and header.isVisible()
            header.click()
            assert not entries["1"].isHidden()
            sidebar.finish_drag("2", header.mapToGlobal(header.rect().center()))
            assert sidebar.folder_for("2") == folder_id, "窄竖条仍应接收卡片拖入"
            sidebar.move_to_folder(["2"], "")
    sidebar.remove_room(rooms[0])
    assert not sidebar.folder_for("1")
    sidebar.delete_folder(folder_id)
    assert header.isHidden() and folder_id not in sidebar._folder_buttons
    assert not sidebar.folder_for("huya:a")
    assert entries["huya:a"] in sidebar.visible_items()
    assert len(sidebar.rooms()) == 2, "删除文件夹不能删除关注"
    assert changes
    sidebar.close()

    # 平台停用/重新启用不丢文件夹归属；旧配置无文件夹时保持原列表。
    state = {"version": 1, "rooms": ["1", "huya:a"], "wall": [],
             "follow_folders": snapshot, "plugins_enabled": []}
    suspended = config.sync_platform_rooms(state, set())
    assert suspended["follow_folders"] == snapshot
    resumed = config.sync_platform_rooms(suspended, {"huya"})
    assert resumed["follow_folders"] == snapshot and "huya:a" in resumed["rooms"]
    from ddm.app import MainWindow
    followed, wall = config.build_rooms(state)
    window = MainWindow(followed, wall, state=state)
    saved = window.current_state()
    assert saved["follow_folders"] == snapshot
    assert window.sidebar.folder_for("huya:a") == folder_id
    with tempfile.TemporaryDirectory(prefix="ddm_folder_config_") as root:
        with patch.object(config, "CONFIG_PATH", str(Path(root) / "config.json")), \
                patch.dict(os.environ, {"DDM_NO_SAVE": ""}):
            config.save(saved)
            assert config.load()["follow_folders"] == snapshot
    window.close()
    print("PASS: follow folders, mixed platforms, menus, collapse/search, geometry and persistence")


if __name__ == "__main__":
    main()
