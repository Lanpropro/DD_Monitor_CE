"""滚动弹幕亚像素采样与暂停/继续图标中心回归。"""
import os
from pathlib import Path
import sys
import time
from unittest.mock import Mock, patch

from PySide6.QtCore import QCoreApplication, QEvent, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm.video_danmaku import VideoDanmaku, _TimerResolution
from ddm.widgets import PauseButton


def check_sampling():
    overlay = VideoDanmaku()
    overlay.resize(900, 540)
    overlay.apply_settings({"video_danmaku_scale": False, "video_danmaku_size": 28})
    emoji = QImage(24, 24, QImage.Format_ARGB32_Premultiplied)
    emoji.fill(QColor("#ff9900"))
    overlay._images["test:emoji"] = emoji
    try:
        for ratio in (1, 1.75, 2):
            with patch.object(overlay, "devicePixelRatioF", return_value=ratio):
                images = [overlay._render_text("流畅滚动 Ag", QColor("white")),
                          overlay._render_content("弹幕", QColor("white"),
                                                  [("弹幕", ""), ("", "test:emoji")])]
            for source in images:
                assert source.devicePixelRatioF() == ratio * 2
                frames = []
                for phase in (0, .25, .5, .75):
                    frame = QImage(round(400 * ratio), round(80 * ratio),
                                   QImage.Format_ARGB32_Premultiplied)
                    frame.setDevicePixelRatio(ratio)
                    frame.fill(Qt.black)
                    painter = QPainter(frame)
                    painter.setRenderHint(QPainter.SmoothPixmapTransform)
                    painter.drawPixmap(QPointF(10 + phase / ratio, 0), source)
                    painter.end()
                    frames.append(bytes(frame.bits()))
                assert len(set(frames)) == 4, "四个亚像素位置不能吸附为两个整像素位置"
    finally:
        overlay.close()


def check_motion_clock(app):
    overlay = VideoDanmaku()
    overlay.set_native_video(False)
    overlay.resize(900, 540)
    overlay.set_enabled(True)
    overlay.set_active(True)
    app.processEvents()
    try:
        with patch("time.monotonic", return_value=100):
            assert overlay.add_event({"text": "Sub-frame clock precision"})
            comment = overlay.comments[0]
            x = comment.x
            time.sleep(.006)
            overlay._tick()
            assert comment.x < x - .2, "Motion must advance even inside one monotonic tick"
    finally:
        overlay.close()


def check_icon_centers(app):
    button = PauseButton()
    button.setStyleSheet("QPushButton {background: black; border: none;}")
    button.show()
    try:
        for width in (26, 34):
            button.setFixedSize(width, 26)
            for paused in (False, True):
                button.set_paused(paused)
                app.processEvents()
                with patch("ddm.widgets._icon_color", return_value=QColor("white")):
                    image = button.grab().toImage()
                mass = x_sum = y_sum = 0
                for y in range(image.height()):
                    for x in range(image.width()):
                        weight = image.pixelColor(x, y).red()
                        mass += weight
                        x_sum += (x + .5) * weight
                        y_sum += (y + .5) * weight
                assert mass > 0
                ratio = image.devicePixelRatio()
                assert abs(x_sum / mass - button.width() * ratio / 2) < .2, (width, paused, "x")
                assert abs(y_sum / mass - button.height() * ratio / 2) < .2, (width, paused, "y")
    finally:
        button.close()


def check_timer_resolution(app):
    import ctypes
    if sys.platform != "win32":
        resolution = _TimerResolution()
        resolution.acquire()
        assert resolution._winmm is None
        return
    winmm = Mock()
    winmm.timeBeginPeriod.return_value = 0
    with patch("ctypes.windll.winmm", winmm), \
            patch.object(QApplication, "platformName", return_value="windows"):
        resolution = _TimerResolution()
        resolution.acquire()
        resolution.acquire()
        winmm.timeBeginPeriod.assert_called_once_with(1)
        resolution.release()
        resolution.release()
        winmm.timeEndPeriod.assert_called_once_with(1)
        winmm.reset_mock()
        overlay = VideoDanmaku()
        overlay.set_native_video(False)
        overlay.resize(900, 540)
        overlay.set_enabled(True)
        overlay.set_active(True)
        app.processEvents()
        try:
            assert overlay.add_event({"text": "计时精度生命周期"})
            assert overlay._timer_resolution._winmm is winmm
            overlay.set_paused(True)
            assert overlay._timer_resolution._winmm is None
            overlay.set_paused(False)
            assert overlay._timer_resolution._winmm is winmm
            overlay.hide()
            assert overlay._timer_resolution._winmm is None
            overlay.show()
            assert overlay._timer_resolution._winmm is winmm
            overlay.comments[0].x = -10000
            overlay._tick()
            assert not overlay.comments and overlay._timer_resolution._winmm is None
            assert overlay.add_event({"text": "清空后释放"})
            overlay.clear()
            assert overlay._timer_resolution._winmm is None
            assert overlay.add_event({"text": "销毁后释放"})
            overlay.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
            assert winmm.timeBeginPeriod.call_count == winmm.timeEndPeriod.call_count == 5
        finally:
            if overlay._timer_resolution._winmm is not None:
                overlay.close()
        winmm.timeBeginPeriod.return_value = 1
        winmm.reset_mock()
        resolution.acquire()
        assert resolution._winmm is None
        resolution.release()
        winmm.timeEndPeriod.assert_not_called()
        winmm.timeBeginPeriod.return_value = 0
        with patch.object(QApplication, "platformName", return_value="offscreen"):
            winmm.reset_mock()
            resolution.acquire()
            winmm.timeBeginPeriod.assert_not_called()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    check_sampling()
    check_motion_clock(app)
    check_icon_centers(app)
    check_timer_resolution(app)
    print("弹幕亚像素滚动、高精度时钟、图标居中与定时精度申请/释放：通过")
