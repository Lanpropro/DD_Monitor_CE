"""来源文件夹、移入/副本显示、状态回退及单份关注数据。"""
import os
from pathlib import Path
import sys
from unittest.mock import patch

os.environ['DDM_NO_SAVE'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from ddm import follow_folders as groups
from ddm.widgets import Sidebar, SmartFolderCard, SmartFolderDialog


def main():
    app = QApplication([])
    rooms = [{'room_id': str(i), 'uname': name, 'live': live}
             for i, name, live in ((1, 'Apex A', True), (2, 'Apex B', False), (3, '音乐', True))]
    sidebar = Sidebar(rooms, auto_compact=False)
    sidebar.resize(248, 1000)
    sidebar.show()
    apex = sidebar.create_folder('Apex')
    music = sidebar.create_folder('音乐')
    sidebar.move_to_folder(['1', '2'], apex)
    sidebar.move_to_folder(['3'], music)
    rule = {'status': 'live', 'platforms': [], 'sources': [apex], 'display': 'move'}
    smart = sidebar.create_folder('Apex 开播', rule=rule)
    assert sidebar.folder_for('1') == smart and sidebar.folder_for('3') == music
    assert sidebar.get_folder(apex)['rooms'] == ['1', '2']
    original = next(item for item in sidebar.items() if item.room['room_id'] == '1')
    original.set_live(False)
    sidebar.resort()
    assert sidebar.folder_for('1') == apex
    original.set_live(True)
    sidebar.get_folder(smart)['rule']['display'] = 'copy'
    sidebar.resort()
    assert sidebar.folder_for('1') == apex
    entries = sidebar.folder_entries()
    copies = [item for item in entries if isinstance(item, SmartFolderCard)]
    assert len(copies) == 1 and copies[0].original is original
    assert len(sidebar.rooms()) == 3 and len(sidebar.items()) == 3
    app.processEvents()
    assert not copies[0].grab().isNull()
    selected = []
    sidebar.roomSelected.connect(selected.append)
    QTest.mouseClick(copies[0], Qt.LeftButton)
    assert selected == [rooms[0]]
    sidebar.toggle_folder(apex)
    assert original.isHidden() and not copies[0].isHidden()
    sidebar.toggle_folder(smart)
    assert copies[0].isHidden()
    sidebar.toggle_folder(smart)
    sidebar.search.setText('Apex 开播')
    assert not copies[0].isHidden()
    sidebar.search.clear()
    dialog = SmartFolderDialog(sidebar, sidebar.get_folder(smart))
    assert dialog.source_checks[apex].isChecked() and not dialog.all_sources.isChecked()
    assert dialog.display_combo.currentData() == 'copy'
    assert dialog.values()['rule'] == sidebar.get_folder(smart)['rule']
    restored = Sidebar(rooms)
    restored.set_folders(sidebar.folder_state())
    assert restored.get_folder(smart)['rule'] == rule | {'display': 'copy'}
    # 多选菜单保持打开，多个来源按并集筛选，并保留各自原归属。
    dialog.show()
    app.processEvents()
    dialog.source_menu.popup(dialog.source_button.mapToGlobal(QPoint(0, dialog.source_button.height())))
    app.processEvents()
    music_check = dialog.source_checks[music]
    QTest.mouseClick(music_check, Qt.LeftButton, pos=QPoint(8, music_check.height() // 2))
    assert dialog.source_menu.isVisible(), 'checkbox selection must not close the multi-select menu'
    assert set(dialog.values()['rule']['sources']) == {apex, music}
    assert '2' in dialog.source_button.text()
    dialog.source_menu.hide()
    multi_rule = dialog.values()['rule']
    sidebar.get_folder(smart)['rule'] = multi_rule
    sidebar.resort()
    assert {card.room['room_id'] for card in sidebar.folder_entries() if isinstance(card, SmartFolderCard)} == {'1', '3'}
    assert sidebar.folder_for('1') == apex and sidebar.folder_for('3') == music
    multi_restored = Sidebar(rooms)
    multi_restored.set_folders(sidebar.folder_state())
    assert multi_restored.get_folder(smart)['rule'] == multi_rule
    edited = SmartFolderDialog(multi_restored, multi_restored.get_folder(smart))
    assert set(edited.values()['rule']['sources']) == {apex, music}
    multi_folders = groups.normalize_folders(sidebar.folder_state())
    multi_smart = next(folder for folder in multi_folders if folder['id'] == smart)
    multi_smart['rule']['display'] = 'move'
    assert groups.assign_folders(rooms, multi_folders)['1'] == smart
    assert groups.assign_folders(rooms, multi_folders)['3'] == smart
    offline_music = [dict(room, live=False) if room['room_id'] == '3' else room for room in rooms]
    assert groups.assign_folders(offline_music, multi_folders)['3'] == music
    dialog.all_sources.setChecked(True)
    assert dialog.values()['rule']['sources'] == [] and not any(check.isChecked() for check in dialog.source_checks.values())
    dialog.source_checks[apex].setChecked(True)
    dialog.source_checks[groups.UNCLASSIFIED].setChecked(True)
    extra_rooms = rooms + [{'room_id': '4', 'uname': '未分类主播', 'live': True}]
    multi_smart['rule'] = dialog.values()['rule']
    assert groups.smart_members(extra_rooms, multi_folders, multi_smart) == {'1', '4'}
    assert groups.smart_members(extra_rooms, multi_folders, multi_smart, pending=['4']) == {'1'}
    multi_smart['rule']['platforms'] = ['huya']
    platform_rooms = [dict(room, platform='huya') if room['room_id'] == '4' else room for room in extra_rooms]
    assert groups.smart_members(platform_rooms, multi_folders, multi_smart) == {'4'}, \
        'platform and status filters must still apply across all selected sources'
    dialog.source_checks[apex].setChecked(False)
    dialog.source_checks[groups.UNCLASSIFIED].setChecked(False)
    assert dialog.all_sources.isChecked() and dialog.values()['rule']['sources'] == []
    second = sidebar.create_folder('另一份筛选', rule=rule | {'display': 'copy'})
    app.processEvents()
    for card in sidebar._smart_cards.values():
        card._preview_timer.stop()
    with patch.object(original, 'grab', wraps=original.grab) as paint:
        original.update()
        QTest.qWait(80)
        count = paint.call_count
        QTest.qWait(80)
        assert paint.call_count <= count + 2, 'multiple copies must not trigger continuous reciprocal repaints'
    sidebar.delete_folder(smart)
    sidebar.delete_folder(second)
    assert sidebar.folder_for('1') == apex and len(sidebar.rooms()) == 3
    assert not sidebar._smart_cards
    # 来源不存在时不能误扩展成全部；旧规则仍不抢手动分类。
    folders = groups.normalize_folders([
        {'id': apex, 'name': 'Apex', 'rooms': ['1']},
        {'id': 'missing', 'name': '来源已删', 'type': 'smart', 'rule': rule | {'sources': ['deleted']}},
        {'id': 'legacy', 'name': '旧规则', 'type': 'smart', 'rule': {'status': 'live'}}])
    assert groups.assign_folders(rooms, folders)['1'] == apex
    missing = SmartFolderDialog(sidebar, {'name': '已删除来源', 'rule': rule | {'sources': [apex, 'deleted']}})
    assert set(missing.values()['rule']['sources']) == {apex, 'deleted'}
    missing.source_checks['deleted'].setChecked(False)
    assert missing.values()['rule']['sources'] == [apex]
    fresh = SmartFolderDialog(sidebar)
    assert fresh.all_sources.isChecked() and fresh.values()['rule']['sources'] == []
    for widget in (dialog, sidebar, restored, multi_restored, edited, missing, fresh):
        widget.close()
    print('PASS: multi-source selection, union matching, source return, both display modes and persistence')


if __name__ == '__main__':
    main()
