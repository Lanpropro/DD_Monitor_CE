"""放大渲染：暂停图标、刷新图标（画面格 + 侧栏）看看细节。"""
import os
import sys
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import theme  # noqa: E402
from ddm.app import MainWindow  # noqa: E402

OUT = os.path.join(REPO, "dev", "preview")
SCALE = 4

ROOM = {"room_id": "1001", "uname": "示例主播A", "title": "示例直播标题", "live": True,
        "viewers": "3.1万", "online": "7124", "muted": True, "volume": 55}


def settle(app, seconds):
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.03)


def shots(widget):
    """放大 + 深色底，方便看清线条。"""
    pixmap = widget.grab()
    result = QPixmap(pixmap.width() * SCALE + 40, pixmap.height() * SCALE + 40)
    result.fill(QColor(theme.BG))
    painter = QPainter(result)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    painter.drawPixmap(20, 20,
                       pixmap.scaled(pixmap.width() * SCALE, pixmap.height() * SCALE,
                                     Qt.KeepAspectRatio, Qt.SmoothTransformation))
    painter.end()
    return result


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())
    window = MainWindow([dict(ROOM)], [], layout_id="dm_pair")
    window.setGeometry(-8000, -8000, 1200, 700)
    window.show()
    settle(app, 0.6)
    tile = window.wall.add_room(dict(ROOM))
    tile.set_controls_visible(True)
    settle(app, 0.5)

    def zoom(widget):
        pixmap = widget.grab()
        return pixmap.scaled(pixmap.width() * SCALE, pixmap.height() * SCALE,
                             Qt.KeepAspectRatio, Qt.SmoothTransformation)

    shots_list = [("右上角控制条（画质 / 刷新 / 关闭）", zoom(tile.controls)),
                  ("暂停图标（播放中）", zoom(tile.pause_button))]
    tile.set_paused(True)
    settle(app, 0.3)
    shots_list.append(("暂停图标（已暂停 -> 继续）", zoom(tile.pause_button)))
    shots_list.append(("侧栏刷新图标", zoom(window.sidebar.refresh_button)))

    height = 20 + sum(30 + pixmap.height() for _label, pixmap in shots_list)
    sheet = QPixmap(900, height)
    sheet.fill(QColor(theme.BG))
    painter = QPainter(sheet)
    painter.setFont(QFont("Microsoft YaHei UI", 11))
    y = 10
    for label, pixmap in shots_list:
        painter.setPen(QColor(theme.TEXT1))
        painter.drawText(20, y + 18, label)
        painter.drawPixmap(20, y + 26, pixmap)
        y += 26 + pixmap.height() + 10
    painter.end()
    out = os.path.join(OUT, "icons.png")
    sheet.save(out, "PNG")
    print("已保存", out)
    window.close()


if __name__ == "__main__":
    main()
