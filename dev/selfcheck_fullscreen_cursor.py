"""Fullscreen idle cursor: native VLC video, controls, dialogs and cleanup."""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QMenu

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import app as app_module
from ddm.app import MainWindow
from ddm.player import TilePlayer
from ddm.recording import ffmpeg_path
from selfcheck_tile_fullscreen import SilentPoller


def wait(app, predicate, seconds=4):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        if predicate():
            return
        QTest.qWait(20)
    assert predicate(), "Timed out"


def main():
    app_module.StatusPoller = app_module.StatsPoller = SilentPoller
    app = QApplication(sys.argv)
    rooms = [{"room_id": "1000", "uname": "Cursor test", "live": False}]
    window = MainWindow(rooms, [dict(room) for room in rooms], layout_id="1x1")
    window._upgrade_fullscreen_quality = lambda _tile: False
    window.setWindowFlag(Qt.WindowStaysOnTopHint, True)
    window.isActiveWindow = lambda: True
    window.show()
    window.activateWindow()
    tile = window.wall.tiles[0]
    cursor = window._fullscreen_cursor
    cursor.IDLE_SECONDS = 0.25
    with tempfile.TemporaryDirectory() as directory:
        video = str(Path(directory) / "cursor.mp4")
        subprocess.run([ffmpeg_path(), "-hide_banner", "-loglevel", "error", "-y",
                        "-f", "lavfi", "-i", "color=c=blue:s=320x180:r=25",
                        "-t", "15", "-c:v", "mpeg4", video], check=True)
        player = TilePlayer(tile.video, tile)
        window.players[tile] = player
        player.play(video)
        try:
            wait(app, lambda: player.player.get_time() > 0)
            tile.room.update(live=True, live_start_ts=int(time.time()) - 60)
            tile.start_elapsed_timer()
            window._on_fullscreen(tile)
            window._clear_fullscreen_cover()
            window.activateWindow()
            app.processEvents()
            video_point = tile.video.mapToGlobal(tile.video.rect().center())
            video_geometry = tile.video.geometry()
            QCursor.setPos(video_point)
            wait(app, lambda: cursor.hidden)
            assert QApplication.overrideCursor().shape() == Qt.BlankCursor
            assert not tile.bottom.isVisible() and not tile.controls.isVisible()
            assert not tile.stream_badge.isVisible() and not tile.title_badge.isVisible()
            assert not tile.time_badge.isVisible()
            assert tile.video.geometry() == video_geometry
            # Metadata/hover/layout updates must not bring idle controls back.
            tile.set_controls_visible(True)
            tile.set_uname_title("Cursor test", "Updated title")
            tile._refresh_elapsed()
            tile._layout_areas()
            assert not tile.controls.isVisible() and not tile.title_badge.isVisible()
            assert not tile.time_badge.isVisible()
            if sys.platform == "win32" and app.platformName() == "windows":
                class CursorInfo(ctypes.Structure):
                    _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                                ("hCursor", wintypes.HANDLE), ("position", wintypes.POINT)]
                info = CursorInfo()
                info.cbSize = ctypes.sizeof(info)
                cursor.update_cursor()
                assert ctypes.windll.user32.GetCursorInfo(ctypes.byref(info))
                assert not info.hCursor, "Native Windows cursor must also be hidden"
            QCursor.setPos(video_point.x() + 10, video_point.y())
            wait(app, lambda: not cursor.hidden)
            assert QApplication.overrideCursor() is None
            assert tile.bottom.isVisible() and tile.controls.isVisible()
            assert tile.stream_badge.isVisible() and tile.title_badge.isVisible()
            assert tile.time_badge.isVisible()
            assert tile.video.geometry() == video_geometry
            if sys.platform == "win32" and app.platformName() == "windows":
                info.cbSize = ctypes.sizeof(info)
                assert ctypes.windll.user32.GetCursorInfo(ctypes.byref(info))
                assert info.hCursor, "Native cursor must be restored on movement"
            wait(app, lambda: cursor.hidden)

            QCursor.setPos(tile.volume_slider.mapToGlobal(tile.volume_slider.rect().center()))
            wait(app, lambda: not cursor.hidden)
            QTest.qWait(400)
            assert not cursor.hidden, "Controls must keep their cursor"

            QCursor.setPos(video_point)
            wait(app, lambda: cursor.hidden)
            menu = QMenu(window)
            menu.addAction("Test")
            menu.popup(video_point)
            wait(app, lambda: not cursor.hidden)
            QTest.qWait(400)
            assert not cursor.hidden
            menu.close()
            window.activateWindow()
            QCursor.setPos(video_point)
            wait(app, lambda: cursor.hidden)
            dialog = QDialog(window)
            dialog.setModal(True)
            dialog.show()
            wait(app, lambda: not cursor.hidden)
            dialog.close()
            window.activateWindow()
            QCursor.setPos(video_point)
            wait(app, lambda: cursor.hidden)
            window._exit_fullscreen()
            assert not cursor.hidden and not cursor.timer.isActive()
            assert QApplication.overrideCursor() is None
            assert tile.bottom.isVisible()
            assert not tile._fullscreen_controls_hidden
            window._on_fullscreen(tile)
            window._clear_fullscreen_cover()
            window.activateWindow()
            app.processEvents()
            QCursor.setPos(tile.video.mapToGlobal(tile.video.rect().center()))
            wait(app, lambda: cursor.hidden)
        finally:
            window.close()
        assert not cursor.hidden and not cursor.timer.isActive()
        assert QApplication.overrideCursor() is None
    print("Fullscreen cursor over VLC: idle, movement, controls, menu, dialog, exit and close passed")


if __name__ == "__main__":
    main()
