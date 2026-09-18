"""渲染预览：全局设置窗口、收起后的侧栏头像居中、信息条状态提示。"""
import os
import sys
import time

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import theme  # noqa: E402
from ddm.app import MainWindow  # noqa: E402
from ddm.dialogs import SettingsDialog  # noqa: E402

OUT = os.path.join(REPO, "work", "preview")
NOW = int(time.time())

ROOMS = [
    {"room_id": "1001", "uname": "示例主播A", "title": "示例直播标题", "live": True,
     "viewers": "3.1万", "muted": True, "volume": 55, "live_start_ts": NOW - 4512},
    {"room_id": "1002", "uname": "示例主播B", "title": "示例标题二",
     "live": True, "viewers": "1.8万", "online": "2288", "muted": True, "volume": 42,
     "live_start_ts": NOW - 890},
]
COLORS = ["#3d5a80", "#5f4b8b"]


def cover_pixmap(name: str, color: str) -> QPixmap:
    pixmap = QPixmap(QSize(1280, 720))
    painter = QPainter(pixmap)
    gradient = QLinearGradient(0, 0, 1280, 720)
    gradient.setColorAt(0.0, QColor(color))
    gradient.setColorAt(1.0, QColor("#11131a"))
    painter.fillRect(0, 0, 1280, 720, gradient)
    font = QFont("Microsoft YaHei UI", 64)
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QColor(255, 255, 255, 210))
    painter.drawText(QRectF(0, 0, 1280, 720), int(Qt.AlignCenter), name)
    painter.end()
    return pixmap


def face_pixmap(color: str) -> QPixmap:
    """预览用的头像（纯色圆，不放名字）。"""
    pixmap = QPixmap(QSize(128, 128))
    painter = QPainter(pixmap)
    gradient = QLinearGradient(0, 0, 128, 128)
    gradient.setColorAt(0.0, QColor(color).lighter(125))
    gradient.setColorAt(1.0, QColor(color).darker(115))
    painter.fillRect(0, 0, 128, 128, gradient)
    painter.end()
    return pixmap


def settle(app, seconds):
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.03)


def main() -> None:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())

    window = MainWindow([dict(room) for room in ROOMS], [], layout_id="1x2")
    window.setGeometry(-8000, -8000, 1400, 800)
    window.show()
    settle(app, 0.8)
    for index, room in enumerate(ROOMS):
        tile = window.wall.add_room(dict(room))
        tile.set_cover(cover_pixmap(room["uname"], COLORS[index % len(COLORS)]))
        tile.start_elapsed_timer()
    for index, entry in enumerate(window.sidebar.items()):
        entry.thumb.set_cover(cover_pixmap(entry.room["uname"], COLORS[index % len(COLORS)]))
        entry.thumb.set_face(face_pixmap(COLORS[index % len(COLORS)]))
    window.sidebar.set_layout_name("1x2")
    window._refresh_meta()
    settle(app, 0.6)

    # 一格显示"正在获取人数"，另一格显示"缓冲中…"
    window.wall.tiles[1].set_watched("2288")
    window.wall.tiles[0].set_buffering(True)
    settle(app, 0.6)
    window.grab().save(os.path.join(OUT, "wall_status.png"), "PNG")
    print("已保存 wall_status.png")

    # 收起侧栏：头像要居中
    window.sidebar.set_account("示例主播A")
    window.sidebar.set_collapsed(True, animate=False)
    settle(app, 0.6)
    window.sidebar.grab().save(os.path.join(OUT, "sidebar_rail.png"), "PNG")
    print("已保存 sidebar_rail.png")
    window.sidebar.set_collapsed(False, animate=False)
    settle(app, 0.3)

    dialog = SettingsDialog(window.settings, window.shortcuts, window)
    dialog.move(-8000, -8000)
    dialog.show()
    settle(app, 0.6)
    dialog.grab().save(os.path.join(OUT, "dialog_settings.png"), "PNG")
    print("已保存 dialog_settings.png")
    dialog.nav.setCurrentRow(1)
    settle(app, 0.4)
    dialog.grab().save(os.path.join(OUT, "dialog_danmaku.png"), "PNG")
    print("已保存 dialog_danmaku.png")
    dialog.nav.setCurrentRow(2)
    settle(app, 0.4)
    dialog.grab().save(os.path.join(OUT, "dialog_shortcuts.png"), "PNG")
    print("已保存 dialog_shortcuts.png")
    dialog.close()

    window.close()


if __name__ == "__main__":
    main()
