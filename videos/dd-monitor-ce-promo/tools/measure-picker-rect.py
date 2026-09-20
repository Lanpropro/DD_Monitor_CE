"""定位布局弹层的**真实屏幕范围**，并给出点它不会把它关掉的坐标。

为什么需要：Qt::Popup 弹层一旦失去焦点/被点到范围外就会收起，而它弹出时
盖在按钮上方 —— 「点按钮」这一步如果落进弹层范围，反而会把它关掉。
前面的失败就是这么来的（点第二次时把弹层点没了）。

做法：
  1. 用按钮的 click() 把弹层打开（纯 Qt 调用，绕过鼠标）
  2. 用 QApplication.widgetAt 在弹层可能出现的区域扫一遍，找出哪些屏幕点
     属于弹层窗口 -> 得到弹层的真实屏幕矩形
  3. 打印「窗口内坐标」口径下的矩形，供动作计划判断哪个 y 是安全的

用法：
    python tools/measure-picker-rect.py
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

VLC_DLL = os.path.join(PROJ, "libvlc.dll")
if os.path.isfile(VLC_DLL):
    os.environ.setdefault("PYTHON_VLC_LIB_PATH", VLC_DLL)

from PySide6.QtCore import QTimer                      # noqa: E402
from PySide6.QtWidgets import QApplication             # noqa: E402

from ddm import config as config_module                # noqa: E402
from ddm import theme                                  # noqa: E402
from ddm.app import MainWindow                         # noqa: E402

OUT = os.path.join(PROJ, "videos", "dd-monitor-ce-promo", "raw",
                   "picker-rect.json")
user32 = ctypes.windll.user32


def win_rect(win):
    user32.SetProcessDPIAware()
    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(ctypes.c_void_p(int(win.winId())), ctypes.byref(rect))
    return rect.left, rect.top, rect.right, rect.bottom


def force_geometry(win, lw=1920, lh=1080):
    scale = win.devicePixelRatioF()
    user32.SetProcessDPIAware()
    handle = ctypes.c_void_p(int(win.winId()))
    for _ in range(6):
        user32.ShowWindow(handle, 9)
        user32.MoveWindow(handle, 0, 0, int(lw * scale), int(lh * scale), True)
        QApplication.processEvents()
        left, top, right, bottom = win_rect(win)
        if right - left == int(lw * scale) and bottom - top == int(lh * scale):
            break
        time.sleep(0.8)


def main() -> int:
    app = QApplication([sys.argv[0]])
    app.setApplicationName("DD监控室CE · picker-rect")
    app.setStyleSheet(theme.qss())
    state = config_module.load()
    sidebar, wall = config_module.build_rooms(state) if state else ([], [])
    win = MainWindow(sidebar, wall,
                     layout_id=(state.get("ui") or {}).get("layout") or "",
                     state=state)
    win.showMaximized()
    report = {}

    def run() -> None:
        try:
            force_geometry(win)
            QApplication.processEvents()
            time.sleep(1.0)
            QApplication.processEvents()
            left, top, right, bottom = win_rect(win)
            bar = win.sidebar
            # 1) 打开弹层
            bar.layout_button.click()
            QApplication.processEvents()
            time.sleep(0.5)
            QApplication.processEvents()
            picker = getattr(bar, "_picker", None)
            if picker is None:
                raise RuntimeError("按钮点了但弹层没建出来")
            size = [picker.width(), picker.height()]
            report["visible"] = picker.isVisible()
            report["size"] = size
            report["pos_by_qt"] = [picker.pos().x(), picker.pos().y()]

            # 2) 扫出弹层真实的屏幕范围：用 widgetAt 判断某个屏幕点是不是弹层里的控件
            found = []
            for x in range(max(0, picker.pos().x() - 40),
                           min(right, picker.pos().x() + size[0] + 40), 24):
                for y in range(max(0, picker.pos().y() - 40),
                               min(bottom, picker.pos().y() + size[1] + 40), 24):
                    widget = QApplication.widgetAt(x, y)
                    node = widget
                    while node is not None and node is not picker:
                        node = node.parentWidget()
                    if node is picker:
                        found.append([x, y])
            if not found:
                report["scan"] = None
                report["hint"] = "widgetAt 找不到弹层（Popup 可能不吃这个查询）"
            else:
                xs = [item[0] for item in found]
                ys = [item[1] for item in found]
                rect = [min(xs), min(ys), max(xs), max(ys)]
                report["scan"] = rect
                report["window_relative"] = [
                    rect[0] - left, rect[1] - top, rect[2] - left, rect[3] - top]
                # 由外框左上角换算：动作计划里写的「窗口内坐标」
                report["frame_coords"] = [
                    rect[0] - left, rect[1] - top, rect[2] - left, rect[3] - top]
                button = bar.layout_button
                btop = button.mapToGlobal(button.rect().topLeft())
                report["button_frame_top"] = [btop.x() - left, btop.y() - top]
                report["free_band_frame"] = [
                    report["frame_coords"][1], report["button_frame_top"][1]]
            # 3) 卡片在弹层里的相对位置（供判断点哪里是第几张卡）
            cards = {}
            for card in bar._picker._cards[bar._picker.group()]:     # noqa: SLF001
                top_left = card.mapToGlobal(card.rect().topLeft())
                cards[card.property("layoutId")] = {
                    "name": card.text(),
                    "screen": [top_left.x(), top_left.y(),
                               card.width(), card.height()],
                    "frame": [top_left.x() - left, top_left.y() - top],
                    "visible": card.isVisible(),
                }
            report["cards"] = cards
        except Exception:
            import traceback
            report["error"] = traceback.format_exc()
        finally:
            with io.open(OUT, "w", encoding="utf-8") as handle:
                json.dump(report, handle, ensure_ascii=False, indent=1)
            print(json.dumps(report, ensure_ascii=False, indent=1), flush=True)
            sys.stdout.flush()
            os._exit(0)

    QTimer.singleShot(6000, run)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
