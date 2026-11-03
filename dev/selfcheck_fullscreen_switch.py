"""Offline fullscreen layout/lifetime regression, not live performance evidence."""
import os
import ctypes
from pathlib import Path
import sys
from contextlib import ExitStack
from unittest.mock import Mock, patch

from PySide6.QtCore import QCoreApplication, QEvent, QObject, QRect, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault('DDM_NO_SAVE', '1')

from ddm import theme
from ddm.app import MainWindow


class HandoffEvents(QObject):
    def __init__(self, target, peers, layer):
        super().__init__()
        self.target = target
        self.peers = peers
        self.layer = layer
        self.comments_held = []
        self.enter = []
        self.leave = []
        self.native_cover = []
        target.installEventFilter(self)
        for peer in peers:
            peer.installEventFilter(self)

    @staticmethod
    def native_visible(widget):
        return bool(ctypes.windll.user32.IsWindowVisible(ctypes.c_void_p(int(widget.internalWinId()))))

    def eventFilter(self, watched, event):
        if watched in self.peers and event.type() == QEvent.Hide:
            self.native_cover.append(self.target.isWindow() and self.native_visible(self.target))
        if watched is self.target and watched.isWindow():
            if event.type() == QEvent.Show:
                self.enter.append(all(peer.isVisible() for peer in self.peers))
            elif event.type() == QEvent.Hide:
                self.leave.append(all(peer.isVisible() and self.native_visible(peer) for peer in self.peers))
            if event.type() in (QEvent.Show, QEvent.Hide) and self.layer is not None:
                self.comments_held.append(self.layer._presentation_changing and not self.layer.window.isVisible())
        return False

    def detach(self):
        for widget in (self.target, *self.peers):
            widget.removeEventFilter(self)


def main():
    app = QApplication(sys.argv)
    if app.platformName() != 'windows':
        print('SKIP: native promotion/teardown is checked with the Windows Qt backend; qoffscreen has no HWNDs')
        return
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
        # Use the real promotion, with its final rectangle kept off the user's screen.
        presentation = window._fullscreen_presentation
        enter = presentation.enter
        area = QRect(-15000, -15000, 1600, 900)
        stack.enter_context(patch.object(presentation, 'enter', side_effect=lambda tile: enter(tile, area)))
        window.show()
        app.processEvents()
        layer = window.wall.ensure_quick_danmaku_layer()
        if layer is not None:
            for tile in (window.wall.tiles[0], window.wall.tiles[4]):
                tile.video_danmaku.set_active(True)
                tile.video_danmaku.set_enabled(True)
                assert tile.video_danmaku.add_event({'text': 'Local handoff fixture'})
            QTest.qWait(180)
            assert layer.items, 'Shared layer fixture did not receive its comments'
        try:
            tiles = list(window.wall.tiles)
            native = app.platformName() == 'windows'
            video_handles = [int(tile.video.winId()) for tile in tiles] if native else None
            handles = int(window.winId()) if native else None
            main_geometry = QRect(window.geometry())
            wall_geometry = QRect(window.wall.geometry())
            pane_geometries = [QRect(tile.geometry()) for tile in tiles]
            sidebar_geometry = QRect(window.sidebar.geometry())
            before_windows = set(QApplication.topLevelWidgets())
            players = {tile: Mock() for tile in tiles}
            window.players = dict(players)
            for target in (tiles[4], tiles[0], tiles[1], tiles[8]):
                handoff = HandoffEvents(target, [tile for tile in tiles if tile is not target], layer)
                with patch.object(window.wall, 'relayout', wraps=window.wall.relayout) as relayout:
                    window._on_fullscreen(target)
                    assert relayout.call_count == 0, 'Independent fullscreen must not relayout the playback wall'
                assert handoff.enter and all(handoff.enter), 'Peers disappeared before the presentation was shown'
                assert handoff.native_cover and all(handoff.native_cover), 'Peers hidden before fullscreen HWND became visible'
                assert window.wall.visible_tiles() == [target]
                assert window._fullscreen_tile is target and window.sidebar.isVisible()
                assert target.isWindow() and target.geometry() == area
                user32 = ctypes.windll.user32
                user32.GetWindow.argtypes = [ctypes.c_void_p, ctypes.c_uint]
                user32.GetWindow.restype = ctypes.c_void_p
                assert user32.GetWindow(int(target.winId()), 4) == handles, 'Presentation must remain owned by the app'
                assert target.parentWidget() is window.wall
                assert all(shortcut.parent() is target for shortcut in window._window_shortcuts)
                QTest.qWait(80)
                assert window.geometry() == main_geometry and window.wall.geometry() == wall_geometry
                assert window.sidebar.geometry() == sidebar_geometry
                assert all(tile.geometry() == original for tile, original in zip(tiles, pane_geometries) if tile is not target)
                if app.platformName() == 'offscreen':
                    before = target.volume
                    next(shortcut for shortcut in window._window_shortcuts
                         if shortcut.key().toString() == 'Up').activated.emit()
                    assert target.volume == before + 10, 'Shortcuts must belong to the independent presentation'
                assert not [w for w in set(QApplication.topLevelWidgets())-before_windows if isinstance(w, QLabel)]
                with patch.object(window.wall, 'relayout', wraps=window.wall.relayout) as relayout:
                    window._exit_fullscreen()
                    assert relayout.call_count == 0, 'Restoring the original rectangle must not relayout the wall'
                assert handoff.leave and all(handoff.leave), 'Presentation disappeared before peers were restored'
                if layer is not None:
                    assert handoff.comments_held and all(handoff.comments_held), 'Peer comments leaked during presentation transfer'
                    assert not layer._presentation_changing
                handoff.detach()
                assert window.wall.visible_tiles() == tiles, 'Every pane must be visible on return, without staggered reveal'
                assert not window.wall._pending_reveal and not window.wall._defer_show
                assert not window.wall._fullscreen_layout_pending
                assert window.centralWidget().updatesEnabled()
                assert target.bottom.updatesEnabled()
                assert window.centralWidget().layout().isEnabled() and window.wall.grid.isEnabled()
                assert window.sidebar.isVisible() and window.wall.layout_id == '3x3'
                assert window.wall.tiles == tiles and window.players == players
                assert [tile.geometry() for tile in tiles] == pane_geometries
                assert not target.isWindow() and all(shortcut.parent() is window for shortcut in window._window_shortcuts)
                if native:
                    assert int(window.winId()) == handles
                    assert [int(tile.video.winId()) for tile in tiles] == video_handles
            tiles[7].hide()
            window._on_fullscreen(tiles[0])
            window._exit_fullscreen()
            assert not tiles[7].isVisible(), 'A previously hidden pane must stay hidden on return'
            tiles[7].show()
            window._on_fullscreen(tiles[0])
            window.hide()
            app.processEvents()
            assert not tiles[0].isVisible(), 'Hiding the app must hide its independent presentation'
            window.show()
            app.processEvents()
            assert tiles[0].isVisible() and window._fullscreen_tile is tiles[0]
            for player in players.values():
                assert not player.play.called and not player.release.called
            window.players.clear()
        finally:
            window.close()
            assert window._fullscreen_presentation.tile is None and not tiles[0].isWindow()
            app.processEvents()
            window.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    print('PASS: visible wall handoff, shared comments held during transfer, no wall relayout, original panes, shortcuts and HWND/player continuity')


if __name__ == '__main__':
    main()
