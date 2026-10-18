"""离线回归：首轮状态先送达、取流不重复、人数查询合并。"""
import os
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DDM_NO_SAVE"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QThread, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from ddm import bili  # noqa: E402
from ddm.app import MainWindow  # noqa: E402


def wait_for(app, predicate, seconds=3):
    deadline = time.monotonic() + seconds
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)
    assert predicate(), "Timed out waiting for queued callbacks"


def check_status(app):
    status = {"1001": {"live": True, "title": "live", "uname": "test", "face": "", "viewers": ""}}
    updates, failures = [], []
    foreign_gate, face_gate = threading.Event(), threading.Event()
    face_started = threading.Event()

    def foreign(_ids):
        assert foreign_gate.wait(5)
        return {"douyu:123": {"live": True}}

    def fill_faces(result, _uids):
        face_started.set()
        assert face_gate.wait(5)
        result["1001"]["face"] = "https://test/avatar.jpg"

    platform = SimpleNamespace(label="斗鱼", rooms_status=foreign)
    poller = bili.StatusPoller(["1001", "douyu:123"], platforms={"douyu": platform})
    poller.updated.connect(updates.append)
    poller.failed.connect(failures.append)
    with patch.object(bili, "_rooms_status_base", return_value=(status, {"1001": 1})), \
            patch.object(bili, "_fill_faces", side_effect=fill_faces):
        try:
            poller.start()
            wait_for(app, lambda: len(updates) == 1)
            assert updates[0]["1001"]["live"] and not face_started.is_set()
            foreign_gate.set()
            wait_for(app, lambda: len(updates) == 2 and face_started.is_set())
            assert "douyu:123" in updates[1] and updates[0]["1001"]["face"] == ""
            face_gate.set()
            wait_for(app, lambda: len(updates) == 3)
            assert updates[2]["1001"]["face"] and updates[0]["1001"]["face"] == ""
            assert not failures
        finally:
            foreign_gate.set()
            face_gate.set()
            assert poller.wait(5000)
    updates.clear()
    failures.clear()
    with patch.object(bili, "_rooms_status_base", side_effect=RuntimeError("Bili timeout")):
        poller.run()
    assert updates == [{"douyu:123": {"live": True}}] and failures == ["Bili timeout"]
    updates.clear()
    failures.clear()
    platform.rooms_status = Mock(side_effect=RuntimeError("Douyu timeout"))
    good = SimpleNamespace(label="抖音", rooms_status=lambda _ids: {"douyin:456": {"live": True}})
    poller = bili.StatusPoller(["douyu:123", "douyin:456"], platforms={"douyu": platform, "douyin": good})
    poller.updated.connect(updates.append)
    poller.failed.connect(failures.append)
    poller.run()
    assert updates == [{"douyin:456": {"live": True}}] and failures == ["斗鱼 状态获取失败"]
    print("PASS: live state before slow platform/avatar, immutable queued snapshot, isolated failures")


def check_window(app):
    gate = threading.Event()
    resolved_ids, stats_ids = [], []

    class Resolver(QThread):
        resolved = Signal(str, str, int, str, list)
        failed = Signal(str, str)

        def __init__(self, room_id, _quality, parent=None, **kwargs):
            super().__init__(parent)
            self.platform = kwargs.get("platform")
            self.headers = {}
            self.cancelled = False
            resolved_ids.append(room_id)

        def cancel(self):
            self.cancelled = True

        def is_cancelled(self):
            return self.cancelled

        def run(self):
            gate.wait(5)

    class Stats(QThread):
        updated = Signal(dict)

        def __init__(self, ids, parent=None):
            super().__init__(parent)
            stats_ids.append(ids)

        def run(self):
            pass

    rooms = [{"room_id": rid, "live": True, "uname": rid, "title": "", "face": ""}
             for rid in ("1001", "1002", "douyu:123")]
    rooms[-1].update(live=False, live_known=False, platform="douyu")
    state = {"plugins_enabled": ["domestic_live"], "settings": {"recording_enabled": False,
             "recording_replay_enabled": False, "preview_on_hover": False}}
    with patch("ddm.app.QTimer.singleShot"), patch("ddm.app.StreamResolver", Resolver), \
            patch("ddm.app.StatsPoller", Stats), \
            patch.object(bili.requests, "get", side_effect=AssertionError("Unexpected network")):
        window = MainWindow([dict(r) for r in rooms], [dict(r) for r in rooms], state=state, layout_id="1x3")
        try:
            window.start_all()
            assert resolved_ids == ["1001", "1002", "douyu:123"] and not stats_ids
            tile = next(t for t in window.wall.tiles if t.room.get("room_id") == "douyu:123")
            original = window._resolvers[tile]
            window._on_status_updated({"douyu:123": {"live": True, "uname": "test", "title": "live", "viewers": ""}})
            assert window._resolvers[tile] is original and not original.cancelled
            assert resolved_ids == ["1001", "1002", "douyu:123"]
            wait_for(app, lambda: len(stats_ids) == 1)
            assert set(stats_ids[0]) == {"1001", "1002"}, "Foreign platforms must not request audience counts"
            assert not window._stats_refresh_timer.isActive()
            gate.set()
            wait_for(app, lambda: not window._resolvers_running)
            window._stats_refresh_timer.start()
        finally:
            gate.set()
            window.close()
        assert not window._stats_refresh_timer.isActive()
        window.refresh_stats()
        assert len(stats_ids) == 1
    print("PASS: pending stream preserved, one batched audience request, timer stopped on close")


def main():
    app = QApplication([])
    check_status(app)
    check_window(app)


if __name__ == "__main__":
    main()
