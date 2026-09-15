"""扫码登录自检：二维码生成、轮询状态、窗口外观。"""
import os
import sys
import time

from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DDM_NO_SAVE', '1')  # 自检脚本不要动真实配置
sys.path.insert(0, REPO)

from ddm import theme  # noqa: E402
from ddm.login import LoginWindow, make_qr_pixmap  # noqa: E402

OUT = os.path.join(REPO, "work", "preview")


def main() -> None:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())

    print("=== 二维码渲染自检 ===")
    pixmap = make_qr_pixmap("https://example.com/scan?key=abc", 260)
    print(f"  尺寸 {pixmap.width()}x{pixmap.height()} 非空={not pixmap.isNull()}")
    image = pixmap.toImage()
    dark = sum(1 for y in range(0, image.height(), 4) for x in range(0, image.width(), 4)
               if image.pixelColor(x, y).red() < 128)
    total = len(range(0, image.height(), 4)) * len(range(0, image.width(), 4))
    print(f"  黑色模块占比 {dark / total:.1%}（二维码正常在 30%~50%）")

    print("\n=== 登录窗口自检 ===")
    window = LoginWindow()
    window.setGeometry(-8000, -8000, 420, 460)
    window.show()
    deadline = time.time() + 12
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.05)
    print("  状态文案:", window.status.text())
    print("  二维码已显示:", window.qr_label.pixmap() is not None
          and not window.qr_label.pixmap().isNull())
    path = os.path.join(OUT, "login_window.png")
    window.grab().save(path, "PNG")
    print("  截图:", path)
    window.close()


if __name__ == "__main__":
    main()
    # 直接退出进程：Qt / VLC 在线程收尾时析构会偶发崩在退出瞬间（程序本体也是这么做的）
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
