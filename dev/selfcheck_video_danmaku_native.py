"""真 VLC 画面上的弹幕透明度、原生命中、重连及多格/全屏切换。"""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import config, theme
from ddm.app import MainWindow
from ddm.player import TilePlayer
from ddm.recording import ffmpeg_path
from selfcheck_video_danmaku import Client


def settle(app, seconds=.15):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(.01)


def show_comment(tile, opacity):
    overlay = tile.video_danmaku
    overlay.set_paused(False)
    overlay.apply_settings(dict(config.DEFAULT_SETTINGS, video_danmaku_scale=False,
                                video_danmaku_size=32, video_danmaku_opacity=opacity))
    assert overlay.add_event({"text": "这是直播画面弹幕", "color": "#ffffff"})
    overlay.set_paused(True)
    overlay.comments[0].x = 30
    overlay.comments[0].lane = 2
    tile.set_controls_visible(False)
    tile.raise_overlays()
    overlay.update()


def capture(tile):
    point = tile.video.mapToGlobal(QPoint())
    return tile.screen().grabWindow(0, point.x(), point.y(),
                                    tile.video.width(), tile.video.height()).toImage()


def brightest_text(image, tile):
    scale = image.devicePixelRatio()
    overlay = tile.video_danmaku
    comment = overlay.comments[0]
    left = max(0, round(comment.x * scale))
    top = round(comment.lane * overlay.lane_height() * scale)
    width = comment.image.width() / comment.image.devicePixelRatioF()
    height = comment.image.height() / comment.image.devicePixelRatioF()
    return max(image.pixelColor(x, y).green()
               for y in range(top, min(image.height(), top + round(height * scale)))
               for x in range(left, min(image.width(), left + round(width * scale))))


def main():
    app = QApplication(sys.argv)
    if app.platformName() != "windows":
        print("跳过：需要 Windows 原生窗口")
        return
    app.setStyleSheet(theme.qss())
    rooms = [{"room_id": str(1000 + i), "uname": f"本地视频 {i}", "live": False}
             for i in range(4)]
    with tempfile.TemporaryDirectory(prefix="ddm-video-dm-") as temp, \
            patch("ddm.app.DanmakuClient", Client), patch.object(MainWindow, "start_tile"), \
            patch.object(MainWindow, "refresh_status"), patch.object(MainWindow, "refresh_stats"):
        source = str(Path(temp) / "blue.mp4")
        subprocess.run([ffmpeg_path(), "-y", "-hide_banner", "-loglevel", "error",
                        "-f", "lavfi", "-i", "color=c=blue:s=640x360:r=25",
                        "-t", "30", "-c:v", "libx264", "-preset", "ultrafast",
                        "-pix_fmt", "yuv420p", source], check=True)
        window = MainWindow(rooms, [dict(room) for room in rooms], layout_id="2x2",
                            state={"plugins_enabled": []})
        window.setGeometry(40, 60, 1200, 800)
        window.show()
        window.activateWindow()
        QCursor.setPos(0, 0)
        settle(app)
        try:
            for tile in window.wall.tiles:
                tile.room["live"] = True
                player = TilePlayer(tile.video, tile, silent=True)
                window.players[tile] = player
                player.play(source)
                tile.set_video_active(True)
                tile.danmaku_button.setChecked(True)
            settle(app, 2)
            assert all(player.player.get_time() > 0 for player in window.players.values())
            target = window.wall.tiles[0]
            for tile in window.wall.tiles:
                show_comment(tile, 100)
            settle(app)
            high = capture(target)
            shot = Path(tempfile.gettempdir()) / "ddm-video-danmaku-native.png"
            frame = window.frameGeometry()
            window.screen().grabWindow(0, frame.x(), frame.y(), frame.width(), frame.height()).save(str(shot))
            print(f"多格子截图：{shot}")
            assert brightest_text(high, target) > 200, "弹幕应显示在真实 VLC 画面之上"
            center = high.pixelColor(high.width() // 2, high.height() // 2)
            assert center.blue() > 200 and center.red() < 40, "透明区域不能遮黑视频"
            show_comment(target, 20)
            settle(app)
            low = capture(target)
            assert brightest_text(low, target) < brightest_text(high, target) - 100, "不透明度修改应影响真实画面"
            user32 = ctypes.windll.user32
            user32.ChildWindowFromPointEx.argtypes = [wintypes.HWND, wintypes.POINT, wintypes.UINT]
            user32.ChildWindowFromPointEx.restype = wintypes.HWND
            point = target.video.pos() + QPoint(80, 92)
            scale = target.devicePixelRatioF()
            hit = user32.ChildWindowFromPointEx(int(target.winId()),
                                               wintypes.POINT(round(point.x() * scale),
                                                              round(point.y() * scale)), 7)
            assert hit != int(target.video_danmaku.winId()), "弹幕窗口必须鼠标穿透"
            user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
            user32.WindowFromPoint.argtypes = [wintypes.POINT]
            user32.WindowFromPoint.restype = wintypes.HWND
            screen_point = wintypes.POINT(round(point.x() * scale), round(point.y() * scale))
            user32.ClientToScreen(int(target.winId()), ctypes.byref(screen_point))
            assert user32.WindowFromPoint(screen_point) != int(target.video_danmaku.winId()), \
                "实际鼠标命中不能被弹幕遮挡"
            handle = int(target.video.winId())
            overlay = target.video_danmaku
            comment = overlay.comments[0]
            overlay.apply_settings(dict(overlay.settings, video_danmaku_opacity=100))
            QTest.mouseClick(target.danmaku_settings_button, Qt.LeftButton)
            settle(app)
            assert target.danmaku_settings_menu.isVisible(), "设置浮层应能显示在 VLC 窗口之上"
            target.danmaku_settings_menu.controls["video_danmaku_opacity"].setValue(25)
            settle(app)
            assert window.settings["video_danmaku_opacity"] == 25
            assert brightest_text(capture(target), target) < 120
            target.danmaku_settings_menu.controls["video_danmaku_opacity"].setValue(100)
            QTest.keyClick(target.danmaku_settings_menu, Qt.Key_Escape)
            window._on_fullscreen(target)
            window._clear_fullscreen_cover()
            settle(app)
            assert overlay.comments[0] is comment, "进入全屏不能通过清屏后重新发弹幕来恢复画面"
            assert int(target.video.winId()) == handle
            assert brightest_text(capture(target), target) > 200
            window._exit_fullscreen()
            window._clear_fullscreen_cover()
            settle(app)
            assert overlay.comments[0] is comment, "退出全屏也应保留当前弹幕"
            # 原生播放窗口重建后，弹幕仍应在上面，播放器本身不需要换掉。
            window.players[target].play(source)
            settle(app, 1)
            show_comment(target, 100)
            settle(app)
            assert brightest_text(capture(target), target) > 200
            target.danmaku_button.setChecked(False)
            settle(app)
            disabled = capture(target)
            assert max(disabled.pixelColor(x, 100).green() for x in range(30, 300)) < 100
        finally:
            window.close()
    print("真 VLC 多格子/全屏弹幕、透明背景、不透明度、鼠标穿透与重连：通过")


if __name__ == "__main__":
    main()
