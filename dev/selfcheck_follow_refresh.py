"""关注栏刷新：真实重复点击、忙碌图标、失败恢复和排队期间列表变空。"""
import os
from pathlib import Path
import sys
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

os.environ["DDM_NO_SAVE"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QAbstractAnimation, QObject, Qt, Signal, qInstallMessageHandler
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from ddm import app as app_module, theme
from ddm.widgets import Sidebar


class Poller(QObject):
    updated = Signal(dict)
    failed = Signal(str)
    finished = Signal()
    status_ready = Signal()
    instances = []

    def __init__(self, room_ids, parent=None, **kwargs):
        super().__init__(parent)
        self.running = False
        self.instances.append(self)

    def start(self):
        self.running = True

    def isRunning(self):
        return self.running

    def finish(self):
        self.running = False
        self.finished.emit()


class Window(QObject):
    refresh_follow = app_module.MainWindow.refresh_follow
    refresh_status = app_module.MainWindow.refresh_status
    _on_poller_finished = app_module.MainWindow._on_poller_finished
    _on_status_failed = app_module.MainWindow._on_status_failed

    def __init__(self, sidebar):
        super().__init__()
        self.sidebar = sidebar
        self._closing = False
        self._poller = None
        self._refresh_queued = False
        self.plugins = SimpleNamespace(platforms={})

    def load_room_avatars(self):
        pass

    def _on_status_updated(self, status):
        pass


def has_color(button, color):
    image = button.grab().toImage()
    return any(image.pixelColor(x, y) == QColor(color)
               for x in range(image.width()) for y in range(image.height()))


def main(side):
    qInstallMessageHandler(lambda kind, context, message: print(message, flush=True))
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    app.setStyleSheet(theme.qss())
    with patch.object(app_module, "StatusPoller", Poller):
        sidebar = Sidebar([{"room_id": "1", "uname": "test", "live": False}], auto_compact=False)
        sidebar.resize(248, 600)
        sidebar.set_side(side)
        if side == "top":
            sidebar.resize(1200, sidebar.height())
        window = Window(sidebar)
        sidebar.refreshRequested.connect(window.refresh_follow)
        sidebar.show()
        QTest.qWait(50)
        button = sidebar.refresh_button
        # 固定悬停状态，避免原生桌面上其他窗口遮挡测试窗口。
        button.setAttribute(Qt.WA_UnderMouse, True)
        assert has_color(button, theme.ACCENT), "hover icon must remain visible on the dark background"
        QTest.mouseClick(button, Qt.LeftButton)
        first = window._poller
        assert first is not None and button.isEnabled() and not button.isDown()
        assert has_color(button, theme.ACCENT), "busy icon must remain visible"
        count = len(Poller.instances)
        for _ in range(3):
            QTest.mouseClick(button, Qt.LeftButton)
        assert window._refresh_queued and len(Poller.instances) == count
        first.status_ready.emit()
        assert not button.property("refreshing") and button._spin.state() != QAbstractAnimation.Running
        assert first.isRunning(), "avatar enrichment may still be running after status completion"
        first.finish()
        second = window._poller
        assert second is not first and len(Poller.instances) == count + 1
        assert button.property("refreshing"), "the queued status round must resume busy feedback"
        first.status_ready.emit()
        assert button.property("refreshing"), "old-round completion must not stop the next round"
        second.failed.emit("test failure")
        second.finish()
        assert window._poller is None and button.isEnabled() and not button.property("refreshing")
        QTest.mouseClick(button, Qt.LeftButton)
        third = window._poller
        assert third is not None, "button must accept another refresh after completion"
        QTest.mouseClick(button, Qt.LeftButton)
        sidebar.remove_room({"room_id": "1"})
        third.finish()
        assert window._poller is None and not window._refresh_queued
        assert button.isEnabled() and not button.property("refreshing")
        QTest.mouseClick(button, Qt.LeftButton)
        assert window._poller is None and not button.property("refreshing")
        sidebar.close()
        app.processEvents()
    print("PASS: follow refresh hover/busy visibility, repeated clicks, queued rounds, failure and empty-list recovery")


if __name__ == "__main__":
    if len(sys.argv) == 2:
        main(sys.argv[1])
    else:
        for side in ("left", "top"):
            result = subprocess.run([sys.executable, "-X", "faulthandler", __file__, side],
                                    capture_output=True, text=True, encoding="utf-8", timeout=20)
            assert result.returncode == 0 and "PASS:" in result.stdout, (side, result.stdout, result.stderr)
            print(side, result.stdout.strip())
