"""最大化跟随屏幕方向，还原保留最大化前的窗口方向。"""
import ctypes
import os
import sys
from unittest.mock import patch
from ctypes import wintypes

from PySide6.QtWidgets import QApplication

repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, repo)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm.app import MainWindow
from ddm.plugins import PluginManager
from dev.selfcheck_window_resize import wait_orientation


class _WindowPlacement(ctypes.Structure):
    _fields_ = [("length", wintypes.UINT), ("flags", wintypes.UINT),
                ("showCmd", wintypes.UINT), ("ptMinPosition", wintypes.POINT),
                ("ptMaxPosition", wintypes.POINT), ("rcNormalPosition", wintypes.RECT)]


def restore_size(window):
    ctypes.windll.user32.GetWindowPlacement.argtypes = (wintypes.HWND, ctypes.POINTER(_WindowPlacement))
    placement = _WindowPlacement()
    placement.length = ctypes.sizeof(placement)
    assert ctypes.windll.user32.GetWindowPlacement(
        int(window.winId()), ctypes.byref(placement))
    rect = placement.rcNormalPosition
    return rect.right - rect.left, rect.bottom - rect.top


def main():
    app = QApplication([])
    if sys.platform != "win32" or app.platformName() != "windows":
        print("SKIP: Windows Alt+Tab 窗口位置自检仅在 Windows 桌面运行")
        return
    with patch.object(PluginManager, 'load'):
        window = MainWindow([], [], state={'plugins_enabled': [],
            'settings': {'close_behavior': 'exit'}})
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
            window._on_layout_changed('3x2' if portrait else 'portrait_main2')
            window.setGeometry(area.left() + 25, area.top() + 25, width, height)
            wait_orientation(window, 'landscape' if portrait else 'portrait')
            normal_portrait = window.orientation == 'portrait'
            window.showMaximized()
            wait_orientation(window, 'portrait' if portrait else 'landscape')
            restored_width, restored_height = restore_size(window)
            assert window.isMaximized() and window.screen() is screen
            assert (restored_width <= restored_height * 0.9) == normal_portrait, \
                f"{screen.name()} 还原尺寸方向错误：{restored_width}x{restored_height}"
            assert window.orientation == ("portrait" if portrait else "landscape")
            window.showNormal()
            wait_orientation(window, 'portrait' if normal_portrait else 'landscape')
            assert (window.width() <= window.height() * 0.9) == normal_portrait, \
                "退出最大化后应恢复成最大化前的窗口方向"
    finally:
        window.close()
    print("OK: 最大化跟随屏幕，还原保留原窗口方向")


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
