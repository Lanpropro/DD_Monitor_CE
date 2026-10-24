"""Shared native danmaku host and bounded, asynchronous image preparation."""
from __future__ import annotations

import importlib
import itertools
import math
import os
import sys
from collections import OrderedDict, deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from time import perf_counter, sleep
from typing import Any, Protocol

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPainter, QRegion, QWindow
from PySide6.QtWidgets import QApplication, QWidget

from .danmaku_content import content_runs
from .danmaku_raster import PreparedRaster, RasterStyle, rasterize
from .images import load_image


class NativeHost(Protocol):
    def attach(self, hwnd: int) -> None: ...
    def update_scene(self, scene: dict[str, Any]) -> None: ...
    def submit_batch(self, batch: list[dict[str, Any]]) -> tuple[int, int]: ...
    def status_snapshot(self) -> dict[str, Any]: ...
    def request_close(self) -> None: ...
    def reap(self) -> bool: ...


_view_ids = itertools.count(1)
_comment_ids = itertools.count(1)
_extension: Any = None
_import_attempted = False


def native_available() -> bool:
    global _extension, _import_attempted
    if (sys.platform != "win32" or QApplication.platformName() != "windows"
            or os.environ.get("DDM_NATIVE_DANMAKU", "1") == "0"
            or os.environ.get("DDM_QTQUICK_DANMAKU") == "1"):
        return False
    if not _import_attempted:
        _import_attempted = True
        try:
            _extension = importlib.import_module("ddm._native_danmaku")
            if getattr(_extension, "contract_version", None) != 1:
                raise ImportError("Unsupported native danmaku contract")
        except (ImportError, OSError) as exc:
            _extension = None
            print(f"[弹幕] D3D11 模块不可用，使用 QPainter：{exc}", file=sys.stderr)
    return _extension is not None


def image_payload(image: QImage) -> dict[str, Any]:
    if image.format() != QImage.Format.Format_ARGB32_Premultiplied:
        image = image.convertToFormat(QImage.Format.Format_ARGB32_Premultiplied)
    return {"format": "BGRA_PREMULTIPLIED", "width": image.width(),
            "height": image.height(), "stride": image.bytesPerLine(),
            "pixels": bytes(image.constBits())}


@dataclass
class _Entry:
    view_id: int
    comment_id: int
    epoch: int
    style_rev: int
    received: float
    text: str
    color: str
    runs: tuple[tuple[str, str], ...]
    self_sent: bool
    sequence: int = 0
    needs_image: bool = False


@dataclass
class _Job:
    entry: _Entry
    style_rev: int
    replace: bool
    future: Future[PreparedRaster]


@dataclass
class _View:
    overlay: Any
    view_id: int = field(default_factory=lambda: next(_view_ids))
    epoch: int = 1
    style_rev: int = 1
    signature: Any = None
    mask: dict[str, Any] | None = None
    mask_signature: Any = None
    jobs: deque[_Job] = field(default_factory=deque)


