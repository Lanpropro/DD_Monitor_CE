"""Real native binding validation and copied-buffer lifetime checks on Windows."""
from __future__ import annotations

from array import array
import gc
import importlib
import os
from pathlib import Path
import socket
import sys
import tempfile
from time import perf_counter
from typing import Any, Callable
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
os.environ["DDM_NO_SAVE"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import Qt
from PySide6.QtGui import QWindow
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from ddm import config, images


def check(condition: bool, description: str) -> None:
    if not condition:
        raise AssertionError(description)


def payload(**changes: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"format": "BGRA_PREMULTIPLIED", "width": 1,
                              "height": 2, "stride": 8, "pixels": bytes(16)}
    result.update(changes)
    return result


def comment(image: dict[str, Any], **changes: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"view_id": 1, "room_epoch": 1, "style_rev": 1,
                              "comment_id": 1, "width": 40, "height": 20, "image": image}
    result.update(changes)
    return result


def scene(visible: bool = True) -> dict[str, Any]:
    return {"width": 320, "height": 180, "visible": visible, "views": [{
        "view_id": 1, "room_epoch": 1, "style_rev": 1, "width": 320, "height": 180,
        "lanes": 3, "lane_height": 30, "speed": 1, "opacity": 1,
        "clip": {"x": 0, "y": 0, "width": 320, "height": 180}}]}


def rejected(action: Callable[[], Any], description: str) -> None:
    try:
        action()
    except (ValueError, TypeError, OverflowError, RuntimeError):
        return
    raise AssertionError(description)


def pump_until(app: QApplication, condition: Callable[[], bool], description: str,
               timeout: float = 3) -> None:
    deadline = perf_counter() + timeout
    while perf_counter() < deadline:
        app.processEvents()
        if condition():
            return
        QTest.qWait(5)
    raise AssertionError(description)


def run_checks(app: QApplication, extension: Any) -> None:
    host = extension.NativeDanmakuHost()
    try:
        invalid = [payload(format="RGBA"), payload(width=0), payload(width=-1),
                   payload(height=0), payload(stride=3), payload(stride=-1),
                   payload(width=2**62), payload(height=2**62), payload(stride=2**62),
                   payload(width=16385), payload(height=16385),
                   payload(stride=16 * 1024 * 1024, height=2),
                   payload(pixels=bytes(15)), payload(pixels=bytes(17)),
                   payload(pixels=memoryview(bytes(32))[::2]),
                   payload(pixels=memoryview(bytes(16)).cast("B", shape=(4, 4))),
                   payload(pixels=array("H", range(8))), payload(pixels="invalid")]
        for index, image in enumerate(invalid):
            rejected(lambda image=image: host.submit_batch([comment(image)]),
                     f"invalid image {index} must fail before queue ownership")
        for changes in ({"width": float("nan")}, {"height": float("inf")},
                        {"age_seconds": -1}, {"comment_id": 0}, {"view_id": 0}):
            rejected(lambda changes=changes: host.submit_batch([comment(payload(), **changes)]),
                     "invalid logical metadata must fail")
        rejected(lambda: host.submit_batch([comment(payload())] * 257), "oversized batch fails")
        invalid_scene = scene()
        invalid_scene["views"] *= 2
        rejected(lambda: host.update_scene(invalid_scene), "duplicate view IDs fail")
        invalid_scene = scene()
        invalid_scene["views"][0]["mask"] = payload(stride=3)
        rejected(lambda: host.update_scene(invalid_scene), "mask uses same stride validation")
        check(host.status_snapshot()["image_bytes"] == 0, "validation refusals leave no image ledger")
        queued, _ = host.submit_batch([comment(payload(), comment_id=1), comment(payload(), comment_id=2)])
        check(queued == 2 and host.status_snapshot()["cpu_image_bytes"] == 32,
              "CPU total includes host queue before a render thread consumes images")
        check(host.status_snapshot()["image_bytes"] == 0, "engine ledger stays separate from host queue")
    finally:
        host.request_close()
        check(host.reap(), "unattached host closes without worker")
        check(host.status_snapshot()["cpu_image_bytes"] == 0, "close releases queued CPU images")

    window = QWindow()
    window.setFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                    Qt.WindowType.WindowTransparentForInput | Qt.WindowType.WindowDoesNotAcceptFocus)
    window.setGeometry(40, 40, 320, 180)
    window.create()
    host = extension.NativeDanmakuHost()
    attached = False
    try:
        host.attach(int(window.winId()))
        attached = True
        host.update_scene(scene(False))
        pump_until(app, lambda: host.status_snapshot()["state"] == "Suspended", "real host enters suspended scene")
        pixels = bytearray([0, 0, 255, 255, 0, 0, 0, 0] * 2)
        queued, sequence = host.submit_batch([comment(payload(pixels=pixels))])
        check(queued == 1 and sequence > 0, "padded-stride mutable byte buffer accepted")
        pixels[:] = bytes(len(pixels))
        pixels.clear()
        del pixels
        gc.collect()
        window.show()
        host.update_scene(scene())
        pump_until(app, lambda: host.status_snapshot()["state"] == "Failed" or
                   bool(host.status_snapshot()["active"]), "copied image admitted after Python buffer destruction")
        status = host.status_snapshot()
        check(status["state"] == "Running", f"real renderer running: {status}")
        check(status["active"] == [(1, 1)] and status["image_bytes"] == 16,
              "native owns original padded bytes after caller mutation and resize")
        check(status["frames"] > 0, "real D3D11 submitted copied image")
        host.update_scene({"width": 320, "height": 180, "views": []})
        pump_until(app, lambda: not host.status_snapshot()["active"] and
                   host.status_snapshot()["image_bytes"] == 0, "view removal releases native copied storage")
    finally:
        host.request_close()
        if attached:
            pump_until(app, host.reap, "real host completes asynchronous close")
        else:
            host.reap()
        window.destroy()


def main() -> int:
    app = QApplication.instance() or QApplication([])
    if not isinstance(app, QApplication):
        raise RuntimeError("QApplication is required")
    if sys.platform != "win32" or QApplication.platformName() != "windows":
        print("SKIP: binding native checks require Windows Qt platform and D3D11")
        return 0
    extension = importlib.import_module("ddm._native_danmaku")
    check(extension.contract_version == 1, "native contract version")
    with tempfile.TemporaryDirectory(prefix="ddm-native-binding-") as directory:
        config.CONFIG_PATH = str(Path(directory) / "config.json")
        images.CACHE_DIR = str(Path(directory) / "cache")
        with (patch.object(socket, "create_connection", side_effect=AssertionError("network forbidden")),
              patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden"))):
            run_checks(app, extension)
    print("native danmaku binding checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
