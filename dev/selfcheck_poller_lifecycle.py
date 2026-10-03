"""A queued finished signal must delete its own poller, never the next round."""
import os
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DDM_NO_SAVE", "1")

from PySide6.QtCore import (QCoreApplication, QEvent, QObject, QThread, Signal,
                           qInstallMessageHandler)
from shiboken6 import isValid
from ddm import app as app_module


class ControlledPoller(QThread):
    updated = Signal(dict)
    failed = Signal(str)
    instances = []

    def __init__(self, room_ids, parent=None, **kwargs):
        super().__init__(parent)
        self.room_ids = room_ids
        self.entered = threading.Event()
        self.release = threading.Event()
        if len(self.instances) % 2 == 0:
            self.release.set()
        self.instances.append(self)

    def run(self):
        self.entered.set()
        self.release.wait(5)


class Window(QObject):
    refresh_stats = app_module.MainWindow.refresh_stats
    refresh_status = app_module.MainWindow.refresh_status
    _on_stats_finished = app_module.MainWindow._on_stats_finished
    _on_poller_finished = app_module.MainWindow._on_poller_finished

    def __init__(self):
        super().__init__()
        self._closing = False
        self._stats_poller = None
        self._poller = None
        self._refresh_queued = False
        self.plugins = SimpleNamespace(platforms={})
        room = {"room_id": "7001", "live": True}
        self.wall = SimpleNamespace(tiles=[SimpleNamespace(room=room)])
        self.refreshing = True
        self.sidebar = SimpleNamespace(rooms=lambda: [room],
                                       set_refreshing=self.set_refreshing)

    def set_refreshing(self, value):
        self.refreshing = value

    def _on_stats_updated(self, _stats):
        pass

    def _on_status_updated(self, _status):
        pass

    def _on_status_failed(self, _reason):
        pass


def drain(app):
    app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def child(kind):
    qInstallMessageHandler(lambda _kind, _context, message: print(message, flush=True))
    app = QCoreApplication([])
    attribute = "_stats_poller" if kind == "stats" else "_poller"
    with patch.object(app_module, "StatsPoller", ControlledPoller), \
            patch.object(app_module, "StatusPoller", ControlledPoller):
        for _ in range(6):
            window = Window()
            refresh = window.refresh_stats if kind == "stats" else window.refresh_status
            refresh()
            first = getattr(window, attribute)
            assert first.wait(1000), "First round must finish before its queued callback"
            refresh()  # Main thread has not delivered first.finished yet.
            current = getattr(window, attribute)
            assert current is not first and current.entered.wait(1)
            if kind == "status":
                window._refresh_queued = True
            try:
                drain(app)  # Old code deletes the running current thread here (Qt fatal).
                assert not isValid(first), "Finished round must be deleted"
                assert isValid(current) and current.isRunning()
                assert getattr(window, attribute) is current
                if kind == "status":
                    assert window.refreshing, "Old completion must not end the new refresh UI"
                    assert window._refresh_queued, "Old completion must not consume the queued refresh"
                count = len(ControlledPoller.instances)
                refresh()
                assert len(ControlledPoller.instances) == count, "No overlapping third round"
                window._closing = True
                window._refresh_queued = True
            finally:
                current.release.set()
                assert current.wait(1000)
            drain(app)
            assert getattr(window, attribute) is None
            assert not isValid(current)
            refresh()
            assert len(ControlledPoller.instances) == count, "Closing must not start another round"
    print(f"PASS: {kind} delayed completion, next-round ownership and closing (six rounds)")


def main():
    if len(sys.argv) == 3 and sys.argv[1] == "--child":
        child(sys.argv[2])
        return
    for kind in ("stats", "status"):
        result = subprocess.run([sys.executable, "-X", "utf8", __file__, "--child", kind],
                                cwd=ROOT, capture_output=True, text=True, timeout=30)
        assert result.returncode == 0, (kind, result.returncode, result.stdout, result.stderr)
        print(result.stdout.strip())


if __name__ == "__main__":
    main()
