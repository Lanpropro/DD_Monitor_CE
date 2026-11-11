"""轻量画面弹幕：有界轨道、匀速滚动，原生视频窗口上的鼠标穿透浮层。"""
import math
import os
import sys
# Python 3.12 on Windows uses a 15.625ms monotonic clock; QPC preserves sub-frame motion.
from time import perf_counter
from dataclasses import dataclass, field

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetrics, QImage, QPainter, QPen, QPixmap, QRegion
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from . import motion, theme
from .danmaku_content import content_runs
from .danmaku_raster import CommentRaster, CommentRasterJob
from .images import AvatarLoader
from .badge_surface import BadgeSurface
from .super_chat_avatar import SuperChatAvatar, paint_sc_avatar
from .super_chat_animation import SuperChatPresentation
from .super_chat_layout import paint_sc_background, sc_placement_rects, sc_message_document
from .super_chat_model import format_price, format_remaining, super_chat_palette, SC_USER_COLOR, SC_PRICE_COLOR, SC_CONTENT_COLOR, remaining_seconds, order_super_chats, SC_BODY_PADDING


from .video_super_chat import SuperChatOverlay, _paint_super_chat
from .video_danmaku_raster import VideoDanmakuRaster
from .video_danmaku_surface import VideoDanmakuSurface


class _TimerResolution:
    """Keep the Windows multimedia timer request paired with active scrolling."""

    def __init__(self):
        self._winmm = None

    def acquire(self):
        if self._winmm is None and sys.platform == "win32" and QApplication.platformName() == "windows":
            import ctypes
            winmm = ctypes.windll.winmm
            if winmm.timeBeginPeriod(1) == 0:
                self._winmm = winmm

    def release(self):
        if self._winmm is not None:
            self._winmm.timeEndPeriod(1)
            self._winmm = None


@dataclass
class _Comment:
    image: QPixmap
    x: float
    lane: int
    speed: float
    text: str
    color: QColor
    runs: list[tuple[str, str]]
    render_id: int = 0
    self_sent: bool = False
    message: str = ''
    held: bool = False
    event: dict = field(default_factory=dict)
    raster_key: tuple = ()
    rasters: dict = field(default_factory=dict)


