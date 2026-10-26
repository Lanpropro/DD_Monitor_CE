"""Offline native adapter checks with controlled futures and no network."""
from __future__ import annotations

import os
from pathlib import Path
import socket
import sys
import tempfile
import shiboken6
from concurrent.futures import Future
from typing import Any, cast
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["DDM_NO_SAVE"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtGui import QFont, QImage
from PySide6.QtWidgets import QApplication, QWidget

from ddm import config, images
from ddm import native_danmaku as bridge
from ddm.danmaku_raster import PreparedRaster


def check(value: bool, description: str) -> None:
    if not value:
        raise AssertionError(description)


def raster() -> PreparedRaster:
    image = QImage(4, 4, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0xFFFFFFFF)
    return PreparedRaster(image, 4, 4, 4, 4, image.bytesPerLine(), bytes(image.constBits()))


class ControlledPool:
    def __init__(self, **kwargs: Any) -> None:
        self.futures: list[Future[Any]] = []
        self.closed = False

    def submit(self, *args: Any, **kwargs: Any) -> Future[Any]:
        future: Future[Any] = Future()
        future.set_running_or_notify_cancel()
        self.futures.append(future)
        return future

    def shutdown(self, **kwargs: Any) -> None:
        check(kwargs.get("wait") is False, "executor shutdown never waits on GUI thread")
        self.closed = True

    def complete(self, result: Any = None) -> None:
        for future in self.futures:
            if not future.done():
                future.set_result(raster() if result is None else result)


class FakeHost:
    def __init__(self) -> None:
        self.scenes: list[dict[str, Any]] = []
        self.batches: list[list[dict[str, Any]]] = []
        self.sequence = 0
        self.accept = True
        self.closed = False
        self.reaped = False
        self.status: dict[str, Any] = {"state": "Running", "active": [], "pending": [],
                                      "views": [], "processed_sequence": 0, "needs_visible": False}

    def attach(self, hwnd: int) -> None:
        check(hwnd != 0, "adapter creates host window")

    def update_scene(self, scene: dict[str, Any]) -> None:
        self.scenes.append(scene)
        if "views" in self.status:
            self.status["views"] = [{
                "view_id": item["view_id"], "room_epoch": item["room_epoch"],
                "style_rev": item["style_rev"], "can_start": True,
            } for item in scene.get("views", [])]

    def submit_batch(self, batch: list[dict[str, Any]]) -> tuple[int, int]:
        self.batches.append(batch)
        if not self.accept:
            return 0, self.sequence
        self.sequence += len(batch)
        return len(batch), self.sequence

    def status_snapshot(self) -> dict[str, Any]:
        return dict(self.status)

    def request_close(self) -> None:
        self.closed = True

    def reap(self) -> bool:
        return self.reaped


class Overlay(QWidget):
    def __init__(self, wall: QWidget) -> None:
        super().__init__(wall)
        self.enabled = self.active = True
        self.paused = False
        self.settings: dict[str, Any] = {}
        self.comments: list[Any] = []
        self.font_size = 20
        self._native_view_id = 0
        self._native_adapter: Any = None
        self._native_requested = True
        self._native_mask_widgets: tuple[QWidget, ...] = ()
        self.resize(320, 180)
        self.show()

    def _font(self) -> QFont:
        return QFont("Arial")

    def font_pixels(self) -> int:
        return self.font_size

    def outline_width(self) -> float:
        return 1

    def lane_height(self) -> int:
        return 28

    def lane_count(self) -> int:
        return 3

    def _stop_timer(self) -> None:
        pass

    def _sync_visible(self) -> None:
        self.setVisible(self.enabled and self.active)

    def use_raster_fallback(self) -> None:
        from ddm.video_danmaku import VideoDanmaku

        VideoDanmaku.use_raster_fallback(cast(Any, self))


class Harness:
    def __init__(self) -> None:
        self.wall = QWidget()
        self.wall.resize(640, 360)
        self.wall.show()
        self.host = FakeHost()
        self.layer = bridge.NativeDanmakuLayer(self.wall, self.host)
        self.layer._poll_timer.stop()
        self.pool = cast(ControlledPool, self.layer._pool)
        self.downloads = cast(ControlledPool, self.layer._downloads)
        self.overlay = Overlay(self.wall)
        self.layer.attach(self.overlay)
        self.layer.sync_scene()

    def dispose(self) -> None:
        self.layer.request_close()
        self.pool.complete()
        self.downloads.complete(QImage())
        self.host.reaped = True
        self.host.status["state"] = "Stopped"
        self.layer._poll()
        check(self.layer.close_ready(), "completed host and futures close")
        self.wall.close()
        app = QApplication.instance()
        if app is not None:
            app.processEvents()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        check(not shiboken6.isValid(self.layer.window),
              "stopped native host releases its Qt window on the GUI thread")


def check_bounds() -> None:
    h = Harness()
    try:
        accepted = sum(h.layer.add_event(h.overlay, {"text": f"comment {i}"}) for i in range(400))
        view = h.layer.views[h.overlay._native_view_id]
        check(0 < accepted <= 64 and len(view.jobs) <= 64, "per view preparation remains bounded")
        check(h.layer.status_snapshot()["prepare_reserved_bytes"] == sum(h.layer._reserved.values()),
              "public status reports preparation reservations")
        for _ in range(8):
            h.layer.clear(h.overlay)
            for i in range(80):
                h.layer.add_event(h.overlay, {"text": str(i)})
        pending = sum(len(view.jobs) for view in h.layer.views.values())
        check(pending + len(h.layer._retired) <= 256, "running canceled jobs consume global preparation bound")
        check(len(h.layer.entries) <= 256, "metadata remains bounded before acknowledgment")
    finally:
        h.dispose()


def check_epoch_removal_and_ack() -> None:
    h = Harness()
    try:
        check(h.layer.add_event(h.overlay, {"text": "old"}), "prepare old generation")
        old_epoch = h.layer.views[h.overlay._native_view_id].epoch
        h.layer.clear(h.overlay)
        h.pool.complete()
        h.layer._flush_jobs()
        check(not h.host.batches and not h.layer.entries, "clear discards late old generation result")
        h.layer.sync_scene()
        check(h.host.scenes[-1]["views"][0]["room_epoch"] == old_epoch + 1, "clear advances scene epoch")
        check(h.layer.add_event(h.overlay, {"text": "new"}), "prepare new generation")
        h.pool.complete()
        h.layer._flush_jobs()
        comment_id = h.host.batches[-1][0]["comment_id"]
        h.host.status.update(processed_sequence=h.host.sequence, active=[(h.overlay._native_view_id, comment_id)])
        h.layer._poll()
        check(comment_id in h.layer.entries, "active native ID keeps metadata after watermark")
        h.host.status["active"] = []
        h.layer._poll()
        check(not h.layer.entries, "watermark plus active and pending IDs release metadata")
        check(h.layer.add_event(h.overlay, {"text": "remove pending"}), "prepare before removal")
        h.layer.remove(h.overlay)
        h.pool.complete()
        h.layer._flush_jobs()
        check(not h.host.scenes[-1]["views"] and not h.layer.entries, "removed view disappears and frees metadata")
        check(not h.layer.add_event(h.overlay, {"text": "removed"}), "removed overlay refuses work")
    finally:
        h.dispose()


def check_native_lane_preflight() -> None:
    h = Harness()
    try:
        h.layer._status = h.host.status_snapshot()
        h.host.status["views"][0]["can_start"] = False
        check(not h.layer.add_event(h.overlay, {"text": "blocked"}), "blocked lane is rejected before raster")
        check(not h.pool.futures and len(h.layer.entries) == 0
              and h.layer.lane_preflight_offered == 1
              and h.layer.lane_preflight_rejected == 1
              and h.layer.lane_preflight_refreshed == 1,
              "lane preflight refusal creates no worker or metadata")
        h.host.status["views"][0]["can_start"] = True
        h.layer._status = h.host.status_snapshot()
        check(h.layer.add_event(h.overlay, {"text": "released"}), "released lane starts raster")
        check(len(h.pool.futures) == 1 and len(h.layer.entries) == 1,
              "released lane queues exactly once")
        h.host.status["views"][0]["style_rev"] += 1
        check(h.layer.add_event(h.overlay, {"text": "stale status"}),
              "stale preflight state defers the decision to native lane ownership")
        check(h.layer.lane_preflight_rejected == 1,
              "stale preflight state is not treated as an explicit refusal")
        h.host.status["views"][0]["style_rev"] -= 1
        entry = next(iter(h.layer.entries.values()))
        view = h.layer.views[h.overlay._native_view_id]
        check(h.layer._prepare(view, entry, replace=True), "active replacement bypasses lane preflight")
        h.host.status.pop("views")
        check(h.layer.add_event(h.overlay, {"text": "legacy host"}),
              "legacy host status preserves compatibility fallback")
    finally:
        h.dispose()


def check_lane_preflight_switch() -> None:
    h = Harness()
    try:
        h.host.status["views"][0]["can_start"] = False
        h.layer._status = h.host.status_snapshot()
        with patch.object(bridge, "_LANE_PREFLIGHT", False):
            check(h.layer.add_event(h.overlay, {"text": "control"}),
                  "A/B control bypasses only the early lane check")
        check(len(h.pool.futures) == 1 and h.layer.lane_preflight_offered == 0
              and h.layer.lane_preflight_rejected == 0,
              "disabled preflight still uses final native lane ownership")
        with patch.object(bridge, "_LANE_PREFLIGHT", True), \
                patch.object(bridge, "_LANE_PREFLIGHT_REFRESH", False):
            h.layer._status = h.host.status_snapshot()
            check(not h.layer.add_event(h.overlay, {"text": "cached false"}),
                  "cached lane query fails closed")
            check(h.layer.lane_preflight_refreshed == 0,
                  "cached lane query performs no status refresh")
    finally:
        h.dispose()


def check_rejected_batch_cleanup() -> None:
    h = Harness()
    try:
        h.host.accept = False
        check(h.layer.add_event(h.overlay, {"text": "rejected"}), "queued before native refusal")
        h.pool.complete()
        h.layer._flush_jobs()
        h.layer._poll()
        check(not h.layer.entries, "fully rejected first batch cannot leak sequence-zero metadata")
    finally:
        h.dispose()


def check_style_under_budget_pressure() -> None:
    h = Harness()
    try:
        for index in range(400):
            h.layer.add_event(h.overlay, {"text": f"reserved {index}"})
        check(bool(h.layer.entries), "pressure scenario has prepared metadata")
        h.overlay.font_size += 1
        h.layer.sync_scene()
        queued_ids = {job.entry.comment_id for view in h.layer.views.values() for job in view.jobs}
        check(all(entry.sequence or entry.comment_id in queued_ids for entry in h.layer.entries.values()),
              "style rebuild cannot strand sequence-zero metadata when preparation budget is full")
        check(sum(h.layer._reserved.values()) <= 128 * 1024 * 1024,
              "in-flight plus retired future reservations stay within CPU budget")
    finally:
        h.dispose()


def check_prepare_ttl_and_order() -> None:
    h = Harness()
    try:
        check(h.layer.add_event(h.overlay, {"text": "slow first"}), "first task accepted")
        check(h.layer.add_event(h.overlay, {"text": "ready second"}), "second task accepted")
        h.pool.futures[-1].set_result(raster())
        h.layer._flush_jobs()
        check(not h.host.batches, "prepared follower waits for earlier message within ordering window")
        first_entry = next(iter(h.layer.entries.values()))
        first_entry.received -= 1
        h.layer._flush_jobs()
        check(len(h.host.batches) == 1 and len(h.host.batches[0]) == 1,
              "expired preparation head releases ready follower")
        check(first_entry.comment_id not in h.layer.entries, "expired preparation frees metadata")
        check(bool(h.layer._retired) and not h.layer._retired[-1].done(), "running expired worker retained until completion")
        h.pool.complete()
        h.layer._poll()
        check(not h.layer._retired, "completed retired worker is reclaimed")
    finally:
        h.dispose()


def check_native_bytes_limit_preparation() -> None:
    h = Harness()
    try:
        h.host.status["image_bytes"] = 128 * 1024 * 1024
        h.layer._poll()
        check(not h.layer.add_event(h.overlay, {"text": "budget exhausted"}),
              "native CPU images share preparation reservation budget")
        check(not h.layer.entries and not h.pool.futures,
              "byte-budget refusal creates no worker or metadata")
        h.host.status["image_bytes"] = 0
        h.layer._poll()
        check(h.layer.add_event(h.overlay, {"text": "budget reclaimed"}),
              "preparation resumes after native image reclamation")
    finally:
        h.dispose()


def check_binding_copy_fits_total_budget() -> None:
    h = Harness()
    try:
        h.overlay.resize(1920, 1080)
        h.overlay.font_size = 144
        h.layer.sync_scene()
        native_bytes = 20 * 1024 * 1024
        h.host.status["cpu_image_bytes"] = native_bytes
        h.host.status["views"][0]["can_start"] = True
        h.layer._poll()
        with patch.object(h.overlay, "lane_height", return_value=152):
            event = {"text": "W" * 300, "self_sent": True}
            accepted = sum(h.layer.add_event(h.overlay, event) for _ in range(12))
            image = bridge.rasterize(event["text"], "white", (), True, h.layer._style(h.overlay))
        peak = native_bytes + accepted * (image.image.sizeInBytes() + len(image.bgra) * 2)
        check(accepted > 0 and peak <= 128 * 1024 * 1024,
              "ready QImage, Python BGRA and binding copy fit the shared CPU image budget")
    finally:
        h.dispose()


def check_wall_initialization_fallback() -> None:
    from ddm.widgets import WallGrid

    wall = QWidget()
    overlays = [Overlay(wall), Overlay(wall)]
    for overlay in overlays:
        overlay.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
    owner = SimpleNamespace(_native_danmaku_layer=None, _native_danmaku_attempted=False,
                            tiles=[SimpleNamespace(video_danmaku=overlay) for overlay in overlays])
    try:
        with patch.object(bridge, "NativeDanmakuLayer", side_effect=RuntimeError("injected host initialization failure")):
            layer = WallGrid.ensure_native_danmaku_layer(cast(Any, owner))
        check(layer is None and owner._native_danmaku_attempted, "initialization fallback remains attempt-once")
        check(all(not overlay._native_requested for overlay in overlays), "initialization failure restores every overlay backend")
        check(all(not overlay.testAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen) for overlay in overlays),
              "initialization fallback restores onscreen rendering for every overlay")
    finally:
        wall.close()


