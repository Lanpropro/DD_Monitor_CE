"""竖屏顶部横栏预览：把「展开一行 + 收起一行」渲染出来，供肉眼核对。

用法：
    python dev\\preview_bar.py

输出：
    dev/preview/bar_expanded.png   1080 宽下的展开态横栏（裁切，1:1）
    dev/preview/bar_collapsed.png  同一个窗口的收起态横栏（裁切，1:1）
    docs/portrait-bar.png          上面两张拼在一起，进版本库给用户看

横栏是**一行**：搜索框 + 右侧那一块（账号头像 / 布局预设 / ⋯ / 展开键），
下面只剩横向卡片条。收起时搜索框换成头像排，展开键仍在同一行右端。
不联网：取流、状态轮询、头像下载全部打桩。
"""
import os
import sys
import time

from PySide6.QtCore import QRect, QThread, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import bili, images, theme  # noqa: E402
from ddm import app as app_module  # noqa: E402
from ddm.app import MainWindow  # noqa: E402

OUT = os.path.join(REPO, "dev", "preview")
DOCS = os.path.join(REPO, "docs")
SIZE = (1080, 1920)
GAP = 8


class SilentPoller(QThread):
    updated = Signal(dict)

    def __init__(self, room_ids, parent=None):
        super().__init__(parent)
        self.room_ids = list(room_ids)

    def run(self) -> None:
        return


def boom(room_id, quality=250):        # noqa: ANN001, ANN201
    raise RuntimeError("预览：不联网")


def fake_pixmap(url):                  # noqa: ANN001, ANN201
    pixmap = QPixmap(64, 64)
    pixmap.fill(QColor("#3b6ea5"))
    return pixmap


def settle(app, seconds: float) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.03)


def shoot(app, path: str, collapsed: bool) -> QImage:
    """渲染一张横栏裁切图；返回 QImage 供拼接。"""
    rooms = [{"room_id": str(8000 + index), "uname": f"主播{index + 1}",
              "title": "标题", "live": True, "viewers": "1万", "muted": True,
              "volume": 42, "quality": 250,
              "pinned": index == 0} for index in range(6)]
    window = MainWindow([dict(room) for room in rooms],
                        [dict(room) for room in rooms])
    window.setGeometry(-9000, -9000, *SIZE)
    window.show()
    settle(app, 1.4)
    sidebar = window.sidebar
    sidebar.set_account("Asaki大人")
    # 置顶标记要真的走一次 apply_pins 才亮（房间字典里的 pinned 会被它覆盖）
    sidebar.apply_pins([str(rooms[0]["room_id"])])
    settle(app, 0.3)
    # 头排用的是「列表里已下载的那张头像」：这里喂几张假图，免得截图里全是字母
    for index, room in enumerate(rooms):
        pixmap = QPixmap(64, 64)
        pixmap.fill(QColor(("#3b6ea5", "#7a4a8c", "#2f6f5e", "#8c5a3b")[index % 4]))
        sidebar.set_room_face(str(room["room_id"]), pixmap)
    sidebar.set_collapsed(collapsed, animate=False)
    settle(app, 0.5)
    bar_height = sidebar.height()
    shot = window.grab().toImage()
    # 高分屏下 grab() 是设备像素（1.5x），裁切要跟着放大，否则右边会被切掉
    scale = shot.width() / max(1, window.width())
    image = shot.copy(QRect(0, 0, int(sidebar.width() * scale),
                            int(bar_height * scale)))
    image.setDevicePixelRatio(1.0)
    image.save(path, "PNG")
    print(f"  {os.path.basename(path)}  {image.width()}x{image.height()}  "
          f"collapsed={collapsed} 横栏高={bar_height}")
    window.close()
    settle(app, 0.3)
    return image


def main() -> None:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass
    bili.play_url = boom
    app_module.StatusPoller = SilentPoller
    app_module.StatsPoller = SilentPoller
    images.load_pixmap = fake_pixmap
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())

    os.makedirs(OUT, exist_ok=True)
    expanded = shoot(app, os.path.join(OUT, "bar_expanded.png"), False)
    collapsed = shoot(app, os.path.join(OUT, "bar_collapsed.png"), True)

    # 两张拼一起（展开在上、收起在下），中间一条分隔线
    width = max(expanded.width(), collapsed.width())
    total = expanded.height() + GAP + collapsed.height()
    sheet = QImage(width, total, QImage.Format_ARGB32)
    sheet.fill(QColor(theme.BG) if hasattr(theme, "BG") else QColor("#101114"))
    painter = QPainter(sheet)
    painter.drawImage(0, 0, expanded)
    painter.fillRect(0, expanded.height(), width, GAP, QColor(theme.ACCENT))
    painter.drawImage(0, expanded.height() + GAP, collapsed)
    painter.end()
    sheet_path = os.path.join(DOCS, "portrait-bar.png")
    sheet.save(sheet_path, "PNG")
    print(f"  {os.path.relpath(sheet_path, REPO)}  {sheet.width()}x{sheet.height()}")


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
