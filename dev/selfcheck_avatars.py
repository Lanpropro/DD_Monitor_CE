"""自检：导入对话框的头像回填、缓冲状态、tile 圆角遮罩。"""
import os
import sys
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import theme  # noqa: E402
from ddm.dialogs import FollowImportDialog  # noqa: E402
from ddm.app import MainWindow  # noqa: E402

ROOMS = [
    {"room_id": "1001", "uname": "主播A", "title": "房间A", "live": True, "face": "http://x/a.jpg"},
    {"room_id": "1002", "uname": "主播B", "title": "房间B", "live": False, "face": "http://x/b.jpg"},
]


def make_pixmap(color: str) -> QPixmap:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setBrush(QColor(color))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(0, 0, 64, 64)
    painter.end()
    return pixmap


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())

    print("=== 导入对话框头像回填 ===")
    dialog = FollowImportDialog([dict(r) for r in ROOMS], set())
    print("  条目数:", dialog.list.count(),
          "| 初始有图标:", dialog.list.item(0).icon().isNull() is False)
    dialog.set_avatar("1001", make_pixmap("#4c6ef5"))
    icon = dialog.list.item(0).icon()
    print("  回填后第 1 条有图标:", not icon.isNull(),
          "| 尺寸:", icon.availableSizes()[0] if icon.availableSizes() else "-")
    print("  第 2 条仍无图标（正常）:", dialog.list.item(1).icon().isNull())

    print("\n=== tile 圆角遮罩 ===")
    window = MainWindow([dict(r) for r in ROOMS[:1]], [dict(r) for r in ROOMS[:1]],
                        layout_id="1x1")
    window.setGeometry(-8000, -8000, 900, 560)
    window.show()
    deadline = time.time() + 1.2
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.03)
    tile = window.wall.tiles[0]
    mask = tile.mask()
    from PySide6.QtCore import QPoint
    video_mask = tile.video.mask()
    print("  tile 有遮罩:", not mask.isEmpty())
    print("  视频区有圆角遮罩:", not video_mask.isEmpty(),
          "| 左上角(2,2) 在内:", video_mask.contains(QPoint(2, 2)),
          "| 角点(0,0) 被切掉:", not video_mask.contains(QPoint(0, 0)),
          "| 正中在内:", video_mask.contains(QPoint(tile.video.width() // 2, tile.video.height() // 2)))

    print("\n=== 缓冲状态 ===")
    tile.set_buffering(True)
    print("  缓冲中: 转圈可见", tile.spinner.isVisible(), "| 封面文字", repr(tile.cover.text()))
    tile.set_buffering(False)
    print("  缓冲结束: 转圈可见", tile.spinner.isVisible())

    window.close()
    print("\n完成")


if __name__ == "__main__":
    main()
    # 直接退出进程：Qt / VLC 在线程收尾时析构会偶发崩在退出瞬间（程序本体也是这么做的）
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
