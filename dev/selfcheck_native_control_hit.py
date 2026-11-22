"""Windows 原生控件命中回归；默认生成本地视频，也可传入文件。"""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication, QHBoxLayout, QMenu, QVBoxLayout, QWidget

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from ddm import theme  # noqa: E402
from ddm.widgets import WallGrid  # noqa: E402
from ddm.player import TilePlayer  # noqa: E402
from selfcheck_mpv import ready


def settle(app, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)


def main(source=None):
    if os.name != "nt":
        print("Skipped: Windows native window test")
        return
    app = QApplication(sys.argv)
    app.setAttribute(Qt.AA_DontCreateNativeWidgetSiblings, True)
    app.setStyleSheet(theme.qss())
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.ChildWindowFromPointEx.argtypes = [wintypes.HWND, wintypes.POINT, wintypes.UINT]
    user32.ChildWindowFromPointEx.restype = wintypes.HWND
    user32.MapWindowPoints.argtypes = [wintypes.HWND, wintypes.HWND,
                                       ctypes.POINTER(wintypes.POINT), wintypes.UINT]
    user32.IsChild.argtypes = [wintypes.HWND, wintypes.HWND]
    user32.IsChild.restype = wintypes.BOOL
    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                    wintypes.WPARAM, wintypes.LPARAM]
    user32.SendMessageW.restype = wintypes.LPARAM
    user32.GetParent.argtypes = (wintypes.HWND,)
    user32.GetParent.restype = wintypes.HWND

    def hit(tile, button):
        hwnd = int(tile.winId())
        point = button.mapTo(tile, button.rect().center())
        scale = tile.devicePixelRatioF()
        point = wintypes.POINT(round(point.x() * scale), round(point.y() * scale))
        for _ in range(15):
            child = user32.ChildWindowFromPointEx(hwnd, point, 3)
            if not child or child == hwnd:
                return hwnd
            user32.MapWindowPoints(hwnd, child, ctypes.byref(point), 1)
            hwnd = child
        raise AssertionError("Native window recursion did not stop")

    def show_controls(tile):
        # 屏外窗口不移动系统鼠标；固定悬停显示状态，单独检查原生窗口命中。
        tile.set_controls_visible(True)
        tile._control_hover_timer.stop()
        tile._controls_hide_timer.stop()
        app.processEvents()
        assert tile.controls.isVisible(), "Controls must be visible before hit testing"

    for layout, count in (("2x2", 4), ("3x2", 6), ("3x3", 9),
                          ("portrait_main6", 7)):
        host = QWidget()
        host.setAttribute(Qt.WA_ShowWithoutActivating)
        host.setGeometry(-9000, -9000, 1480, 800)
        row = QHBoxLayout(host)
        sidebar = QWidget(host)
        sidebar.setFixedWidth(280)
        row.addWidget(sidebar)
        content = QWidget(host)
        row.addWidget(content, 1)
        column = QVBoxLayout(content)
        wall = WallGrid([{"room_id": str(i + 1), "uname": str(i), "live": True,
                          "quality": 250} for i in range(count)], layout_id=layout, parent=content)
        column.addWidget(wall)
        host.show()
        settle(app, 0.2)
        assert content.internalWinId() and not sidebar.internalWinId()
        assert user32.GetParent(int(wall.winId())) == int(content.internalWinId())
        origin = wintypes.POINT()
        user32.MapWindowPoints(int(wall.winId()), int(host.winId()), ctypes.byref(origin), 1)
        position = wall.mapTo(host, QPoint())
        scale = wall.devicePixelRatioF()
        assert abs(origin.x-round(position.x()*scale)) <= 1
        assert abs(origin.y-round(position.y()*scale)) <= 1
        for tile in wall.tiles:
            show_controls(tile)
        players = []
        try:
            if source:
                for tile in wall.tiles:
                    player = TilePlayer(tile.video, silent=True)
                    player.play(source)
                    players.append(player)
                for player in players:
                    ready(app, player)
                # 保持浮层已显示，模拟所有播放器重建视频窗口。
                for player in players:
                    player.play(source)
                for player in players:
                    ready(app, player)
            wall.set_fullscreen_tile(wall.tiles[-1])
            settle(app, 0.1)
            wall.set_fullscreen_tile(None)
            settle(app, 0.1)
            settle(app, 0.1)
            for index, tile in enumerate(wall.tiles):
                show_controls(tile)
                controls = int(tile.controls.winId())
                for button in (tile.quality_button, tile.reload_button, tile.close_button):
                    target = hit(tile, button)
                    ok = target == controls or user32.IsChild(controls, target)
                    print(layout, index, button.text(), "hit", hex(target),
                          "controls", hex(controls), "OK" if ok else "BLOCKED", flush=True)
                    assert ok, "Native video blocked controls"
                reloads, closes = [], []
                tile.reloadRequested.connect(reloads.append)
                tile.closeRequested.connect(closes.append)

                class TestMenu(QMenu):
                    def exec(self, _pos):
                        next(a for a in self.actions() if a.text() == "流畅").trigger()

                with patch("ddm.tile_widgets.QMenu", TestMenu):
                    for button in (tile.quality_button, tile.reload_button, tile.close_button):
                        pos = button.mapTo(tile.controls, button.rect().center())
                        scale = tile.devicePixelRatioF()
                        packed = round(pos.x() * scale) | (round(pos.y() * scale) << 16)
                        user32.SendMessageW(controls, 0x0201, 1, packed)
                        user32.SendMessageW(controls, 0x0202, 0, packed)
                        app.processEvents()
                assert tile.quality == 80, "Native click did not change quality"
                assert len(reloads) == len(closes) == 1, "Native click did not emit action"
        finally:
            for player in players:
                player.release()
            wall.close()
            host.close()
            host.deleteLater()
            settle(app, 0.1)
    print("Native control hit checks passed", flush=True)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        main(sys.argv[1])
    else:
        with tempfile.TemporaryDirectory(prefix='ddm-native-controls-') as directory:
            source = str(Path(directory) / 'blue.mp4')
            subprocess.run([shutil.which('ffmpeg') or 'ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
                            '-f', 'lavfi', '-i', 'color=c=blue:s=320x180:r=30', '-t', '20',
                            '-c:v', 'libx264', '-preset', 'ultrafast', '-pix_fmt', 'yuv420p', source],
                           check=True, timeout=30)
            main(source)
    os._exit(0)
