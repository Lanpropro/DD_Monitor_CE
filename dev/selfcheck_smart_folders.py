"""智能文件夹：组合归类、状态迁移、独立排序、未分类和配置迁移。"""
import os
from pathlib import Path
import sys
from unittest.mock import patch

os.environ["DDM_NO_SAVE"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox
from ddm import follow_folders as groups, theme
from ddm.app import MainWindow
from ddm.widgets import Sidebar, SmartFolderDialog


def ids(sidebar, fid):
    return [item.room["room_id"] for item in sidebar.items() if sidebar.folder_for(item.room["room_id"]) == fid]


def main():
    app = QApplication([])
    app.setStyleSheet(theme.qss())
    rooms = [{"room_id": rid, "uname": name, "live": live, "live_known": known}
             for rid, name, live, known in (("1", "Z", False, True), ("2", "A", True, True),
                                           ("huya:a", "B", False, True), ("huya:b", "C", True, True),
                                           ("douyu:x", "D", False, False))]
    legacy = [{"id": "old", "name": "旧分组", "rooms": ["1", "1", "huya:disabled"]}]
    migrated = groups.normalize_folders(legacy, "live")
    assert migrated[0]["type"] == "normal" and migrated[0]["rooms"] == ["1", "huya:disabled"]
    assert migrated[-1]["sort"] == "live" and legacy[0]["rooms"] == ["1", "1", "huya:disabled"]
    assert not groups.matches_rule(rooms[-1], {"status": "offline", "platforms": ["douyu"]})
    assert not groups.matches_rule({"room_id": "3"}, {"status": "offline"})
    sidebar = Sidebar(rooms, auto_compact=False)
    sidebar.resize(248, 1000)
    sidebar.show()
    unclassified = sidebar._folder_buttons[groups.UNCLASSIFIED]
    assert ids(sidebar, groups.UNCLASSIFIED) == [room["room_id"] for room in rooms]
    manual = sidebar.create_folder("手动分组")
    sidebar.move_to_folder(["1", "2"], manual)
    offline = sidebar.create_folder("未开播虎牙", rule={"status": "offline", "platforms": ["huya"]})
    live = sidebar.create_folder("开播", rule={"status": "live", "platforms": []})
    assert ids(sidebar, offline) == ["huya:a"] and ids(sidebar, live) == ["huya:b"]
    assert ids(sidebar, manual) == ["1", "2"] and ids(sidebar, groups.UNCLASSIFIED) == ["douyu:x"]
    # 状态变化会移出未开播规则；未知状态不会被当作下播。
    entries = {item.room["room_id"]: item for item in sidebar.items()}
    entries["huya:a"].set_live(True)
    sidebar.resort()
    assert sidebar.folder_for("huya:a") == live
    assert not sidebar.get_folder(offline)["rooms"], "智能归类不应改写手动房间列表"
    entries["huya:a"].set_live(False)
    sidebar.resort()
    assert sidebar.folder_for("huya:a") == offline
    sidebar.toggle_folder(offline)
    assert entries["huya:a"].isHidden()
    sidebar.search.setText("未开播虎牙")
    assert [item.room["room_id"] for item in sidebar.visible_items()] == ["huya:a"]
    sidebar.search.clear()
    sidebar.toggle_folder(offline)
    sidebar.toggle_folder(live)
    sidebar.select_sort_item("huya:a", Qt.ControlModifier)
    entries["huya:a"].set_live(True)
    sidebar.resort()
    assert entries["huya:a"].isHidden() and not sidebar.selected_sort_ids()
    entries["huya:a"].set_live(False)
    sidebar.resort()
    sidebar.set_select_mode(True)
    entries["huya:a"].check.setChecked(True)
    entries["huya:a"].set_live(True)
    sidebar.resort()
    assert not entries["huya:a"].is_checked(), "自动移入折叠文件夹后不能留下隐藏的批量删除选择"
    sidebar.set_select_mode(False)
    entries["huya:a"].set_live(False)
    sidebar.toggle_folder(live)
    # 从真实文件夹右键菜单触发排序动作，其他文件夹不变。
    before = ids(sidebar, live), ids(sidebar, groups.UNCLASSIFIED)
    folder_menu = sidebar._folder_buttons[manual]._context_menu()
    sort_action = next(action for action in folder_menu.actions() if action.text() == "排序")
    submenu = sort_action.menu()
    next(action for action in submenu.actions() if action.text() == "开播优先").trigger()
    assert ids(sidebar, manual) == ["2", "1"]
    assert (ids(sidebar, live), ids(sidebar, groups.UNCLASSIFIED)) == before
    assert sidebar.get_folder(live)["sort"] == "custom"
    sidebar.reorder_item("2", len(sidebar.items()))
    assert ids(sidebar, manual) == ["1", "2"] and sidebar.get_folder(manual)["sort"] == "custom"
    assert (ids(sidebar, live), ids(sidebar, groups.UNCLASSIFIED)) == before
    sidebar.set_folder_sort(manual, "name")
    assert ids(sidebar, manual) == ["2", "1"]
    sidebar.freeze_current_order(manual)
    entries["2"].set_uname("ZZ")
    sidebar.resort()
    assert ids(sidebar, manual) == ["2", "1"]
    sidebar.set_folder_sort(manual, "imported")
    assert ids(sidebar, manual) == ["1", "2"]
    sidebar.set_folder_sort(manual, "offline")
    assert ids(sidebar, manual) == ["1", "2"]
    sidebar.toggle_pin(entries["2"].room)
    assert ids(sidebar, manual)[0] == "2" and ids(sidebar, live) == before[0]
    # 全部归类后隐藏未分类；删除普通文件夹不删关注，并交由智能规则接收。
    sidebar.move_to_folder(["douyu:x"], manual)
    assert unclassified.isHidden()
    sidebar.delete_folder(manual)
    assert sidebar.folder_for("2") == live and sidebar.folder_for("1") == groups.UNCLASSIFIED
    assert not unclassified.isHidden() and len(sidebar.items()) == 5
    # 多条智能规则匹配时只出现一次；文件夹顺序决定优先级。
    all_platforms = sidebar.create_folder("全部平台", rule={"status": "any", "platforms": []})
    assert unclassified.isHidden()
    while sidebar.folders[0]["id"] != all_platforms:
        sidebar.move_folder(all_platforms, -1)
    assert ids(sidebar, all_platforms) == ["2", "1", "huya:a", "huya:b", "douyu:x"]
    assert len(sidebar.visible_items()) == len(set(item.room["room_id"] for item in sidebar.visible_items()))
    header = sidebar._folder_buttons[all_platforms]
    menu = header._context_menu()
    assert any(action.text() == "编辑智能文件夹…" for action in menu.actions())
    assert not any(action.text() == "重命名文件夹…" for action in menu.actions())
    # 编辑器可组合条件、保存排序，并保留暂时不可用的平台。
    dialog = SmartFolderDialog(sidebar, sidebar.get_folder(offline))
    assert dialog.values()["rule"] == {"status": "offline", "platforms": ["huya"],
                                      "sources": [groups.UNCLASSIFIED], "display": "move"}
    dialog.name_edit.setText("规则修改")
    dialog.status_combo.setCurrentIndex(dialog.status_combo.findData("live"))
    dialog.platform_checks["douyu"].setChecked(True)
    dialog.sort_combo.setCurrentIndex(dialog.sort_combo.findData("name"))
    values = dialog.values()
    with patch("ddm.widgets.SmartFolderDialog", return_value=dialog), patch.object(dialog, "exec", return_value=QDialog.Accepted):
        sidebar.prompt_smart_folder(offline)
    assert sidebar.get_folder(offline)["name"] == "规则修改"
    assert sidebar.get_folder(offline)["rule"] == values["rule"]
    snapshot = sidebar.folder_state()
    dialog.name_edit.clear()
    assert not dialog.findChild(QDialogButtonBox).button(QDialogButtonBox.Ok).isEnabled()
    with patch("ddm.widgets.SmartFolderDialog", return_value=dialog), patch.object(dialog, "exec", return_value=QDialog.Rejected):
        sidebar.prompt_smart_folder(offline)
    assert sidebar.folder_state() == snapshot
    dialog.close()
    restored = Sidebar(rooms)
    restored.set_folders(snapshot)
    assert restored.folder_state() == snapshot
    copied = restored.folder_state()
    next(folder for folder in copied if folder["id"] == offline)["rule"]["platforms"].append("extra")
    assert restored.folder_state() == snapshot
    for widget in (restored, sidebar):
        widget.close()
    # 调整另一文件夹不能覆盖暂时按开播排序的文件夹原有拖动顺序。
    isolated = Sidebar(rooms)
    first, second = isolated.create_folder("一"), isolated.create_folder("二")
    isolated.move_to_folder(["1", "2"], first)
    isolated.move_to_folder(["huya:a", "huya:b"], second)
    isolated.set_folder_sort(second, "live")
    assert ids(isolated, second) == ["huya:b", "huya:a"]
    isolated.reorder_item("1", len(isolated.items()))
    assert ids(isolated, second) == ["huya:b", "huya:a"]
    isolated.set_folder_sort(second, "custom")
    assert ids(isolated, second) == ["huya:a", "huya:b"]
    isolated.close()
    # 平台规则无需等待状态轮询；导入后立即归类，空刷新不能把它移回未分类。
    with patch.object(MainWindow, "refresh_status"), patch.object(MainWindow, "refresh_stats"):
        window = MainWindow([], [], state={"plugins_enabled": [], "follow_folders": snapshot})
        new = {"room_id": "99", "uname": "新关注", "live": True, "live_known": True}
        assert window.sidebar.add_room(new)
        assert window.sidebar.folder_for("99") == all_platforms
        window._on_status_updated({})
        assert window.sidebar.folder_for("99") == all_platforms
        window._on_status_updated({"99": {"live": True, "viewers": "", "title": ""}})
        assert window.sidebar.folder_for("99") == all_platforms
        assert window.sidebar._folder_buttons[groups.UNCLASSIFIED].isHidden()
        saved = window.current_state()
        assert saved["follow_folders"] == snapshot
        window.close()
    # 已有按平台的智能文件夹后继续导入：移入、副本、来源过滤和未知状态。
    with patch.object(MainWindow, "refresh_status"), patch.object(MainWindow, "refresh_stats"):
        window = MainWindow([], [], state={"plugins_enabled": []})
        sidebar = window.sidebar
        live = sidebar.create_folder("仅开播", rule={"status": "live", "sources": []})
        offline = sidebar.create_folder("仅下播", rule={"status": "offline", "sources": []})
        bili = sidebar.create_folder("哔哩哔哩", rule={"platforms": ["bilibili"], "sources": []})
        copies = sidebar.create_folder("平台副本", rule={"platforms": ["bilibili"],
                                                       "sources": [], "display": "copy"})
        manual = sidebar.create_folder("手动目标")
        batch = [{"room_id": "101", "uname": "新关注", "live": True, "live_known": True},
                 {"room_id": "102", "uname": "未知状态", "live": False, "live_known": False},
                 {"room_id": "huya:103", "uname": "其他平台", "live": False, "live_known": False}]
        with patch.object(window, "load_avatars_for"), patch("ddm.online_ui.show_result"):
            window._import_selected_follows(batch)
            assert sidebar.folder_for("101") == bili and sidebar.folder_for("102") == bili
            assert sidebar.folder_for("huya:103") == groups.UNCLASSIFIED
            assert groups.smart_members(sidebar.rooms(), sidebar.folders, sidebar.get_folder(copies),
                                        sidebar._folder_pending) == {"101", "102"}
            window._on_status_updated({})
            assert sidebar.folder_for("101") == bili
            window._on_status_updated({"101": {"live": True, "viewers": "", "title": ""},
                                       "102": {"live": False, "live_known": False,
                                               "viewers": "", "title": ""}})
            assert sidebar.folder_for("101") == live and sidebar.folder_for("102") == bili
            sidebar.get_folder(bili)["rule"]["sources"] = [groups.UNCLASSIFIED]
            window._import_selected_follows([{"room_id": "104", "uname": "指定来源"}], folder_id=manual)
            assert sidebar.folder_for("104") == manual
        assert not ids(sidebar, offline), "未知状态不能被归入未开播规则"
        window.close()
    print("PASS: combined smart rules, status migration, per-folder sorting, unclassified lifecycle, editor and persistence")


if __name__ == "__main__":
    main()
