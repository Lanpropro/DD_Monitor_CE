"""Offline fullscreen layout/lifetime regression, not live performance evidence."""
import os
from pathlib import Path
import sys
from contextlib import ExitStack
from unittest.mock import Mock, patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QLabel

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('DDM_NO_SAVE', '1')

from ddm import theme
from ddm.app import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())
    rooms = [dict(room_id=str(9800+i), uname=f'Fixture {i}', live=False) for i in range(9)]
    with ExitStack() as stack:
        for name in ('start_all', 'start_tile', 'refresh_status', 'refresh_stats',
                     'refresh_account', 'load_room_avatars', 'load_cached_avatars',
                     'load_cached_covers', '_check_startup_update', '_check_startup_plugins'):
            stack.enter_context(patch.object(MainWindow, name, Mock()))
        window = MainWindow(rooms, [dict(room) for room in rooms], layout_id='3x3',
                            state={'plugins_enabled': [], 'settings': {'close_behavior': 'exit'}})
        window.setGeometry(-9000, -9000, 1200, 700)
        window.setAttribute(Qt.WA_ShowWithoutActivating)
        window.setWindowFlag(Qt.WindowDoesNotAcceptFocus, True)
        window._upgrade_fullscreen_quality = lambda tile: False
        # Native fullscreen would move a background test onto the user's screen.
        stack.enter_context(patch.object(window, 'showFullScreen', lambda: window.resize(1600, 900)))
        stack.enter_context(patch.object(window, 'showNormal', lambda: window.resize(1200, 700)))
        if app.platformName() == 'windows':
            from ddm import window_fullscreen
            stack.enter_context(patch.object(window_fullscreen, 'enter', lambda owner: owner.resize(1600, 900)))
        window.show()
        app.processEvents()
        try:
            tiles = list(window.wall.tiles)
            video_handles = [int(tile.video.winId()) for tile in tiles]
            handles = int(window.winId())
            before_windows = set(QApplication.topLevelWidgets())
            players = {tile: Mock() for tile in tiles}
            window.players = dict(players)
            for target in (tiles[4], tiles[0], tiles[1], tiles[8]):
                with patch.object(window.wall, 'relayout', wraps=window.wall.relayout) as relayout:
                    window._on_fullscreen(target)
                    assert relayout.call_count == 1, 'Enter must lay out only after the final window size'
                assert window.wall.visible_tiles() == [target]
                assert window._fullscreen_tile is target and not window.sidebar.isVisible()
                assert not [w for w in set(QApplication.topLevelWidgets())-before_windows if isinstance(w, QLabel)]
                with patch.object(window.wall, 'relayout', wraps=window.wall.relayout) as relayout:
                    window._exit_fullscreen()
                    assert relayout.call_count == 1, 'Exit must restore the final layout once'
                assert window.wall.visible_tiles() == tiles, 'Every pane must be visible on return, without staggered reveal'
                assert not window.wall._pending_reveal and not window.wall._defer_show
                assert not window.wall._fullscreen_layout_pending
                assert window.centralWidget().updatesEnabled()
                assert target.bottom.updatesEnabled()
                assert window.centralWidget().layout().isEnabled() and window.wall.grid.isEnabled()
                assert window.sidebar.isVisible() and window.wall.layout_id == '3x3'
                assert window.wall.tiles == tiles and window.players == players
                assert int(window.winId()) == handles
                assert [int(tile.video.winId()) for tile in tiles] == video_handles
            for player in players.values():
                assert not player.play.called and not player.release.called
            window.players.clear()
        finally:
            window.close()
            app.processEvents()
    print('PASS: direct fullscreen, one layout, complete restoration, HWND/player continuity')


if __name__ == '__main__':
    main()