def _load_emote_image(url: str) -> QImage | None:
    image = load_image(url, "emoticons")
    if image is not None and image.sizeInBytes() > 1024 * 1024:
        image = image.scaled(512, 512, Qt.AspectRatioMode.KeepAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
    return image


class _CompositionWindow(QWindow):
    def nativeEvent(self, event_type: Any, message: Any) -> Any:
        if sys.platform == "win32":
            from ctypes import wintypes
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == 0x0084:
                return True, -1
            if msg.message == 0x0021:
                return True, 3
        return super().nativeEvent(event_type, message)


class NativeDanmakuLayer(QObject):
    stopped = Signal()

    def __init__(self, wall: QWidget, host: NativeHost | None = None) -> None:
        super().__init__(wall)
        if host is None and not native_available():
            raise RuntimeError("Native danmaku extension is unavailable")
        self.wall = wall
        self.host: NativeHost = host if host is not None else _extension.NativeDanmakuHost()
        self.views: dict[int, _View] = {}
        self.entries: dict[int, _Entry] = {}
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="danmaku-image")
        self._downloads = ThreadPoolExecutor(max_workers=2, thread_name_prefix="danmaku-emote")
        self._download_jobs: dict[str, Future[QImage | None]] = {}
        self._images: OrderedDict[str, QImage] = OrderedDict()
        self._image_bytes = 0
        self._retired: list[Future[Any]] = []
        self._reserved: dict[Future[Any], int] = {}
        self._closing = False
        self._stopped = False
        self._failed = False
        self._scene_revision = 0
        self._last_scene: Any = None
        self._status: dict[str, Any] = {}
        self.offered = 0
        self.queued = 0
        self.dropped_prepare = 0
        self.window = (_CompositionWindow() if QApplication.platformName() == "windows" else QWindow())
        self.window.setFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint |
                             Qt.WindowType.WindowTransparentForInput |
                             Qt.WindowType.WindowDoesNotAcceptFocus)
        wall.window().winId()
        self.window.setTransientParent(wall.window().windowHandle())
        self.window.setTitle("DDMonitor D3D11 Danmaku")
        self.window.create()
        self._configure_window(int(self.window.winId()))
        self._scene_timer = QTimer(self)
        self._scene_timer.setSingleShot(True)
        self._scene_timer.timeout.connect(self.sync_scene)
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(50)
        self._poll_timer.timeout.connect(self._poll)
        app = QApplication.instance()
        if app is None:
            raise RuntimeError("QApplication is required")
        app.installEventFilter(self)
        try:
            self.host.attach(int(self.window.winId()))
            self.sync_scene()
        except Exception:
            self.request_close()
            if self.host.reap():
                self._finish_close()
            else:
                self._poll_timer.start()
            raise
        self._poll_timer.start()

    @staticmethod
    def _configure_window(hwnd: int) -> None:
        if sys.platform != "win32" or QApplication.platformName() != "windows":
            return
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
        user32.EnableWindow.argtypes = [wintypes.HWND, wintypes.BOOL]
        style = user32.GetWindowLongW(hwnd, -20)
        user32.SetWindowLongW(hwnd, -20, (style & ~0x00080000) | 0x00200000 | 0x08000000 | 0x20)
        user32.EnableWindow(hwnd, False)
        user32.EnableWindow(hwnd, True)

    def attach(self, overlay: Any) -> None:
        if self._closing or any(view.overlay is overlay for view in self.views.values()):
            return
        view = _View(overlay)
        self.views[view.view_id] = view
        overlay._native_adapter = self
        overlay._native_view_id = view.view_id
        overlay._stop_timer()
        overlay.comments.clear()
        self.schedule_scene()

    def remove(self, overlay: Any) -> None:
        view = self.views.pop(overlay._native_view_id, None)
        if view is not None:
            self._cancel_jobs(view)
            self.entries = {key: entry for key, entry in self.entries.items()
                            if entry.view_id != view.view_id}
        overlay._native_adapter = None
        overlay._native_view_id = 0
        self.sync_scene()

    def clear(self, overlay: Any) -> None:
        view = self.views.get(overlay._native_view_id)
        if view is None:
            return
        view.epoch += 1
        self._cancel_jobs(view)
        self.entries = {key: entry for key, entry in self.entries.items()
                        if entry.view_id != view.view_id}
        self.schedule_scene()

    def _cancel_jobs(self, view: _View) -> None:
        while view.jobs:
            future = view.jobs.popleft().future
            future.cancel()
            self._retired.append(future)

    def schedule_scene(self) -> None:
        if not self._closing and not self._scene_timer.isActive():
            self._scene_timer.start(0)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() in (QEvent.Type.Move, QEvent.Type.Resize, QEvent.Type.Show,
                            QEvent.Type.Hide, QEvent.Type.WindowStateChange,
                            QEvent.Type.ScreenChangeInternal, QEvent.Type.WinIdChange):
            if isinstance(watched, QWidget) and (watched is self.wall.window() or
                    watched is self.wall or self.wall.isAncestorOf(watched)):
                self.schedule_scene()
        return False

    def _style(self, overlay: Any) -> RasterStyle:
        sampling = 1 if os.environ.get("DDM_NATIVE_DANMAKU_SAMPLE_SCALE") == "1" else 2
        return RasterStyle(overlay._font().family(), overlay.font_pixels(),
                           overlay.outline_width(), max(128, overlay.width() * 2),
                           overlay.devicePixelRatioF(), sampling)

    def _mask(self, view: _View) -> dict[str, Any] | None:
        overlay = view.overlay
        holes = QRegion()
        for widget in getattr(overlay, "_native_mask_widgets", ()):
            if widget.isVisible():
                region = widget.mask()
                if region.isEmpty():
                    region = QRegion(widget.rect())
                holes |= region.translated(widget.pos() - overlay.pos()).intersected(QRegion(overlay.rect()))
        signature = (overlay.width(), overlay.height(), overlay.devicePixelRatioF(),
                     holes, overlay.mask())
        if signature == view.mask_signature:
            return view.mask
        view.mask_signature = signature
        scale = overlay.devicePixelRatioF()
        width, height = round(overlay.width() * scale), round(overlay.height() * scale)
        if width <= 0 or height <= 0:
            view.mask = None
            return None
        image = QImage(width, height, QImage.Format.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(scale)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        region = overlay.mask()
        if region.isEmpty():
            region = QRegion(overlay.rect())
        painter.setClipRegion(region.subtracted(holes))
        painter.fillRect(overlay.rect(), Qt.GlobalColor.white)
        painter.end()
        view.mask = image_payload(image)
        return view.mask

    def sync_scene(self) -> None:
        if self._closing or self._failed:
            return
        origin = self.wall.mapToGlobal(QPoint())
        self.window.setGeometry(origin.x(), origin.y(), self.wall.width(), self.wall.height())
        scale = self.window.devicePixelRatio()
        views = []
        signatures = []
        for view in self.views.values():
            overlay = view.overlay
            style = self._style(overlay)
            if style != view.signature:
                if view.signature is not None:
                    view.style_rev += 1
                    self._cancel_jobs(view)
                    for entry in list(self.entries.values()):
                        if entry.view_id == view.view_id and entry.epoch == view.epoch:
                            entry.style_rev = view.style_rev
                            if not self._prepare(view, entry, replace=entry.sequence > 0) and not entry.sequence:
                                self.entries.pop(entry.comment_id, None)
                view.signature = style
            point = overlay.mapTo(self.wall, QPoint())
            left, top = round(point.x() * scale), round(point.y() * scale)
            right = round((point.x() + overlay.width()) * scale)
            bottom = round((point.y() + overlay.height()) * scale)
            mask = self._mask(view)
            data = {"view_id": view.view_id, "room_epoch": view.epoch,
                    "style_rev": view.style_rev, "width": overlay.width(),
                    "height": overlay.height(), "lane_height": overlay.lane_height(),
                    "lanes": overlay.lane_count(),
                    "speed": int(overlay.settings.get("video_danmaku_speed") or 100) / 100,
                    "opacity": int(overlay.settings.get("video_danmaku_opacity") or 80) / 100,
                    "visible": bool(overlay.isVisible() and overlay.enabled and overlay.active),
                    "paused": overlay.paused, "clip": {"x": left, "y": top,
                    "width": right - left, "height": bottom - top}, "mask": mask}
            views.append(data)
            signatures.append((view.view_id, view.epoch, view.style_rev, point.x(), point.y(),
                               overlay.width(), overlay.height(), data["lane_height"],
                               data["lanes"], data["speed"], data["opacity"], data["visible"],
                               data["paused"], view.mask_signature))
        screen = self.window.screen()
        visible = self.wall.isVisible() and not self.wall.window().isMinimized()
        signature = (self.wall.width(), self.wall.height(), scale, visible,
                     screen.name() if screen else "", signatures)
        if signature == self._last_scene:
            return
        self._last_scene = signature
        self._scene_revision += 1
        self.host.update_scene({"layout_rev": self._scene_revision,
            "width": round(self.wall.width() * scale), "height": round(self.wall.height() * scale),
            "screen": screen.name() if screen else "", "visible": visible, "views": views})
        if not visible:
            self.window.hide()

    def add_event(self, overlay: Any, event: dict[str, Any]) -> bool:
        self.offered += 1
        view = self.views.get(overlay._native_view_id)
        if view is None or self._closing or self._failed:
            return False
        pending = sum(len(item.jobs) for item in self.views.values())
        if (len(view.jobs) >= 64 or pending + len(self._retired) >= 256
                or len(self.entries) >= 16 * 144):
            self.dropped_prepare += 1
            return False
        text = " ".join(str(event.get("text") or "").split())[:300]
        if (not text and not event.get("emoticon")) or not overlay.lane_count():
            return False
        entry = _Entry(view.view_id, next(_comment_ids), view.epoch, view.style_rev,
                       perf_counter(), text, str(event.get("color") or "#ffffff"),
                       tuple(content_runs(dict(event, text=text))), bool(event.get("self_sent")))
        self.entries[entry.comment_id] = entry
        if not self._prepare(view, entry):
            self.entries.pop(entry.comment_id, None)
            return False
        for _, url in entry.runs:
            if url and url not in self._images and url not in self._download_jobs and len(self._download_jobs) < 16:
                self._download_jobs[url] = self._downloads.submit(_load_emote_image, url)
        self.queued += 1
        return True

    def _prepare(self, view: _View, entry: _Entry, replace: bool = False) -> bool:
        if len(view.jobs) >= 64 or sum(len(item.jobs) for item in self.views.values()) >= 256:
            self.dropped_prepare += 1
            return False
        style = self._style(view.overlay)
        scale = style.dpr * style.sample_scale
        reserve = (math.ceil((style.logical_max_width + 64) * scale)
                   * math.ceil((view.overlay.lane_height() + 64) * scale) * 4 * 3)
        native_bytes = int(self._status.get("cpu_image_bytes", self._status.get("image_bytes", 0)))
        if (reserve > 48 * 1024 * 1024
                or sum(self._reserved.values()) + native_bytes + reserve > 128 * 1024 * 1024):
            self.dropped_prepare += 1
            return False
        images = {url: QImage(self._images[url]) for _, url in entry.runs if url in self._images}
        future = self._pool.submit(rasterize, entry.text, entry.color, entry.runs,
                                   entry.self_sent, style, images)
        self._reserved[future] = reserve
        view.jobs.append(_Job(entry, view.style_rev, replace, future))
        return True

    def _collect_downloads(self) -> None:
        for url, future in list(self._download_jobs.items()):
            if not future.done():
                continue
            del self._download_jobs[url]
            try:
                image = future.result()
            except Exception:
                continue
            if image is None or image.isNull() or image.sizeInBytes() > 16 * 1024 * 1024:
                continue
            self._images[url] = image
            self._image_bytes += image.sizeInBytes()
            while self._image_bytes > 16 * 1024 * 1024 or len(self._images) > 128:
                _, removed = self._images.popitem(last=False)
                self._image_bytes -= removed.sizeInBytes()
            for entry in list(self.entries.values()):
                view = self.views.get(entry.view_id)
                if (view and entry.epoch == view.epoch
                        and any(image_url == url for _, image_url in entry.runs)):
                    entry.needs_image = True

    def _flush_jobs(self) -> None:
        batch = []
        submitted = []
        now = perf_counter()
        for view in self.views.values():
            while view.jobs and len(batch) < 32:
                job = view.jobs[0]
                entry = job.entry
                expired = not job.replace and now - entry.received >= .5
                if not job.future.done() and not expired:
                    break
                view.jobs.popleft()
                if not job.future.done():
                    job.future.cancel()
                    self._retired.append(job.future)
                if (expired or entry.epoch != view.epoch or job.style_rev != view.style_rev
                        or job.future.cancelled()):
                    self.dropped_prepare += 1
                    if not job.replace:
                        self.entries.pop(entry.comment_id, None)
                    continue
                try:
                    raster = job.future.result()
                except Exception as exc:
                    self.dropped_prepare += 1
                    if not job.replace:
                        self.entries.pop(entry.comment_id, None)
                    print(f"[弹幕] 图片准备失败：{exc}", file=sys.stderr)
                    continue
                if len(raster.bgra) > 16 * 1024 * 1024:
                    self.dropped_prepare += 1
                    if not job.replace:
                        self.entries.pop(entry.comment_id, None)
                    continue
                batch.append({"view_id": view.view_id, "room_epoch": entry.epoch,
                    "style_rev": job.style_rev, "comment_id": entry.comment_id,
                    "replace": job.replace, "width": raster.logical_width,
                    "height": raster.logical_height, "age_seconds": max(0, now - entry.received),
                    "image": {"format": "BGRA_PREMULTIPLIED", "width": raster.pixel_width,
                        "height": raster.pixel_height, "stride": raster.stride, "pixels": raster.bgra}})
                submitted.append(entry)
        if batch:
            queued, sequence = self.host.submit_batch(batch)
            for entry in submitted:
                if queued == 0 and not entry.sequence:
                    self.entries.pop(entry.comment_id, None)
                else:
                    entry.sequence = sequence
            if queued < len(batch):
                self.dropped_prepare += len(batch) - queued

    def _poll(self) -> None:
        self._retired = [future for future in self._retired if not future.done()]
        retained = {job.future for view in self.views.values() for job in view.jobs} | set(self._retired)
        self._reserved = {future: size for future, size in self._reserved.items() if future in retained}
        self._status = self.host.status_snapshot()
        if self._closing:
            if (self.host.reap() and not self._retired
                    and all(future.done() for future in self._download_jobs.values())):
                self._finish_close()
            return
        if self._status.get("state") == "Failed":
            self._failed = True
            print(f"[弹幕] D3D11 运行失败：{self._status}", file=sys.stderr)
            self.request_close()
            return
        active = {int(item[1]) for item in self._status.get("active", [])}
        pending = {int(item[1]) for item in self._status.get("pending", [])}
        jobs = {job.entry.comment_id for view in self.views.values() for job in view.jobs}
        watermark = int(self._status.get("processed_sequence", 0))
        for key, entry in list(self.entries.items()):
            if entry.sequence and entry.sequence <= watermark and key not in active | pending | jobs:
                del self.entries[key]
        self._collect_downloads()
        for entry in self.entries.values():
            view = self.views.get(entry.view_id)
            if (view and entry.needs_image and entry.comment_id in active
                    and entry.comment_id not in jobs and self._prepare(view, entry, replace=True)):
                entry.needs_image = False
        self.sync_scene()
        self._flush_jobs()
        visible = bool(self._status.get("needs_visible") and self.wall.isVisible()
                       and not self.wall.window().isMinimized())
        self.window.setVisible(visible)

    def status_snapshot(self) -> dict[str, Any]:
        return dict(self.host.status_snapshot(), prepare_offered=self.offered,
                    prepare_queued=self.queued, dropped_prepare=self.dropped_prepare,
                    metadata_entries=len(self.entries),
                    prepare_reserved_bytes=sum(self._reserved.values()),
                    emoticon_bytes=self._image_bytes,
                    prepare_pending=sum(len(view.jobs) for view in self.views.values()))

    def request_close(self) -> None:
        if self._closing:
            return
        self._closing = True
        self._scene_timer.stop()
        self.window.hide()
        for view in self.views.values():
            self._cancel_jobs(view)
        for future in self._download_jobs.values():
            future.cancel()
        self._pool.shutdown(wait=False, cancel_futures=True)
        self._downloads.shutdown(wait=False, cancel_futures=True)
        self.host.request_close()

    def close_ready(self) -> bool:
        return self._stopped

    def _finish_close(self) -> None:
        self._poll_timer.stop()
        self._stopped = True
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        self.window.destroy()
        self.entries.clear()
        self._images.clear()
        if self._failed:
            for view in self.views.values():
                view.overlay.use_raster_fallback()
        self.stopped.emit()


def run_probe(output: str) -> int:
    import json
    from pathlib import Path
    from PySide6.QtCore import qVersion
    from .video_danmaku import VideoDanmaku

    destination = Path(output).resolve()
    app = QApplication.instance() or QApplication([sys.argv[0]])
    if not isinstance(app, QApplication):
        raise RuntimeError("QApplication is required")
    app.setQuitOnLastWindowClosed(False)
    wall = QWidget()
    wall.resize(480, 240)
    wall.show()
    overlay = VideoDanmaku(wall)
    overlay.resize(480, 240)
    overlay.apply_settings({"video_danmaku_scale": False, "video_danmaku_size": 24})
    overlay.set_enabled(True)
    overlay.set_active(True)
    layer: NativeDanmakuLayer | None = None
    forced = os.environ.get("DDM_NATIVE_PROBE_FORCE_FAILURE") == "1"
    result: dict[str, Any] = {"ok": False, "backend": "d3d11", "attached": False,
        "reaped": False, "python_tag": f"cp{sys.version_info.major}{sys.version_info.minor}",
        "qt_version": qVersion(), "state": "Starting", "error": None}
    try:
        extension = importlib.import_module("ddm._native_danmaku")
        result["module_path"] = extension.__file__
        if forced:
            host: NativeHost = extension.NativeDanmakuHost()
            try:
                host.attach(0)
            except Exception as exc:
                result["error"] = {"stage": "attach", "message": str(exc)}
            else:
                raise RuntimeError("Invalid HWND injection unexpectedly succeeded")
            host.request_close()
            if not host.reap():
                raise RuntimeError("Failed probe did not stop")
            overlay.use_raster_fallback()
            app.processEvents()
            if not overlay.add_event({"text": "Fallback probe"}) or not overlay.timer.isActive():
                raise RuntimeError("Raster fallback did not start")
            result.update(ok=True, backend="qpainter", fallback=True, reaped=True,
                          state="Stopped", frames=0)
        else:
            layer = NativeDanmakuLayer(wall)
            layer.attach(overlay)
            if not overlay.add_event({"text": "D3D11 probe"}):
                raise RuntimeError("Probe preparation rejected")
            deadline = perf_counter() + 8
            while perf_counter() < deadline:
                app.processEvents()
                status = layer.host.status_snapshot()
                if status["state"] == "Failed":
                    raise RuntimeError(str(status))
                if status["frames"] > 1 and status["counters"]["admitted"]:
                    break
                sleep(.005)
            else:
                raise TimeoutError("Native probe did not render")
            result.update(attached=True, frames=status["frames"])
            layer.request_close()
            deadline = perf_counter() + 8
            while not layer.close_ready() and perf_counter() < deadline:
                app.processEvents()
                sleep(.005)
                sleep(.005)
            result.update(ok=layer.close_ready(), reaped=layer.close_ready(),
                          state=layer.host.status_snapshot()["state"])
    except Exception as exc:
        result["error"] = {"stage": "probe", "message": str(exc)}
    finally:
        if layer is not None and not layer.close_ready():
            layer.request_close()
            deadline = perf_counter() + 8
            while not layer.close_ready() and perf_counter() < deadline:
                app.processEvents()
        overlay.close()
        wall.close()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if result["ok"] else 1
