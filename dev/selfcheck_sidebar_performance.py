"""60 张封面、16 格：收缩期间不重配播放格子，屏外封面延迟到滚入视野。"""
import os
from pathlib import Path
import sys
import time
from unittest.mock import Mock, patch
os.environ['DDM_NO_SAVE'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QHBoxLayout, QWidget
from ddm import motion, theme
from ddm.widgets import Sidebar, WallGrid

class ResizeCounter(QObject):
    def __init__(self):
        super().__init__()
        self.count = 0
    def eventFilter(self, watched, event):
        if event.type() == QEvent.Resize:
            self.count += 1
        return False

def main():
    callback_errors = []
    original_hook = sys.excepthook
    def capture_error(kind, error, trace):
        callback_errors.append(error)
        original_hook(kind, error, trace)
    sys.excepthook = capture_error
    app = QApplication([])
    app.setStyleSheet(theme.qss())
    root = QWidget()
    layout = QHBoxLayout(root)
    sidebar = Sidebar([{'room_id': str(i), 'uname': f'主播{i}'} for i in range(60)], auto_compact=False)
    wall = WallGrid([], '4x4')
    layout.addWidget(sidebar)
    layout.addWidget(wall, 1)
    if hasattr(sidebar, 'collapseAnimationChanged'):
        sidebar.collapseAnimationChanged.connect(wall.set_sidebar_animating)
    root.resize(1400, 850)
    root.show()
    QTest.qWait(150)
    players = []
    if '--vlc' in sys.argv:
        from ddm.player import TilePlayer
        media = Path('logs/control-edge-test.mp4').resolve()
        assert media.is_file()
        for tile in wall.tiles[:6]:
            player = TilePlayer(tile.video, root)
            player.set_muted(True)
            player.play(str(media))
            players.append(player)
        QTest.qWait(1000)
    source = QPixmap(400, 225)
    source.fill(Qt.darkCyan)
    for item in sidebar.items():
        item.thumb.set_cover(source)
    QTest.qWait(50)
    counter = ResizeCounter()
    for tile in wall.tiles:
        tile.installEventFilter(counter)
    original = sidebar.list_box.relayout
    calls = []
    def relayout(*args, **kwargs):
        start = time.perf_counter()
        result = original(*args, **kwargs)
        calls.append((time.perf_counter() - start) * 1000)
        return result
    sidebar.list_box.relayout = relayout
    baseline = os.environ.get('DDM_BENCHMARK_BASELINE') == '1'
    quick = Mock()
    wall._quick_danmaku_layer = quick
    with patch.object(motion, 'enabled', return_value=True):
        sidebar.set_collapsed(True)
        QTest.qWait(60)
        assert quick.resize.call_count == 0, 'Quick surface must not resize during collapse frames'
        assert quick.move.called, 'Quick overlay must still follow the wall position'
        QTest.qWait(240)
        assert quick.resize.called, 'Quick surface geometry must catch up after collapse'
        wall._quick_danmaku_layer = None
        sidebar.set_collapsed(False, animate=False)
    with patch.object(motion, 'enabled', return_value=True):
        for collapsed in (True, False):
            calls.clear()
            counter.count = 0
            geometry = [tile.geometry() for tile in wall.tiles]
            surfaces = [int(tile.video.winId()) for tile in wall.tiles]
            sidebar.set_collapsed(collapsed)
            app.processEvents()
            cards = [item.geometry() for item in sidebar.items()]
            QTest.qWait(60)
            if not baseline:
                assert [tile.geometry() for tile in wall.tiles] == geometry, '动画中不得调整播放器尺寸'
                assert [item.geometry() for item in sidebar.items()] == cards, '动画中不得逐帧排版卡片'
            QTest.qWait(220)
            print(f'{collapsed=}: list_layouts={len(calls)}, layout_ms={sum(calls):.2f}, tile_resizes={counter.count}', flush=True)
            if not baseline:
                assert counter.count <= len(wall.tiles) * 2
                assert len(calls) <= 4
                assert sidebar.width() == (theme.SIDEBAR_RAIL_WIDTH if collapsed else theme.SIDEBAR_WIDTH)
                assert [int(tile.video.winId()) for tile in wall.tiles] == surfaces
                assert wall.grid.isEnabled()
                assert not any(item.thumb._cover_hold for item in sidebar.items())
        if not baseline:
            last = sidebar.items()[-1].thumb
            assert last._cover_dirty, "屏外封面必须延迟重裁"
            bar = sidebar.scroll.verticalScrollBar()
            bar.setValue(bar.maximum())
            QTest.qWait(60)
            assert not last.visibleRegion().isEmpty()
            assert not last._cover_dirty, "滚入视野必须自动恢复封面"
            assert last.cover.pixmap().size() == last.size()
            sidebar.set_collapsed(True)
            QTest.qWait(40)
            sidebar.set_collapsed(False)
            QTest.qWait(240)
            assert sidebar.width() == theme.SIDEBAR_WIDTH and wall.grid.isEnabled()
            sidebar.set_collapsed(True)
            QTest.qWait(40)
            sidebar.set_side('top')
            QTest.qWait(200)
            assert wall.grid.isEnabled() and not sidebar._collapse_animating
            sidebar.set_side('left')
            sidebar.set_collapsed(False, animate=False)
            sidebar.set_collapsed(True)
            QTest.qWait(40)
            root.resize(1500, 900)
            QTest.qWait(220)
            assert wall.grid.isEnabled() and not sidebar._collapse_animating
            sidebar.set_collapsed(False)
            QTest.qWait(40)
            root.hide()
            assert wall.grid.isEnabled() and not sidebar._collapse_animating
            root.show()
            QTest.qWait(50)
            with patch.object(motion, 'enabled', return_value=False):
                sidebar.set_collapsed(True)
                assert not sidebar._collapse_animating
                assert sidebar.width() == theme.SIDEBAR_RAIL_WIDTH
            wall.set_fullscreen_tile(wall.tiles[0])
            fullscreen = wall.fullscreen_tile
            sidebar.set_collapsed(False)
            QTest.qWait(240)
            assert wall.fullscreen_tile is fullscreen and wall.grid.isEnabled()
            assert len(wall.visible_tiles()) == 1
            wall.set_fullscreen_tile(None)
            wall.set_layout('auto')
            QTest.qWait(140)
            geometry = [tile.geometry() for tile in wall.tiles]
            sidebar.set_collapsed(True)
            QTest.qWait(50)
            assert [tile.geometry() for tile in wall.tiles] == geometry
            QTest.qWait(240)
            assert wall.grid.isEnabled() and not wall._sidebar_animating
    assert not callback_errors, callback_errors
    if players:
        assert all(not player._released and player._picture_signature()[1] > 0 for player in players)
        for player in players:
            player.release()
        print('PASS: six real VLC players survive collapse, reversal, resize and hide', flush=True)
    root.close()
    print('PASS: collapse layout budget and interruption recovery' if not baseline else 'BASELINE COMPLETE', flush=True)

if __name__ == '__main__':
    main()
