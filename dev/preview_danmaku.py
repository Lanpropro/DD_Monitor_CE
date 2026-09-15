"""渲染预览：带弹幕的独立布局、暂停图形按钮、标题浮窗（不联网、不落盘）。"""
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
from ddm.widgets import LayoutPicker, Tile  # noqa: E402

OUT = os.path.join(REPO, "dev", "preview")
NOW = int(time.time())

ROOMS = [
    {"room_id": "6154037", "uname": "Asaki大人", "title": "随便玩玩战狗", "live": True,
     "viewers": "3.1万", "online": "7124", "muted": True, "volume": 55,
     "live_start_ts": NOW - 4512},
    {"room_id": "21452505", "uname": "七海Nana7mi", "title": "和队友最后练一次大米",
     "live": True, "viewers": "1.8万", "online": "2288", "muted": True, "volume": 42,
     "live_start_ts": NOW - 890},
    {"room_id": "26376408", "uname": "烛不遥", "title": "看新三国吐槽——", "live": True,
     "viewers": "6.1万", "online": "1043", "muted": True, "volume": 70,
     "live_start_ts": NOW - 12800},
    {"room_id": "22603245", "uname": "永雏塔菲", "title": "守望先锋（9）", "live": True,
     "viewers": "9.4万", "online": "5602", "muted": True, "volume": 36,
     "live_start_ts": NOW - 305},
]

DANMAKU = [
    ("天草_", "这个操作太秀了", "#ff7f50"),
    ("打工人已下班", "前面的等等我", "#7bc96f"),
    ("夜航星", "哈哈哈这也行", "#f0c674"),
    ("一条小白鲨", "主播今天状态真好", "#e36ea7"),
    ("阿岚", "已三连", "#00a1d6"),
    ("深海鲸鱼", "画面好高清啊", "#9b8cff"),
    ("咕咕咕", "什么时候睡觉", "#66c2cd"),
    ("纸片人观察员", "弹幕占一格，画面不挤了", "#ff9f43"),
    ("路人甲", "打卡打卡", "#8ab4f8"),
    ("夜猫子", "这段我来回看了三遍", "#f28b82"),
    ("路人乙", "主播加油！", "#7fdbca"),
    ("小北", "刚来，前面发生了什么", "#c792ea"),
]

COLORS = ["#3d5a80", "#5f4b8b", "#2d6a4f", "#7a4a3a"]


def cover_pixmap(name: str, color: str, size=(1280, 720)) -> QPixmap:
    pixmap = QPixmap(QSize(*size))
    painter = QPainter(pixmap)
    gradient = QLinearGradient(0, 0, size[0], size[1])
    gradient.setColorAt(0.0, QColor(color))
    gradient.setColorAt(1.0, QColor("#11131a"))
    painter.fillRect(0, 0, size[0], size[1], gradient)
    painter.setPen(QColor(255, 255, 255, 26))
    for index in range(0, size[0], 40):
        painter.drawLine(index, 0, index, size[1])
    font = QFont("Microsoft YaHei UI", 64)
    font.setBold(True)
    painter.setFont(font)
    painter.setPen(QColor(255, 255, 255, 210))
    painter.drawText(QRectF(0, 0, size[0], size[1]), int(Qt.AlignCenter), name)
    painter.setFont(QFont("Microsoft YaHei UI", 26))
    painter.setPen(QColor(255, 255, 255, 120))
    painter.drawText(QRectF(0, size[1] * 0.62, size[0], size[1] * 0.2),
                     int(Qt.AlignCenter), "直播画面预览")
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
    os.makedirs(OUT, exist_ok=True)

    window = MainWindow([dict(room) for room in ROOMS], [], layout_id="dm_main3")
    window.setGeometry(-8000, -8000, 1600, 900)
    window.show()
    settle(app, 0.8)

    for index, room in enumerate(ROOMS):
        tile = window.wall.add_room(dict(room))
        tile.set_cover(cover_pixmap(room["uname"], COLORS[index % len(COLORS)]))
        tile.set_watched(room["online"])
        tile.start_elapsed_timer()
    window.wall.set_layout("dm_main3")
    window.sidebar.set_layout_name("dm_main3")
    window._refresh_meta()
    settle(app, 0.6)

    window.wall.danmaku.set_sample(DANMAKU[:9])
    window.wall.tiles[1].set_controls_visible(True)      # 展示右上角控制条
    window.wall.tiles[2]._player_active = True
    window.wall.tiles[2].set_paused(True)                # 展示"已暂停"
    settle(app, 0.8)

    window.grab().save(os.path.join(OUT, "wall_danmaku.png"), "PNG")
    print("已保存 wall_danmaku.png")

    tile = window.wall.tiles[0]
    tile.grab().save(os.path.join(OUT, "tile_chrome.png"), "PNG")
    print("已保存 tile_chrome.png")

    picker = LayoutPicker("dm_main3", window)
    picker.move(-8000, -8000)
    picker.show()
    settle(app, 0.6)
    picker.grab().save(os.path.join(OUT, "picker_danmaku.png"), "PNG")
    print("已保存 picker_danmaku.png")
    picker.set_group("普通布局")
    settle(app, 0.4)
    picker.grab().save(os.path.join(OUT, "picker_normal.png"), "PNG")
    print("已保存 picker_normal.png")
    picker.close()

    # 侧栏拖动排序的高亮线
    sidebar = window.sidebar
    if len(sidebar.items()) >= 3:
        sidebar.toggle_pin(sidebar.items()[0].room)
        settle(app, 0.4)
        held = sidebar.items()[2]
        ghost = held._drag_pixmap()          # 拖动时跟着鼠标的那张卡片
        ghost.save(os.path.join(OUT, "nav_ghost.png"), "PNG")
        sidebar.show_drop_indicator(str(held.room.get("room_id")), 4)
        settle(app, 0.5)
        sidebar.grab().save(os.path.join(OUT, "sidebar_drag.png"), "PNG")
        print("已保存 sidebar_drag.png / nav_ghost.png")

    # 下播：画面清黑，格子保留
    window.wall.tiles[1].set_offline()
    settle(app, 0.5)
    window.grab().save(os.path.join(OUT, "wall_offline.png"), "PNG")
    print("已保存 wall_offline.png")

    window.close()


if __name__ == "__main__":
    main()
