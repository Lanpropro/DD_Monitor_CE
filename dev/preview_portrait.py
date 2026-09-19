"""竖屏适配原型：把当前代码在竖屏尺寸下真实渲染出来，供确认「哪些已经能用」。

用法：
    python dev\\preview_portrait.py

输出到 dev/preview/（已在 .gitignore 里）：
    portrait_landscape.png      横屏基准（1600x900），用来对照
    portrait_full.png           竖屏 + 侧栏展开 + 「主画面+弹幕」布局
    portrait_rail.png           竖屏 + 侧栏收起成窄条
    portrait_grid.png           竖屏 + 自适应网格布局（看格子挤成什么样）
    portrait_picker.png         竖屏下点「布局预设」弹层会不会超出屏幕

不联网：取流、状态轮询、头像下载全部打桩。
"""
import os
import sys
import time

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import bili, images, theme  # noqa: E402
from ddm import app as app_module  # noqa: E402
from ddm.app import MainWindow  # noqa: E402

OUT = os.path.join(REPO, "dev", "preview")
os.makedirs(OUT, exist_ok=True)

# 假房间足够多，才能看出侧栏在竖屏里占多少、列表还能不能读
ROOMS = [
    {"room_id": "1001", "uname": "示例主播A", "title": "示例标题", "live": True,
     "viewers": "3.1万", "muted": True, "quality": 250, "volume": 55},
    {"room_id": "1002", "uname": "示例主播B", "title": "示例标题二",
     "live": True, "viewers": "1.8万", "muted": True, "quality": 250, "volume": 42},
    {"room_id": "22637261", "uname": "嘉然今天吃什么", "title": "今天的晚饭是火锅",
     "live": True, "viewers": "6.1万", "muted": True, "quality": 250, "volume": 70},
    {"room_id": "22625025", "uname": "贝拉kira", "title": "练舞日常", "live": False,
     "viewers": "", "muted": True, "quality": 250, "volume": 36},
    {"room_id": "22632424", "uname": "向晚大魔王", "title": "写歌中", "live": True,
     "viewers": "9.4万", "muted": True, "quality": 250, "volume": 50},
    {"room_id": "672328094", "uname": "乃琳Queen", "title": "深夜电台", "live": False,
     "viewers": "", "muted": True, "quality": 250, "volume": 42},
]


def boom(room_id, quality=250, **_kwargs):        # noqa: ANN001, ANN201
    raise RuntimeError("原型图：不联网")


class SilentPoller(QThread):
    updated = Signal(dict)

    def __init__(self, room_ids, parent=None):
        super().__init__(parent)
        self.room_ids = list(room_ids)

    def run(self) -> None:
        return


def fake_status(room_ids):             # noqa: ANN001, ANN201
    return {}


def fake_pixmap(url):                  # noqa: ANN001, ANN201
    pixmap = QPixmap(240, 135)
    for index, colour in enumerate(("#3b6ea5", "#7a4a8c", "#2f6f5e")):
        pixmap.fill(QColor(colour))
        break
    return pixmap


def settle(app, seconds: float) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.03)


def shoot(app, path: str, size: tuple, *, layout: str = "dm_main3",
          collapsed: bool = False, open_picker: bool = False,
          show_controls: bool = False) -> None:
    window = MainWindow([dict(r) for r in ROOMS], [dict(r) for r in ROOMS],
                        layout_id=layout)
    # 放到屏幕外，避免弹到用户眼前
    window.setGeometry(-9000, -9000, size[0], size[1])
    window.show()
    settle(app, 1.2)
    if collapsed:
        window.sidebar.set_collapsed(True, animate=False)
        settle(app, 0.5)
    if show_controls and window.wall.tiles:
        window.wall.tiles[0].set_controls_visible(True)
        settle(app, 0.3)
    if open_picker:
        window.sidebar.open_layout_picker()
        settle(app, 0.5)
    window.grab().save(path, "PNG")
    print(f"  {os.path.basename(path)}  {size[0]}x{size[1]}"
          f"{' 侧栏收起' if collapsed else ''}"
          f"{' 布局=' + layout if layout else ''}")
    window.close()
    settle(app, 0.3)


def main() -> None:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass
    bili.play_url = boom
    bili.rooms_status = fake_status
    app_module.StatusPoller = SilentPoller
    app_module.StatsPoller = SilentPoller
    images.load_pixmap = fake_pixmap

    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())

    print("渲染中（全部不联网）…")
    shoot(app, os.path.join(OUT, "portrait_landscape.png"), (1600, 900))
    shoot(app, os.path.join(OUT, "portrait_full.png"), (1080, 1920))
    shoot(app, os.path.join(OUT, "portrait_rail.png"), (1080, 1920), collapsed=True)
    shoot(app, os.path.join(OUT, "portrait_grid.png"), (1080, 1920), layout="3x3")
    shoot(app, os.path.join(OUT, "portrait_picker.png"), (1080, 1920),
          open_picker=True, show_controls=True)
    shoot(app, os.path.join(OUT, "portrait_914x1463.png"), (914, 1463),
          collapsed=True)
    print(f"输出目录：{OUT}")


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
