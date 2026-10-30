"""轻量画面弹幕：有界轨道、匀速滚动，原生视频窗口上的鼠标穿透浮层。"""
import math
import os
import sys
# Python 3.12 on Windows uses a 15.625ms monotonic clock; QPC preserves sub-frame motion.
from time import perf_counter
from dataclasses import dataclass

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetrics, QImage, QPainter, QPainterPath, QPen, QPixmap, QRegion, QTextCharFormat, QTextCursor, QTextDocument
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from . import motion, theme
from .danmaku_content import content_runs, content_html
from .images import AvatarLoader
from .badge_surface import BadgeSurface
from .super_chat import (SuperChatAvatar, SuperChatPresentation, format_price, format_remaining, readable_text_color,
                         remaining_seconds, paint_sc_avatar, paint_sc_background, order_super_chats, sc_stack_rects)


class SuperChatOverlay(BadgeSurface):
    """Movable SC cards with per-pixel alpha above native video."""
    dismissed = Signal(str)
    settingsChanged = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SuperChatOverlay")
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setMouseTracking(True)
        self.setCursor(Qt.OpenHandCursor)
        self.setToolTip('拖动标题移动，拖动边角缩放；折叠后点击展开')
        self.chats = []
        self.opacity = 0.8
        self._video_danmaku = None
        self._content_origin = QPoint()
        self._selected_id = ''
        self._gesture = None
        self._moved = False
        self._paint_scale = 1.0
        self.presentation = SuperChatPresentation(self)
        self.presentation.changed.connect(self._refresh)
        self._avatars = [SuperChatAvatar(self) for _ in range(3)]
        self.avatar_image = self._avatars[0]
        for avatar in self._avatars:
            avatar.changed.connect(self._refresh)
        self.close_buttons = []
        for index in range(2):
            button = QPushButton('×', self)
            button.setCursor(Qt.PointingHandCursor)
            button.setToolTip('隐藏这条醒目留言')
            button.setAccessibleName('关闭醒目留言')
            button.clicked.connect(lambda checked=False, i=index: self._dismiss(i))
            self.close_buttons.append(button)
        self.close_button = self.close_buttons[0]
        self.hide()

    def _dismiss(self, index):
        if index < len(self.chats):
            self.dismissed.emit(str(self.chats[index]['id']))

    def bind(self, owner):
        self._video_danmaku = owner
        self.setParent(owner.parentWidget())
        self.sync(owner)

    def sync(self, owner):
        if self._video_danmaku is not owner:
            return
        rects = self.card_rects()
        if not rects:
            return
        bounds = rects[0].toAlignedRect()
        for rect in rects[1:]:
            bounds |= rect.toAlignedRect()
        bounds = bounds.adjusted(-1, -1, 1, 1).intersected(owner.rect())
        self._content_origin = bounds.topLeft()
        self.setGeometry(QRect(owner.pos() + bounds.topLeft(), bounds.size()))
        region = QRegion()
        for rect in rects:
            region |= QRegion(rect.toAlignedRect().adjusted(-1, -1, 1, 1))
        region &= QRegion(bounds)
        video = owner._quick_video_mask if getattr(owner, '_quick_requested', False) else owner.mask()
        if not video.isEmpty():
            region &= video
        region.translate(-self._content_origin)
        if region != self.mask():
            self.setMask(region)
        scale = self._paint_scale
        for index, button in enumerate(self.close_buttons):
            button.setVisible(index < len(rects) and (index == 0 or len(self.chats) == 2)
                              and self.presentation.progress == 1.0)
            button.setFixedSize(max(12, round(22 * scale)), max(12, round(22 * scale)))
            if index < len(rects):
                button.move(rects[index].topRight().toPoint() - self._content_origin
                            + QPoint(round(-26 * scale), round(7 * scale)))

    def set_chats(self, chats, opacity):
        self.chats = order_super_chats([dict(chat) for chat in chats], self._selected_id)
        if len(self.chats) < 3 or not any(str(chat.get('id')) == self._selected_id for chat in self.chats):
            self._selected_id = ''
        for index, avatar in enumerate(self._avatars):
            avatar.set_url(self.chats[index].get('face') if index < len(self.chats) else '')
        self.opacity = max(0.0, min(1.0, float(opacity)))
        owner = self._video_danmaku
        if owner is not None:
            self.presentation.configure(owner.settings)
        self.presentation.set_events(self.chats)
        self._refresh()

    def _refresh(self):
        owner = self._video_danmaku
        if owner is None:
            return
        was_visible = self.isVisible()
        visible = bool(self.chats) and owner.sc_visible()
        if self.chats:
            self.sync(owner)
            for chat, button in zip(self.chats, self.close_buttons):
                colour = readable_text_color(chat.get('background_bottom_color') or chat.get('background_color')).name()
                style = ('QPushButton {background:transparent;border:0;'
                         f'color:{colour};font-size:{round(18 * self._paint_scale)}px;padding:0;}}')
                if style != button.styleSheet():
                    button.setStyleSheet(style)
        self.setVisible(visible)
        if visible and not was_visible:
            self.raise_()
        self._refresh_quick_mask()
        self.update()
        if visible and sys.platform == 'win32' and QApplication.platformName() == 'windows':
            self._schedule_layered_paint()

    def select_chat(self, chat_id):
        self._selected_id = str(chat_id)
        self.set_chats(self.chats, self.opacity)

    def _corner(self, point):
        rects = self.card_rects()
        if not rects:
            return None
        bounds = rects[0]
        for rect in rects[1:]:
            bounds = bounds.united(rect)
        for x, y, corner in ((bounds.left(), bounds.top(), (-1, -1)),
                             (bounds.right(), bounds.top(), (1, -1)),
                             (bounds.left(), bounds.bottom(), (-1, 1)),
                             (bounds.right(), bounds.bottom(), (1, 1))):
            if abs(point.x() - x) <= 12 and abs(point.y() - y) <= 12:
                return corner
        return None

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton or not self.chats:
            return super().mousePressEvent(event)
        self._press_global = event.globalPosition()
        self._press_point = event.position() + self._content_origin
        self._corner_sign = self._corner(self._press_point)
        self._gesture = 'resize' if self._corner_sign else 'drag'
        self._moved = False
        rects = self.card_rects()
        self._start_origin = QPointF(min(rect.left() for rect in rects), min(rect.top() for rect in rects))
        self._start_scale = int(self._video_danmaku.settings.get('super_chat_scale', 100))
        self._start_extent = self.size()
        self.presentation.timer.stop()
        event.accept()

    def mouseMoveEvent(self, event):
        point = event.position() + self._content_origin
        if self._gesture is None:
            corner = self._corner(point)
            self.setCursor((Qt.SizeFDiagCursor if corner[0] == corner[1] else Qt.SizeBDiagCursor)
                           if corner else Qt.PointingHandCursor if self.presentation.collapsed else Qt.OpenHandCursor)
            return
        delta = event.globalPosition() - self._press_global
        if not self._moved and abs(delta.x()) + abs(delta.y()) < QApplication.startDragDistance():
            return
        self._moved = True
        self.presentation.entrance.stop()
        self.presentation.progress = 1.0
        owner = self._video_danmaku
        if self._gesture == 'resize':
            dx = delta.x() * self._corner_sign[0] / max(1, self._start_extent.width())
            dy = delta.y() * self._corner_sign[1] / max(1, self._start_extent.height())
            change = dx if abs(dx) >= abs(dy) else dy
            owner.settings['super_chat_scale'] = max(75, min(200, round(self._start_scale * (1 + change))))
        else:
            self._place_at(self._start_origin + delta)
            self.setCursor(Qt.ClosedHandCursor)
        self._refresh()
        event.accept()

    def _place_at(self, point):
        owner = self._video_danmaku
        rects = self.card_rects()
        width = max(rect.right() for rect in rects) - min(rect.left() for rect in rects)
        height = max(rect.bottom() for rect in rects) - min(rect.top() for rect in rects)
        spans = (max(0, owner.width() - 20 - width), max(0, owner.height() - 20 - height))
        values = []
        for value, span in zip((point.x() - 10, point.y() - 10), spans):
            value = max(0, min(span, value))
            if value <= 16:
                value = 0
            elif span - value <= 16:
                value = span
            values.append(round(value / span, 6) if span else 0.0)
        owner.settings['super_chat_position'] = values

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton or self._gesture is None:
            return super().mouseReleaseEvent(event)
        gesture, self._gesture = self._gesture, None
        if self._moved:
            key = 'super_chat_scale' if gesture == 'resize' else 'super_chat_position'
            self.settingsChanged.emit({key: self._video_danmaku.settings[key]})
        else:
            self._activate(self._press_point)
        if self.chats and not self.presentation.collapsed:
            self.presentation.timer.start(self.presentation.delay * 1000)
        self.setCursor(Qt.OpenHandCursor)
        event.accept()

    def _activate(self, point):
        if self.presentation.collapsed:
            self.presentation.expand()
            return
        if len(self.chats) < 3:
            return
        front = self.card_rects()[0]
        if front.adjusted(front.width() - 110 * self._paint_scale,
                          front.height() - 24 * self._paint_scale, -24 * self._paint_scale, 0).contains(point):
            ordered = order_super_chats(self.chats)
            index = next((i for i, chat in enumerate(ordered) if str(chat['id']) == str(self.chats[0]['id'])), 0)
            self.select_chat(ordered[(index + 1) % len(ordered)]['id'])
            return
        for index, rect in enumerate(self.card_rects()):
            if rect.contains(point):
                if index:
                    self.select_chat(self.chats[index]['id'])
                return

    def card_rects(self):
        owner = self._video_danmaku
        if not self.chats or owner is None:
            return []
        base_width = min(340, max(168, round(owner.width() * .30)))
        card_height = 36 if self.presentation.collapsed else 100
        base_height = card_height + 40 if len(self.chats) >= 3 else card_height * len(self.chats) + 8 * (len(self.chats) - 1)
        scale = max(.75, min(2.0, int(owner.settings.get('super_chat_scale', 100)) / 100))
        scale = min(scale, max(1, owner.width() - 20) / base_width,
                    max(1, owner.height() - 20) / base_height)
        self._paint_scale = scale
        width, height = base_width * scale, base_height * scale
        spans = (max(0, owner.width() - 20 - width), max(0, owner.height() - 20 - height))
        position = owner.settings.get('super_chat_position')
        if isinstance(position, (list, tuple)) and len(position) == 2:
            try:
                ratios = [max(0.0, min(1.0, float(value))) for value in position]
            except (TypeError, ValueError):
                ratios = [1.0, 0.0]
            left, top = [10 + ratio * span for ratio, span in zip(ratios, spans)]
        else:
            left = 10 + spans[0]
            top = min(54 if owner.height() >= 320 else 10, 10 + spans[1])
        rects = sc_stack_rects(width, height, len(self.chats), card_height, scale)
        return [rect.translated(left, top) for rect in rects]

    def _refresh_quick_mask(self):
        owner = self._video_danmaku
        tile = owner.parentWidget() if owner is not None else None
        refresh = getattr(tile, '_update_quick_danmaku_mask', None)
        if refresh is not None:
            refresh()

    def _render_layered(self, painter):
        owner = self._video_danmaku
        if owner is None:
            return
        scale = self.devicePixelRatioF()
        layer = QImage(round(self.width() * scale), round(self.height() * scale), QImage.Format_ARGB32_Premultiplied)
        layer.setDevicePixelRatio(scale)
        layer.fill(Qt.transparent)
        content = QPainter(layer)
        content.translate(-self._content_origin)
        rects = self.card_rects()
        for index in reversed(range(len(rects))):
            owner._paint_super_chat(content, rects[index], self.chats[index], self._paint_scale,
                                    avatar=self._avatars[index].pixmap, collapsed=self.presentation.collapsed)
        if len(self.chats) >= 3 and rects:
            content.setPen(readable_text_color(self.chats[0].get('background_color')))
            font = QFont(theme.FONT_DEFAULT)
            font.setPixelSize(max(7, round(11 * self._paint_scale)))
            content.setFont(font)
            if not self.presentation.collapsed:
                content.drawText(rects[0].adjusted(12, 0, -32, -4), int(Qt.AlignRight | Qt.AlignBottom),
                                 f'共 {len(self.chats)} 条')
        if rects:
            content.setPen(QPen(readable_text_color(self.chats[0].get('background_color')), 1))
            corner = rects[0].bottomLeft() + QPointF(4, -4)
            for length in (4, 7):
                content.drawLine(corner + QPointF(0, -length), corner + QPointF(length, 0))
        content.end()
        painter.save()
        painter.setOpacity(self.opacity * self.presentation.progress)
        painter.translate(0, 6 * (1 - self.presentation.progress))
        painter.drawImage(QPoint(), layer)
        painter.restore()
        for button in self.close_buttons:
            if button.isVisible():
                button.render(painter, button.pos())

    def _layered_render_key(self):
        fields = ('id', 'uname', 'face', 'message', 'price', 'background_color', 'background_bottom_color', 'background_price_color')
        return (self.opacity, self.presentation.progress, self.presentation.collapsed, self._paint_scale,
                self._content_origin.x(), self._content_origin.y(), len(self.chats),
                tuple(avatar.pixmap.cacheKey() if avatar.pixmap is not None else None for avatar in self._avatars),
                tuple(tuple(str(chat.get(key, '')) for key in fields)
                      + (remaining_seconds(chat.get('end_time')),)
                      for chat in self.chats[:3]), tuple(button.isDown() for button in self.close_buttons))

    def render_image(self):
        scale = self.devicePixelRatioF()
        image = QImage(round(self.width() * scale), round(self.height() * scale), QImage.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(scale)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        self._render_layered(painter)
        painter.end()
        return image

    def paintEvent(self, event):
        if sys.platform == 'win32' and QApplication.platformName() == 'windows':
            if self.isVisible():
                self._schedule_layered_paint()
            return
        painter = QPainter(self)
        self._render_layered(painter)
        painter.end()

    def showEvent(self, event):
        if sys.platform == 'win32' and QApplication.platformName() == 'windows':
            self.setAttribute(Qt.WA_NativeWindow, True)
        super().showEvent(event)

    def hideEvent(self, event):
        self._gesture = None
        super().hideEvent(event)


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


class VideoDanmaku(QWidget):
    actionsRequested = Signal(str, QPoint)
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
        self._menu_open = True
        try:
            self.actionsRequested.emit(comment.message, position)
        finally:
            self._menu_open = False
            self._poll_hover()
        return True

    def apply_settings(self, settings: dict) -> None:
        values = {key: settings.get(key) for key in (
            "danmaku_font", "video_danmaku_size", "video_danmaku_speed",
            "video_danmaku_opacity", "video_danmaku_area", "video_danmaku_scale",
            "video_danmaku_outline_width", "super_chat_enabled", "super_chat_opacity",
            "super_chat_collapse_delay", "super_chat_scale", "super_chat_position")}
        values['super_chat_enabled'] = settings.get('super_chat_enabled', True)
        values['super_chat_opacity'] = settings.get('super_chat_opacity', 80)
        values['super_chat_collapse_delay'] = settings.get('super_chat_collapse_delay', 7)
        values['super_chat_scale'] = settings.get('super_chat_scale', 100)
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
        visible = self.enabled and self.active
        self.super_chat_overlay.setVisible(self.sc_visible() and
            bool(self.super_chats))
        if not visible:
            # Erase the native backing while still visible. Hiding first leaves
            # its last rendered comments cached until the next asynchronous paint.
            self._set_hover(None)
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
                           self_sent=self_sent, message=str(event.get('text') or ''))
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

    @staticmethod
    def _paint_super_chat(painter, rect, chat: dict, scale: float,
                          paint_opacity: float | None = None, avatar=None, collapsed=False) -> None:
        background = QColor(str(chat.get('background_color') or '#f59e0b'))
        header = QColor(str(chat.get('background_bottom_color') or background.name()))
        accent = QColor(str(chat.get('background_price_color') or header.name()))
        painter.save()
        if paint_opacity is not None:
            painter.setOpacity(paint_opacity)
        paint_sc_background(painter, rect, background, header, accent, 36 * scale)
        top = rect.top() + 6 * scale
        avatar_rect = QRectF(rect.left() + 10 * scale, top, 24 * scale, 24 * scale)
        paint_sc_avatar(painter, avatar_rect, avatar, str(chat.get('uname') or '?'))
        left = avatar_rect.right() + 6 * scale
        font = QFont(theme.FONT_DEFAULT)
        font.setPixelSize(max(6, round(13 * scale)))
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(readable_text_color(header))
        metrics = QFontMetrics(font)
        price = format_price(chat.get('price'))
        price_width = metrics.horizontalAdvance(price) + 4 * scale
        price_left = rect.right() - 34 * scale - price_width
        painter.drawText(QRectF(price_left, top, price_width, 24 * scale),
                         int(Qt.AlignRight | Qt.AlignVCenter), price)
        small = QFont(theme.FONT_DEFAULT)
        small.setPixelSize(max(6, round(11 * scale)))
        remaining = '剩 ' + format_remaining(remaining_seconds(chat.get('end_time')))
        time_width = QFontMetrics(small).horizontalAdvance(remaining)
        name_width = max(0, price_left - left - time_width - 12 * scale)
        name = metrics.elidedText(str(chat.get('uname') or '匿名用户'), Qt.ElideRight, round(name_width))
        painter.drawText(QRectF(left, top, name_width, 24 * scale),
                         int(Qt.AlignLeft | Qt.AlignVCenter), name)
        painter.setFont(small)
        painter.drawText(QRectF(left + metrics.horizontalAdvance(name) + 6 * scale,
                               top, time_width, 24 * scale), int(Qt.AlignLeft | Qt.AlignVCenter), remaining)
        if collapsed:
            painter.restore()
            return
        body = QFont(theme.FONT_DEFAULT)
        body.setPixelSize(max(7, round(14 * scale)))
        painter.setFont(body)
        painter.setPen(readable_text_color(background))
        painter.drawText(rect.adjusted(11 * scale, 42 * scale, -11 * scale, -7 * scale),
                         int(Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap),
                         str(chat.get('message') or chat.get('text') or ''))
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
        if self.sc_visible() and self.super_chats:
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
        self._set_hover(None)
        if self._quick_animated() and self.timer.isActive():
            self._tick()
        self._stop_timer()
        if self._quick_layer is not None and self._quick_group is not None:
            self._quick_layer.set_group_visible(self._quick_group, False)
        self.super_chat_overlay.setVisible(self.sc_independent and self.sc_visible() and bool(self.super_chats))
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
