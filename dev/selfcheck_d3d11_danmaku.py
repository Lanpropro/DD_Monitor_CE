"""Real shared D3D11 composition over four local mpv windows; no live services."""
import os
import ctypes
from ctypes import wintypes
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

os.environ["DDM_NATIVE_DANMAKU"] = "1"
os.environ["DDM_QTQUICK_DANMAKU"] = "0"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import QPoint
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QMenu
from ddm import config, images, theme
from ddm.player import TilePlayer
from ddm.recording import ffmpeg_path
from ddm.widgets import WallGrid


def settle(app, seconds=.15):
    until = time.perf_counter() + seconds
    while time.perf_counter() < until:
        app.processEvents()
        time.sleep(.005)


def wait_for(app, predicate, timeout=5):
    until = time.perf_counter() + timeout
    while not predicate():
        if time.perf_counter() >= until:
            raise AssertionError("Native condition timed out")
        settle(app, .02)


class _MouseInput(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _InputUnion(ctypes.Union):
    _fields_ = [("mi", _MouseInput)]


class _Input(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("data", _InputUnion)]


def check_input_target(app, wall, layer):
    user32 = ctypes.windll.user32
    user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    user32.WindowFromPoint.argtypes = [wintypes.POINT]
    user32.WindowFromPoint.restype = wintypes.HWND
    user32.IsChild.argtypes = [wintypes.HWND, wintypes.HWND]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(_Input), ctypes.c_int]
    user32.SendInput.restype = wintypes.UINT
    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.SendMessageW.restype = wintypes.LPARAM
    original = QCursor.pos()
    try:
        wall.raise_()
        wall.activateWindow()
        settle(app, .1)
        for tile in wall.tiles:
            tile.set_controls_visible(True)
            settle(app, .06)
            target = tile.pause_button.mapToGlobal(tile.pause_button.rect().center())
            QCursor.setPos(target)
            settle(app, .03)
            point = wintypes.POINT()
            assert user32.GetCursorPos(ctypes.byref(point))
            hwnd = user32.WindowFromPoint(point)
            if hwnd == int(layer.window.winId()):
                packed = (point.x & 0xffff) | ((point.y & 0xffff) << 16)
                assert user32.SendMessageW(hwnd, 0x0084, 0, packed) == -1, "Host must return HTTRANSPARENT"
            else:
                name = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
                user32.GetClassNameW(hwnd, name, len(name))
                assert hwnd == int(wall.winId()) or user32.IsChild(int(wall.winId()), hwnd), (
                    "Control hit left the wall", name.value, target, point.x, point.y,
                    tile.pause_button.isVisible(), int(wall.winId()), hwnd)
            clicks = []
            def callback():
                clicks.append(True)
            tile.pause_button.clicked.connect(callback)
            try:
                for _ in range(2):
                    target = tile.pause_button.mapToGlobal(tile.pause_button.rect().center())
                    QCursor.setPos(target)
                    assert QCursor.pos() == target, "Mouse moved during input check"
                    assert user32.GetCursorPos(ctypes.byref(point))
                    assert QCursor.pos() == target, "Mouse moved during input check"
                    hwnd = user32.WindowFromPoint(point)
                    target_pid = wintypes.DWORD()
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(target_pid))
                    assert target_pid.value == os.getpid(), "Input target left the test process"
                    left, top = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
                    width, height = user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)
                    x = round((point.x - left) * 65535 / (width - 1))
                    y = round((point.y - top) * 65535 / (height - 1))
                    events = (_Input * 3)(
                        _Input(0, _InputUnion(_MouseInput(x, y, 0, 0xC001, 0, 0))),
                        _Input(0, _InputUnion(_MouseInput(0, 0, 0, 0x0002, 0, 0))),
                        _Input(0, _InputUnion(_MouseInput(0, 0, 0, 0x0004, 0, 0))))
                    # SendInput keeps this move/down/up batch free from interleaved user input.
                    assert user32.SendInput(len(events), events, ctypes.sizeof(_Input)) == len(events)
                    settle(app, .05)
                assert clicks, ("Windows mouse click did not reach the underlying pause control",
                                tile.pause_button.isEnabled(), tile.pause_button.isVisible())
            finally:
                tile.pause_button.clicked.disconnect(callback)
    finally:
        QCursor.setPos(original)


