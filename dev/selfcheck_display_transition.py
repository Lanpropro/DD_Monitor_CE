"""Offline DPI/maximize layout batching; --screens exercises attached monitors."""
import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DDM_NO_SAVE'] = '1'

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtWidgets import QApplication
from ddm import theme
from ddm.app import MainWindow
from ddm.player import TilePlayer
from ddm.plugins import PluginManager
from dev.selfcheck_mpv import ready
from dev.selfcheck_window_resize import Work, latest_geometry, settle, wait_orientation


def make_window(count, layout):
    rooms = [dict(room_id=str(9000+i), uname='synthetic', live=True, muted=True)
             for i in range(count)]
    window = MainWindow(rooms, [dict(r) for r in rooms], layout_id=layout,
        state={'plugins_enabled': [], 'settings': {'close_behavior': 'exit',
            'auto_update': False, 'preview_on_hover': False, 'recording_enabled': False,
            'recording_replay_enabled': False}})
    window.setAttribute(Qt.WA_ShowWithoutActivating)
    window.setGeometry(-9000, 40, 1420, 860)
    window.show()
    settle(250)
    return window


def dpi_event(window):
    QCoreApplication.sendEvent(window, QEvent(QEvent.Type.DevicePixelRatioChange))


def assert_settled(window):
    assert not window._display_transition and not window._resize_dirty
    assert window._root_layout.isEnabled()
    assert not window.wall._interactive_resize
    assert not window._resize_idle_timer.isActive()
    assert not window.wall._resize_timer.isActive()
    area = window.centralWidget().contentsRect()
    content = window._content.geometry()
    assert content.bottomRight() == area.bottomRight(), (content, area)
    if window.orientation == 'portrait':
        assert content.top() == window.sidebar.geometry().bottom()+1
    else:
        assert content.left() == window.sidebar.geometry().right()+1
    # Fractional Windows DPI can round a minimum size by one logical pixel.
    assert window.wall.pos() == window._content.contentsRect().topLeft()
    assert abs(window.wall.width()-window._content.width()) <= 1
    assert abs(window.wall.height()-window._content.height()) <= 1
    latest_geometry(window)


def check_lifecycle():
    window = make_window(6, 'corner')
    try:
        window._begin_interactive_resize()
        before = window.wall.geometry()
        for height in (950, 1200, 1550):
            dpi_event(window)
            window.resize(1100, height)
            QApplication.processEvents()
            assert window._display_transition and not window._root_layout.isEnabled()
            assert window.wall.geometry() == before, 'Intermediate screen geometry was committed'
        window._finish_interactive_resize()
        wait_orientation(window, 'portrait')
        assert_settled(window)

        dpi_event(window)
        window.hide()
        assert not window._display_transition and window._root_layout.isEnabled()
        assert not window._resize_idle_timer.isActive()
        window.show()
        wait_orientation(window, 'portrait')
        assert_settled(window)

        window._root_layout.setEnabled(False)
        dpi_event(window)
        window._cancel_interactive_resize()
        assert not window._root_layout.isEnabled(), 'Preserve caller-disabled layout state'
        window._root_layout.setEnabled(True)
        window._root_layout.invalidate()
        window._root_layout.activate()

        dpi_event(window)
        window.resize(1420, 860)
        with patch.object(window, '_apply_orientation', side_effect=RuntimeError('test')):
            try:
                window._finish_interactive_resize()
                raise AssertionError('Expected injected orientation failure')
            except RuntimeError:
                pass
        assert not window._display_transition and window._root_layout.isEnabled()
        assert not window.wall._interactive_resize and not window._resize_idle_timer.isActive()

        dpi_event(window)
        window.close()
        assert not window._display_transition and window._root_layout.isEnabled()
        assert not window._resize_idle_timer.isActive()
    finally:
        window.close()
        QApplication.processEvents()


def check_screens(app, player_count, source):
    screens = app.screens()
    if len(screens) < 2:
        raise RuntimeError('--screens requires two attached monitors')
    landscape = max(screens, key=lambda s: s.availableGeometry().width()/s.availableGeometry().height())
    portrait = min(screens, key=lambda s: s.availableGeometry().width()/s.availableGeometry().height())
    assert portrait.availableGeometry().height() > portrait.availableGeometry().width()
    results = []
    for count, layout in ((6, 'corner'), (16, '4x4')):
        window = make_window(count, layout)
        identities = {tile: int(tile.video.winId()) for tile in window.wall.tiles}
        cores = []
        try:
            area = landscape.availableGeometry()
            window.setGeometry(area.x()+40, area.y()+40, 1200, 750)
            settle(300)
            for tile in window.wall.tiles[:player_count]:
                player = TilePlayer(tile.video, window)
                window.players[tile] = player
                player.set_muted(True)
                player.bind()
                player.player.loop_file = 'inf'
                player.play(str(source))
                ready(app, player)
                cores.append((player, player.player, player.play_session, player._prop('time-pos')))
            with ExitStack() as measured:
                work = Work(window, measured)
                for target, maximize in ((portrait, False), (portrait, True),
                                          (portrait, False), (landscape, False)):
                    work.reset()
                    started = time.perf_counter()
                    if maximize:
                        window.showMaximized()
                    else:
                        window.showNormal()
                        area = target.availableGeometry()
                        window.setGeometry(area.x()+10, area.y()+60, 1100, 700)
                    settle(500)
                    expected = 'portrait' if maximize else 'landscape'
                    wait_orientation(window, expected)
                    assert_settled(window)
                    assert window.screen() is target
                    assert window.devicePixelRatioF() == target.devicePixelRatio()
                    assert all(int(tile.video.winId()) == hwnd for tile, hwnd in identities.items())
                    if maximize:
                        assert work.calls['_relayout_corner'] == 0, 'Old landscape layout ran during maximize'
                        assert work.calls['_relayout_preset'] <= 3, 'Repeated final orientation layout'
                    results.append(dict(panes=count, maximize=maximize,
                        screen=target.name(), dpr=window.devicePixelRatioF(), orientation=window.orientation,
                        elapsed_ms=round((time.perf_counter()-started)*1000, 2), **work.snapshot()))
            for player, core, session, position in cores:
                assert player.player is core and player.play_session == session
                assert player._prop('time-pos') > position and player.state == 'playing'
        finally:
            window.close()
            QApplication.processEvents()
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--screens', action='store_true')
    parser.add_argument('--players', type=int, choices=range(0, 7), default=0)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.players and not args.screens:
        parser.error('--players requires --screens')
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(theme.qss())
    with ExitStack() as stack, tempfile.TemporaryDirectory(prefix='ddm-screen-') as temporary:
        stack.enter_context(patch.object(PluginManager, 'load'))
        for name in ('start_tile', 'refresh_status', 'refresh_stats', 'refresh_account',
                     'sync_danmaku', 'load_avatars_for', 'load_room_avatars',
                     'load_cached_covers', 'load_cached_avatars', '_check_startup_update'):
            stack.enter_context(patch.object(MainWindow, name))
        source = Path(temporary) / 'synthetic.mp4'
        if args.players:
            subprocess.run([shutil.which('ffmpeg') or 'ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
                '-f', 'lavfi', '-i', 'color=c=blue:s=640x360:r=30', '-t', '30',
                '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', str(source)],
                check=True, timeout=30)
        check_lifecycle()
        report = {'passed': True, 'players': args.players,
                  'scope': 'Qt layout work and native identity; not DWM or decoder FPS',
                  'screens': check_screens(app, args.players, source) if args.screens else []}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
