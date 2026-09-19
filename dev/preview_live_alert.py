"""把开播提醒动效按几个关键时间点抓成一条逐帧对照图（不联网、不用等真开播）。

输出：work/preview/live_alert_frames.png
"""
import os
import sys
import time

from PySide6.QtCore import QPoint, QRect, QThread, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import bili, theme  # noqa: E402
from ddm import app as app_module  # noqa: E402
from ddm.app import MainWindow  # noqa: E402
from ddm.widgets import LiveAlert  # noqa: E402

OUT = os.path.join(REPO, "work", "preview", "live_alert_frames.png")
OUT_ZOOM = os.path.join(REPO, "work", "preview", "live_alert_zoom.png")

# 抓这些时刻（毫秒），配一句说明
FRAMES = [
    (230, "0.23s 水滴从徽标上方落下"),
    (330, "0.33s 快落到了，拉成雨滴"),
    (500, "0.50s 砸中：徽标变粉「直播中」+ 涟漪"),
    (700, "0.70s 涟漪里长出气泡"),
    (1000, "1.00s 气泡弹出到位"),
    (2200, "2.20s 停留中（还会再停 1 秒）"),
    (3000, "3.00s 淡出"),
]

# 放大版：挑三个关键帧放大了看白边和细节
ZOOM_FRAMES = [
    (400, "0.40s 水滴（白边 + 高光）"),
    (560, "0.56s 砸中（光环 + 涟漪）"),
    (1000, "1.00s 气泡（白边 + 小尾巴，盖住上面一行）"),
]
ZOOM_SCALE = 2.4

ROOMS = [
    {"room_id": "3001", "uname": "上面这位主播", "title": "正在播", "live": True,
     "muted": True, "quality": 250},
    {"room_id": "3002", "uname": "刚开播的主播", "title": "开播了！", "live": True,
     "muted": True, "quality": 250},
    {"room_id": "3003", "uname": "下面这位主播", "title": "正在播", "live": True,
     "muted": True, "quality": 250},
]


class NoConnect(QThread):
    """预览不联网：顶掉状态 / 人数轮询。"""

    updated = Signal(dict)

    def __init__(self, room_ids=None, parent=None):
        super().__init__(parent)
        self.room_ids = list(room_ids or [])

    def run(self) -> None:
        return


def settle(app, seconds: float) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)


def frame_at(alert: LiveAlert, milliseconds: int) -> None:
    alert._timer.stop()                                   # noqa: SLF001
    alert._elapsed = max(0, milliseconds - 16)            # noqa: SLF001
    alert._tick()                                         # noqa: SLF001  推进并触发"砸中"
    alert.repaint()


def crop_item(sidebar, item, extra_top: int = 40) -> QPixmap:
    """把侧栏里这一行（连同上方的余地）裁出来，气泡才不会被切掉。"""
    whole = sidebar.grab()
    ratio = whole.devicePixelRatio()
    top_left = item.mapTo(sidebar, QPoint(0, 0))
    y = max(0, top_left.y() - extra_top)
    height = item.height() + (top_left.y() - y)
    return whole.copy(int(top_left.x() * ratio), int(y * ratio),
                      int(item.width() * ratio), int(height * ratio))


def main() -> None:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass
    bili.play_url = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("预览不联网"))
    app_module.StatusPoller = NoConnect
    app_module.StatsPoller = NoConnect
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())

    window = MainWindow([dict(room) for room in ROOMS], [dict(room) for room in ROOMS],
                        layout_id="2x2")
    window.setGeometry(-8000, -8000, 1300, 760)
    window.show()
    settle(app, 1.0)

    item = window.sidebar.items()[1]          # 第二行：气泡正好能盖到上面那一行
    for index, entry in enumerate(window.sidebar.items()):     # 缩略图也给张封面
        pixmap = QPixmap(320, 180)
        pixmap.fill(QColor(["#3d5a80", "#5f4b8b", "#2d6a4f"][index % 3]))
        entry.thumb.set_cover(pixmap)
    item.set_live(False)                      # 手动走一遍完整动效（原右键测试项已删）
    item.play_live_alert()
    settle(app, 0.1)
    alert = item._alert                       # noqa: SLF001
    assert alert is not None, "动效没起来"

    shots: list[tuple[QPixmap, str]] = []
    for milliseconds, caption in FRAMES:
        frame_at(alert, milliseconds)
        settle(app, 0.05)
        shots.append((crop_item(window.sidebar, item), caption))

    width = max(pixmap.width() for pixmap, _ in shots) + 24
    label_height = 22
    height = sum(pixmap.height() + label_height + 8 for pixmap, _ in shots) + 24
    sheet = QPixmap(width, height)
    sheet.fill(QColor(theme.BG))
    painter = QPainter(sheet)
    painter.setRenderHint(QPainter.Antialiasing, True)
    font = QFont(theme.FONT_DEFAULT)
    font.setPixelSize(13)
    painter.setFont(font)
    y = 12
    for pixmap, caption in shots:
        painter.setPen(QColor(theme.TEXT2))
        painter.drawText(QRect(12, y, width - 24, label_height),
                         int(Qt.AlignVCenter | Qt.AlignLeft), caption)
        y += label_height
        painter.drawPixmap(12, y, pixmap)
        y += pixmap.height() + 8
    painter.end()
    sheet.save(OUT, "PNG")
    print(f"已保存 {OUT}（{len(shots)} 帧）")

    zoomed = []
    for milliseconds, caption in ZOOM_FRAMES:
        frame_at(alert, milliseconds)
        settle(app, 0.05)
        pixmap = crop_item(window.sidebar, item)
        zoomed.append((pixmap.scaled(int(pixmap.width() * ZOOM_SCALE),
                                     int(pixmap.height() * ZOOM_SCALE),
                                     Qt.KeepAspectRatio, Qt.SmoothTransformation), caption))
    width = max(pixmap.width() for pixmap, _ in zoomed) + 24
    height = sum(pixmap.height() + label_height + 10 for pixmap, _ in zoomed) + 24
    zoom_sheet = QPixmap(width, height)
    zoom_sheet.fill(QColor(theme.BG))
    painter = QPainter(zoom_sheet)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setFont(font)
    y = 12
    for pixmap, caption in zoomed:
        painter.setPen(QColor(theme.TEXT2))
        painter.drawText(QRect(12, y, width - 24, label_height),
                         int(Qt.AlignVCenter | Qt.AlignLeft), caption)
        y += label_height
        painter.drawPixmap(12, y, pixmap)
        y += pixmap.height() + 10
    painter.end()
    zoom_sheet.save(OUT_ZOOM, "PNG")
    print(f"已保存 {OUT_ZOOM}（{len(zoomed)} 帧，放大 {ZOOM_SCALE}x）")
    window.close()


if __name__ == "__main__":
    main()
