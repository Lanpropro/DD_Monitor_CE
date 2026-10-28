"""轻量画面弹幕：有界轨道、匀速滚动，原生视频窗口上的鼠标穿透浮层。"""
import math
import os
import sys
# Python 3.12 on Windows uses a 15.625ms monotonic clock; QPC preserves sub-frame motion.
from time import perf_counter
from dataclasses import dataclass

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter, QPainterPath, QPen, QPixmap, QRegion, QTextCharFormat, QTextCursor, QTextDocument
from PySide6.QtWidgets import QApplication, QWidget

from . import theme
from .danmaku_content import content_runs, content_html
from .images import AvatarLoader
from .super_chat import (format_price, format_remaining, readable_text_color,
                         remaining_seconds)


class SuperChatOverlay(QWidget):
    """Fixed Super Chat cards kept above the optional Qt Quick danmaku layer."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SuperChatOverlay")
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.chats: list[dict] = []
        self.opacity = 0.8
        self._video_danmaku: VideoDanmaku | None = None
        self.hide()

    def bind(self, owner: "VideoDanmaku") -> None:
        self._video_danmaku = owner
        self.setParent(owner.parentWidget())
        self.setGeometry(owner.geometry())
        self.setMask(owner.mask())

    def sync(self, owner: "VideoDanmaku") -> None:
        if self._video_danmaku is owner:
            # bind() 可能发生在 owner 最终摆位之前；resize 不再重复同步，这里必须
            # 使用与视频一致的父级坐标，而不是 owner.geometry() 的旧尺寸。
            self.setGeometry(owner.x(), owner.y(), owner.width(), owner.height())
            self.setMask(owner.mask())
        self.raise_()

    def set_chats(self, chats: list[dict], opacity: float) -> None:
        self.chats = [dict(chat) for chat in chats]
        self.opacity = max(0.0, min(1.0, float(opacity)))
        self.setVisible(bool(self.chats) and self._video_danmaku is not None
                         and self._video_danmaku.enabled
                         and self._video_danmaku.active)
        self._refresh_quick_mask()
        if self.isVisible():
            self.sync(self._video_danmaku)
        self.update()

    def card_rects(self) -> list[QRectF]:
        if not self.chats:
            return []
        scale = max(0.65, min(1.25, self.height() / 720))
        margin = round(12 * scale)
        available_width = max(1, self.width() - margin * 2)
        available_height = max(1, self.height() - margin * 2
                               - (44 if self.height() >= 320 else 0))
        count = 1 if self.height() < 320 else 2 if self.height() < 560 else 3
        count = min(count, max(1, available_height // max(1, round(82 * scale))))
        gap = round(7 * scale)
        card_height = min(round(82 * scale),
                          max(1, (available_height - gap * (count - 1)) // count))
        width = min(max(168, round(self.width() * 0.30)), available_width, 340)
        right = margin + available_width
        top = margin + (44 if self.height() >= 320 else 0)
        return [QRectF(right - width, top + index * (card_height + gap),
                       width, card_height)
                for index in range(min(count, len(self.chats)))]

    def _refresh_quick_mask(self) -> None:
        owner = self._video_danmaku
        tile = owner.parentWidget() if owner is not None else None
        refresh = getattr(tile, "_update_quick_danmaku_mask", None)
        if refresh is not None:
            refresh()

    def paintEvent(self, event) -> None:
        if not self.chats:
            return
        owner = self._video_danmaku
        scale = max(0.65, min(1.25, self.height() / 720))
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setOpacity(self.opacity)
        for chat, rect in zip(self.chats, self.card_rects()):
            if owner is not None:
                owner._paint_super_chat(painter, rect, chat, scale)
            else:
                VideoDanmaku._paint_super_chat(
                    painter, rect, chat, scale)
        painter.end()


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


class VideoDanmaku(QWidget):
    MAX_COMMENTS = 80
    GAP = 24
    COLOR_KEY = QColor(1, 2, 3)
    # Downsampling enables fractional-pixel filtering in Qt's raster painter;
    # same-resolution pixmaps snap to whole pixels even with SmoothPixmapTransform.
    TEXT_SAMPLE_SCALE = 2

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_DontCreateNativeAncestors, True)
        self.enabled = False
        self.active = False
        self.native_video = True
        self.paused = False
        self.settings = {}
        self._comment_width = self.width()
        self.comments: list[_Comment] = []
        self.super_chats: list[dict] = []
        self.super_chat_overlay = SuperChatOverlay(parent)
        self.super_chat_overlay.bind(self)
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
        self.hide()

    def apply_settings(self, settings: dict) -> None:
        values = {key: settings.get(key) for key in (
            "danmaku_font", "video_danmaku_size", "video_danmaku_speed",
            "video_danmaku_opacity", "video_danmaku_area", "video_danmaku_scale",
            "video_danmaku_outline_width")}
        if values != self.settings:
            if self._quick_animated() and self.timer.isActive():
                self._tick()
            redraw = any(values.get(key) != self.settings.get(key)
                         for key in ("danmaku_font", "video_danmaku_size", "video_danmaku_scale",
                                     "video_danmaku_outline_width"))
            self.settings = values
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
            if self.super_chats:
                self.super_chat_overlay.set_chats(
                    self.super_chats,
                    int(values.get("video_danmaku_opacity") or 80) / 100)
            if self.isVisible():
                self._apply_layered()

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)
        self._sync_visible()

    def set_native_video(self, native: bool) -> None:
        """Select the backing surface before the overlay is first shown."""
        self.native_video = bool(native)
        self.setAttribute(Qt.WA_NoSystemBackground, self.native_video)

    def set_active(self, active: bool) -> None:
        self.active = bool(active)
        self._sync_visible()

    def set_paused(self, paused: bool) -> None:
        if self._quick_animated() and self.timer.isActive():
            self._tick()
        self.paused = bool(paused)
        if not self.paused:
            self.super_chat_overlay.raise_()
        self._set_quick_active()
        if self.paused:
            self._stop_timer()
        elif self.comments and self.isVisible():
            self._start_timer()

    def _sync_visible(self) -> None:
        visible = self.enabled and self.active
        self.super_chat_overlay.setVisible(visible and bool(self.super_chats))
        if not visible:
            # Erase the native backing while still visible. Hiding first leaves
            # its last rendered comments cached until the next asynchronous paint.
            self._stop_timer()
            self.comments.clear()
            if self._quick_layer is not None and self._quick_group is not None:
                self._quick_layer.clear_group(self._quick_group)
            self._last_tick = 0.0
            if self.isVisible():
                self.repaint()
            else:
                self.update()
        self.setVisible(visible)
        if visible and self.comments and not self.paused:
            self._start_timer()

    def font_pixels(self) -> int:
        size = int(self.settings.get("video_danmaku_size") or 28)
        if self.settings.get("video_danmaku_scale", True):
            size = round(size * self.height() / 720)
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
        kind = event.get("kind") or "danmaku"
        if kind == "super_chat":
            self.set_super_chats([*self.super_chats, event])
            return True
        if (not self.enabled or not self.active or self.paused or not self.isVisible()
                or kind != "danmaku"
                or len(self.comments) >= self.MAX_COMMENTS):
            return False
        text = " ".join(str(event.get("text") or "").split())[:300]
        lanes = self.lane_count()
        if (not text and not event.get("emoticon")) or not lanes:
            return False
        self._tick()
        if not any(self._lane_available(lane, 0) for lane in range(lanes)):
            return False
        color = QColor(str(event.get("color") or "#ffffff"))
        if not color.isValid():
            color = QColor("#ffffff")
        runs = content_runs(dict(event, text=text))
        self_sent = bool(event.get("self_sent"))
        image = self._render_content(text, color, runs, self_sent)
        width = image.width() / image.devicePixelRatioF()
        speed = (self.width() + width) / 8 * int(
            self.settings.get("video_danmaku_speed") or 100) / 100
        lane = next((lane for lane in range(lanes)
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
                           self_sent=self_sent)
        if self._quick_layer is not None and self._quick_group is not None:
            comment.render_id = self._quick_layer.add(
                self._quick_group, image.toImage(), comment.x,
                lane * self.lane_height(), width,
                image.height() / image.devicePixelRatioF(), speed)
        self.comments.append(comment)
        for _, url in runs:
            if url:
                self._ensure_emoticon(url)
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
            chats, int(self.settings.get("video_danmaku_opacity") or 80) / 100)
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

    def clear_comments(self) -> None:
        self._stop_timer()
        self.comments.clear()
        self.super_chat_overlay.hide()
        if self._quick_layer is not None and self._quick_group is not None:
            self._quick_layer.clear_group(self._quick_group)
        self._last_tick = 0.0
        if self.isVisible():
            self.repaint()
        else:
            self.update()

    def _ensure_emoticon(self, url: str) -> None:
        if url in self._images or url in self._emoticon_loaders or len(self._emoticon_loaders) >= 16:
            return
        # The app owns downloads so removing a tile cannot destroy a running thread.
        app = QApplication.instance()
        loader = AvatarLoader({url: url}, app, subdir="emoticons")
        self._emoticon_loaders[url] = loader
        loader.loaded.connect(self._on_emoticon_loaded)
        loader.finished.connect(lambda: self._emoticon_loaders.pop(url, None))
        loader.finished.connect(loader.deleteLater)
        app.aboutToQuit.connect(loader.wait)
        loader.start()

    def _on_emoticon_loaded(self, url: str, pixmap) -> None:
        if pixmap.isNull():
            return
        if len(self._images) >= 128 and url not in self._images:
            self._images.pop(next(iter(self._images)))
        self._images[url] = pixmap.toImage()
        if any(url == image_url for comment in self.comments for _, image_url in comment.runs):
            self._resize_comments()

    def _render_content(self, text, color, runs, self_sent=False) -> QPixmap:
        if not any(url in self._images for _, url in runs if url):
            return self._render_text(text, color, self_sent)
        outline = self.outline_width()
        pad = (9 if self_sent else 4) + math.ceil(outline)
        document = QTextDocument()
        document.setDefaultFont(self._font())
        document.setDocumentMargin(0)
        for _, url in runs:
            if url in self._images:
                document.addResource(QTextDocument.ImageResource, QUrl(url), self._images[url])
        body = content_html(runs, self._images, QFontMetrics(self._font()).height())
        document.setHtml(f'<span style="color:{color.name()}">{body}</span>')
        if outline:
            style = QTextCharFormat()
            style.setTextOutline(QPen(Qt.black, outline * 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            cursor = QTextCursor(document)
            cursor.select(QTextCursor.Document)
            cursor.mergeCharFormat(style)
            transparent = QImage(1, 1, QImage.Format_ARGB32_Premultiplied)
            transparent.fill(Qt.transparent)
            for _, url in runs:
                if url in self._images:
                    document.addResource(QTextDocument.ImageResource, QUrl(url), transparent)
        document.adjustSize()
        document.setTextWidth(-1)  # A rolling comment stays on one line.
        scale = self.devicePixelRatioF() * self.TEXT_SAMPLE_SCALE
        width = min(document.idealWidth(), max(128, self.width() * 2)) + pad * 2
        image = QPixmap(math.ceil(width * scale), math.ceil((document.size().height() + pad * 2) * scale))
        image.setDevicePixelRatio(scale)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        painter.save()
        painter.translate(pad, pad)
        document.drawContents(painter)
        if outline:
            # Qt's text-outline pass covers thin glyph interiors; paint the
            # original colored text over it. Images are drawn only in this pass
            # so translucent emotes retain their original alpha.
            style.setTextOutline(QPen(Qt.NoPen))
            cursor.select(QTextCursor.Document)
            cursor.mergeCharFormat(style)
            for _, url in runs:
                if url in self._images:
                    document.addResource(QTextDocument.ImageResource, QUrl(url), self._images[url])
            document.drawContents(painter)
        painter.restore()
        if self_sent:
            self._draw_self_sent_box(painter, image)
        painter.end()
        return image

    @staticmethod
    def _draw_self_sent_box(painter, image):
        scale = image.devicePixelRatioF()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor(255, 255, 255, 225), 1.6))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(QRectF(1.6, 1.6, image.width() / scale - 3.2,
                                     image.height() / scale - 3.2), 6, 6)

    def _render_text(self, text: str, color: QColor, self_sent=False) -> QPixmap:
        font = self._font()
        metrics = QFontMetrics(font)
        text = metrics.elidedText(text, Qt.ElideRight, max(128, self.width() * 2))
        path = QPainterPath()
        path.addText(0, 0, font, text)
        bounds = path.boundingRect()
        left = min(0, bounds.left())
        top = min(-metrics.ascent(), bounds.top())
        outline = self.outline_width()
        pad = (9 if self_sent else 4) + math.ceil(outline)
        width = max(metrics.horizontalAdvance(text), bounds.right()) - left + pad * 2
        height = max(metrics.descent(), bounds.bottom()) - top + pad * 2
        # 字形四周留出边距，避免默认字体的下沿、英文下伸部被裁切。
        scale = self.devicePixelRatioF() * self.TEXT_SAMPLE_SCALE
        image = QPixmap(math.ceil(width * scale), math.ceil(height * scale))
        image.setDevicePixelRatio(scale)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)
        if outline:
            painter.save()
            painter.translate(pad - left, pad - top)
            painter.strokePath(path, QPen(Qt.black, outline * 2, Qt.SolidLine,
                                         Qt.RoundCap, Qt.RoundJoin))
            painter.restore()
        # drawText keeps Qt's font fallback and colour Unicode emoji glyphs.
        painter.setPen(color)
        painter.setFont(font)
        painter.drawText(QPointF(pad - left, pad - top), text)
        if self_sent:
            self._draw_self_sent_box(painter, image)
        painter.end()
        return image

    def _resize_comments(self) -> None:
        if self._quick_animated() and self.timer.isActive():
            self._tick()
        for comment in self.comments:
            old_distance = self._comment_width + comment.image.width() / comment.image.devicePixelRatioF()
            progress = (self._comment_width - comment.x) / max(1, old_distance)
            comment.image = self._render_content(comment.text, comment.color, comment.runs,
                                                 comment.self_sent)
            distance = self.width() + comment.image.width() / comment.image.devicePixelRatioF()
            comment.x = self.width() - progress * distance
            comment.speed = distance / 8 * int(self.settings.get("video_danmaku_speed") or 100) / 100
        self._comment_width = self.width()
        self._prune_lanes()
        if self._quick_layer is not None and self._quick_group is not None:
            for comment in self.comments:
                self._quick_layer.update(
                    comment.render_id, comment.image.toImage(), comment.x,
                    comment.lane * self.lane_height(),
                    comment.image.width() / comment.image.devicePixelRatioF(),
                    comment.image.height() / comment.image.devicePixelRatioF(), comment.speed)
        else:
            self.update()

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
        self._set_quick_active()
        if bottom and self._quick_layer is None:
            self.update(QRect(0, 0, self.width(), min(self.height(), bottom)))
        if not self.comments:
            self._stop_timer()

    def clear(self) -> None:
        self._stop_timer()
        self.comments.clear()
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
                painter.drawPixmap(QPointF(comment.x - elapsed * comment.speed, y), comment.image)

    @staticmethod
    def _paint_super_chat(painter, rect, chat: dict, scale: float,
                          paint_opacity: float | None = None) -> None:
        background = QColor(str(chat.get("background_color") or "#f59e0b"))
        accent = QColor(str(chat.get("background_price_color") or "#b45309"))
        if not background.isValid():
            background = QColor("#f59e0b")
        if not accent.isValid():
            accent = QColor("#b45309")
        painter.save()
        if paint_opacity is not None:
            painter.setOpacity(paint_opacity)
        painter.setPen(Qt.NoPen)
        painter.setBrush(background)
        painter.drawRoundedRect(rect, 7 * scale, 7 * scale)
        painter.setBrush(accent)
        painter.drawRoundedRect(
            QRectF(rect.left(), rect.top(), 4 * scale, rect.height()),
            2 * scale, 2 * scale)
        text = readable_text_color(background)
        left = rect.left() + 11 * scale
        top = rect.top() + 6 * scale
        font = QFont(theme.FONT_DEFAULT)
        font.setPixelSize(max(10, round(13 * scale)))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QPen(text))
        painter.drawText(
            QRectF(left, top, rect.width() * 0.56, 18 * scale),
            int(Qt.AlignLeft | Qt.AlignVCenter),
            QFontMetrics(font).elidedText(
                str(chat.get("uname") or "匿名用户"), Qt.ElideRight,
                max(40, round(rect.width() * 0.56))))
        painter.drawText(
            QRectF(rect.right() - 88 * scale, top, 76 * scale, 18 * scale),
            int(Qt.AlignRight | Qt.AlignVCenter), format_price(chat.get("price")))
        small = QFont(theme.FONT_DEFAULT)
        small.setPixelSize(max(9, round(11 * scale)))
        painter.setFont(small)
        painter.drawText(
            QRectF(left, top + 17 * scale, rect.width() - 22 * scale, 16 * scale),
            int(Qt.AlignLeft | Qt.AlignVCenter),
            "剩 " + format_remaining(remaining_seconds(chat.get("end_time"))))
        body = QFont(theme.FONT_DEFAULT)
        body.setPixelSize(max(10, round(12 * scale)))
        painter.setFont(body)
        value = str(chat.get("message") or chat.get("text") or "")
        metrics = QFontMetrics(body)
        lines = []
        available = max(40, round(rect.width() - 22 * scale))
        for _ in range(2):
            line = metrics.elidedText(value, Qt.ElideRight, available)
            if not line:
                break
            lines.append(line)
            if line == value:
                break
            value = value[len(line):].lstrip()
        painter.drawText(
            QRectF(left, top + 34 * scale, available, rect.height() - 40 * scale),
            int(Qt.AlignLeft | Qt.AlignTop), "\n".join(lines))
        painter.restore()

    def _native_layered(self) -> bool:
        return (self.native_video and sys.platform == "win32"
                and QApplication.platformName() == "windows")

    def _apply_layered(self) -> None:
        if not self._native_layered():
            return
        if self._quick_requested:
            self._suppress_quick_raster_surface()
            if self._quick_layer is not None and self._quick_group is not None:
                self._quick_layer.set_group_opacity(
                    self._quick_group, int(self.settings.get("video_danmaku_opacity") or 80))
            return
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
        user32.SetLayeredWindowAttributes.argtypes = [
            wintypes.HWND, wintypes.DWORD, wintypes.BYTE, wintypes.DWORD]
        hwnd = int(self.winId())
        style = user32.GetWindowLongW(hwnd, -20)
        user32.SetWindowLongW(hwnd, -20, style | 0x00080000 | 0x00000020)
        key = self.COLOR_KEY.red() | self.COLOR_KEY.green() << 8 | self.COLOR_KEY.blue() << 16
        alpha = round(int(self.settings.get("video_danmaku_opacity") or 80) * 255 / 100)
        user32.SetLayeredWindowAttributes(hwnd, key, alpha, 0x00000001 | 0x00000002)

    def setMask(self, region) -> None:
        if hasattr(self, "super_chat_overlay"):
            self.super_chat_overlay.setMask(region)
        if self._quick_requested:
            self._quick_video_mask = QRegion(region)
            self._suppress_quick_raster_surface()
        else:
            super().setMask(region)

    def clearMask(self) -> None:
        if hasattr(self, "super_chat_overlay"):
            self.super_chat_overlay.clearMask()
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
        if not self._quick_requested or layer is None:
            return
        if self._quick_layer is layer and self._quick_group is not None:
            self._sync_quick_geometry()
            return
        if self._quick_layer is not None and self._quick_group is not None:
            self._quick_layer.remove_group(self._quick_group)
        self._quick_layer = layer
        tile = self.parentWidget()
        self._quick_rounded = not bool(tile.property("fullscreen"))
        self._quick_group = layer.create_group(
            0, 0, self.width(), self.height(),
            int(self.settings.get("video_danmaku_opacity") or 80),
            rounded=self._quick_rounded)
        self._sync_quick_geometry()
        for comment in self.comments:
            comment.render_id = layer.add(
                self._quick_group, comment.image.toImage(), comment.x,
                comment.lane * self.lane_height(),
                comment.image.width() / comment.image.devicePixelRatioF(),
                comment.image.height() / comment.image.devicePixelRatioF(), comment.speed)
        self._set_quick_active()

    def schedule_quick_geometry(self) -> None:
        # QWidget move/resize events run before its native child windows settle.
        # Coalesce updates after that move, rather than submitting Quick geometry inside it.
        if self._quick_layer is not None and self._quick_group is not None:
            point = self.mapTo(self._quick_layer.parent, QPoint())
            self._quick_layer.begin_group_move(
                self._quick_group, point.x(), point.y(), self.width(), self.height())
            self._quick_geometry_timer.start(0)

    def _sync_quick_geometry(self) -> None:
        if self._quick_layer is None or self._quick_group is None:
            return
        point = self.mapTo(self._quick_layer.parent, QPoint())
        self._quick_layer.set_group_geometry(
            self._quick_group, point.x(), point.y(), self.width(), self.height())

    def set_quick_rounded(self, rounded: bool) -> None:
        rounded = bool(rounded)
        if self._quick_rounded == rounded:
            return
        self._quick_rounded = rounded
        self._quick_mask_signature = None
        if self._quick_layer is not None and self._quick_group is not None:
            self._quick_layer.set_group_rounded(self._quick_group, rounded)

    def update_quick_mask(self, widgets) -> None:
        if self._quick_layer is None or self._quick_group is None:
            return
        holes = QRegion()
        for widget in widgets:
            if widget.isVisible():
                origin = widget.pos() - self.pos()
                region = widget.mask()
                if region.isEmpty():
                    region = QRegion(widget.rect())
                holes |= region.translated(origin).intersected(QRegion(self.rect()))
        if self.super_chat_overlay.isVisible():
            for rect in self.super_chat_overlay.card_rects():
                holes |= QRegion(rect.toAlignedRect()).intersected(
                    QRegion(self.rect()))
        video_mask = self._quick_video_mask if self._quick_requested else self.mask()
        signature = (self.width(), self.height(), self.devicePixelRatioF(),
                     self._quick_rounded,
                     holes, video_mask)
        if signature == self._quick_mask_signature:
            return
        self._quick_mask_signature = signature

        scale = self.devicePixelRatioF()
        image = QImage(math.ceil(self.width() * scale), math.ceil(self.height() * scale),
                       QImage.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(scale)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        region = video_mask
        if region.isEmpty():
            region = QRegion(self.rect())
        painter.setClipRegion(region.subtracted(holes))
        painter.fillRect(self.rect(), Qt.white)
        painter.end()
        self._quick_layer.set_group_mask(self._quick_group, image)

    def _set_quick_active(self) -> None:
        if self._quick_layer is not None and self._quick_group is not None:
            self._quick_layer.set_group_active(
                self._quick_group,
                bool(self.comments) and not self.paused and self.isVisible())

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.super_chat_overlay.sync(self)
        if self.enabled and self.active and self.super_chats:
            self.super_chat_overlay.show()
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
        if self._quick_animated() and self.timer.isActive():
            self._tick()
        self._stop_timer()
        if self._quick_layer is not None and self._quick_group is not None:
            self._quick_layer.set_group_visible(self._quick_group, False)
        self.super_chat_overlay.hide()
        self._set_quick_active()
        super().hideEvent(event)

    def resizeEvent(self, event) -> None:
        self._resize_comments()
        self.super_chat_overlay.sync(self)
        self.schedule_quick_geometry()
        super().resizeEvent(event)

    def moveEvent(self, event) -> None:
        self.super_chat_overlay.sync(self)
        self.schedule_quick_geometry()
        super().moveEvent(event)
