"""展开多个文件夹跨过滚动阈值时，现有卡片尺寸应保持稳定。"""
import os
from pathlib import Path
import sys
os.environ['DDM_NO_SAVE'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from ddm import theme
from ddm.widgets import Sidebar


def main():
    app = QApplication([])
    app.setStyleSheet(theme.qss())
    rooms = [{'room_id': str(i), 'uname': f'主播{i}'} for i in range(12)]
    sidebar = Sidebar(rooms, auto_compact=False)
    sidebar.set_folders([{'id': f'f{i}', 'name': f'文件夹{i}', 'type': 'normal',
                          'collapsed': True, 'rooms': [str(j) for j in range(i*3, i*3+3)]}
                         for i in range(4)])
    sidebar.resize(theme.SIDEBAR_WIDTH, 950)
    sidebar.show()
    QTest.qWait(50)
    sidebar.toggle_folder('f0')
    for card_mode, height in ((True, 950), (False, 650)):
        sidebar.set_compact_policy(card_mode, False, 18)
        sidebar.resize(theme.SIDEBAR_WIDTH, height)
        # 经历横竖屏切换、侧栏收起再展开后也应保持稳定。
        sidebar.set_side('top')
        QTest.qWait(50)
        card = sidebar.items()[0]
        portrait_size = card.size()
        sidebar.toggle_folder('f1')
        QTest.qWait(50)
        assert card.size() == portrait_size
        sidebar.toggle_folder('f1')
        sidebar.set_side('left')
        sidebar.set_collapsed(True, animate=False)
        sidebar.set_collapsed(False, animate=False)
        QTest.qWait(50)
        baseline = card.size()
        bar = sidebar.scroll.verticalScrollBar()
        assert bar.maximum() == 0, '第一个文件夹应能完整显示'
        for _ in range(2):
            sidebar.toggle_folder('f1')
            QTest.qWait(50)
            assert bar.maximum() > 0, '第二个文件夹展开后应触发滚动'
            assert card.size() == baseline, (baseline, card.size())
            sidebar.toggle_folder('f1')
            QTest.qWait(50)
            assert bar.maximum() == 0
            assert card.size() == baseline
    sidebar.close()
    print('PASS: folder expansion and collapse keep card size stable across vertical scrolling threshold')


if __name__ == '__main__':
    main()
