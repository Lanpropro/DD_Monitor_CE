"""自检：顶栏音量按钮移除、格子音量图标、画质按钮自适应宽度。"""
import os
import sys
import time

from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import theme  # noqa: E402
from ddm.app import MainWindow  # noqa: E402

ROOMS = [{"room_id": "6154037", "uname": "Asaki大人", "title": "玩玩战狗", "live": True,
          "viewers": "3.1万", "muted": True, "volume": 55}]


def settle(app, seconds: float) -> None:
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

    window = MainWindow([dict(r) for r in ROOMS], [dict(r) for r in ROOMS], layout_id="1x1")
    window.setGeometry(-8000, -8000, 900, 560)
    window.show()
    settle(app, 1.5)
    tile = window.wall.tiles[0]

    print("右侧顶栏已去掉:", not hasattr(window, "topbar"))
    print("格子音量按钮:", f"{tile.volume_button.width()}x{tile.volume_button.height()}",
          "| 静音:", tile.volume_button.muted)
    tile.volume_button.click()
    print("点击后 格子静音:", tile.muted, "| 按钮状态:", tile.volume_button.muted)

    print("\n画质按钮宽度（应随文字变化）:")
    for value in (10000, 400, 250, 80):
        tile.set_quality(value)
        app.processEvents()
        print(f"  请求 {value:<6} 文本 {tile.quality_button.text():<10} 宽度 {tile.quality_button.width()}")
    tile.set_actual_quality(250)
    app.processEvents()
    print(f"  实际 720P 文本 {tile.quality_button.text():<10} 宽度 {tile.quality_button.width()}"
          f" | 控制条宽 {tile.controls.width()}")

    window.close()
    print("\n完成")


if __name__ == "__main__":
    main()
