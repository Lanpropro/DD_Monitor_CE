"""反查：动作计划里的「窗口内坐标」和屏幕像素到底是什么关系。

前面在这个点上翻过两次车（先按 1:1 点、再按 ×1.5 点，两次都没点中），
所以不再靠推理，直接**枚举**：让 Qt 的窗口原点取整到网格，把
「窗口外框左上角 + 窗口内坐标」和「窗口外框左上角 + 窗口内坐标 × DPR」
两组候选都拿去 QApplication.widgetAt 反查，看哪一组能把布局预设按钮、
关注条目、音量按钮各自命中到真控件上。

用法：
    python tools/measure-frame-map.py
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
                   "frame-map.json")
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


def name_of(widget):
    if widget is None:
        return None
    text = ""
    try:
        text = widget.text()
    except Exception:                     # noqa: BLE001
        text = ""
    return f"{widget.__class__.__name__}{'(' + text + ')' if text else ''}"


def main() -> int:
    app = QApplication([sys.argv[0]])
    app.setApplicationName("DD监控室CE · frame-map")
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
            dpr = win.devicePixelRatioF()
            qt_origin = win.mapToGlobal(win.rect().topLeft())
            button = win.sidebar.layout_button
            report["win32_rect"] = [left, top, right, bottom]
            report["dpr"] = dpr
            report["qt_origin"] = [qt_origin.x(), qt_origin.y()]
            report["button_qt_global"] = [
                button.mapToGlobal(button.rect().topLeft()).x(),
                button.mapToGlobal(button.rect().topLeft()).y(),
                button.width(), button.height()]
            report["button_size_logical"] = [button.width(), button.height()]

            # 用 widgetAt 反查：把按钮**全局矩形**扫一遍，找出哪些屏幕点真的落在它上面
            probes = {}
            hits = []
            gx = button.mapToGlobal(button.rect().topLeft()).x()
            gy = button.mapToGlobal(button.rect().topLeft()).y()
            for dx in range(-40, 260, 10):
                for dy in range(-40, 80, 10):
                    x, y = gx + dx, gy + dy
                    widget = QApplication.widgetAt(x, y)
                    if widget is button:
                        hits.append([x, y])
            if hits:
                xs = [item[0] for item in hits]
                ys = [item[1] for item in hits]
                probes["button_screen_bounds_by_widgetAt"] = [
                    min(xs), min(ys), max(xs), max(ys)]
                probes["button_screen_center_by_widgetAt"] = [
                    (min(xs) + max(xs)) // 2, (min(ys) + max(ys)) // 2]
                probes["button_frame_coords_1to1"] = [
                    probes["button_screen_center_by_widgetAt"][0] - left,
                    probes["button_screen_center_by_widgetAt"][1] - top]
                probes["button_frame_coords_divided_dpr"] = [
                    round((probes["button_screen_center_by_widgetAt"][0] - left) / dpr),
                    round((probes["button_screen_center_by_widgetAt"][1] - top) / dpr)]
            report["button_probe"] = probes

            # 关注列表第 1 项、音量按钮也照做一遍
            def probe_widget(widget, label, span_x=140, span_y=60, step=10):
                base = widget.mapToGlobal(widget.rect().topLeft())
                found = []
                for dx in range(-20, span_x, step):
                    for dy in range(-20, span_y, step):
                        x, y = base.x() + dx, base.y() + dy
                        if QApplication.widgetAt(x, y) is widget:
                            found.append([x, y])
                if not found:
                    return {label: None}
                xs = [item[0] for item in found]
                ys = [item[1] for item in found]
                center = [(min(xs) + max(xs)) // 2, (min(ys) + max(ys)) // 2]
                return {
                    label + "_screen_bounds": [min(xs), min(ys), max(xs), max(ys)],
                    label + "_screen_center": center,
                    label + "_frame_1to1": [center[0] - left, center[1] - top],
                }

            # 关注列表：sidebar 是 Sidebar 还是房间列表，按实际类型取
            sidebar_obj = getattr(win, "sidebar", sidebar)
            items = getattr(sidebar_obj, "_items", None)
            if items:
                report["nav_probe"] = probe_widget(
                    items[0].thumb, "nav_thumb", 220, 140, 20)
            tile = next((item for item in wall.tiles if item.isVisible()), None)
            if tile is not None:
                from ddm.widgets import VolumeButton
                buttons = tile.findChildren(VolumeButton)
                if buttons:
                    report["volume_probe"] = probe_widget(buttons[0], "volume", 60, 40, 4)
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
