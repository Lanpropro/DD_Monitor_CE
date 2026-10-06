"""来源文件夹、移入/副本显示、状态回退及单份关注数据。"""
import os
from pathlib import Path
import sys

os.environ['DDM_NO_SAVE'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import Qt
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
    assert dialog.source_combo.currentData() == apex
    assert dialog.display_combo.currentData() == 'copy'
    assert dialog.values()['rule'] == sidebar.get_folder(smart)['rule']
    restored = Sidebar(rooms)
    restored.set_folders(sidebar.folder_state())
    assert restored.get_folder(smart)['rule'] == rule | {'display': 'copy'}
    sidebar.delete_folder(smart)
    assert sidebar.folder_for('1') == apex and len(sidebar.rooms()) == 3
    assert not sidebar._smart_cards
    # 来源不存在时不能误扩展成全部；旧规则仍不抢手动分类。
    folders = groups.normalize_folders([
        {'id': apex, 'name': 'Apex', 'rooms': ['1']},
        {'id': 'missing', 'name': '来源已删', 'type': 'smart', 'rule': rule | {'sources': ['deleted']}},
        {'id': 'legacy', 'name': '旧规则', 'type': 'smart', 'rule': {'status': 'live'}}])
    assert groups.assign_folders(rooms, folders)['1'] == apex
    for widget in (dialog, sidebar, restored):
        widget.close()
    print('PASS: scoped smart folders, both display modes, return to source, shared actions and persistence')


if __name__ == '__main__':
    main()