class VideoDanmaku(QWidget):
    actionsRequested = Signal(object, QPoint)
    superChatDismissed = Signal(str)
    superChatSettingsChanged = Signal(dict)
    MAX_COMMENTS = 80
    GAP = 24
    COLOR_KEY = QColor(1, 2, 3)
    # Downsampling enables fractional-pixel filtering in Qt's raster painter;
    # same-resolution pixmaps snap to whole pixels even with SmoothPixmapTransform.
    TEXT_SAMPLE_SCALE = 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self.surface_control = VideoDanmakuSurface(self)
        self.raster_control = VideoDanmakuRaster(self)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_DontCreateNativeAncestors, True)
        self.enabled = False
        self.sc_independent = False
        self.sc_in_panel = False
        self.active = False
        self.native_video = True
        self.paused = False
        self.settings = {}
        self._comment_width = self.width()
        self.comments: list[_Comment] = []
        self._pending_comments = {}
        self._comment_resize_timer = QTimer(self)
        self._comment_resize_timer.setSingleShot(True)
        self._comment_resize_timer.timeout.connect(self._queue_comment_raster)
        self._comment_raster_job = None
        self.super_chats: list[dict] = []
        self.super_chat_overlay = SuperChatOverlay(parent)
        self.super_chat_overlay.bind(self)
        self.super_chat_overlay.dismissed.connect(self.superChatDismissed)
        self.super_chat_overlay.settingsChanged.connect(self.superChatSettingsChanged)
        self._images = {}
        self._emoticon_loaders = {}
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._tick)
        self._timer_resolution = _TimerResolution()
        self._quick_requested = (os.environ.get("DDM_QTQUICK_DANMAKU") == "1"
                                 and self._native_layered())
        self._quick_layer = None
        self._quick_group = None
        self._quick_rounded = True
        self._quick_mask_signature = None
        self._quick_video_mask = QRegion()
        self._quick_geometry_timer = QTimer(self)
        self._quick_geometry_timer.setSingleShot(True)
        self._quick_geometry_timer.timeout.connect(self._sync_quick_geometry)
        self.timer.destroyed.connect(self._timer_resolution.release)
        self._last_tick = 0.0
        self._hovered = None
        self._menu_open = False
        self.hide()

    def comment_at(self, point):
        mask = self._quick_video_mask if self._quick_requested else self.mask()
        if not self.rect().contains(point) or (not mask.isEmpty() and not mask.contains(point)):
            return None
        for comment in reversed(self.comments):
            scale = comment.image.devicePixelRatioF()
            rect = QRectF(comment.x, comment.lane * self.lane_height(),
                          comment.image.width() / scale, comment.image.height() / scale)
            if rect.contains(QPointF(point)):
                return comment
        return None

    def _set_hover(self, comment):
        if self._hovered is comment:
            return
        previous, self._hovered = self._hovered, comment
        if previous is not None:
            previous.held = False
            if self._quick_layer is not None:
                self._quick_layer.pause_comment(previous.render_id, False, previous.x)
        if comment is not None:
            comment.held = True
            if self._quick_layer is not None:
                self._quick_layer.pause_comment(comment.render_id, True, comment.x)
        self.update()

    def _poll_hover(self):
        if self._menu_open or QApplication.mouseButtons():
            return
        point = QCursor.pos()
        tile = self.parentWidget()
        active = self.window().isActiveWindow()
        if not active and self._native_layered():
            import ctypes
            user32 = ctypes.windll.user32
            user32.GetForegroundWindow.restype = ctypes.c_void_p
            user32.GetAncestor.argtypes = (ctypes.c_void_p, ctypes.c_uint)
            user32.GetAncestor.restype = ctypes.c_void_p
            active = user32.GetAncestor(user32.GetForegroundWindow(), 2) == int(self.window().winId())
        eligible = (self.isVisible() and not self.paused and active
                    and QApplication.activePopupWidget() is None
                    and QApplication.activeModalWidget() is None and not QApplication.mouseButtons())
        if eligible and tile is not None:
            for name in ('controls', 'stream_badge', 'title_badge', 'bottom'):
                widget = getattr(tile, name, None)
                if widget is not None and widget.isVisible() and widget.rect().contains(widget.mapFromGlobal(point)):
                    eligible = False
                    break
        self._set_hover(self.comment_at(self.mapFromGlobal(point)) if eligible else None)

    def open_actions_at(self, position):
        if not self.isVisible():
            return False
        comment = self.comment_at(self.mapFromGlobal(position))
        if comment is None:
            return False
        self._set_hover(comment)
        self.actionsRequested.emit(comment.event, position)
        return True

    def apply_settings(self, settings: dict) -> None:
        values = {key: settings.get(key) for key in (
            "danmaku_font", "video_danmaku_size", "video_danmaku_speed",
            "video_danmaku_opacity", "video_danmaku_area", "video_danmaku_scale",
            "video_danmaku_color_mode", "video_danmaku_color",
            "video_danmaku_outline_width", "super_chat_enabled", "super_chat_opacity",
            "super_chat_collapse_delay", "super_chat_scale", "super_chat_position")}
        values['super_chat_enabled'] = settings.get('super_chat_enabled', True)
        values['super_chat_opacity'] = settings.get('super_chat_opacity', 80)
        values['super_chat_collapse_delay'] = settings.get('super_chat_collapse_delay', 7)
        values['super_chat_scale'] = settings.get('super_chat_scale', 100)
        values['super_chat_scale_with_video'] = bool(settings.get('super_chat_scale_with_video', False))
        values['super_chat_scale_strength'] = settings.get('super_chat_scale_strength', 35)
        values['video_danmaku_scale_strength'] = settings.get('video_danmaku_scale_strength', 35)
        values['super_chat_scale_curve'] = settings.get('super_chat_scale_curve')
        values['video_danmaku_scale_curve'] = settings.get('video_danmaku_scale_curve')
        if values != self.settings:
            if self._quick_animated() and self.timer.isActive():
                self._tick()
            redraw = any(values.get(key) != self.settings.get(key)
                         for key in ("danmaku_font", "video_danmaku_size", "video_danmaku_scale", "video_danmaku_scale_strength", "video_danmaku_scale_curve",
                                     "video_danmaku_outline_width"))
            self.settings = values
            color_changed = False
            for comment in self.comments:
                color = self._comment_color(comment.event)
                color_changed |= color != comment.color
                comment.color = color
            for token, (text, color, runs, self_sent, event) in list(self._pending_comments.items()):
                current = self._comment_color(event)
                color_changed |= current != color
                self._pending_comments[token] = (text, current, runs, self_sent, event)
            if redraw:
                self._resize_comments()
            else:
                for comment in self.comments:
                    distance = self.width() + comment.image.width() / comment.image.devicePixelRatioF()
                    comment.speed = distance / 8 * int(values.get("video_danmaku_speed") or 100) / 100
                self._prune_lanes()
                if self._quick_layer is not None and self._quick_group is not None:
                    for comment in self.comments:
                        self._quick_layer.move(comment.render_id, comment.x,
                                               comment.lane * self.lane_height(), comment.speed)
                self.update()
            if color_changed:
                self._comment_resize_timer.start(0)
            if self.super_chats:
                self.super_chat_overlay.set_chats(
                    self.super_chats,
                    int(values.get("super_chat_opacity") or 80) / 100)
            if self.isVisible():
                self._apply_layered()

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)
        self._sync_visible()

    def set_native_video(self, native: bool) -> None:
        """Select the backing surface before the overlay is first shown."""
        was_quick = self._quick_requested
        self.native_video = bool(native)
        self._quick_requested = (os.environ.get("DDM_QTQUICK_DANMAKU") == "1"
                                 and self._native_layered())
        if was_quick and not self._quick_requested:
            self._stop_timer()
            if self._quick_layer is not None and self._quick_group is not None:
                self._quick_layer.remove_group(self._quick_group)
            self._quick_layer = self._quick_group = None
            self._quick_mask_signature = None
            super().setMask(self._quick_video_mask)
        self.setAttribute(Qt.WA_NoSystemBackground, self.native_video)

    def set_active(self, active: bool) -> None:
        self.active = bool(active)
        self._sync_visible()

    def set_paused(self, paused: bool) -> None:
        if self._quick_animated() and self.timer.isActive():
            self._tick()
        self.paused = bool(paused)
        if self.paused:
            self._set_hover(None)
        if not self.paused:
            self.super_chat_overlay.raise_()
        self._set_quick_active()
        if self.paused:
            self._stop_timer()
        elif self.comments and self.isVisible():
            self._start_timer()

    def sc_visible(self):
        return (self.active and not self.sc_in_panel and (self.enabled or self.sc_independent)
                and self.settings.get('super_chat_enabled', True))

    def set_sc_in_panel(self, in_panel):
        if self.sc_in_panel != in_panel:
            self.sc_in_panel = in_panel
            self._sync_visible()

    def set_sc_independent(self, independent):
        if self.sc_independent != independent:
            self.sc_independent = independent
            self._sync_visible()

    def _sync_visible(self) -> None:
        return self.surface_control.sync_visible()

    def font_pixels(self) -> int:
        size = int(self.settings.get("video_danmaku_size") or 28)
        if self.settings.get("video_danmaku_scale", True):
            from .viewport_scale import viewport_scale
            size = round(size * viewport_scale(self.height(), self.settings.get('video_danmaku_scale_strength', 35),
                                              self.settings.get('video_danmaku_scale_curve')))
        return max(10, min(144, size))

    def lane_height(self) -> int:
        return QFontMetrics(self._font()).height() + 8 + math.ceil(self.outline_width() * 2)

    def outline_width(self) -> float:
        width = max(0, min(6, int(self.settings.get("video_danmaku_outline_width") or 0)))
        if self.settings.get("video_danmaku_scale", True):
            width *= self.font_pixels() / int(self.settings.get("video_danmaku_size") or 28)
        return float(width)

    def _font(self) -> QFont:
        font = QFont(str(self.settings.get("danmaku_font") or theme.danmaku_font_family()))
        font.setPixelSize(self.font_pixels())
        font.setWeight(QFont.Medium)
        return font

    def lane_count(self) -> int:
        area = int(self.settings.get("video_danmaku_area") or 50)
        return max(0, int(self.height() * area / 100) // self.lane_height())

    def add_event(self, event: dict) -> bool:
        """Accept a comment for bounded background painting; admit it when ready."""
        kind = event.get("kind") or "danmaku"
        if kind == "super_chat":
            self.set_super_chats([*self.super_chats, event])
            return True
        if (not self.enabled or not self.active or self.paused or not self.isVisible()
                or kind != "danmaku"
                or len(self.comments) + len(self._pending_comments) >= self.MAX_COMMENTS):
            return False
        text = " ".join(str(event.get("text") or "").split())[:300]
        lanes = self.lane_count()
        if (not text and not event.get("emoticon")) or not lanes:
            return False
        self._tick()
        if sum(self._lane_available(lane, 0) for lane in range(lanes)) <= len(self._pending_comments):
            return False
        color = self._comment_color(event)
        runs = content_runs(dict(event, text=text))
        self_sent = bool(event.get("self_sent"))
        self._pending_comments[object()] = (text, color, runs, self_sent, dict(event))
        self._comment_resize_timer.start(0)
        for _, url in runs:
            if url:
                self._ensure_emoticon(url)
        return True

    def _comment_color(self, event):
        value = (self.settings.get('video_danmaku_color')
                 if self.settings.get('video_danmaku_color_mode') == 'custom'
                 else event.get('color'))
        color = QColor(str(value or '#ffffff'))
        return color if color.isValid() else QColor('#ffffff')

    def _admit_comment(self, image, key, text, color, runs, self_sent, event):
        image = QPixmap.fromImage(image)
        width = image.width() / image.devicePixelRatioF()
        speed = (self.width() + width) / 8 * int(
            self.settings.get("video_danmaku_speed") or 100) / 100
        lane = next((lane for lane in range(self.lane_count())
                     if self._lane_available(lane, speed)), None)
        if lane is None:
            return False  # 满轨道时丢弃，不积压过时的弹幕。
        if self._quick_requested and self._quick_layer is None:
            tile = self.parentWidget()
            wall = tile.parentWidget() if tile is not None else None
            ensure_layer = getattr(wall, "ensure_quick_danmaku_layer", None)
            if ensure_layer is not None:
                self.attach_quick_layer(ensure_layer())
        comment = _Comment(image, float(self.width()), lane, speed, text, color, runs,
                           self_sent=self_sent, message=str(event.get('text') or ''), event=dict(event))
        comment.raster_key = key
        comment.rasters[comment.raster_key] = image.toImage()
        if self._quick_layer is not None and self._quick_group is not None:
            comment.render_id = self._quick_layer.add(
                self._quick_group, image.toImage(), comment.x,
                lane * self.lane_height(), width,
                image.height() / image.devicePixelRatioF(), speed)
        self.comments.append(comment)
        if self._quick_layer is not None and self._quick_group is not None:
            if not self.isVisible():
                self._quick_layer.set_group_visible(self._quick_group, False)
            if self.paused or not self.isVisible():
                self._set_quick_active()
        if not self.paused and self.isVisible():
            self._start_timer()
        return True

    def set_super_chats(self, events: list[dict]) -> None:
        chats = []
        seen = set()
        for event in events:
            if (event.get("kind") or "") != "super_chat":
                continue
            chat_id = str(event.get("super_chat_id") or event.get("id") or "")
            if chat_id and chat_id in seen:
                continue
            if chat_id:
                seen.add(chat_id)
            chats.append(dict(event))
        self.super_chats = chats
        self.super_chat_overlay.set_chats(
            chats, int(self.settings.get("super_chat_opacity") or 80) / 100)
        if chats:
            self.super_chat_overlay.sync(self)
            parent = self.parentWidget()
            raise_overlays = getattr(parent, "raise_overlays", None)
            if raise_overlays is not None:
                raise_overlays()
        elif self._quick_layer is not None and self._quick_group is not None:
            tile = self.parentWidget()
            refresh_mask = getattr(tile, "_update_quick_danmaku_mask", None)
            if refresh_mask is not None:
                refresh_mask()
        self.update()

    def filter_events(self, allowed):
        kept = []
        for comment in self.comments:
            if allowed(comment.event):
                kept.append(comment)
            else:
                if self._hovered is comment:
                    self._set_hover(None)
                if self._quick_layer is not None and self._quick_group is not None:
                    self._quick_layer.remove(comment.render_id)
        self.comments = kept
        self._pending_comments = {key: value for key, value in self._pending_comments.items() if allowed(value[-1])}
        self._set_quick_active()
        self.update()

    def clear_comments(self) -> None:
        self._comment_resize_timer.stop()
        self._stop_timer()
        self.comments.clear()
        self._pending_comments.clear()
        self.super_chat_overlay.hide()
        if self._quick_layer is not None and self._quick_group is not None:
            self._quick_layer.clear_group(self._quick_group)
        self._last_tick = 0.0
        if self.isVisible():
            self.repaint()
        else:
            self.update()

    def _ensure_emoticon(self, url: str) -> None:
        return self.raster_control.ensure_emoticon(url)

    def _on_emoticon_loaded(self, url: str, pixmap) -> None:
        return self.raster_control.on_emoticon_loaded(url, pixmap)

    def _comment_renderer(self):
        return self.raster_control.comment_renderer()

    def _render_content(self, text, color, runs, self_sent=False) -> QPixmap:
        return self.raster_control.render_content(text, color, runs, self_sent)

    def _render_text(self, text, color, self_sent=False) -> QPixmap:
        return self.raster_control.render_text(text, color, self_sent)

    def _queue_comment_raster(self):
        return self.raster_control.queue_comment_raster()

    def _finish_comment_raster(self, images):
        return self.raster_control.finish_comment_raster(images)

    def _apply_comment_rasters(self, images):
        return self.raster_control.apply_comment_rasters(images)

    def _resize_comments(self, *, redraw=True) -> None:
        return self.raster_control.resize_comments(redraw=redraw)

    def _prune_lanes(self) -> None:
        comments, self.comments = self.comments, []
        for comment in comments:
            if (comment.lane < self.lane_count() and
                    self._lane_available(comment.lane, comment.speed, comment.x)):
                self.comments.append(comment)
            elif self._quick_layer is not None and self._quick_group is not None:
                self._quick_layer.remove(comment.render_id)

    def _lane_available(self, lane: int, speed: float, x: float | None = None) -> bool:
        for comment in self.comments:
            if comment.lane != lane:
                continue
            right = comment.x + comment.image.width() / comment.image.devicePixelRatioF()
            gap = (self.width() if x is None else x) - right
            if gap < self.GAP:
                return False
            # 后发的长弹幕更快；必须在前一条离开画面之前追不上它。
            if speed > comment.speed and (gap - self.GAP) / (speed - comment.speed) < right / comment.speed:
                return False
        return True

    def _start_timer(self) -> None:
        if not self.timer.isActive():
            screen = self.screen()
            rate = max(60, screen.refreshRate() if screen else 60)
            self.timer.setInterval(50 if self._quick_animated() else
                                   max(4, min(16, round(1000 / rate))))
            self._last_tick = perf_counter()
            if not self._quick_animated():
                self._timer_resolution.acquire()
            self.timer.start()

    def _quick_animated(self) -> bool:
        return self._quick_layer is not None and self._quick_layer.render_thread_animation

    def _stop_timer(self) -> None:
        self.timer.stop()
        self._timer_resolution.release()

    def _tick(self) -> None:
        # Include rows whose last comment expires so their old pixels are erased.
        height = self.lane_height() if self.comments else 0
        bottom = max((comment.lane * height + math.ceil(comment.image.height() /
                       comment.image.devicePixelRatioF()) for comment in self.comments), default=0)
        now = perf_counter()
        elapsed = now - self._last_tick if self._last_tick else 0.0
        self._last_tick = now
        for comment in self.comments:
            if not comment.held:
                comment.x -= elapsed * comment.speed
            if (self._quick_layer is not None and self._quick_group is not None
                    and not self._quick_animated()):
                self._quick_layer.move(comment.render_id, comment.x,
                                       comment.lane * height)
        active = []
        for comment in self.comments:
            if comment.x + comment.image.width() / comment.image.devicePixelRatioF() > 0:
                active.append(comment)
            elif self._quick_layer is not None and self._quick_group is not None:
                self._quick_layer.remove(comment.render_id)
        self.comments = active
        self._poll_hover()
        self._set_quick_active()
        if bottom and self._quick_layer is None:
            self.update(QRect(0, 0, self.width(), min(self.height(), bottom)))
        if not self.comments:
            self._stop_timer()

    def clear(self) -> None:
        self._set_hover(None)
        self._stop_timer()
        self.comments.clear()
        self._pending_comments.clear()
        self.super_chats.clear()
        self.super_chat_overlay.set_chats([], 0)
        if self._quick_layer is not None and self._quick_group is not None:
            self._quick_layer.clear_group(self._quick_group)
        self._last_tick = 0.0
        if self.isVisible():
            self.repaint()
        else:
            self.update()

    def paintEvent(self, event) -> None:
        if self._quick_requested:
            return  # The shared Quick window is the only canvas in this mode.
        painter = QPainter(self)
        if self._native_layered():
            painter.fillRect(event.rect(), self.COLOR_KEY)
        else:
            painter.setOpacity(int(self.settings.get("video_danmaku_opacity") or 80) / 100)
        if self._quick_layer is not None and self._quick_group is not None:
            return
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        height = self.lane_height()
        # Sample at paint time as queued QWidget updates may follow the timer.
        elapsed = max(0, perf_counter() - self._last_tick) if self.timer.isActive() and not self.paused else 0
        for comment in self.comments:
            y = comment.lane * height
            if y < event.rect().bottom() + 1 and y + height > event.rect().top():
                painter.drawPixmap(QPointF(comment.x - (0 if comment.held else elapsed * comment.speed), y), comment.image)

    _paint_super_chat = staticmethod(_paint_super_chat)

    def _native_layered(self) -> bool:
        return self.surface_control.native_layered()

    def _apply_layered(self) -> None:
        return self.surface_control.apply_layered()

    def setMask(self, region) -> None:
        if self._quick_requested:
            self._quick_video_mask = QRegion(region)
            self._suppress_quick_raster_surface()
        else:
            super().setMask(region)

    def clearMask(self) -> None:
        if self._quick_requested:
            self._quick_video_mask = QRegion()
            self._suppress_quick_raster_surface()
        else:
            super().clearMask()

    def _suppress_quick_raster_surface(self) -> None:
        # Qt and Windows must both know this controller has no visible canvas.
        # An empty QWidget mask means unrestricted, so clip to an off-widget pixel.
        super().setMask(QRegion(-1, -1, 1, 1))

    def attach_quick_layer(self, layer) -> None:
        return self.surface_control.attach_quick_layer(layer)

    def schedule_quick_geometry(self) -> None:
        # QWidget move/resize events run before its native child windows settle.
        # Coalesce updates after that move, rather than submitting Quick geometry inside it.
        return self.surface_control.schedule_quick_geometry()

    def _sync_quick_geometry(self) -> None:
        return self.surface_control.sync_quick_geometry()

    def _quick_origin(self):
        return self.surface_control.quick_origin()

    def set_quick_rounded(self, rounded: bool) -> None:
        return self.surface_control.set_quick_rounded(rounded)

    def update_quick_mask(self, widgets) -> None:
        return self.surface_control.update_quick_mask(widgets)

    def _set_quick_active(self) -> None:
        return self.surface_control.set_quick_active()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.super_chat_overlay._refresh()
        if self.super_chat_overlay.isVisible():
            self.super_chat_overlay.raise_()
        if self._native_layered():
            self.setAttribute(Qt.WA_OpaquePaintEvent, not self._quick_requested)
            self.setAttribute(Qt.WA_NativeWindow, True)
            self._apply_layered()
            self._sync_quick_geometry()
            if self._quick_layer is not None and self._quick_group is not None:
                self._quick_layer.set_group_visible(self._quick_group, True)
            self._set_quick_active()
        if self.comments and not self.paused:
            self._last_tick = perf_counter()
            self._tick()
            self._start_timer()
        self.raise_()

    def hideEvent(self, event) -> None:
        # 布局/全屏可能短暂隐藏浮层；仅停止绘制，显式关弹幕或换台才清空。
        self._set_hover(None)
        if self._quick_animated() and self.timer.isActive():
            self._tick()
        self._stop_timer()
        if self._quick_layer is not None and self._quick_group is not None:
            self._quick_layer.set_group_visible(self._quick_group, False)
        if self.sc_independent:
            self.super_chat_overlay._refresh()
        else:
            self.super_chat_overlay.hide()
        self._set_quick_active()
        super().hideEvent(event)

    def resizeEvent(self, event) -> None:
        # Fullscreen changes several geometries in one turn. Rasterize glyphs
        # once at the final size, outside synchronous native window resizing.
        self._resize_comments(redraw=False)
        self._comment_resize_timer.start(0)
        self.super_chat_overlay.sync(self)
        self.schedule_quick_geometry()
        super().resizeEvent(event)

    def moveEvent(self, event) -> None:
        self.super_chat_overlay.sync(self)
        self.schedule_quick_geometry()
        super().moveEvent(event)
