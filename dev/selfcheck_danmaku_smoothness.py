"""滚动弹幕亚像素采样与暂停/继续图标中心回归。"""
import os
from pathlib import Path
import sys
from unittest.mock import patch

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm.video_danmaku import VideoDanmaku
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


if __name__ == "__main__":
    app = QApplication(sys.argv)
    check_sampling()
    check_icon_centers(app)
    print("弹幕文字/表情亚像素滚动与暂停/继续图标居中：通过")
