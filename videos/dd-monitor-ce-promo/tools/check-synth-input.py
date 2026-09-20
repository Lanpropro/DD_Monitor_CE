"""最小验证：这个环境里，合成鼠标点击到底能不能驱动 Qt。

录屏动作计划全靠 SetCursorPos + mouse_event。如果连一个自建的小窗口都点不动，
那问题就不在软件的坐标上，继续量坐标是白费 —— 先把这个前提钉死。

脚本会：
  1. 开一个 900x600 的窗口，中间放一个大按钮
  2. 用 widgetAt 确认「按钮中心」这个屏幕点确实属于按钮
  3. SetCursorPos + mouse_event 点它，看 clicked 信号有没有来
  4. 再试一次「先 move 再 click」（两步之间多等一会儿），排除时序问题

用法：
    python tools/check-synth-input.py
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

from PySide6.QtCore import QTimer                      # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton, QWidget  # noqa: E402

user32 = ctypes.windll.user32
user32.SetProcessDPIAware()
OUT = os.path.join(PROJ, "videos", "dd-monitor-ce-promo", "raw",
                   "check-synth-input.json")


def rect_of(handle):
    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(ctypes.c_void_p(handle), ctypes.byref(rect))
    return [rect.left, rect.top, rect.right, rect.bottom]


def synth_click(x, y):
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.25)
    user32.mouse_event(0x0002, 0, 0, 0, None)     # LEFTDOWN
    time.sleep(0.12)
    user32.mouse_event(0x0004, 0, 0, 0, None)     # LEFTUP


def main() -> int:
    app = QApplication([sys.argv[0]])
    win = QWidget()
    win.setWindowTitle("合成输入自检")
    win.setGeometry(200, 200, 900, 600)
    button = QPushButton("目标按钮", win)
    button.setGeometry(300, 250, 300, 100)
    hits = []
    button.clicked.connect(lambda: hits.append(len(hits) + 1))
    win.show()
    win.activateWindow()
    win.raise_()
    report = {"hits": hits}

    def run() -> None:
        try:
            time.sleep(0.8)
            center = button.mapToGlobal(button.rect().center())
            handle = int(win.winId())
            report["dpr"] = win.devicePixelRatioF()
            report["win32_rect"] = rect_of(handle)
            report["button_global_center"] = [center.x(), center.y()]
            report["button_global_rect"] = [
                button.mapToGlobal(button.rect().topLeft()).x(),
                button.mapToGlobal(button.rect().topLeft()).y(),
                button.mapToGlobal(button.rect().bottomRight()).x(),
                button.mapToGlobal(button.rect().bottomRight()).y()]
            report["widget_at_button_center"] = (
                QApplication.widgetAt(center.x(), center.y()).__class__.__name__
                if QApplication.widgetAt(center.x(), center.y()) else None)
            report["foreground_is_win"] = (
                user32.GetForegroundWindow() == handle)
            report["hits_after_qt_click_before"] = list(hits)

            # 1) 合成点击（按钮中心）
            synth_click(center.x(), center.y())
            time.sleep(0.4)
            report["hits_after_synth_click"] = list(hits)

            # 2) 再来一次，中间多等
            user32.SetCursorPos(center.x(), center.y())
            time.sleep(0.6)
            user32.mouse_event(0x0002, 0, 0, 0, None)
            time.sleep(0.3)
            user32.mouse_event(0x0004, 0, 0, 0, None)
            time.sleep(0.6)
            report["hits_after_second_click"] = list(hits)

            # 3) 用 WM_LBUTTONDOWN/UP 直接投递消息（绕过鼠标队列）
            lparam = (int(center.y()) << 16) | (int(center.x()) & 0xFFFF)
            user32.PostMessageW(ctypes.c_void_p(handle), 0x0201, 1, lparam)
            user32.PostMessageW(ctypes.c_void_p(handle), 0x0202, 0, lparam)
            time.sleep(0.5)
            report["hits_after_postmessage"] = list(hits)
            point = ctypes.wintypes.POINT()
            user32.GetCursorPos(ctypes.byref(point))
            report["cursor_now"] = [point.x, point.y]
        except Exception:
            import traceback
            report["error"] = traceback.format_exc()
        finally:
            with io.open(OUT, "w", encoding="utf-8") as handle_out:
                json.dump(report, handle_out, ensure_ascii=False, indent=1)
            print(json.dumps(report, ensure_ascii=False, indent=1), flush=True)
            sys.stdout.flush()
            os._exit(0)

    QTimer.singleShot(3500, run)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
