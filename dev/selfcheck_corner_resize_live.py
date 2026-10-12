"""真实 VLC 本地视频：拖动、全屏几何恢复与换位不重启播放器，不联网。"""
from contextlib import ExitStack
import os
from pathlib import Path
import struct
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DDM_NO_SAVE", "1")
os.environ.setdefault("PYTHON_VLC_LIB_PATH", str(ROOT / "libvlc.dll"))
os.environ.setdefault("QT_QPA_PLATFORM", "windows" if "--native" in sys.argv else "offscreen")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
import vlc
from ddm import layouts, theme
from ddm.app import MainWindow
from ddm.player import TilePlayer
from selfcheck_corner_resize import drag, border_for, CORNER_KEYS
from selfcheck_corner_drag_updates import begin, move_to, release_at
from selfcheck_pane_borders import point_on, resize as resize_border


def settle(app, seconds=0.3):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)


def main():
    app = QApplication([])
    app.setStyleSheet(theme.qss())
    rooms = [{"room_id": str(1000 + i), "uname": f"Local fixture {i}", "live": False,
              "muted": True, "volume": 40} for i in range(6)]
    with ExitStack() as stack:
        for method in ("start_tile", "refresh_status", "refresh_stats", "refresh_account",
                       "sync_danmaku", "load_avatars_for", "load_room_avatars",
                       "load_cached_covers", "load_cached_avatars"):
            stack.enter_context(patch.object(MainWindow, method))
        window = MainWindow(rooms, [dict(room) for room in rooms], layout_id="corner",
                            state={"plugins_enabled": [], "settings": {
                                "recording_enabled": False, "recording_replay_enabled": False,
                                "preview_on_hover": False, "auto_update": False}})
        if "--native" in sys.argv:
            window.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        window.setGeometry(40 if "--native" in sys.argv else -9000, 40, 1400, 900)
        window.show()
        settle(app)
        window.start_tile.reset_mock()  # 启动布局的调用不属于后续拖动操作。
        players = []
        directory = ROOT / "work/corner-resize-tmp"
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=directory) as temporary:
            path = Path(temporary) / "fixture.bmp"
            width, height = 320, 180
            pixels = (b"\x90\x45\x20" * (width // 2)
                      + b"\x30\x50\xc0" * (width // 2)) * height
            path.write_bytes(b"BM" + struct.pack("<IHHI", 54 + len(pixels), 0, 0, 54)
                             + struct.pack("<IIIHHIIIIII", 40, width, height, 1, 24,
                                           0, len(pixels), 0, 0, 0, 0) + pixels)
            try:
                for tile in window.wall.tiles:
                    tile.room["live"] = True
                    player = TilePlayer(tile.video, tile)
                    player.freeze_watch = False
                    player.set_muted(True)
                    window.players[tile] = player
                    players.append(player)
                    player.play(str(path), options=[":image-duration=60", ":image-fps=25"])
                    tile.set_video_active(True)
                settle(app, 2)
                assert all(player.player.is_playing() for player in players), "本地视频必须实际播放"
                if "--native" in sys.argv:
                    window.raise_()
                    window.activateWindow()
                    settle(app, .1)
                identities = [(player.player, player._media, int(player.video_widget.winId()))
                              for player in players]
                initial_time = [player.player.get_time() for player in players]
                border = window.wall._pane_borders[window.wall.tiles[0]]
                if app.platformName() == "windows":
                    import ctypes
                    from ctypes import wintypes
                    user32 = ctypes.windll.user32
                    user32.WindowFromPoint.argtypes = (wintypes.POINT,)
                    user32.WindowFromPoint.restype = wintypes.HWND
                    point = border.mapToGlobal(point_on(border, ["right"]))
                    hit = user32.WindowFromPoint(wintypes.POINT(point.x(), point.y()))
                    assert hit == int(border.winId()), (
                        f"VLC must not intercept border mouse hits: hit={hit}, border={int(border.winId())}, "
                        f"point={point}, wall={window.wall.geometry()}")
                resize_border(app, border, ["right", "bottom"], QPoint(-32, -32))
                settle(app)
                # 持续拖动只更新轮廓，VLC 原生窗口在松手前保持原几何和句柄。
                for target, axis in ((Qt.Horizontal, QPoint(1, 0)),
                                     (Qt.Vertical, QPoint(0, 1)),
                                     ("right", QPoint(0, 1)),
                                     ("bottom_left", QPoint(1, 0)),
                                     ("bottom_right", QPoint(1, 0))):
                    handle, point = border_for(window.wall, CORNER_KEYS[target])
                    still = [tile.geometry() for tile in window.wall.tiles]
                    video_still = [tile.video.geometry() for tile in window.wall.tiles]
                    origin = begin(handle, pos=point)
                    for frame in range(8):
                        for sample in range(20):
                            offset = (sample + frame * 20) % 61 - 30
                            destination = origin + axis * offset
                            move_to(handle, destination)
                        settle(app, 0.05)
                        assert [tile.geometry() for tile in window.wall.tiles] == still
                        assert [tile.video.geometry() for tile in window.wall.tiles] == video_still
                        assert window.wall._border_preview.isVisible(), (
                            target, frame, destination, window.wall._border_preview.guides)
                        assert len(window.wall._border_preview.rectangles) == 6
                        assert window.wall._border_preview.guides
                        assert all(int(tile.video.winId()) == identity[2]
                                   for tile, identity in zip(window.wall.tiles, identities))
                        if "--native" in sys.argv and target == Qt.Horizontal and frame == 0:
                            preview = window.wall._border_preview
                            guide = preview.guides[CORNER_KEYS[Qt.Horizontal]]
                            spot = window.wall.mapToGlobal(QPoint(
                                guide.center().x(), guide.top() + 8 * (preview.DASH + preview.GAP)))
                            screen = QApplication.screenAt(spot)
                            snapshot = screen.grabWindow(0).toImage()
                            ratio = screen.devicePixelRatio()
                            top_left = window.wall.mapToGlobal(QPoint(0, 0))
                            snapshot.copy(
                                round((top_left.x() - screen.geometry().left()) * ratio),
                                round((top_left.y() - screen.geometry().top()) * ratio),
                                round(window.wall.width() * ratio),
                                round(window.wall.height() * ratio)).save(
                                    str(ROOT / "work/resize-guide-native.png"))
                            pixel = snapshot.pixelColor(
                                round((spot.x() - screen.geometry().left()) * ratio),
                                round((spot.y() - screen.geometry().top()) * ratio))
                            assert pixel == preview.COLOR, pixel.name()
                    release_at(handle, destination)
                    settle(app)
                    assert not window.wall._border_preview.isVisible()
                    handle, point = border_for(window.wall, CORNER_KEYS[target])
                    QTest.mouseDClick(handle, Qt.LeftButton, pos=point)
                    settle(app, .05)
                for index in range(4):
                    for target, movement in ((Qt.Horizontal, QPoint(30 if index % 2 else -30, 0)),
                                             (Qt.Vertical, QPoint(0, 25 if index % 2 else -25))):
                        handle, point = border_for(window.wall, CORNER_KEYS[target])
                        drag(app, handle, movement, pos=point)
                    settle(app)
                window.resize(1600, 950)
                settle(app)
                target = window.wall.tiles[2]
                window.wall.set_fullscreen_tile(target)
                settle(app)
                window.wall.set_fullscreen_tile(None)
                settle(app)
                assert window._hot_swap(window.wall.tiles[0], window.wall.tiles[4])
                settle(app, 0.6)
                window.wall.reset_corner_ratios()
                settle(app)
                # 同一批真实播放器轮流进入所有其他预设，不经过取流/播放器重启。
                # 隔离窗口方向自动切换；实际应用切到容量更小的布局会按设计停掉隐藏路。
                stack.enter_context(patch.object(window, '_apply_orientation'))
                for identifier in layouts.BY_ID:
                    if identifier == 'corner':
                        continue
                    window.wall.set_layout(identifier)
                    window.resize(850 if layouts.is_portrait_layout(identifier) else 1600, 1300)
                    settle(app, .08)
                    for key in list(window.wall._preset_dividers):
                        handle, point = border_for(window.wall, key)
                        node = window.wall._preset_dividers[key][0]
                        direction = QPoint(1, 0) if node.axis == Qt.Horizontal else QPoint(0, 1)
                        drag(app, handle, direction * 12, pos=point)
                        handle, point = border_for(window.wall, key)
                        QTest.mouseDClick(handle, Qt.LeftButton, pos=point)
                    pane = window.wall.tiles[0]
                    border = window.wall._pane_borders[pane]
                    if border.targets:
                        edges = (["right", "bottom"] if "right" in border.targets and "bottom" in border.targets
                                 else [next(iter(border.targets))])
                        resize_border(app, border, edges, QPoint(-12, -12))
                    if identifier in ('3x2', 'two_rows', 'dm_left', 'portrait_dm4'):
                        window.grab().save(str(ROOT / f'work/resize-{identifier}.png'))
                    window.wall.reset_layout_ratios()
                    settle(app, .04)
                window.wall.set_layout('corner')
                window.resize(1600, 950)
                settle(app, .6)
                assert all(window.players[player.video_widget.parentWidget()] is player
                           for player in players)
                for player, identity, before in zip(players, identities, initial_time):
                    assert (player.player, player._media, int(player.video_widget.winId())) == identity
                    assert player.player.is_playing() and player.player.get_time() > before
                    stats = vlc.MediaStats()
                    assert player._media.get_stats(stats) and stats.decoded_video > 0
                    if app.platformName() == "windows":
                        assert stats.displayed_pictures > 0, "Windows 原生输出必须显示视频帧"
                    print(f"VLC time={player.player.get_time()}ms, decoded={stats.decoded_video}, "
                          f"displayed={stats.displayed_pictures}", flush=True)
                window.start_tile.assert_not_called()
                image = window.wall.grab().toImage()
                for rect in window.wall._divider_rects.values():
                    assert image.pixelColor(rect.center()) == theme.qcolor(theme.BG)
                window.grab().save(str(ROOT / "work/corner-resize-application.png"))
                print(f"PASS: {app.platformName()}, six real VLC players, drag/resize/fullscreen "
                      "geometry/hot swap/all presets, stable handles and continuous media")
            finally:
                window.close()
                settle(app)


if __name__ == "__main__":
    main()
