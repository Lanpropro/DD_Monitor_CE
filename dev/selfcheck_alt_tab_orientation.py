"""最大化窗口跨横竖屏时，Windows 还原矩形应与当前屏幕方向一致。"""
import ctypes
import os
import sys
import time

from PySide6.QtWidgets import QApplication

repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, repo)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm.app import MainWindow
from ddm.window_fullscreen import _WindowPlacement


def restore_size(window):
    placement = _WindowPlacement()
    placement.length = ctypes.sizeof(placement)
    assert ctypes.windll.user32.GetWindowPlacement(
        int(window.winId()), ctypes.byref(placement))
    rect = placement.rcNormalPosition
    return rect.right - rect.left, rect.bottom - rect.top


def settle(app):
    end = time.monotonic() + 0.2
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.02)


def main():
    app = QApplication([])
    if sys.platform != "win32" or app.platformName() != "windows":
        print("SKIP: Windows Alt+Tab 窗口位置自检仅在 Windows 桌面运行")
        return
    window = MainWindow([], [], state={})
    window.setWindowOpacity(0)
    screens = sorted(app.screens(), key=lambda screen: screen.geometry().width()
                     > screen.geometry().height())
    try:
        for screen in screens + screens[:1]:
            area = screen.availableGeometry()
            portrait = area.width() <= area.height() * 0.9
            # 先给与目标方向相反的普通窗口尺寸，模拟旧尺寸被最大化保留下来。
            width, height = ((min(area.width() - 50, 850), 500) if portrait
                             else (500, min(area.height() - 50, 1000)))
            window.showNormal()
            window.setGeometry(area.left() + 25, area.top() + 25, width, height)
            window.showMaximized()
            settle(app)
            restored_width, restored_height = restore_size(window)
            assert window.isMaximized() and window.screen() is screen
            assert (restored_width <= restored_height * 0.9) == portrait, \
                f"{screen.name()} 还原尺寸方向错误：{restored_width}x{restored_height}"
            assert window.orientation == ("portrait" if portrait else "landscape")
            window.showNormal()
            settle(app)
            assert (window.width() <= window.height() * 0.9) == portrait, \
                "退出最大化后也应恢复成当前方向的窗口"
    finally:
        window.close()
    print("OK: 最大化窗口在横屏/竖屏上的还原尺寸方向正确")


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