def check_constructor_failure_cleanup() -> None:
    wall = QWidget()
    host = FakeHost()
    host.reaped = True
    try:
        with patch.object(host, "attach", side_effect=RuntimeError("injected attach failure")):
            try:
                bridge.NativeDanmakuLayer(wall, host)
            except RuntimeError as error:
                check(str(error) == "injected attach failure", "original startup error is preserved")
            else:
                raise AssertionError("host attachment must fail")
        check(host.closed, "partially initialized host receives asynchronous stop")
        layers = wall.findChildren(bridge.NativeDanmakuLayer)
        check(len(layers) == 1 and layers[0].close_ready(), "partial startup is fully reaped")
        check(not layers[0]._poll_timer.isActive(), "partial startup leaves no polling timer")
        check(cast(ControlledPool, layers[0]._pool).closed and cast(ControlledPool, layers[0]._downloads).closed,
              "partial startup cancels both executors")
    finally:
        wall.close()
        app = QApplication.instance()
        if app is not None:
            app.processEvents()


def check_missing_contract_falls_back() -> None:
    with (patch.object(bridge, "_import_attempted", False),
          patch.object(bridge, "_extension", None),
          patch.object(bridge.QApplication, "platformName", return_value="windows"),
          patch.object(bridge.importlib, "import_module", return_value=SimpleNamespace()),
          patch.dict(os.environ, {"DDM_NATIVE_DANMAKU": "1", "DDM_QTQUICK_DANMAKU": "0"})):
        check(not bridge.native_available(), "old native binary without contract_version falls back cleanly")


