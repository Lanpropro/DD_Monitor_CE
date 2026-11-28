"""Native and Quick surface integration; VideoDanmaku retains timers, mask overrides and Qt ownership."""
import math
import sys
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetrics, QImage, QPainter, QPen, QPixmap, QRegion
from PySide6.QtWidgets import QApplication, QPushButton, QWidget


class VideoDanmakuSurface:
    def __init__(self, host):
        self.host = host
        self.windowed_occluders = None

    def sync_visible(self) -> None:
        host = self.host
        visible = host.enabled and host.active
        host.super_chat_overlay._refresh()
        if not visible:
            # Erase the native backing while still visible. Hiding first leaves
            # its last rendered comments cached until the next asynchronous paint.
            host._set_hover(None)
            host._stop_timer()
            host.comments.clear()
            host._pending_comments.clear()
            if host._quick_layer is not None and host._quick_group is not None:
                host._quick_layer.clear_group(host._quick_group)
            host._last_tick = 0.0
            if host.isVisible():
                host.repaint()
            else:
                host.update()
        host.setVisible(visible)
        if visible and host.comments and not host.paused:
            host._start_timer()

    def native_layered(self) -> bool:
        host = self.host
        return (host.native_video and sys.platform == "win32"
                and QApplication.platformName() == "windows")

    def apply_layered(self) -> None:
        host = self.host
        if host._quick_requested:
            host._suppress_quick_raster_surface()
            if host._quick_layer is not None and host._quick_group is not None:
                host._quick_layer.set_group_opacity(
                    host._quick_group, int(host.settings.get("video_danmaku_opacity") or 80))
            return
        if not host._native_layered():
            return
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
        user32.SetLayeredWindowAttributes.argtypes = [
            wintypes.HWND, wintypes.DWORD, wintypes.BYTE, wintypes.DWORD]
        hwnd = int(host.winId())
        style = user32.GetWindowLongW(hwnd, -20)
        user32.SetWindowLongW(hwnd, -20, style | 0x00080000 | 0x00000020)
        if host.native_alpha:
            host._schedule_layered_paint()
            return
        key = host.COLOR_KEY.red() | host.COLOR_KEY.green() << 8 | host.COLOR_KEY.blue() << 16
        alpha = round(int(host.settings.get("video_danmaku_opacity") or 80) * 255 / 100)
        user32.SetLayeredWindowAttributes(hwnd, key, alpha, 0x00000001 | 0x00000002)

    def set_windowed_quick_layer(self, layer, occluders=None) -> None:
        host = self.host
        if host.native_video or layer is host._quick_layer:
            return
        if host.timer.isActive():
            host._tick()
        host._stop_timer()
        host._last_tick = 0
        if layer is None:
            host._quick_requested = False
            if host._quick_group is not None:
                host._quick_layer.remove_group(host._quick_group)
            host._quick_layer = host._quick_group = None
            host._quick_mask_signature = None
            self.windowed_occluders = None
            host.setMask(host._quick_video_mask)
            host.update()
        else:
            host._quick_video_mask = host.mask()
            host._quick_requested = True
            self.windowed_occluders = occluders
            self.attach_quick_layer(layer)
            self.apply_layered()
        if host.comments and host.isVisible() and not host.paused:
            host._start_timer()

    def attach_quick_layer(self, layer) -> None:
        host = self.host
        if not host._quick_requested or layer is None:
            return
        if host._quick_layer is layer and host._quick_group is not None:
            host._sync_quick_geometry()
            return
        if host._quick_layer is not None and host._quick_group is not None:
            host._quick_layer.remove_group(host._quick_group)
        host._quick_layer = layer
        tile = host.parentWidget()
        host._quick_rounded = not bool(tile.property("fullscreen"))
        host._quick_group = layer.create_group(
            0, 0, host.width(), host.height(),
            int(host.settings.get("video_danmaku_opacity") or 80),
            rounded=host._quick_rounded)
        host._sync_quick_geometry()
        if self.windowed_occluders is not None:
            layer.set_group_visible(host._quick_group, host.isVisible())
            tile._update_quick_danmaku_mask()
        for comment in host.comments:
            comment.render_id = layer.add(
                host._quick_group, comment.image.toImage(), comment.x,
                comment.lane * host.lane_height(),
                comment.image.width() / comment.image.devicePixelRatioF(),
                comment.image.height() / comment.image.devicePixelRatioF(), comment.motion_speed)
            if comment.held:
                layer.pause_comment(comment.render_id, True, comment.x)
        host._set_quick_active()

    def schedule_quick_geometry(self) -> None:
        # QWidget move/resize events run before its native child windows settle.
        # Coalesce updates after that move, rather than submitting Quick geometry inside it.
        host = self.host
        if host._quick_layer is not None and host._quick_group is not None:
            point = host._quick_origin()
            host._quick_layer.begin_group_move(
                host._quick_group, point.x(), point.y(), host.width(), host.height())
            host._quick_geometry_timer.start(0)

    def sync_quick_geometry(self) -> None:
        host = self.host
        if host._quick_layer is None or host._quick_group is None:
            return
        point = host._quick_origin()
        host._quick_layer.set_group_geometry(
            host._quick_group, point.x(), point.y(), host.width(), host.height())

    def quick_origin(self):
        host = self.host
        parent = host._quick_layer.parent
        if host.window() is parent.window():
            return host.mapTo(parent, QPoint())
        return parent.mapFromGlobal(host.mapToGlobal(QPoint()))

    def set_quick_rounded(self, rounded: bool) -> None:
        host = self.host
        rounded = bool(rounded)
        if host._quick_rounded == rounded:
            return
        host._quick_rounded = rounded
        host._quick_mask_signature = None
        if host._quick_layer is not None and host._quick_group is not None:
            host._quick_layer.set_group_rounded(host._quick_group, rounded)

    def update_quick_mask(self, widgets) -> None:
        host = self.host
        if host._quick_layer is None or host._quick_group is None:
            return
        holes = QRegion()
        if self.windowed_occluders is not None:
            widgets = (*widgets, *self.windowed_occluders())
        for widget in widgets:
            if widget.isVisible():
                origin = host.mapFromGlobal(widget.mapToGlobal(QPoint()))
                region = widget.mask()
                if region.isEmpty():
                    region = QRegion(widget.rect())
                holes |= region.translated(origin).intersected(QRegion(host.rect()))
        sc = host.super_chat_overlay
        clips_window = getattr(host._quick_layer, 'clips_sc_window', None)
        if sc.isVisible() and not (sc.qt_composited and clips_window and clips_window(sc)):
            for rect in sc.card_rects():
                holes |= QRegion(rect.toAlignedRect()).intersected(
                    QRegion(host.rect()))
        video_mask = host._quick_video_mask if host._quick_requested else host.mask()
        if self.windowed_occluders is not None:
            # Keep the overlay off the desktop sampling band and out of child
            # window composition below the configured scrolling area.
            area = QRect(0, 0, host.width(), min(host.height(), host.lane_count() * host.lane_height()))
            video_mask = (video_mask if not video_mask.isEmpty() else QRegion(host.rect())) & QRegion(area)
        signature = (host.width(), host.height(), host.devicePixelRatioF(),
                     host._quick_rounded,
                     holes, video_mask)
        if signature == host._quick_mask_signature:
            return
        host._quick_mask_signature = signature

        scale = host.devicePixelRatioF()
        image = QImage(math.ceil(host.width() * scale), math.ceil(host.height() * scale),
                       QImage.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(scale)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        region = video_mask
        if region.isEmpty() and self.windowed_occluders is None:
            region = QRegion(host.rect())
        painter.setClipRegion(region.subtracted(holes))
        painter.fillRect(host.rect(), Qt.white)
        painter.end()
        host._quick_layer.set_group_mask(host._quick_group, image)

    def set_quick_active(self) -> None:
        host = self.host
        if host._quick_layer is not None and host._quick_group is not None:
            host._quick_layer.set_group_active(
                host._quick_group,
                bool(host.comments) and not host.paused and host.isVisible())
