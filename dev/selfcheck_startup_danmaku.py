"""Saved platform chat layouts must start only after plugin registration."""
import os
from pathlib import Path
import sys
from unittest.mock import patch

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm.app import MainWindow
from ddm.plugins import Platform, PluginManager


class Client(QThread):
    message = Signal(dict)
    status = Signal(str)

    def __init__(self, room_id, parent=None):
        super().__init__(parent)

    def run(self):
        return

    def stop(self):
        return


class TestPlatform(Platform):
    kind = "test"
    label = "Test"

    def matches(self, room_id):
        return room_id.startswith("test:")

    def danmaku_client(self, room_id, parent=None):
        assert hasattr(parent, "plugins"), "Chat started before plugin manager initialization"
        return Client(room_id, parent)


def main():
    app = QApplication(sys.argv)
    def load(manager):
        manager.register_platform("startup_test", TestPlatform())
    for room_id in ("test:123", "123"):
        room = {"room_id": room_id, "uname": "Startup test", "live": False}
        with patch.object(PluginManager, "load", load), patch("ddm.app.DanmakuClient", Client):
            window = MainWindow([dict(room)], [dict(room)], layout_id="dm_main2",
                                state={"plugins_enabled": None})
            try:
                assert window._danmaku is not None
                assert window._danmaku_room == room_id
                assert window.wall.danmaku.count.text() == "连接中…"
            finally:
                window.close()
    print("Saved Bilibili/platform danmaku layouts start after plugin initialization: passed")


if __name__ == "__main__":
    main()