def main():
    app = QApplication.instance() or QApplication(sys.argv[:1])
    assert isinstance(app, QApplication)
    if app.platformName() != "windows":
        raise RuntimeError("This check requires Windows, a desktop and hardware D3D11")
    app.setStyleSheet(theme.qss())
    with tempfile.TemporaryDirectory(prefix="ddm-d3d11-integration-") as temporary:
        root = Path(temporary)
        with patch.object(config, "REPO", temporary), patch.object(config, "CONFIG_PATH", str(root / "config.json")), \
                patch.object(images, "REPO", temporary):
            source = root / "local.mp4"
            subprocess.run([ffmpeg_path(), "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                "-i", "color=c=blue:s=1920x1080:r=30", "-t", "30", "-c:v", "libx264",
                "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(source)], check=True)
            rooms = [{"room_id": f"local-{i}", "uname": f"Local video {i}"} for i in range(4)]
            wall = WallGrid(rooms, "2x2")
            wall.setWindowTitle("D3D11 four-video integration check")
            wall.setGeometry(40, 60, 1200, 800)
            wall.show()
            wall.raise_()
            wall.activateWindow()
            user32 = ctypes.windll.user32
            user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int,
                                           ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
            user32.SetWindowPos(int(wall.winId()), -1, 0, 0, 0, 0, 0x0013)
            players = []
            layer = None
            try:
                settle(app)
                handles = [int(tile.video.winId()) for tile in wall.tiles]
                for tile in wall.tiles:
                    player = TilePlayer(tile.video, tile, silent=True)
                    players.append(player)
                    player.play(str(source))
                    tile.set_video_active(True)
                    overlay = tile.video_danmaku
                    overlay.apply_settings(dict(config.DEFAULT_SETTINGS, video_danmaku_scale=False,
                        video_danmaku_size=28, video_danmaku_area=100, video_danmaku_speed=100))
                    overlay.set_enabled(True)
                settle(app, .5)
                wait_for(app, lambda: all((player._prop("time-pos", 0) or 0) > .1 for player in players))
                for tile in wall.tiles:
                    center = tile.video.mapToGlobal(tile.video.rect().center())
                    pixel = wall.screen().grabWindow(0, center.x(), center.y(), 1, 1).toImage().pixelColor(0, 0)
                    if not (pixel.blue() > 180 and pixel.red() < 50):
                        origin = wall.mapToGlobal(QPoint())
                        wall.screen().grabWindow(0, origin.x(), origin.y(), wall.width(), wall.height()).save(
                            str(Path(__file__).resolve().parents[1] / "work/failed-video-before.png"))
                    assert pixel.blue() > 180 and pixel.red() < 50, ("Video covered before native attach", pixel.name())
                for tile in wall.tiles:
                    assert tile.video_danmaku.add_event({"text": "原生弹幕 Native Ag 😀", "color": "#ffffff"})
                layer = wall._native_danmaku_layer
                assert layer is not None
                wait_for(app, lambda: layer.status_snapshot().get("counters", {}).get("admitted", 0) >= 4)
                status = layer.status_snapshot()
                assert status["state"] == "Running", status
                assert len(status["active"]) == 4, status
                assert len({int(ref[0]) for ref in status["active"]}) == 4
                for tile in wall.tiles:
                    center = tile.video.mapToGlobal(tile.video.rect().center())
                    pixel = wall.screen().grabWindow(0, center.x(), center.y(), 1, 1).toImage().pixelColor(0, 0)
                    assert pixel.blue() > 180 and pixel.red() < 50, ("Native host covered video", pixel.name())
                assert all(not tile.video_danmaku.timer.isActive() and not tile.video_danmaku.comments
                           for tile in wall.tiles)
                check_input_target(app, wall, layer)
                settle(app, .5)
                assert all((player._prop("time-pos", 0) or 0) > 0 for player in players)
                before = layer.host.status_snapshot()["frames"]
                time.sleep(.3)
                after = layer.host.status_snapshot()["frames"]
                assert after > before + 3, ("Native motion must continue during GUI sleep", before, after)
                before = after
                until = time.perf_counter() + .3
                while time.perf_counter() < until:
                    sum(index * index for index in range(1000))
                after = layer.host.status_snapshot()["frames"]
                assert after > before + 3, ("Native motion must continue during Python work", before, after)
                for tile in wall.tiles:
                    tile.set_paused(True)
                settle(app, .2)
                paused = layer.host.status_snapshot()["frames"]
                time.sleep(.15)
                assert layer.host.status_snapshot()["frames"] <= paused + 1, "Paused host must not spin"
                for tile in wall.tiles:
                    tile.set_paused(False)
                wall.resize(1100, 740)
                settle(app, .15)
                assert handles == [int(tile.video.winId()) for tile in wall.tiles], "Danmaku changed mpv HWND"
                wall.showFullScreen()
                settle(app, .15)
                wall.showNormal()
                settle(app, .15)
                assert handles == [int(tile.video.winId()) for tile in wall.tiles], "Fullscreen changed mpv HWND"
                wall.showMinimized()
                settle(app, .2)
                assert layer.host.status_snapshot()["state"] == "Suspended"
                wall.showNormal()
                settle(app, .2)
                assert layer.host.status_snapshot()["state"] == "Running"
                menu = QMenu(wall)
                menu.addAction("Native danmaku menu remains visible")
                menu.popup(wall.mapToGlobal(QPoint(160, 160)))
                settle(app)
                assert menu.isVisible()
                assert QApplication.activePopupWidget() is menu
                menu.close()
                point = wall.mapToGlobal(QPoint())
                shot = wall.screen().grabWindow(0, point.x(), point.y(), wall.width(), wall.height())
                out = Path(__file__).resolve().parents[1] / "work/d3d11-integration.png"
                out.parent.mkdir(exist_ok=True)
                shot.save(str(out))
                for tile in wall.tiles:
                    tile.video_danmaku.clear()
                wait_for(app, lambda: not layer.host.status_snapshot()["active"])
                settle(app)
                assert not layer.window.isVisible()
                assert not layer.entries, "Metadata must be reclaimed after clear"
                layer.request_close()
                wait_for(app, layer.close_ready)
                assert layer.host.status_snapshot()["state"] == "Stopped"
                assert not layer.host.reap(), "Shutdown wrapper already reaped the host"
                assert handles == [int(tile.video.winId()) for tile in wall.tiles]
                print(f"PASS shared hardware D3D11 over four 1080p mpv windows; GUI/GIL independence, "
                      f"pause/resize/minimize/clear/async close; screenshot={out}")
                print("UNVERIFIED: final 60/120Hz display cadence and cross-monitor DPI; Win32 input targets checked")
            finally:
                if layer is not None and not layer.close_ready():
                    layer.request_close()
                    wait_for(app, layer.close_ready)
                for player in players:
                    player.release()
                wall.close()
                settle(app, .03)


if __name__ == "__main__":
    main()
