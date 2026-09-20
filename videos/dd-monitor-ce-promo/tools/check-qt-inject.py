"""最小验证：**进程内**注入 Qt 事件能不能驱动界面（合成鼠标被环境挡了）。

背景：实测这个环境里 mouse_event 和 PostMessageW 都点不动窗口（见
tools/check-synth-input.py），所以录屏不能再依赖"系统级鼠标"。
改成在软件进程内直接投递 Qt 事件（QTest / QMouseEvent）——
它走的是完全正常的 Qt 代码路径，不依赖系统输入队列。

这个脚本验证三件事，通过就意味着可以据此重写录屏驱动：
  1. QTest 能不能装得上（PySide6.QtTest）
  2. QTest.mouseClick 点按钮，clicked 信号会不会来
  3. 真的按住/移动/松开（drag）能不能驱动

用法：
    python tools/check-qt-inject.py
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

from PySide6.QtCore import QPoint, Qt, QTimer           # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton, QWidget  # noqa: E402

OUT = os.path.join(PROJ, "videos", "dd-monitor-ce-promo", "raw",
                   "check-qt-inject.json")
user32 = ctypes.windll.user32
user32.SetProcessDPIAware()

report = {"steps": []}


def note(label, value):
    report["steps"].append({label: value})
    print(f"  {label}: {value}", flush=True)


def main() -> int:
    app = QApplication([sys.argv[0]])
    try:
        from PySide6.QtTest import QTest
        note("QtTest 可用", True)
    except Exception as error:                             # noqa: BLE001
        note("QtTest 可用", f"NO: {error}")
        QTest = None

    win = QWidget()
    win.setWindowTitle("Qt 事件注入自检")
    win.setGeometry(200, 200, 900, 600)
    button = QPushButton("目标按钮", win)
    button.setGeometry(300, 250, 300, 100)
    hits = []
    button.clicked.connect(lambda: hits.append(len(hits) + 1))
    drags = []
    win.show()
    win.activateWindow()
    win.raise_()

    class Catcher(QWidget):
        """一个专门接收 press/move/release 的控件，用来验证拖动。"""

        def __init__(self, parent):
            super().__init__(parent)
            self.setGeometry(50, 50, 160, 120)
            self.setMouseTracking(True)

        def mousePressEvent(self, event):
            drags.append(("press", event.position().x(), event.position().y()))
            super().mousePressEvent(event)

        def mouseMoveEvent(self, event):
            drags.append(("move", round(event.position().x()), round(event.position().y())))
            super().mouseMoveEvent(event)

        def mouseReleaseEvent(self, event):
            drags.append(("release", round(event.position().x()), round(event.position().y())))
            super().mouseReleaseEvent(event)

    catcher = Catcher(win)

    def run() -> None:
        try:
            time.sleep(0.6)
            if QTest is not None:
                QTest.mouseClick(button, Qt.LeftButton)
                note("QTest.mouseClick 后 hits", list(hits))
                # 拖动：按下 -> 移动 -> 松开
                QTest.mousePress(catcher, Qt.LeftButton, pos=QPoint(20, 20))
                for step in range(1, 5):
                    QTest.mouseMove(catcher, QPoint(20 + step * 10, 20 + step * 5), 20)
                QTest.mouseRelease(catcher, Qt.LeftButton, pos=QPoint(70, 45))
                note("拖动事件", drags)
            # 再试一次：直接构造 QMouseEvent 投给应用（另一条常见注入路径）
            from PySide6.QtGui import QMouseEvent
            from PySide6.QtCore import QEvent, QPointF
            center = button.rect().center()
            for kind, ev_type in ((QEvent.MouseButtonPress, QEvent.MouseButtonPress),
                                  (QEvent.MouseButtonRelease, QEvent.MouseButtonRelease)):
                event = QMouseEvent(kind, QPointF(center), button.mapToGlobal(center),
                                    Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
                QApplication.sendEvent(button, event)
            note("sendEvent 后 hits", list(hits))
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