def check_runtime_failure_rejects_stopped_layer() -> None:
    from ddm.widgets import WallGrid

    h = Harness()
    try:
        h.overlay.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        h.host.status["state"] = "Failed"
        h.layer._poll()
        h.layer._poll()
        check(not h.layer.close_ready(),
              "runtime failure waits for native thread reaping")
        h.host.reaped = True
        h.layer._poll()
        check(h.layer.close_ready() and not h.overlay._native_requested,
              "runtime failure finishes asynchronous stop from Failed state before fallback")
        check(not h.overlay.testAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen),
              "runtime fallback restores QWidget onscreen rendering")
        owner = SimpleNamespace(_native_danmaku_layer=h.layer, _native_danmaku_attempted=True)
        check(WallGrid.ensure_native_danmaku_layer(cast(Any, owner)) is None,
              "new tiles cannot attach to a stopped failed native layer")
    finally:
        h.dispose()


def check_emote_download_admission_races() -> None:
    for before_initial_prepare in (True, False):
        h = Harness()
        try:
            check(h.layer.add_event(h.overlay, {"text": "delayed emote"}), "initial image preparation accepted")
            entry = next(iter(h.layer.entries.values()))
            entry.runs = (("", "https://example.invalid/race.png"),)
            if not before_initial_prepare:
                h.pool.complete()
                h.layer._flush_jobs()
                h.host.status.update(processed_sequence=h.host.sequence,
                                     pending=[(entry.view_id, entry.comment_id)])
            future: Future[QImage | None] = Future()
            image = QImage(2, 2, QImage.Format.Format_ARGB32_Premultiplied)
            image.fill(0xFFFFFFFF)
            future.set_result(image)
            h.layer._download_jobs[entry.runs[0][1]] = future
            h.layer._poll()
            check(entry.needs_image, "download completion records replacement intent before native admission")
            check(h.layer.status_snapshot()["emoticon_bytes"] == image.sizeInBytes(),
                  "public status reports cached emote bytes")
            if before_initial_prepare:
                check(not h.host.batches and len(h.pool.futures) == 1,
                      "download before initial preparation does not prematurely create replacement")
                h.pool.complete()
                h.layer._poll()
                h.host.status.update(processed_sequence=h.host.sequence,
                                     pending=[(entry.view_id, entry.comment_id)])
            h.layer._poll()
            check(entry.needs_image and len(h.host.batches) == 1 and len(h.pool.futures) == 1,
                  "native pending state retains image intent without rejected premature replacement")
            h.host.status.update(pending=[], active=[(entry.view_id, entry.comment_id)])
            entry.received -= 10
            h.layer._poll()
            check(not entry.needs_image and len(h.pool.futures) == 2,
                  "native active acknowledgment schedules deferred replacement exactly once")
            h.pool.complete()
            h.layer._poll()
            check(len(h.host.batches) == 2 and h.host.batches[-1][0]["replace"]
                  and h.host.batches[-1][0]["comment_id"] == entry.comment_id,
                  "both early-download races eventually replace stable active ID beyond new-comment TTL")
            h.layer._poll()
            check(len(h.pool.futures) == 2, "completed replacement intent does not reschedule indefinitely")
        finally:
            h.dispose()


