"""Movable Super Chat video overlay; independent of scrolling danmaku rendering."""
import sys
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap, QRegion
from PySide6.QtWidgets import QApplication, QPushButton
from . import motion
from .badge_surface import BadgeSurface
from .super_chat_avatar import SuperChatAvatar
from .super_chat_animation import SuperChatPresentation
from .super_chat_layout import sc_placement_rects
from .super_chat_model import SC_USER_COLOR, SC_CONTENT_COLOR, remaining_seconds, order_super_chats
import math
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics
from . import theme
from .super_chat_avatar import paint_sc_avatar
from .super_chat_layout import paint_sc_background, sc_message_document
from .super_chat_model import format_price, format_remaining, super_chat_palette, SC_USER_COLOR, SC_PRICE_COLOR, remaining_seconds, SC_BODY_PADDING


class SuperChatOverlay(BadgeSurface):
    """Movable SC cards with per-pixel alpha above native video."""
    dismissed = Signal(str)
    settingsChanged = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SuperChatOverlay")
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        if self.qt_composited:
            # Keep SC pixels out of the video's shared native-child backing store.
            self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowDoesNotAcceptFocus)
            self.setAttribute(Qt.WA_ShowWithoutActivating)
        self._followed_widgets = set()
        self._settings_process = None
        self._surface_occluded = False
        self._presentation_changing = False
        self._follow_timer = QTimer(self)
        self._follow_timer.setSingleShot(True)
        self._follow_timer.timeout.connect(self._refresh)
        self.setMouseTracking(True)
        self.setCursor(Qt.OpenHandCursor)
        self.setToolTip('拖动标题移动，拖动边角缩放；折叠后点击展开')
        self.chats = []
        self.opacity = 0.8
        self._video_danmaku = None
        self._content_origin = QPoint()
        self._gesture = None
        self._moved = False
        self._paint_scale = 1.0
        self._paper = None
        self._pending_chats = None
        self._closing_index = None
        self._progress = 0.0
        self.animation = motion.paper_animation(self, self._dismiss_frame, self.finish_dismiss)
        self.presentation = SuperChatPresentation(self)
        self.presentation.changed.connect(self._refresh)
        self._avatars = [SuperChatAvatar(self)]
        self.avatar_image = self._avatars[0]
        for avatar in self._avatars:
            avatar.changed.connect(self._refresh)
        self.close_buttons = []
        for index in range(1):
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
            chat_id = str(self.chats[index]['id'])
            if self.presentation.is_collapsed(chat_id):
                self.dismissed.emit(chat_id)
            else:
                self.presentation.collapse(chat_id)

    def bind(self, owner):
        self._video_danmaku = owner
        self.setParent(owner.parentWidget())
        self.sync(owner)

    @property
    def qt_composited(self):
        return sys.platform == 'win32' and QApplication.platformName() == 'windows'

    def _follow_owner(self, owner):
        parent = owner.parentWidget() or owner
        window = parent.window()
        widgets = {parent, window}
        for widget in self._followed_widgets - widgets:
            widget.removeEventFilter(self)
        for widget in widgets - self._followed_widgets:
            widget.installEventFilter(self)
        self._followed_widgets = widgets
        handle = self.windowHandle()
        if handle is not None and window.windowHandle() is not None:
            handle.setTransientParent(window.windowHandle())
        host = parent
        while host.parentWidget() is not None:
            host = host.parentWidget()
        process = getattr(host, '_settings_process', None)
        if process is not self._settings_process:
            if self._settings_process is not None:
                self._settings_process.occlusionChanged.disconnect(self._queue_follow)
            self._settings_process = process
            if process is not None:
                process.occlusionChanged.connect(self._queue_follow)

    def _queue_follow(self):
        self._follow_timer.start(0)

    def eventFilter(self, watched, event):
        if watched in self._followed_widgets and event.type() in (
                QEvent.Move, QEvent.Resize, QEvent.Show, QEvent.Hide, QEvent.WindowStateChange,
                QEvent.WindowActivate, QEvent.WindowDeactivate):
            self._queue_follow()
        return super().eventFilter(watched, event)

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
        if self.qt_composited:
            self._follow_owner(owner)
            position = owner.mapToGlobal(bounds.topLeft())
        else:
            position = owner.pos() + bounds.topLeft()
        self.setGeometry(QRect(position, bounds.size()))
        region = QRegion()
        for rect in rects:
            region |= QRegion(rect.toAlignedRect().adjusted(-1, -1, 1, 1))
        region &= QRegion(bounds)
        video = owner._quick_video_mask if getattr(owner, '_quick_requested', False) else owner.mask()
        if not video.isEmpty():
            region &= video
        region.translate(-self._content_origin)
        if self.qt_composited and self._settings_process is not None:
            region -= QRegion(self._settings_process.occlusion.translated(-position))
        self._surface_occluded = region.isEmpty()
        if region != self.mask():
            self.setMask(region)
        scale = self._paint_scale
        for index, button in enumerate(self.close_buttons):
            button.setVisible(index < len(rects)
                              and self.presentation.progress == 1.0)
            button.setFixedSize(max(12, round(22 * scale)), max(12, round(22 * scale)))
            if index < len(rects):
                action = '关闭' if self.presentation.is_collapsed(self.chats[index]) else '收起'
                button.setToolTip(f'{action}这条醒目留言')
                button.setAccessibleName(f'{action}醒目留言')
                button.move(rects[index].topRight().toPoint() - self._content_origin
                            + QPoint(round(-26 * scale), round(7 * scale)))

    def set_chats(self, chats, opacity):
        if self._paper is not None:
            self._pending_chats = (list(chats), opacity)
            if self._video_danmaku.sc_visible():
                return
            self.finish_dismiss()
            return
        self.chats = order_super_chats([dict(chat) for chat in chats])
        while len(self._avatars) < len(self.chats):
            avatar = SuperChatAvatar(self)
            avatar.changed.connect(self._refresh)
            self._avatars.append(avatar)
            index = len(self.close_buttons)
            button = QPushButton('×', self)
            button.setCursor(Qt.PointingHandCursor)
            button.setToolTip('隐藏这条醒目留言')
            button.setAccessibleName('关闭醒目留言')
            button.clicked.connect(lambda checked=False, i=index: self._dismiss(i))
            self.close_buttons.append(button)
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
        visible = bool(self.chats) and owner.sc_visible() and not self._presentation_changing
        if self.qt_composited:
            parent = owner.parentWidget() or owner
            visible = (visible and parent.isVisible() and not parent.window().isMinimized()
                       and QApplication.activeModalWidget() is None)
        if self.chats:
            self.sync(owner)
            for chat, button in zip(self.chats, self.close_buttons):
                colour = SC_USER_COLOR
                style = ('QPushButton {background:transparent;border:0;'
                         f'color:{colour};font-size:{round(18 * self._paint_scale)}px;padding:0;}}')
                if style != button.styleSheet():
                    button.setStyleSheet(style)
        self.setVisible(visible and not self._surface_occluded)
        if visible and not was_visible:
            self.raise_()
        self._refresh_quick_mask()
        self.update()

    def set_presentation_changing(self, active):
        self._presentation_changing = bool(active)
        if active:
            self.hide()
        else:
            self._refresh()

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
        self._start_scale = int(self._video_danmaku.settings.get('super_chat_video_scale',
                                                                    self._video_danmaku.settings.get('super_chat_scale', 100)))
        self._start_extent = self.size()
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
            value = max(75, min(200, round(self._start_scale * (1 + change))))
            owner.settings['super_chat_video_scale'] = value
            owner.settings['super_chat_scale'] = value
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
            if gesture == 'resize':
                self.settingsChanged.emit({
                    'super_chat_scale': self._video_danmaku.settings['super_chat_scale'],
                    'super_chat_video_scale': self._video_danmaku.settings['super_chat_video_scale']})
            else:
                self.settingsChanged.emit({'super_chat_position': self._video_danmaku.settings['super_chat_position']})
        else:
            self._activate(self._press_point)
        self.setCursor(Qt.OpenHandCursor)
        event.accept()

    def _activate(self, point):
        rects = self.card_rects()
        for index, rect in enumerate(rects):
            if rect.contains(point):
                if self.presentation.is_collapsed(self.chats[index]):
                    self.presentation.expand(self.chats[index]['id'])
                return

    def animate_dismiss(self, chat_id):
        index = next((i for i, chat in enumerate(self.chats) if str(chat.get('id')) == str(chat_id)), None)
        if (self._paper is not None or index is None
                or not self.isVisible() or not motion.enabled()):
            return
        rect = self.card_rects()[index]
        scale = self.devicePixelRatioF()
        image = QImage(round(rect.width() * scale), round(rect.height() * scale), QImage.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(scale)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        self._video_danmaku._paint_super_chat(painter, QRectF(0, 0, rect.width(), rect.height()),
                                            self.chats[index], self._paint_scale, avatar=self._avatars[index].pixmap,
                                            collapsed=self.presentation.is_collapsed(self.chats[index]))
        painter.end()
        self._paper = QPixmap.fromImage(image)
        self._closing_index = index
        for button in self.close_buttons:
            button.hide()
        self.animation.start()
        self._refresh()

    def _dismiss_frame(self, progress):
        self._progress = progress
        self._refresh()

    def finish_dismiss(self):
        self.animation.stop()
        self._paper = None
        self._closing_index = None
        self._progress = 0.0
        pending, self._pending_chats = self._pending_chats, None
        if pending is not None:
            self.set_chats(*pending)

    def card_rects(self):
        owner = self._video_danmaku
        if not self.chats or owner is None:
            return []
        rects, self._paint_scale = sc_placement_rects(
            self.chats, owner.width(), owner.height(),
            max(.75, min(2.0, int(owner.settings.get('super_chat_video_scale',
                                                     owner.settings.get('super_chat_scale', 100))) / 100)),
            owner.settings.get('super_chat_position'), collapsed=self.presentation.is_collapsed,
            scale_with_video=owner.settings.get('super_chat_scale_with_video', False),
            scale_strength=owner.settings.get('super_chat_scale_strength', 35),
            scale_curve=owner.settings.get('super_chat_scale_curve'))
        return rects

    def _refresh_quick_mask(self):
        owner = self._video_danmaku
        if owner is None or owner._quick_group is None:
            return  # Restoring the toggle can run before Tile creates its controls.
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
            if self._paper is not None and index == self._closing_index:
                motion.paint_paper_discard(content, rects[index], self._paper, self._progress)
            else:
                owner._paint_super_chat(content, rects[index], self.chats[index], self._paint_scale,
                                        avatar=self._avatars[index].pixmap,
                                        collapsed=self.presentation.is_collapsed(self.chats[index]))
        if rects:
            content.setPen(QPen(QColor(SC_USER_COLOR if self.presentation.collapsed else SC_CONTENT_COLOR), 1))
            corner = rects[0].bottomLeft() + QPointF(4, -4)
            for length in (4, 7):
                content.drawLine(corner + QPointF(0, -length), corner + QPointF(length, 0))
        content.end()
        painter.save()
        painter.setOpacity(self.opacity * self.presentation.progress)
        painter.translate(0, 6 * (1 - self.presentation.progress))
        painter.drawImage(QPoint(), layer)
        painter.restore()
        if painter.device() is not self:
            for button in self.close_buttons:
                if button.isVisible():
                    button.render(painter, button.pos())

    def _layered_render_key(self):
        fields = ('id', 'uname', 'face', 'message', 'price', 'background_color', 'background_bottom_color', 'background_price_color')
        return (self.opacity, self.presentation.progress, tuple(sorted(self.presentation.collapsed_ids)),
                self._progress, self._closing_index, self._paint_scale,
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
        painter = QPainter(self)
        self._render_layered(painter)
        painter.end()

    def showEvent(self, event):
        if sys.platform == 'win32' and QApplication.platformName() == 'windows':
            self.setAttribute(Qt.WA_NativeWindow, True)
        super().showEvent(event)
        if self.qt_composited and self._video_danmaku is not None:
            self._follow_owner(self._video_danmaku)

    def hideEvent(self, event):
        self._gesture = None
        super().hideEvent(event)


def _paint_super_chat(painter, rect, chat: dict, scale: float,
                      paint_opacity: float | None = None, avatar=None, collapsed=False) -> None:
    palette = super_chat_palette(chat.get('price'))
    header = QColor(palette['background_color'])
    background = QColor(palette['background_bottom_color'])
    painter.save()
    if paint_opacity is not None:
        painter.setOpacity(paint_opacity)
    header_height = 36 if collapsed else 56
    paint_sc_background(painter, rect, background, header, header_height * scale)
    top = rect.top() + (6 if collapsed else 10) * scale
    avatar_size = (24 if collapsed else 36) * scale
    avatar_rect = QRectF(rect.left() + 10 * scale, top, avatar_size, avatar_size)
    paint_sc_avatar(painter, avatar_rect, avatar, str(chat.get('uname') or '?'))
    left = avatar_rect.right() + 6 * scale
    font = QFont(theme.FONT_DEFAULT)
    font.setPixelSize(max(1, round(13 * scale)))
    painter.setFont(font)
    painter.setPen(QColor(SC_USER_COLOR))
    metrics = QFontMetrics(font)
    price = format_price(chat.get('price'))
    price_width = metrics.horizontalAdvance(price) + 4 * scale
    right = rect.right() - 34 * scale
    if collapsed:
        right -= price_width + 4 * scale
    small = QFont(theme.FONT_DEFAULT)
    small.setPixelSize(max(1, round(11 * scale)))
    remaining = '剩 ' + format_remaining(remaining_seconds(chat.get('end_time')))
    time_width = QFontMetrics(small).horizontalAdvance(remaining)
    name_width = max(0, right - left - time_width - 6 * scale)
    name = metrics.elidedText(str(chat.get('uname') or '匿名用户'), Qt.ElideRight, round(name_width))
    painter.drawText(QRectF(left, top, name_width, (24 if collapsed else 18) * scale),
                     int(Qt.AlignLeft | Qt.AlignVCenter), name)
    painter.setFont(small)
    painter.drawText(QRectF(left + metrics.horizontalAdvance(name) + 6 * scale,
                           top, time_width, (24 if collapsed else 18) * scale),
                     int(Qt.AlignLeft | Qt.AlignVCenter), remaining)
    painter.setPen(QColor(SC_PRICE_COLOR))
    font.setPixelSize(max(1, round((13 if collapsed else 15) * scale)))
    painter.setFont(font)
    if collapsed:
        painter.drawText(QRectF(right + 4 * scale, top, price_width, 24 * scale),
                         int(Qt.AlignRight | Qt.AlignVCenter), price)
        painter.restore()
        return
    painter.drawText(QRectF(left, top + 19 * scale, max(0, right - left), 22 * scale),
                     int(Qt.AlignLeft | Qt.AlignVCenter), price)
    padding = math.ceil(SC_BODY_PADDING * scale)
    body_rect = rect.adjusted(11 * scale, round(56 * scale) + padding, -11 * scale, -padding)
    document = sc_message_document(chat, rect.width(), scale)
    painter.setClipRect(body_rect, Qt.IntersectClip)
    painter.translate(body_rect.topLeft())
    document.drawContents(painter, QRectF(0, 0, body_rect.width(), body_rect.height()))
    painter.restore()
