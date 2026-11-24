"""Super Chat cards and stacks inside chat panes; state stays with each Qt widget."""
from PySide6.QtCore import QEvent, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QTextOption
from PySide6.QtWidgets import QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QTextBrowser, QVBoxLayout, QWidget
from . import motion, theme
from .super_chat_model import SC_CONTENT_COLOR, SC_PRICE_COLOR, SC_USER_COLOR, format_price, format_remaining, order_super_chats, remaining_seconds, super_chat_palette
from .super_chat_avatar import SuperChatAvatar, paint_sc_avatar
from .super_chat_animation import SuperChatPresentation
from .super_chat_layout import paint_sc_background, sc_body_padding, sc_card_geometry, sc_card_height, sc_stack_rects


class SuperChatAvatarView(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedSize(24, 24)

    def paintEvent(self, event):
        card = self.parentWidget().parentWidget()
        painter = QPainter(self)
        paint_sc_avatar(painter, QRectF(self.rect()).adjusted(.5, .5, -.5, -.5),
                        card.avatar_image.pixmap, card.name.text())
        painter.end()


class SuperChatMessage(QTextBrowser):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setOpenLinks(False)
        self.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.document().setDocumentMargin(0)
        self.viewport().setAutoFillBackground(False)

    def text(self):
        return self.toPlainText()

    def textFormat(self):
        return Qt.PlainText

    def wheelEvent(self, event):
        super().wheelEvent(event)
        event.accept()


class SuperChatCard(QFrame):
    dismissFinished = Signal()
    """One fixed Super Chat card; colors come from Bilibili with safe fallbacks."""
    dismissed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("SuperChatCard")
        self.chat_id = ""
        self._scale = 1.0
        self.setMinimumHeight(64)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.header = QWidget(self)
        self.header.setObjectName('SuperChatHeader')
        top = QHBoxLayout(self.header)
        top.setContentsMargins(10, 6, 6, 6)
        top.setSpacing(6)
        self.avatar = SuperChatAvatarView(self.header)
        top.addWidget(self.avatar)
        self.avatar_image = SuperChatAvatar(self)
        self.avatar_image.changed.connect(self._refresh_avatar)
        from .ui.labels import ElidedLabel
        self.name = ElidedLabel()
        self.name.setObjectName("SuperChatName")
        self.name.setMinimumWidth(0)
        self.name.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        self.name.setTextFormat(Qt.PlainText)
        self.price = QLabel()
        self.price.setObjectName("SuperChatPrice")
        self.left = QLabel()
        self.left.setObjectName("SuperChatTime")
        self.user_details = QWidget(self.header)
        info = QVBoxLayout(self.user_details)
        info.setContentsMargins(0, 0, 0, 0)
        info.setSpacing(0)
        self.name_row = QHBoxLayout()
        self.name_row.setContentsMargins(0, 0, 0, 0)
        self.name_row.setSpacing(6)
        self.name_row.addWidget(self.name, 1)
        self.name_row.addWidget(self.left)
        info.addLayout(self.name_row)
        info.addWidget(self.price)
        top.addWidget(self.user_details, 1)
        self.close_button = QPushButton('×', self)
        self.close_button.setFixedSize(20, 20)
        self.close_button.setCursor(Qt.PointingHandCursor)
        self.close_button.setToolTip('隐藏这条醒目留言')
        self.close_button.setAccessibleName('关闭当前醒目留言')
        self.close_button.clicked.connect(lambda: self.dismissed.emit(self.chat_id))
        top.addWidget(self.close_button)
        self.message = SuperChatMessage()
        self.message.setObjectName("SuperChatMessage")
        self.message.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.message.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        layout.addWidget(self.header)
        layout.addWidget(self.message)
        self._paper = None
        self._progress = 0.0
        self.animation = motion.paper_animation(self, self._dismiss_frame, self.finish_dismiss)
        self._collapsed = False
        self.configure(1.0, False)

    def set_event(self, event: dict) -> None:
        previous_id = self.chat_id
        self.chat_id = str(event.get("super_chat_id") or event.get("id") or "")
        uname = str(event.get("uname") or "匿名用户")
        message = str(event.get("message") or event.get("text") or "")
        price = format_price(event.get("price"))
        palette = super_chat_palette(event.get('price'))
        self._colours = (palette['background_bottom_color'], palette['background_color'])
        text_color = SC_CONTENT_COLOR
        header_text = SC_USER_COLOR
        remaining = format_remaining(remaining_seconds(event.get("end_time")))
        self.name.setText(uname)
        self.avatar_image.set_url(event.get('face'))
        self._refresh_avatar()
        self.name.setToolTip(uname)
        self.name.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.price.setText(price)
        scroll = self.message.verticalScrollBar().value() if previous_id == self.chat_id else 0
        if self.message.toPlainText() != message or previous_id != self.chat_id:
            self.message.setPlainText(message)
            self.message.verticalScrollBar().setValue(scroll)
        self.message.setToolTip(message)
        self.left.setText(f"剩 {remaining}")
        self.ensurePolished()
        self.setFixedHeight(sc_card_height(event, self.width(), self._scale, self._collapsed))
        self.setStyleSheet(
            "QFrame#SuperChatCard {"
            "background:transparent;border:0;"
            "}"
            f"QFrame#SuperChatCard QLabel {{background:transparent;color:{text_color};}}"
            f"QFrame#SuperChatCard QPushButton {{background:transparent;color:{text_color};border:0;padding:0;font-size:{round(18 * self._scale)}px;}}"
            "QWidget#SuperChatHeader {background:transparent;}"
            f"QFrame#SuperChatCard QLabel#SuperChatName {{color:{header_text};font-size:{max(12, round(13 * self._scale))}px;}}"
            f"QFrame#SuperChatCard QLabel#SuperChatPrice {{color:{SC_PRICE_COLOR};font-size:{round((13 if self._collapsed else 15) * self._scale)}px;}}"
            f"QFrame#SuperChatCard QPushButton {{color:{header_text};}}"
            f"QFrame#SuperChatCard QLabel#SuperChatTime {{font-size:{max(11, round(11 * self._scale))}px;color:{header_text};}}"
            f"QFrame#SuperChatCard QTextBrowser#SuperChatMessage {{background:transparent;border:0;padding:0;color:{SC_CONTENT_COLOR};font-size:{max(1, round(14 * self._scale))}px;}}")

    def _refresh_avatar(self):
        self.avatar.update()

    def tick(self, event: dict) -> None:
        self.left.setText(f"剩 {format_remaining(remaining_seconds(event.get('end_time')))}")

    def configure(self, scale, collapsed):
        self._scale = scale
        self.setMinimumHeight(round((36 if collapsed else 64) * scale))
        self.header.setFixedHeight(round((36 if collapsed else 56) * scale))
        if self._collapsed != collapsed:
            if collapsed:
                self.user_details.layout().removeWidget(self.price)
                self.name_row.addWidget(self.price)
            else:
                self.name_row.removeWidget(self.price)
                self.user_details.layout().addWidget(self.price)
            self._collapsed = collapsed
        margin = round((6 if collapsed else 8) * scale)
        self.header.layout().setContentsMargins(round(10 * scale), margin, round(6 * scale), margin)
        self.header.layout().setSpacing(round(6 * scale))
        self.avatar.setFixedSize(round((24 if collapsed else 36) * scale), round((24 if collapsed else 36) * scale))
        self.close_button.setFixedSize(round(20 * scale), round(20 * scale))
        padding = sc_body_padding(scale)
        self.message.setViewportMargins(round(11 * scale), padding, round(11 * scale), padding)
        self.message.setVisible(not collapsed)

    def animate_dismiss(self, chat_id):
        if self._paper is not None or self.chat_id != str(chat_id) or not self.isVisible() or not motion.enabled():
            return
        self._paper = self.grab()
        self._paper_style = self.styleSheet()
        self.setStyleSheet("QFrame#SuperChatCard {background:transparent;border:0;}")
        for child in self.findChildren(QWidget, options=Qt.FindDirectChildrenOnly):
            child.hide()
        self.animation.start()

    def _dismiss_frame(self, progress):
        self._progress = progress
        self.update()
        self.parentWidget().update()

    def finish_dismiss(self):
        self.animation.stop()
        if self._paper is not None:
            self.setStyleSheet(self._paper_style)
        self._paper = None
        self._progress = 0.0
        for child in self.findChildren(QWidget, options=Qt.FindDirectChildrenOnly):
            child.show()
        self.dismissFinished.emit()

    def paintEvent(self, event):
        if self._paper is None:
            if hasattr(self, '_colours'):
                painter = QPainter(self)
                paint_sc_background(painter, QRectF(self.rect()).adjusted(.5, .5, -.5, -.5),
                                    *self._colours, self.header.height())
                painter.end()
            return
        painter = QPainter(self)
        motion.paint_paper_discard(painter, QRectF(self.rect()), self._paper, self._progress)
        painter.end()


class SuperChatStack(QWidget):
    """Independently collapsible SC cards arranged in a vertical list."""
    dismissed = Signal(str)
    layoutChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._events = []
        self._enabled = True
        self._opacity = .8
        self._scale = 1.0
        self._effective_scale = 1.0
        self._position = None
        self._last_collapsed = frozenset()
        self.presentation = SuperChatPresentation(self)
        self.presentation.changed.connect(self._presentation_changed)
        self._cards = []
        self._viewport = QWidget(self)
        self._content = QWidget(self._viewport)
        self._viewport.installEventFilter(self)
        self._content.installEventFilter(self)
        self._scroll_offset = 0
        self._scroll_maximum = 0
        self.alpha = QGraphicsOpacityEffect(self._viewport)
        self._viewport.setGraphicsEffect(self.alpha)
        self.hide()

    def configure(self, settings):
        self._position = settings.get('super_chat_position' if settings.get('super_chat_position_sync', True)
                                      else 'super_chat_panel_position')
        self._enabled = bool(settings.get('super_chat_enabled', True))
        self._opacity = int(settings.get('super_chat_panel_opacity',
                                         settings.get('super_chat_opacity', 80))) / 100
        self._scale = max(.75, min(2.0, int(settings.get('super_chat_panel_scale',
                                                        settings.get('super_chat_scale', 100))) / 100))
        self.presentation.configure(settings)
        self._presentation_changed()

    def _presentation_changed(self):
        self.alpha.setOpacity(self._opacity * self.presentation.progress)
        if self._last_collapsed != frozenset(self.presentation.collapsed_ids):
            self._last_collapsed = frozenset(self.presentation.collapsed_ids)
            self.layoutChanged.emit()
        self.update()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Wheel and self._scroll_maximum:
            over_message = any(watched is card.message or card.message.isAncestorOf(watched)
                               for card in self._cards)
            if not over_message:
                self.wheelEvent(event)
                return True
        if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            for index, card in enumerate(self._cards[:len(self._events)]):
                if watched is card.close_button:
                    return False
                if card is watched or card.isAncestorOf(watched):
                    chat_id = self._events[index]['id']
                    if self.presentation.is_collapsed(chat_id):
                        self.presentation.expand(chat_id, manual=True)
                        self._scroll_to(max(self._scroll_offset, card.geometry().bottom() + 1 - self.height()))
                        return True
                    if self.presentation.stays_expanded(chat_id) and (
                            watched is card.header or card.header.isAncestorOf(watched)):
                        self.presentation.collapse(chat_id)
                        return True
        return super().eventFilter(watched, event)

    def animate_dismiss(self, chat_id):
        for card in self._cards:
            card.animate_dismiss(chat_id)

    def _dismiss_finished(self):
        self.set_events(self._events)
        self.layoutChanged.emit()

    def _dismiss(self, chat_id):
        if self.presentation.is_collapsed(chat_id):
            self.dismissed.emit(chat_id)
        else:
            self.presentation.collapse(chat_id)

    def set_events(self, events, limit=None):
        self._events = order_super_chats(list(events))
        closing = [card for card in self._cards if card._paper is not None]
        if closing and self._enabled and limit != 0:
            return
        for card in closing:
            card.finish_dismiss()
        self.setVisible(bool(events) and self._enabled and limit != 0)
        self.presentation.set_events(self._events)
        while len(self._cards) < len(self._events):
            card = SuperChatCard(self._content)
            card.dismissed.connect(self._dismiss)
            card.dismissFinished.connect(self._dismiss_finished)
            for child in [card, *card.findChildren(QWidget)]:
                child.installEventFilter(self)
            self._cards.append(card)
        for card, event in zip(self._cards, self._events):
            card.configure(self._effective_scale, self.presentation.is_collapsed(event))
            card.set_event(event)
        self.arrange()
        self.update()

    def arrange(self):
        _, height, _, heights = sc_card_geometry(self._events, self.width() / self._effective_scale,
            self._effective_scale, self.width(), self.height(), self.presentation.is_collapsed,
            scroll_stack=True)
        rects = sc_stack_rects(self.width(), self.height(), len(self._events),
                               scale=self._effective_scale, card_heights=heights)
        content_height = max(round(height), rects[-1].toAlignedRect().bottom() + 1) if rects else 0
        self._scroll_maximum = max(0, content_height - self.height())
        self._viewport.setGeometry(self.rect())
        self._content.resize(self.width(), content_height)
        self._scroll_to(self._scroll_offset)
        for index in reversed(range(len(self._cards))):
            card = self._cards[index]
            card.setVisible(index < len(rects))
            if index < len(rects):
                card.setFixedHeight(round(rects[index].height()))
                card.setGeometry(rects[index].toAlignedRect())
                card.close_button.show()
                action = '关闭' if self.presentation.is_collapsed(self._events[index]) else '收起'
                card.close_button.setToolTip(f'{action}这条醒目留言')
                card.close_button.setAccessibleName(f'{action}醒目留言')
                card.setCursor(Qt.PointingHandCursor if self.presentation.is_collapsed(self._events[index]) else Qt.ArrowCursor)
                card.setToolTip('点击展开醒目留言' if self.presentation.is_collapsed(self._events[index]) else '')
                card.raise_()

    def _scroll_to(self, offset):
        self._scroll_offset = max(0, min(round(offset), self._scroll_maximum))
        self._content.move(0, -self._scroll_offset)

    def wheelEvent(self, event):
        if not self._scroll_maximum:
            return super().wheelEvent(event)
        delta = event.pixelDelta().y() or event.angleDelta().y() / 120 * 42
        self._scroll_to(self._scroll_offset - delta)
        event.accept()

    def paintEvent(self, event):
        if self._scroll_maximum:
            painter = QPainter(self)
            painter.fillRect(event.rect(), QColor('#ffffff' if theme.is_light() else theme.CONTENT))
            painter.end()

    def tick(self):
        for card, event in zip(self._cards, self._events):
            card.tick(event)
