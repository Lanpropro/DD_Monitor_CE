"""60 张封面、16 格：收缩期间不重配播放格子，屏外封面延迟到滚入视野。"""
import os
import argparse
import json
import shutil
import statistics
import subprocess
import tempfile
from pathlib import Path
import sys
import time
from unittest.mock import Mock, patch
os.environ['DDM_NO_SAVE'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QEvent, QEventLoop, QObject, QPropertyAnimation, Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication, QHBoxLayout, QWidget
from ddm import motion, theme
from ddm.widgets import Sidebar, WallGrid

class ResizeCounter(QObject):
    def __init__(self):
        super().__init__()
        self.count = 0
        self.sidebar = None
        self.frames = []
    def eventFilter(self, watched, event):
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


def wait_settled(sidebar):
    deadline = time.monotonic() + 1.5
    while sidebar._collapse_animating and time.monotonic() < deadline:
        wait(10)
    assert not sidebar._collapse_animating, 'Sidebar settlement did not finish'

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--layout', default='4x4')
    parser.add_argument('--players', type=int, default=0)
    parser.add_argument('--quick', action='store_true')
    parser.add_argument('--burst', action='store_true')
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
    root.resize(1400, 850)
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
        for tile in wall.tiles[:args.players]:
            player = TilePlayer(tile.video, root)
            player.set_muted(True)
            player.play(str(media))
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
    baseline = os.environ.get('DDM_BENCHMARK_BASELINE') == '1'
    previous_layer = wall._quick_danmaku_layer
    quick = Mock(wraps=previous_layer) if previous_layer is not None else Mock()
    wall._quick_danmaku_layer = quick
    with patch.object(motion, 'enabled', return_value=True):
        sidebar.set_collapsed(True)
        wait(60)
        assert quick.resize.call_count == 0, 'Quick surface must not resize during collapse frames'
        assert quick.move_window.called, 'Quick overlay must still follow the wall position'
        wait_settled(sidebar)
        assert quick.resize.called, 'Quick surface geometry must catch up after collapse'
        wall._quick_danmaku_layer = previous_layer
        sidebar.set_collapsed(False, animate=False)
    with patch.object(motion, 'enabled', return_value=True):
        for collapsed in (True, False):
            calls.clear()
            counter.count = 0
            counter.frames.clear()
            finishes.clear()
            geometry = [tile.geometry() for tile in wall.tiles]
            surfaces = [int(tile.video.winId()) for tile in wall.tiles]
            started = time.perf_counter()
            cpu = time.process_time()
            sidebar.set_collapsed(collapsed)
            prepare_ms = (time.perf_counter()-started)*1000
            app.processEvents()
            cards = [item.geometry() for item in sidebar.items()]
            wait(60)
            if not baseline:
                assert not wall.updatesEnabled(), 'Qt repaint hold must cover animation frames'
                assert [tile.geometry() for tile in wall.tiles] == geometry, '动画中不得调整播放器尺寸'
                assert [item.geometry() for item in sidebar.items()] == cards, '动画中不得逐帧排版卡片'
            wait(220)
            wait_settled(sidebar)
            print(f'{collapsed=}: list_layouts={len(calls)}, layout_ms={sum(calls):.2f}, tile_resizes={counter.count}', flush=True)
            gaps = sorted((b[0]-a[0])*1000 for a,b in zip(counter.frames,counter.frames[1:]))
            print(json.dumps(dict(collapsed=collapsed, screen_hz=sidebar.screen().refreshRate(),
                prepare_ms=round(prepare_ms,3),finish_ms=round(sum(finishes),3),
                width_updates=len(counter.frames),frame_gap_median_ms=round(statistics.median(gaps),3) if gaps else None,
                frame_gap_max_ms=round(max(gaps),3) if gaps else None,
                cpu_ms=round((time.process_time()-cpu)*1000,3),
                scope='Qt width callbacks, not DWM presentation FPS')),flush=True)
            if not baseline:
                assert counter.count <= len(wall.tiles) * 2
                assert len(calls) <= 4
                assert sidebar.width() == (theme.SIDEBAR_RAIL_WIDTH if collapsed else theme.SIDEBAR_WIDTH)
                assert [int(tile.video.winId()) for tile in wall.tiles] == surfaces
                assert wall.grid.isEnabled()
                assert wall.updatesEnabled()
                assert not sidebar._collapse_timer.isActive()
                bounds = [tile.geometry() for tile in wall.visible_tiles()]
                margins = wall.grid.contentsMargins()
                assert max(rect.right() for rect in bounds)+1 == wall.width()-margins.right()
                assert max(rect.bottom() for rect in bounds)+1 == wall.height()-margins.bottom()
                assert not any(item.thumb._cover_hold for item in sidebar.items())
        if args.burst:
            for delay in (40, 200):
                finishes.clear()
                inputs = []
                for _ in range(12):
                    started = time.perf_counter()
                    sidebar.toggle_collapsed()
                    inputs.append((time.perf_counter()-started)*1000)
                    wait(delay)
                wait(400)
                wait_settled(sidebar)
                print(json.dumps(dict(burst_interval_ms=delay, clicks=12,
                    click_median_ms=round(statistics.median(inputs),3),
                    click_max_ms=round(max(inputs),3), settlements=len(finishes),
                    settlement_total_ms=round(sum(finishes),3))),flush=True)
                if not baseline:
                    assert len(finishes) == 1, 'Continuous clicks must share one expensive settlement'
                assert not sidebar._collapse_timer.isActive() and wall.updatesEnabled()
                assert not sidebar._collapse_settle.isActive()
                assert sidebar.width() == (theme.SIDEBAR_RAIL_WIDTH if sidebar.collapsed else theme.SIDEBAR_WIDTH)
                assert all(item._compact == sidebar.collapsed for item in sidebar.items())
        if not baseline:
            last = sidebar.items()[-1].thumb
            assert last._cover_dirty, "屏外封面必须延迟重裁"
            bar = sidebar.scroll.verticalScrollBar()
            bar.setValue(bar.maximum())
            wait(60)
            assert not last.visibleRegion().isEmpty()
            assert not last._cover_dirty, "滚入视野必须自动恢复封面"
            assert last.cover.pixmap().size() == last.size()
            sidebar.set_collapsed(True)
            wait(40)
            sidebar.set_collapsed(False)
            wait_settled(sidebar)
            assert sidebar.width() == theme.SIDEBAR_WIDTH and wall.grid.isEnabled() and wall.updatesEnabled()
            sidebar.set_collapsed(True)
            wait(40)
            sidebar.set_side('top')
            wait(200)
            assert wall.grid.isEnabled() and not sidebar._collapse_animating
            sidebar.set_side('left')
            sidebar.set_collapsed(False, animate=False)
            sidebar.set_collapsed(True)
            wait(40)
            root.resize(1500, 900)
            wait(220)
            assert wall.grid.isEnabled() and not sidebar._collapse_animating
            sidebar.set_collapsed(False)
            wait(40)
            root.hide()
            assert wall.grid.isEnabled() and wall.updatesEnabled() and not sidebar._collapse_animating
            root.show()
            wait(50)
            with patch.object(motion, 'enabled', return_value=False):
                sidebar.set_collapsed(True)
                assert not sidebar._collapse_animating
                assert sidebar.width() == theme.SIDEBAR_RAIL_WIDTH
            wall.set_fullscreen_tile(wall.tiles[0])
            fullscreen = wall.fullscreen_tile
            sidebar.set_collapsed(False)
            wait_settled(sidebar)
            assert wall.fullscreen_tile is fullscreen and wall.grid.isEnabled()
            assert len(wall.visible_tiles()) == 1
            wall.set_fullscreen_tile(None)
            wall.set_layout('auto')
            wait(140)
            geometry = [tile.geometry() for tile in wall.tiles]
            sidebar.set_collapsed(True)
            wait(50)
            assert [tile.geometry() for tile in wall.tiles] == geometry
            wait_settled(sidebar)
            assert wall.grid.isEnabled() and not wall._sidebar_animating
            # Reversals reuse one timer instead of retaining animation objects.
            before = len(sidebar.findChildren(QPropertyAnimation, options=Qt.FindDirectChildrenOnly))
            for _ in range(10):
                sidebar.set_collapsed(not sidebar.collapsed)
            sidebar.set_collapsed(False, animate=False)
            assert len(sidebar.findChildren(QPropertyAnimation, options=Qt.FindDirectChildrenOnly)) == before
            assert not sidebar._collapse_timer.isActive() and wall.updatesEnabled()
            wall.setUpdatesEnabled(False)
            wall.set_sidebar_animating(True)
            wall.set_sidebar_animating(False)
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
    print('PASS: collapse layout budget and interruption recovery' if not baseline else 'BASELINE COMPLETE', flush=True)

if __name__ == '__main__':
    main()
