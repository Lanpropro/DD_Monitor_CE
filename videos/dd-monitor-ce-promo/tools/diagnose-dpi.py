"""诊断：合成鼠标点击要送**逻辑**还是**物理**坐标？

前面量了半天坐标还是点不中，怀疑 SetCursorPos/mouse_event 用的是物理像素，
而 Qt 的 mapToGlobal 给的是逻辑坐标（缩放 150% 时两者差 1.5 倍）。
这个脚本用一个横跨整个屏幕的窗口做实验：分别用两种换算各点一次按钮，
看哪一种能真正按到按钮 —— 一次把这个问题钉死。

用法：
    python tools/diagnose-dpi.py
"""
import ctypes
import ctypes.wintypes
import io
import json
import os
import sys
import time

PROJ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))))
os.chdir(PROJ)
if PROJ not in sys.path:
    sys.path.insert(0, PROJ)

from PySide6.QtCore import QTimer                      # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton, QWidget  # noqa: E402

user32 = ctypes.windll.user32
user32.SetProcessDPIAware()
OUT = os.path.join(PROJ, "videos", "dd-monitor-ce-promo", "raw", "diagnose-dpi.json")


def click_at(x, y):
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.2)
    user32.mouse_event(0x0002, 0, 0, 0, None)
    time.sleep(0.1)
    user32.mouse_event(0x0004, 0, 0, 0, None)
    time.sleep(0.35)


def main() -> int:
    app = QApplication([sys.argv[0]])
    win = QWidget()
    win.setWindowTitle("DPI 自检")
    win.setGeometry(0, 0, 1900, 1000)
    button = QPushButton("目标", win)
    button.setGeometry(900, 500, 160, 60)
    hits = []
    button.clicked.connect(lambda: hits.append(len(hits) + 1))
    win.show()
    win.activateWindow()
    report = {}

    def run() -> None:
        try:
            time.sleep(0.6)
            dpr = win.devicePixelRatioF()
            center = button.mapToGlobal(button.rect().center())
            frame = win.mapToGlobal(win.rect().topLeft())
            report["dpr"] = dpr
            report["qt_window_origin_logical"] = [frame.x(), frame.y()]
            report["button_center_logical"] = [center.x(), center.y()]
            report["button_center_physical"] = [center.x() * dpr, center.y() * dpr]
            report["widget_at_logical"] = (
                QApplication.widgetAt(center.x(), center.y()).__class__.__name__
                if QApplication.widgetAt(center.x(), center.y()) else None)
            report["widget_at_physical"] = (
                QApplication.widgetAt(center.x() * dpr, center.y() * dpr)
                .__class__.__name__
                if QApplication.widgetAt(center.x() * dpr, center.y() * dpr) else None)
            report["hits_before"] = list(hits)

            # 1) 先按逻辑坐标点
            click_at(center.x(), center.y())
            report["after_logical_click"] = list(hits)
            point = ctypes.wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(point))
            report["cursor_physical_now"] = [point.x, point.y]

            # 2) 再按物理坐标点
            click_at(center.x() * dpr, center.y() * dpr)
            report["after_physical_click"] = list(hits)
            point2 = ctypes.wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(point2))
            report["cursor_physical_after_second"] = [point2.x, point2.y]
            report["button_screen_rect_physical"] = [
                win.mapToGlobal(button.rect().topLeft()).x() * dpr,
                win.mapToGlobal(button.rect().topLeft()).y() * dpr,
                button.width() * dpr, button.height() * dpr]
        except Exception:
            import traceback
            report["error"] = traceback.format_exc()
        finally:
            with io.open(OUT, "w", encoding="utf-8") as handle:
                json.dump(report, handle, ensure_ascii=False, indent=1)
            print(json.dumps(report, ensure_ascii=False, indent=1), flush=True)
            sys.stdout.flush()
            os._exit(0)

    QTimer.singleShot(3000, run)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
