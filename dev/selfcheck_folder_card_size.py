"""展开多个文件夹跨过滚动阈值时，现有卡片尺寸应保持稳定。"""
import os
from pathlib import Path
import sys
from unittest.mock import patch
os.environ['DDM_NO_SAVE'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtTest import QTest
from PySide6.QtCore import QPoint, QRect
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
    # 留出默认文件夹标题的空间；再展开三条时仍须跨过滚动阈值。
    for card_mode, height in ((True, 950), (False, 700)):
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
    sidebar = Sidebar([{'room_id': str(i), 'uname': f'Fixture {i}'} for i in range(120)],
                      auto_compact=False)
    sidebar.set_folders([{'id': f'f{i}', 'name': f'Folder {i}', 'type': 'normal',
                          'collapsed': i == 0, 'rooms': [str(j) for j in range(i*40, i*40+40)]}
                         for i in range(3)])
    sidebar.resize(theme.SIDEBAR_WIDTH, 800)
    sidebar.show()
    QTest.qWait(50)
    box = sidebar.list_box
    for side in ('left', 'top', 'left'):
        sidebar.set_side(side)
        sidebar.resize(800 if side == 'top' else theme.SIDEBAR_WIDTH, 800)
        QTest.qWait(50)
        for card_mode in (True, False):
            sidebar.set_card_mode(card_mode)
            for _ in range(4):
                with patch.object(sidebar, '_sync_count', wraps=sidebar._sync_count) as count:
                    sidebar.toggle_folder('f0', animate=True)
                    assert count.call_count == 1, 'Folder refresh must not repeat platform/count work'
                viewport = sidebar.scroll.viewport()
                visible = QRect(box.mapFrom(viewport, QPoint()), viewport.size())
                running = [(item, animation) for item, animation in box._animations.items()
                           if animation.state().name == 'Running']
                assert running, 'Visible rows should retain their transition'
                assert len(running) < 40, 'Offscreen rows must not all animate'
                for item, animation in running:
                    assert not item.isHidden(), 'Collapsed rows must stop animating'
                    assert (QRect(animation.startValue(), item.size()).intersects(visible)
                            or QRect(animation.endValue(), item.size()).intersects(visible)), \
                        'Only rows visible at either end should animate'
                QTest.qWait(30)  # Reverse before the previous transition finishes.
            QTest.qWait(320)
            assert not any(a.state().name == 'Running' for a in box._animations.values())
            geometry = {item: item.geometry() for item in sidebar.visible_items()}
            box.relayout(animate=False)
            assert all(item.geometry() == rect for item, rect in geometry.items())
    smart = sidebar.create_folder('Mirror', rule={'display': 'copy', 'sources': ['f0'], 'status': 'any'})
    sidebar.toggle_folder(smart)
    sidebar.scroll.ensureWidgetVisible(sidebar._folder_buttons[smart])
    QTest.qWait(30)
    sidebar.toggle_folder(smart, animate=True)
    assert sidebar._smart_cards
    assert sum(a.state().name == 'Running' for a in box._animations.values()) < 40
    sidebar.toggle_folder(smart, animate=True)
    assert all(not item.isHidden() for item, a in box._animations.items() if a.state().name == 'Running')
    QTest.qWait(320)
    sidebar.close()
    print('PASS: folder expansion and collapse keep card size stable across vertical scrolling threshold')


if __name__ == '__main__':
    main()
