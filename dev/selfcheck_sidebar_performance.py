"""60 张封面、16 格：侧栏一次切换完整布局，屏外封面滚入时再补。"""
import os
import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
import sys
import time
from unittest.mock import Mock, patch
os.environ['DDM_NO_SAVE'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEvent, QEventLoop, QObject, Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QHBoxLayout, QWidget
from ddm import motion, theme
from ddm.widgets import Sidebar, WallGrid
from dev.selfcheck_video_danmaku import wait_comment_raster

class ResizeCounter(QObject):
    def __init__(self):
        super().__init__()
        self.count = 0
        self.sidebar = None
        self.frames = []
        self.sidebar_paints = 0
    def eventFilter(self, watched, event):
        if watched is self.sidebar and event.type() == QEvent.Paint:
            self.sidebar_paints += 1
        if event.type() == QEvent.Resize:
            if watched is self.sidebar:
                self.frames.append((time.perf_counter(), event.size().width()))
            else:
                self.count += 1
        return False


def wait(milliseconds):
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--layout', default='4x4')
    parser.add_argument('--players', type=int, default=0)
    parser.add_argument('--size', nargs=2, type=int, default=(1400, 850), metavar=('WIDTH', 'HEIGHT'))
    parser.add_argument('--quick', action='store_true')
    parser.add_argument('--burst', action='store_true')
    parser.add_argument('--background', action='store_true', help='原生回归放在屏幕外，不激活窗口')
    args = parser.parse_args()
    if args.quick:
        os.environ['DDM_QTQUICK_DANMAKU'] = '1'
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
    wall = WallGrid([], args.layout)
    layout.addWidget(sidebar)
    layout.addWidget(wall, 1)
    if hasattr(sidebar, 'collapseAnimationChanged'):
        sidebar.collapseAnimationChanged.connect(wall.set_sidebar_animating)
    root.resize(*args.size)
    if args.background:
        root.setAttribute(Qt.WA_ShowWithoutActivating)
        root.move(-30000, -30000)
    root.show()
    wait(150)
    players = []
    media_dir = tempfile.TemporaryDirectory(prefix='ddm-collapse-')
    if args.players:
        from ddm.player import TilePlayer
        media = str(Path(media_dir.name) / 'local.mp4')
        subprocess.run([shutil.which('ffmpeg') or 'ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
                        '-f', 'lavfi', '-i', 'testsrc2=s=320x180:r=30', '-t', '30',
                        '-c:v', 'libx264', '-preset', 'ultrafast', media], check=True, timeout=30)
        assert 0 < args.players <= len(wall.tiles)
        for index, tile in enumerate(wall.tiles[:args.players]):
            tile.set_room(dict(room_id=f'fixture:{index}', uname=f'Local {index}', live=True))
            player = TilePlayer(tile.video, root)
            player.set_muted(True)
            player.play(str(media))
            tile.set_video_active(True)
            if args.quick:
                tile.video_danmaku.set_enabled(True)
                for number in range(min(8, tile.video_danmaku.lane_count())):
                    assert tile.video_danmaku.add_event(dict(kind='danmaku', uname='Fixture',
                        text=f'Local comment {number}', color='#ffffff'))
                    wait_comment_raster(QApplication.instance(), tile.video_danmaku)
                assert tile.video_danmaku.comments
            players.append(player)
        wait(1000)
    source = QPixmap(400, 225)
    source.fill(Qt.darkCyan)
    for item in sidebar.items():
        item.thumb.set_cover(source)
    wait(50)
    counter = ResizeCounter()
    counter.sidebar = sidebar
    sidebar.installEventFilter(counter)
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
    original_finish = sidebar._finish_collapse
    finishes = []
    def finish(*args):
        started = time.perf_counter()
        try:
            return original_finish(*args)
        finally:
            finishes.append((time.perf_counter()-started)*1000)
    sidebar._finish_collapse = finish
    original_geometry = wall._relayout_preset
    geometry_observations = []
    def geometry_after_sidebar(*args, **kwargs):
        geometry_observations.append((counter.sidebar_paints > 0, sidebar.updatesEnabled()))
        return original_geometry(*args, **kwargs)
    wall._relayout_preset = geometry_after_sidebar
    previous_layer = wall._quick_danmaku_layer
    quick = Mock(wraps=previous_layer) if previous_layer is not None else Mock()
    wall._quick_danmaku_layer = quick
    with patch.object(motion, 'enabled', return_value=True):
        for collapsed in (True, False):
            calls.clear()
            counter.count = 0
            counter.frames.clear()
            counter.sidebar_paints = 0
            geometry_observations.clear()
            finishes.clear()
            surfaces = [int(tile.video.winId()) for tile in wall.tiles]
            quick.reset_mock()
            started = time.perf_counter()
            sidebar.set_collapsed(collapsed)
            elapsed = (time.perf_counter() - started) * 1000
            assert not sidebar._collapse_animating and not wall._sidebar_animating
            assert wall.updatesEnabled() and wall.grid.isEnabled() and sidebar.updatesEnabled()
            assert geometry_observations and all(painted and enabled for painted, enabled in geometry_observations), \
                'Final sidebar must paint before player geometry changes'
            assert quick.resize.called, 'Quick surface must settle before the call returns'
            assert sidebar._column.width() == (theme.SIDEBAR_RAIL_WIDTH if collapsed else theme.SIDEBAR_WIDTH)
            assert len(counter.frames) == 1, 'Width must change directly to its final value'
            assert all(item._compact == collapsed for item in sidebar.items())
            assert not any(item.thumb._cover_hold for item in sidebar.items())
            if not collapsed:
                for item in sidebar.items():
                    if not item.thumb.visibleRegion().isEmpty():
                        assert not item.thumb._cover_dirty
                        assert item.thumb.cover.pixmap().size() == item.thumb.size()
            bounds = [tile.geometry() for tile in wall.visible_tiles()]
            margins = wall.grid.contentsMargins()
            assert max(rect.right() for rect in bounds)+1 == wall.width()-margins.right()
            assert max(rect.bottom() for rect in bounds)+1 == wall.height()-margins.bottom()
            final_geometry = [tile.geometry() for tile in wall.tiles]
            wait(300)
            assert len(counter.frames) == 1, 'No delayed width animation may follow'
            assert [tile.geometry() for tile in wall.tiles] == final_geometry
            assert [int(tile.video.winId()) for tile in wall.tiles] == surfaces
            assert counter.count <= len(wall.tiles) * 2
            print(json.dumps(dict(collapsed=collapsed, call_ms=round(elapsed, 3),
                settlements=len(finishes), width_updates=len(counter.frames), tile_resizes=counter.count,
                scope='Synthetic functional regression, not real performance evidence')), flush=True)
        wall._quick_danmaku_layer = previous_layer
        if args.burst:
            for delay in (0, 40, 200):
                finishes.clear()
                for _ in range(12):
                    sidebar.toggle_collapsed()
                    assert not sidebar._collapse_animating and wall.updatesEnabled()
                    assert sidebar._column.width() == (theme.SIDEBAR_RAIL_WIDTH if sidebar.collapsed else theme.SIDEBAR_WIDTH)
                    assert all(item._compact == sidebar.collapsed for item in sidebar.items())
                    if delay:
                        wait(delay)
                assert len(finishes) == 12, 'Each click completes its requested state'
        last = sidebar.items()[-1].thumb
        assert last._cover_dirty, 'Offscreen covers must stay deferred'
        bar = sidebar.scroll.verticalScrollBar()
        bar.setValue(bar.maximum())
        wait(60)
        assert not last.visibleRegion().isEmpty() and not last._cover_dirty
        assert last.cover.pixmap().size() == last.size()
        sidebar.set_collapsed(True)
        sidebar.set_side('top')
        sidebar.set_collapsed(False)
        assert wall.grid.isEnabled() and not sidebar._collapse_animating
        sidebar.set_side('left')
        sidebar.set_collapsed(True)
        root.resize(1500, 900)
        wait(220)
        assert wall.grid.isEnabled() and not sidebar._collapse_animating
        root.hide()
        assert wall.updatesEnabled()
        root.show()
        wait(50)
        with patch.object(motion, 'enabled', return_value=False):
            sidebar.set_collapsed(False)
            assert sidebar._column.width() == theme.SIDEBAR_WIDTH
        wall.set_fullscreen_tile(wall.tiles[0])
        fullscreen = wall.fullscreen_tile
        sidebar.set_collapsed(True)
        assert wall.fullscreen_tile is fullscreen and wall.grid.isEnabled()
        assert len(wall.visible_tiles()) == 1
        wall.set_fullscreen_tile(None)
        wall.set_layout('auto')
        wait(140)
        sidebar.set_collapsed(False)
        assert wall.grid.isEnabled() and not wall._sidebar_animating
        wall.setUpdatesEnabled(False)
        sidebar.set_collapsed(True)
        assert not wall.updatesEnabled(), 'Respect a pre-existing repaint hold'
        wall.setUpdatesEnabled(True)
        wall.set_sidebar_animating(True)
        with patch.object(wall, 'relayout', side_effect=RuntimeError('synthetic layout failure')):
            try:
                wall.set_sidebar_animating(False)
            except RuntimeError:
                pass
            else:
                raise AssertionError('The injected layout failure did not run')
        assert wall.updatesEnabled() and wall.grid.isEnabled()
    assert not callback_errors, callback_errors
    if players:
        assert all(not player._released and player._picture_signature()[1] > 0 for player in players)
        for player in players:
            player.release()
        print(f'PASS: {len(players)} local libmpv players survive collapse, reversal, resize and hide', flush=True)
    root.close()
    media_dir.cleanup()
    print('PASS: complete sidebar switch, deferred covers and repaint recovery', flush=True)

if __name__ == '__main__':
    main()