def check_emote_future_image_bound() -> None:
    large = QImage(2048, 1024, QImage.Format.Format_ARGB32_Premultiplied)
    large.fill(0xFFFFFFFF)
    with patch.object(bridge, "load_image", return_value=large) as loader:
        result = bridge._load_emote_image("https://example.invalid/large.png")
    loader.assert_called_once_with("https://example.invalid/large.png", "emoticons")
    check(result is not None and result.width() == 512 and result.height() == 256,
          "large download future output preserves aspect ratio within 512 pixels")
    check(result is not None and result.sizeInBytes() <= 1024 * 1024,
          "sixteen completed download future outputs use at most sixteen MiB")
    small = QImage(128, 64, QImage.Format.Format_ARGB32_Premultiplied)
    with patch.object(bridge, "load_image", return_value=small):
        unchanged = bridge._load_emote_image("https://example.invalid/small.png")
    check(unchanged is not None and unchanged.size() == small.size(), "small emote retains original dimensions")
    with patch.object(bridge, "load_image", return_value=None):
        check(bridge._load_emote_image("https://example.invalid/missing.png") is None,
              "failed emote download remains absent")


def check_style_emote_scene_and_close() -> None:
    h = Harness()
    try:
        check(h.layer.add_event(h.overlay, {"text": "active"}), "prepare original image")
        h.pool.complete()
        h.layer._flush_jobs()
        item = h.host.batches[-1][0]
        entry = h.layer.entries[item["comment_id"]]
        entry.received -= 10
        entry.runs = (("", "https://example.invalid/emote.png"),)
        future: Future[QImage | None] = Future()
        image = QImage(2, 2, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(0xFFFFFFFF)
        future.set_result(image)
        h.layer._download_jobs[entry.runs[0][1]] = future
        h.host.status.update(processed_sequence=h.host.sequence,
                             active=[(entry.view_id, entry.comment_id)])
        h.layer._poll()
        h.pool.complete()
        h.layer._flush_jobs()
        replacement = h.host.batches[-1][0]
        check(replacement["replace"] and replacement["comment_id"] == item["comment_id"], "late emote replaces stable ID beyond new-message TTL")
        old_style = replacement["style_rev"]
        h.overlay.font_size += 1
        h.overlay.paused = True
        hole = QWidget(h.wall)
        hole.setGeometry(10, 10, 20, 20)
        hole.show()
        h.overlay._native_mask_widgets = (hole,)
        h.layer.sync_scene()
        current = h.host.scenes[-1]["views"][0]
        check(current["style_rev"] == old_style + 1 and current["paused"], "style revision and pause sent atomically")
        mask = current["mask"]
        check(mask is not None and mask["format"] == "BGRA_PREMULTIPLIED", "mask carries premultiplied BGRA")
        offset = 15 * mask["stride"] + 15 * 4
        check(mask["pixels"][offset + 3] == 0 and mask["pixels"][3] == 255, "control hole excluded from mask")
        h.pool.complete()
        h.layer._flush_jobs()
        check(h.host.batches[-1][0]["replace"], "style redraw replaces active ID")
        view = h.layer.views[h.overlay._native_view_id]
        h.layer._prepare(view, entry, replace=True)
        h.pool.futures[-1].set_exception(RuntimeError("injected replacement failure"))
        h.layer._flush_jobs()
        check(entry.comment_id in h.layer.entries, "replacement failure keeps active image metadata")
        h.layer._poll()
        check(h.layer.add_event(h.overlay, {"text": "running on close"}), "pending worker for close")
        running = h.pool.futures[-1]
        h.layer.request_close()
        check(h.host.closed and not h.layer.close_ready() and not running.done(), "close returns while worker and host are still running")
        h.host.reaped = True
        h.host.status["state"] = "Stopped"
        h.layer._poll()
        check(not h.layer.close_ready(), "host stop waits asynchronously for outstanding worker")
        running.set_result(raster())
        h.layer._poll()
        check(h.layer.close_ready(), "worker completion finishes close without live join")
    finally:
        h.dispose()


def main() -> int:
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory(prefix="ddm-native-bridge-") as directory:
        config.CONFIG_PATH = str(Path(directory) / "config.json")
        images.CACHE_DIR = str(Path(directory) / "cache")
        with (patch.object(bridge, "ThreadPoolExecutor", ControlledPool),
              patch.object(bridge, "load_image", side_effect=AssertionError("network loader forbidden")),
              patch.object(socket, "create_connection", side_effect=AssertionError("network forbidden")),
              patch.object(socket.socket, "connect", side_effect=AssertionError("network forbidden"))):
            check_bounds()
            check_epoch_removal_and_ack()
            check_native_lane_preflight()
            check_lane_preflight_switch()
            check_rejected_batch_cleanup()
            check_style_under_budget_pressure()
            check_prepare_ttl_and_order()
            check_native_bytes_limit_preparation()
            check_binding_copy_fits_total_budget()
            check_wall_initialization_fallback()
            check_constructor_failure_cleanup()
            check_missing_contract_falls_back()
            check_runtime_failure_rejects_stopped_layer()
            check_emote_download_admission_races()
            check_emote_future_image_bound()
            check_style_emote_scene_and_close()
    app.processEvents()
    print("native danmaku bridge checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
