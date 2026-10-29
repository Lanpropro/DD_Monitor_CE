"""离线回归：两处拼音搜索、原筛选语义、勾选保留与缓存。"""
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch

os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from ddm import theme
from ddm.app import MainWindow
from ddm.dialogs import FollowImportDialog
from ddm.search import _pinyin_keys, matches_text


def main():
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(theme.qss())
    for text, query in [('小明', 'xiaoming'), ('小明', 'XM'), ('小明', 'xiao ming'),
                        ('重庆主播', 'chongqing'), ('重庆主播', 'cqzb'),
                        ('莉蔻Liko', 'likouliko'), ('莉蔻Liko', 'lkliko'),
                        ('呂小明', 'lvxiaoming'), ('呂小明', 'lxm'),
                        ('大东彦', 'ddy'), ('大东彦', 'DADONGYAN'),
                        ('大橙橙橙子', 'dcccz'), ('大橙橙橙子', 'dcz'),
                        ('Alice', 'ALICE'), ('小明', '小明')]:
        assert matches_text(text, query), (text, query)
    assert not matches_text('小明', 'xiaohong')
    assert not matches_text('大东彦', 'ydd'), 'Initials must retain their order'
    assert not matches_text('主播111号', 'zb1h'), 'Do not collapse digits in abbreviations'
    assert not matches_text('Alice', 'al ice'), 'Keep the original English substring rule'
    rooms = [dict(room_id='9101', uname='小明', title='深夜音乐', live=True),
             dict(room_id='9102', uname='重庆主播', title='小明', live=False),
             dict(room_id='9103', uname='Alice', title='Morning Coffee', live=True),
             dict(room_id='9104', uname='大橙橙橙子', title='', live=True),
             dict(room_id='9105', uname='大东彦', title='', live=True)]
    with patch('ddm.app.QTimer.singleShot'):
        window = MainWindow([], [], state={'plugins_enabled': []})
    dialog = FollowImportDialog(rooms, {'9101'})
    try:
        for room in rooms:
            window.sidebar.add_room(room)
        folder = window.sidebar.create_folder('音乐区')
        window.sidebar.move_to_folder(['9101'], folder)
        def sidebar(query):
            window.sidebar.search.setText(query)
            return {item.room['room_id'] for item in window.sidebar.visible_items()}
        def imported(query):
            dialog.search_edit.setText(query)
            return {dialog.list.item(i).data(Qt.UserRole)['room_id'] for i in range(dialog.list.count())
                    if not dialog.list.item(i).isHidden()}
        for query, ids in [('xiaoming', {'9101'}), ('xm', {'9101'}),
                           ('xiaoming 9101', {'9101'}), ('yinyuequ', {'9101'}),
                           ('yyq', {'9101'}), ('ALICE', {'9103'}),
                           ('Morning', set()), ('shenyeyinyue', set()),
                           ('深夜音乐', set()), ('9102', {'9102'}),
                           ('dcz', {'9104'}), ('dcccz', {'9104'}), ('ddy', {'9105'})]:
            assert sidebar(query) == ids, query
        for query, ids in [('xiaoming', {'9101'}), ('XM', {'9101'}),
                           ('xiao ming', {'9101'}), ('chongqing', {'9102'}),
                           ('cqzb', {'9102'}), ('Alice', {'9103'}),
                           ('dcz', {'9104'}), ('dcccz', {'9104'}), ('DDY', {'9105'}),
                           ('shenyeyinyue', set()), ('9101', set())]:
            assert imported(query) == ids, query
        imported('cqzb')
        dialog._check_all(True)
        assert {r['room_id'] for r in dialog.selected()} == {'9101', '9102'}
        pixmap = QPixmap(32, 32)
        pixmap.fill(QColor('red'))
        dialog.set_avatar('9102', pixmap)
        imported('XM')
        assert not dialog.list.item(1).icon().isNull()
        imported('')
        assert {r['room_id'] for r in dialog.selected()} == {'9101', '9102'}
        dialog.rooms[0]['uname'] = '小红'
        # Resolve the current row data, as asynchronous account updates do.
        room = dialog.list.item(0).data(Qt.UserRole)
        room['uname'] = '小红'
        dialog.list.item(0).setData(Qt.UserRole, room)
        assert imported('xiaohong') == {'9101'}
        assert imported('xiaoming') == set()
    finally:
        dialog.close()
        window.close()
    many = [dict(room_id=str(10000+i), uname=f'测试主播{i}', title='', live=i % 2 == 0)
            for i in range(750)]
    large = FollowImportDialog(many, set())
    try:
        large.show()
        _pinyin_keys.cache_clear()
        start = time.perf_counter()
        large.search_edit.setText('ceshizhubo')
        cold_ms = (time.perf_counter() - start) * 1000
        from PySide6.QtTest import QTest
        for _ in range(500):
            if not large._populating:
                break
            QTest.qWait(10)
        assert not large._populating, 'All fetched follows must eventually be available'
        assert all(not large.list.item(i).isHidden() for i in range(750))
        misses = _pinyin_keys.cache_info().misses
        start = time.perf_counter()
        large.search_edit.setText('cszb')
        warm_ms = (time.perf_counter() - start) * 1000
        assert _pinyin_keys.cache_info().misses == misses, 'Typing must reuse cached transliterations'
        assert all(not large.list.item(i).isHidden() for i in range(750))
        large._check_live()
        assert len(large.selected()) == 375
        assert _pinyin_keys.cache_info().maxsize == 8192
        print(f'PASS: 750 Chinese names, cold={cold_ms:.1f}ms, cached={warm_ms:.1f}ms')
    finally:
        large.close()
    root = Path(__file__).resolve().parents[1]
    assert 'pypinyin==0.55.0' in (root/'requirements.txt').read_text(encoding='utf-8')
    assert '--collect-all pypinyin' in (root/'dev/build_release.ps1').read_text(encoding='utf-8-sig')
    assert 'Permission is hereby granted' in (root/'ddm/assets/licenses/pypinyin-LICENSE.txt').read_text(encoding='utf-8')
    print('PASS: pinyin, initials, original filters, selections, avatars, changed names and packaging metadata')


if __name__ == '__main__':
    main()
