"""最小验证：这个机器上「合成鼠标点击」到底能不能被 Qt 收到。

为什么需要它：录屏动作计划全靠 SetCursorPos + mouse_event 点击。
如果连一个自己的小窗口都点不动，那问题不在软件的坐标上，而在合成输入这条路，
再量多少坐标都没用。这个脚本把答案一次性钉死。

用法：
    python tools/probe-input.py
"""
import ctypes
import ctypes.wintypes
import os
import sys
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QPushButton, QVBoxLayout, QWidget

user32 = ctypes.windll.user32

hits = []


def win_rect(widget):
    user32.SetProcessDPIAware()
    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(ctypes.c_void_p(int(widget.winId())), ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def synth_click(x, y):
    user32.SetCursorPos(x, y)
    time.sleep(0.2)
    user32.mouse_event(0x0002, 0, 0, 0, None)
    time.sleep(0.1)
    user32.mouse_event(0x0004, 0, 0, 0, None)


def main() -> int:
    app = QApplication([sys.argv[0]])
    win = QWidget()
    win.setWindowTitle("合成输入自检")
    win.resize(600, 400)
    box = QVBoxLayout(win)
    button = QPushButton("点我")
    button.setObjectName("probe")
    button.clicked.connect(lambda: hits.append("qt-clicked"))
    box.addWidget(button)
    win.show()
    win.raise_()
    win.activateWindow()

    def run() -> None:
        left, top, right, bottom = win_rect(win)
        center = button.mapToGlobal(button.rect().center())
        print(f"窗口外框 {right - left}x{bottom - top}@{left},{top}", flush=True)
        print(f"按钮全局中心 {center.x()},{center.y()}"
              f"（窗口内 {center.x() - left},{center.y() - top}）", flush=True)
        print(f"前台窗口 {user32.GetForegroundWindow()} 本窗口 {int(win.winId())}",
              flush=True)
        # 1) Qt 自己触发
        button.click()
        print(f"Qt click() -> hits={hits}", flush=True)
        # 2) 合成鼠标点击
        synth_click(center.x(), center.y())
        print(f"合成点击后 -> hits={hits}", flush=True)
        # 3) 再看一次光标位置（确认 SetCursorPos 真的生效了）
        point = ctypes.wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(point))
        print(f"光标现在 ({point.x},{point.y})", flush=True)
        os._exit(0)

    QTimer.singleShot(4000, run)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
