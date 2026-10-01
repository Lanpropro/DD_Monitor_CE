"""Windows 原生鼠标命中检查；可传入本地视频，验证多路 VLC 播放。"""
import ctypes
from ctypes import wintypes
import os
import sys
import time
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QMenu

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
from ddm import theme  # noqa: E402
from ddm.widgets import WallGrid  # noqa: E402
from ddm.player import TilePlayer  # noqa: E402


def settle(app, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.01)


def main():
    if os.name != "nt":
        print("Skipped: Windows native window test")
        return
    app = QApplication(sys.argv)
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

    for layout, count in (("2x2", 4), ("3x2", 6), ("3x3", 9),
                          ("portrait_main6", 7)):
        wall = WallGrid([{"room_id": str(i + 1), "uname": str(i), "live": True,
                          "quality": 250} for i in range(count)], layout_id=layout)
        wall.setGeometry(-9000, -9000, 1200, 800)
        wall.show()
        settle(app, 0.2)
        for tile in wall.tiles:
            tile.set_controls_visible(True)
        players = []
        try:
            if len(sys.argv) > 1:
                for tile in wall.tiles:
                    player = TilePlayer(tile.video, silent=True)
                    player.play(sys.argv[1])
                    players.append(player)
                settle(app, 2)
                assert all(p.player.get_time() > 0 for p in players), "Video did not start"
                # 保持浮层已显示，模拟所有播放器重建视频窗口。
                for player in players:
                    player.play(sys.argv[1])
                settle(app, 1)
                assert all(p.player.get_time() > 0 for p in players), "Restart did not finish"
            wall.set_fullscreen_tile(wall.tiles[-1])
            settle(app, 0.1)
            wall.set_fullscreen_tile(None)
            settle(app, 0.1)
            settle(app, 0.1)
            for index, tile in enumerate(wall.tiles):
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

                with patch("ddm.widgets.QMenu", TestMenu):
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
            wall.deleteLater()
            settle(app, 0.1)
    print("Native control hit checks passed", flush=True)


if __name__ == "__main__":
    main()
    os._exit(0)
