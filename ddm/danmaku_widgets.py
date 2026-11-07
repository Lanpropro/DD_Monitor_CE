"""Chat pane rendering and Super Chat presentation; connections stay with the host."""
import math
from PySide6.QtCore import QEvent, QMimeData, QPoint, QPointF, QRectF, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import (
    QColor, QCursor, QDrag, QFont, QFontMetrics, QKeySequence, QPainter, QPainterPath, QPalette,
    QPen, QPixmap, QTextDocument, QTextOption
)
from PySide6.QtWidgets import (
    QApplication, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QMenu, QPushButton,
    QSizePolicy, QSlider, QTextBrowser, QVBoxLayout, QWidget
)
from shiboken6 import isValid

from . import motion, theme
from .corner_geometry import continuous_path
from .danmaku_content import content_html, content_runs
from .images import AvatarLoader
from .playback_controls import _icon_color
from .sidebar_drag import ROOM_MIME
from .super_chat import (
    SC_BODY_PADDING, SC_CONTENT_COLOR, SC_PRICE_COLOR, SC_USER_COLOR, SuperChatAvatar,
    SuperChatPresentation, format_price, format_remaining, order_super_chats, paint_sc_avatar,
    paint_sc_background, remaining_seconds, sc_card_height, sc_placement_rects, sc_stack_rects,
    super_chat_palette
)
from .widget_support import DANMAKU_MIME, TILE_BAR_HEIGHT, TILE_MIME, _repolish


def _brightness(color: str) -> int:
    """这个颜色够不够亮（用来决定徽章上写黑字还是白字）。"""
    text = str(color).lstrip("#")
    if len(text) != 6:
        return 0
    try:
        red, green, blue = (int(text[index:index + 2], 16) for index in (0, 2, 4))
    except ValueError:
        return 0
    return (red * 299 + green * 587 + blue * 114) // 1000


def _is_running(thread) -> bool:
    """QThread 已经被 Qt 回收时也算没在跑。"""
    try:
        return thread.isRunning()
    except RuntimeError:
        return False


def _medal_chip(name: str, level: str, color: str, font_size: int) -> QPixmap:
    """粉丝牌底：圆角小色块 + 名字和等级。

    QTextDocument 的富文本不支持圆角，所以直接把牌子画成图片贴进弹幕行里。
    """
    font = QFont(theme.FONT_DEFAULT)
    font.setPixelSize(max(8, round(font_size * 0.82)))
    font.setBold(True)
    text = f"{name}{level}"
    metrics = QFontMetrics(font)
    padding = max(4, round(font_size * 0.42))
    height = max(12, round(font_size * 1.45))
    width = metrics.horizontalAdvance(text) + padding * 2
    pixmap = QPixmap(width, height)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    radius = max(3.0, height * 0.28)
    path = QPainterPath()
    path.addPath(continuous_path(QRectF(0, 0, width, height), radius))
    painter.fillPath(path, QColor(color))
    painter.setPen(QColor("#14161a" if _brightness(color) > 150 else "#ffffff"))
    painter.setFont(font)
    painter.drawText(QRectF(0, 0, width, height), int(Qt.AlignCenter), text)
    painter.end()
    return pixmap


class DanmakuTextBrowser(QTextBrowser):
    """能告诉面板“用户正在查看旧弹幕”的文本区。"""

    userScrolled = Signal()
    messageClicked = Signal(int, QPoint)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self._hover_block = None
        self._action_block = None

    def _block_at(self, position):
        if not getattr(self.parentWidget(), '_has_content', True):
            return None
        block = self.cursorForPosition(position.toPoint()).block()
        rect = self.document().documentLayout().blockBoundingRect(block).translated(
            -self.horizontalScrollBar().value(), -self.verticalScrollBar().value())
        return block if rect.contains(position) and block.text() else None

    def _hover_at(self, position):
        self._hover_block = self._block_at(position)
        self.viewport().setCursor(Qt.PointingHandCursor if self._hover_block is not None else Qt.IBeamCursor)
        self.viewport().update()

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        self._hover_at(event.position())

    def viewportEvent(self, event):
        if event.type() == QEvent.Leave:
            self._hover_block = None
            self.viewport().update()
        return super().viewportEvent(event)

    def scrollContentsBy(self, dx, dy):
        super().scrollContentsBy(dx, dy)
        if self.viewport().underMouse():
            self._hover_at(QPointF(self.viewport().mapFromGlobal(QCursor.pos())))

    def paintEvent(self, event):
        super().paintEvent(event)
        block = self._action_block if self._action_block is not None else self._hover_block
        if block is not None and block.isValid():
            from .danmaku_actions import comment_hover_color
            rect = self.document().documentLayout().blockBoundingRect(block).translated(
                -self.horizontalScrollBar().value(), -self.verticalScrollBar().value())
            rect.setLeft(4)
            rect.setRight(self.viewport().width() - 4)
            painter = QPainter(self.viewport())
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(Qt.NoPen)
            painter.setBrush(comment_hover_color())
            painter.drawPath(continuous_path(rect.adjusted(0, 0, 0, -1), 8))

    def mousePressEvent(self, event):
        self._click_start = event.position().toPoint() if event.button() == Qt.LeftButton else None
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        start = getattr(self, '_click_start', None)
        self._click_start = None
        if (event.button() != Qt.LeftButton or start is None
                or (event.position().toPoint() - start).manhattanLength() >= QApplication.startDragDistance()
                or self.textCursor().hasSelection()):
            return
        block = self._block_at(event.position())
        if block is not None:
            self._hover_at(event.position())
            self.messageClicked.emit(block.blockNumber(), event.globalPosition().toPoint())

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        copy_action = menu.addAction("复制", self.copy)
        copy_action.setShortcut(QKeySequence.Copy)
        copy_action.setEnabled(self.textCursor().hasSelection())
        link = self.anchorAt(event.pos())
        if link:
            menu.addAction("复制链接地址", lambda: QApplication.clipboard().setText(link))
        menu.addSeparator()
        select_action = menu.addAction("全选", self.selectAll)
        select_action.setShortcut(QKeySequence.SelectAll)
        select_action.setEnabled(not self.document().isEmpty())
        try:
            menu.exec(event.globalPos())
        finally:
            menu.deleteLater()

    def wheelEvent(self, event) -> None:
        super().wheelEvent(event)
        self.userScrolled.emit()

    def keyPressEvent(self, event) -> None:
        super().keyPressEvent(event)
        self.userScrolled.emit()


class DanmakuBottomButton(QPushButton):
    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("TileCtrl")
        self.setFixedSize(32, 32)
        self.setStyleSheet("#TileCtrl {padding: 0; min-width: 0; min-height: 0;}")
        self.setToolTip("滚动到底部并继续跟随新弹幕")
        self.setAccessibleName("滚动到最新弹幕")
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(_icon_color(self), 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        painter.setPen(pen)
        center = self.rect().center()
        x, y = center.x(), center.y()
        painter.drawLine(QPointF(x, y - 6), QPointF(x, y + 3))
        painter.drawLine(QPointF(x - 4, y - 1), QPointF(x, y + 3))
        painter.drawLine(QPointF(x + 4, y - 1), QPointF(x, y + 3))
        painter.drawLine(QPointF(x - 5, y + 7), QPointF(x + 5, y + 7))


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
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setOpenLinks(False)
        self.setWordWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.document().setDocumentMargin(0)
        self.viewport().setAutoFillBackground(False)

    def text(self):
        return self.toPlainText()

    def textFormat(self):
        return Qt.PlainText


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
        self.message.setPlainText(message)
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
            f"QFrame#SuperChatCard QLabel#SuperChatName {{color:{header_text};font-size:{round(13 * self._scale)}px;}}"
            f"QFrame#SuperChatCard QLabel#SuperChatPrice {{color:{SC_PRICE_COLOR};font-size:{round((13 if self._collapsed else 15) * self._scale)}px;}}"
            f"QFrame#SuperChatCard QPushButton {{color:{header_text};}}"
            f"QFrame#SuperChatCard QLabel#SuperChatTime {{font-size:{round(11 * self._scale)}px;color:{header_text};}}"
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
        padding = math.ceil(SC_BODY_PADDING * scale)
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
        self.alpha = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.alpha)
        self.hide()

    def configure(self, settings):
        self._position = settings.get('super_chat_position' if settings.get('super_chat_position_sync', True)
                                      else 'super_chat_panel_position')
        self._enabled = bool(settings.get('super_chat_enabled', True))
        self._opacity = int(settings.get('super_chat_opacity', 80)) / 100
        self._scale = max(.75, min(2.0, int(settings.get('super_chat_scale', 100)) / 100))
        self.presentation.configure(settings)
        self._presentation_changed()

    def _presentation_changed(self):
        self.alpha.setOpacity(self._opacity * self.presentation.progress)
        if self._last_collapsed != frozenset(self.presentation.collapsed_ids):
            self._last_collapsed = frozenset(self.presentation.collapsed_ids)
            self.layoutChanged.emit()
        self.update()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            for index, card in enumerate(self._cards[:len(self._events)]):
                if watched is card.close_button:
                    return False
                if card is watched or card.isAncestorOf(watched):
                    if self.presentation.is_collapsed(self._events[index]):
                        self.presentation.expand(self._events[index]['id'])
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
            card = SuperChatCard(self)
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
        heights = [sc_card_height(event, self.width(), self._effective_scale, self.presentation.is_collapsed(event))
                   for event in self._events]
        rects = sc_stack_rects(self.width(), self.height(), len(self._events),
                               scale=self._effective_scale, card_heights=heights)
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

    def tick(self):
        for card, event in zip(self._cards, self._events):
            card.tick(event)


class DanmakuConnectionIcon(QLabel):
    """Keep the status text for accessibility while painting a Wi-Fi symbol."""

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setFixedSize(20, 20)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.translate(10, 10)
        painter.rotate(90)
        painter.translate(-10, -10)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(self.palette().color(QPalette.WindowText), 1.8,
                            Qt.SolidLine, Qt.RoundCap))
        for radius in (5, 9):
            painter.drawArc(QRectF(10 - radius, 15 - radius, radius * 2, radius * 2), 45 * 16, 90 * 16)
        painter.setBrush(self.palette().color(QPalette.WindowText))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QPointF(10, 15), 1.4, 1.4)


class DanmakuPanel(QFrame):
    """弹幕格：占画面墙里的一整格，风格和别的格子统一。

    内容是主画面那一路的弹幕（app.py 里的 sync_danmaku 负责连谁）。
    整格可以像别的窗口一样拖动，换到别的格子上。
    """

    superChatDismissed = Signal(str)

    MAX_BLOCKS = 3000         # 默认最多留多少条（设置里可改）
    MIN_BLOCKS = 20
    EMOTICON_HEIGHT = 22      # 表情在弹幕里的显示高度
    BASE_FONT_SIZE = 13       # 默认弹幕字号
    MIN_FONT_SIZE = 8
    MAX_FONT_SIZE = 32
    KIND_COLORS = {           # 不同消息的配色：弹幕蓝、礼物粉、上舰紫、SC 橙
        "danmaku": theme.ACCENT,
        "gift": theme.PINK,
        "guard": "#c084fc",
        "super_chat": theme.WARNING,
    }

    roomDropped = Signal(str)          # 有直播间被拖到弹幕格上
    fontSizeChanged = Signal(int)      # 面板上的字号滑块被拖动

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DanmakuPanel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAcceptDrops(True)
        self.setCursor(Qt.OpenHandCursor)
        self._status = "未接入"
        self._received = 0
        self._blocks: list[dict] = []            # 每条消息的原始信息，表情下好之后整体重排
        self._images: dict = {}                  # 表情图 / 粉丝牌底图：url -> 图片
        self._loading_emoticons: set[str] = set()
        self._emoticon_loaders: list = []
        self._has_content = False
        self._base_size = self.BASE_FONT_SIZE
        self._font_family = theme.danmaku_font_family()
        self.max_blocks = self.MAX_BLOCKS
        self._follow_tail = True
        self._scroll_dragging = False
        self._scroll_revision = 0
        self._scroll_restore_id = 0
        self._scroll_trim_remainder = 0.0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QWidget(self)
        self.header = header
        header.setObjectName("DanmakuHeader")
        header.setAttribute(Qt.WA_StyledBackground, True)
        header.setFixedHeight(32)
        header_box = QHBoxLayout(header)
        header_box.setContentsMargins(10, 0, 10, 0)
        header_box.setSpacing(6)
        dot = QLabel("●")
        dot.setObjectName("DanmakuDot")
        from .ui.labels import ElidedLabel
        title = ElidedLabel("弹幕")
        self.title = title
        title.setObjectName("DanmakuTitle")
        self.count = DanmakuConnectionIcon("未接入")
        self.count.setObjectName("DanmakuCount")
        self.count.setProperty("state", "idle")
        header_box.addWidget(dot)
        header_box.addWidget(title)
        self.font_controls = QWidget(header)
        self.font_controls.setFixedHeight(24)
        font_box = QHBoxLayout(self.font_controls)
        font_box.setContentsMargins(0, 0, 0, 0)
        font_box.setSpacing(6)
        self.font_slider = QSlider(Qt.Horizontal)
        self.font_slider.setRange(self.MIN_FONT_SIZE, self.MAX_FONT_SIZE)
        self.font_slider.setMinimumWidth(12)
        self.font_slider.setMaximumWidth(96)
        self.font_slider.setFixedHeight(20)
        self.font_slider.setValue(self._base_size)
        self.font_slider.setToolTip("拖一下就能改弹幕字号，直接生效")
        self.font_slider.setAccessibleName("弹幕字号")
        self.font_slider.valueChanged.connect(self._on_font_slider)
        font_box.addWidget(self.font_slider, 0, Qt.AlignVCenter)
        self.font_value = QLabel(str(self._base_size))
        self.font_value.setObjectName("DanmakuBarValue")
        self.font_value.setFixedWidth(22)
        self.font_value.setFixedHeight(20)
        self.font_value.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        font_box.addWidget(self.font_value, 0, Qt.AlignVCenter)
        header_box.addWidget(self.font_controls, 0, Qt.AlignVCenter)
        header_box.addStretch(1)
        header_box.addWidget(self.count, 0, Qt.AlignVCenter)
        layout.addWidget(header)

        self.body = DanmakuTextBrowser(self)
        self.body.setObjectName("DanmakuBody")
        self.body.setFrameShape(QFrame.NoFrame)
        self.body.setOpenExternalLinks(False)
        self.body.document().setDocumentMargin(8)
        self.body.document().setMaximumBlockCount(self.max_blocks)
        self.body.userScrolled.connect(self._on_user_scroll)
        self.body.messageClicked.connect(self._message_clicked)
        scroll_bar = self.body.verticalScrollBar()
        scroll_bar.sliderPressed.connect(self._on_scroll_pressed)
        scroll_bar.sliderReleased.connect(self._on_scroll_released)
        scroll_bar.valueChanged.connect(self._on_scroll_value_changed)
        layout.addWidget(self.body, 1)
        self.super_chats = SuperChatStack(self)
        self.super_chats.layoutChanged.connect(self._sync_super_chat_limit)
        self.super_chats.dismissed.connect(self.superChatDismissed)

        self.bottom_button = DanmakuBottomButton(self.body.viewport())
        self.bottom_button.clicked.connect(self.jump_to_bottom)
        self.bottom_button.hide()
        self.body.viewport().installEventFilter(self)
        self.composer_bar = QWidget(self)
        self.composer_bar.setObjectName("DanmakuBar")
        self.composer_bar.setAttribute(Qt.WA_StyledBackground, True)
        self.composer_bar.setFixedHeight(TILE_BAR_HEIGHT)
        composer_layout = QHBoxLayout(self.composer_bar)
        composer_layout.setContentsMargins(8, 4, 8, 4)
        self.composer_bar.hide()
        layout.addWidget(self.composer_bar)
        self._tile_controls = None
        self.apply_style()
        self._sync_super_chat_limit()
        self.set_placeholder("把直播间放到主画面，这里就会显示它的弹幕")

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._layout_header()
        if self._tile_controls is not None:
            self._tile_controls.layout_panel()
        self._sync_super_chat_limit()

    def _layout_header(self) -> None:
        box = self.header.layout()
        margins = box.contentsMargins()
        minimum = self.font_slider.minimumWidth() + self.font_value.width() + 6
        used = (margins.left() + margins.right() + 4 * box.spacing()
                + sum(box.itemAt(i).widget().sizeHint().width() for i in (0, 1))
                + self.count.width())
        self.font_controls.setMaximumWidth(max(minimum, min(124, self.width() - used)))

    def eventFilter(self, watched, event):
        if watched is self.body.viewport() and event.type() == QEvent.Resize:
            self._position_bottom_button()
            self._sync_super_chat_limit()
        return super().eventFilter(watched, event)

    def _position_bottom_button(self):
        viewport = self.body.viewport()
        self.bottom_button.move(max(0, viewport.width() - self.bottom_button.width() - 10),
                                max(0, viewport.height() - self.bottom_button.height() - 10))
        self.bottom_button.raise_()

    # ---- 拖动 ----
    def mousePressEvent(self, event) -> None:
        self._press_pos = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if not (event.buttons() & Qt.LeftButton):
            return
        start = getattr(self, "_press_pos", None)
        if start is None or (event.pos() - start).manhattanLength() < QApplication.startDragDistance():
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(DANMAKU_MIME, b"1")
        if self.property("paneCell") is not None:
            mime.setData("application/x-ddm-danmaku-cell", str(self.property("paneCell")).encode())
        mime.setText("弹幕")
        drag.setMimeData(mime)
        drag.exec(Qt.MoveAction)

    def dragEnterEvent(self, event) -> None:
        if (event.mimeData().hasFormat(ROOM_MIME) or event.mimeData().hasFormat(TILE_MIME)
                or event.mimeData().hasFormat(DANMAKU_MIME)):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        if event.mimeData().hasFormat(DANMAKU_MIME):
            return
        source = ""
        if event.mimeData().hasFormat(ROOM_MIME):
            source = bytes(event.mimeData().data(ROOM_MIME)).decode("utf-8", "ignore")
        elif event.mimeData().hasFormat(TILE_MIME):
            source = bytes(event.mimeData().data(TILE_MIME)).decode("utf-8", "ignore")
        if source:
            event.acceptProposedAction()
            self.roomDropped.emit(source)

    # ---- 内容 ----
    def _message_clicked(self, index, position):
        if not 0 <= index < len(self._blocks):
            return
        self._scroll_revision += 1
        self._scroll_trim_remainder = 0.0
        self._follow_tail = False
        self._update_bottom_button()
        from .danmaku_actions import show_comment_menu
        self.body._action_block = self.body.document().findBlockByNumber(index)
        self.body.viewport().update()
        def finished():
            self.body._action_block = None
            self.body._hover_at(QPointF(self.body.viewport().mapFromGlobal(QCursor.pos())))
        show_comment_menu(self, self._blocks[index],
                          getattr(self, "_linked_controls", None) or self._tile_controls, position, finished)

    def set_placeholder(self, text: str) -> None:
        self.set_super_chats([])
        self._scroll_revision += 1
        self._scroll_trim_remainder = 0.0
        self._blocks = []
        self._has_content = False
        self._received = 0
        self._status = "未接入"
        self._follow_tail = True
        self._refresh_count()
        color = "#5e6a7d" if theme.is_light() else "#8a8f98"
        self.body.setHtml(
            f'<div style="color:{color};line-height:160%">{text}</div>')
        self._update_bottom_button()

    def set_status(self, text: str) -> None:
        """连接状态（连接中… / 已连接 / 连接失败…）。"""
        self._status = text
        self._refresh_count()
        if text == "已连接" and not self._has_content:
            color = "#5e6a7d" if theme.is_light() else "#8a8f98"
            self.body.setHtml(f'<div style="color:{color};line-height:160%">等待弹幕…</div>')

    def set_count(self, text: str) -> None:
        self._status = text
        self._refresh_count()

    def _refresh_count(self) -> None:
        text = self._status
        if self._status.startswith("已连接"):
            state = "connected"
        elif any(word in self._status for word in ("连接中", "重连中", "准备重连", "切换服务器")):
            state = "connecting"
        elif self._status in ("未接入", "未关联"):
            state = "idle"
        else:
            state = "error"
        if self.count.property("state") != state:
            self.count.setProperty("state", state)
            _repolish(self.count)
        self.count.setText(text)
        self.count.setToolTip(text)
        self.count.setAccessibleName('弹幕连接状态：' + text)
        self.count.update()
        self._layout_header()

    def add_message(self, uname: str, text: str, color: str = "#00a1d6") -> None:
        """直接给文本的简写（预览、自检用）。"""
        self.add_event({"kind": "danmaku", "uname": uname, "text": text, "color": color})

    def add_event(self, event: dict) -> None:
        """一条消息：带粉丝牌、表情（表情图下好之后会补上）。"""
        entry = {
            "uname": event.get("uname") or "",
            "text": event.get("text") or "",
            "color": event.get("color") or self.KIND_COLORS.get(
                event.get("kind") or "danmaku", theme.ACCENT),
            "medal": event.get("medal") or {},
            "emoticon": event.get("emoticon") or "",
            "dm_type": event.get("dm_type", 0),
            "emoticon_unique": event.get("emoticon_unique") or "",
            "emoticons": event.get("emoticons") or {},
            "self_sent": bool(event.get("self_sent")),
        }
        self._received += 1
        self._refresh_count()
        for _, url in content_runs(entry):
            if url:
                self._ensure_emoticon(url)
        self._blocks.append(entry)
        removed = max(0, len(self._blocks) - self.max_blocks)
        scroll_state = self._scroll_state(removed)
        if removed:
            self._blocks = self._blocks[-self.max_blocks:]
        block = self._block_html(entry)
        if self._has_content:
            self.body.append(block)
        else:
            self.body.setHtml(block)              # 第一条：先把占位文字换掉
            self._has_content = True
        self._restore_scroll_state(scroll_state)

    def set_super_chats(self, events: list[dict]) -> None:
        self.super_chats.set_events(events, self._super_chat_limit())
        self._sync_super_chat_limit()

    def _super_chat_limit(self):
        return 1 if self.body.viewport().height() >= 76 else 0

    def apply_super_chat_settings(self, settings):
        self.super_chats.configure(settings)
        self._sync_super_chat_limit()

    def _sync_super_chat_limit(self):
        if any(card._paper is not None for card in self.super_chats._cards):
            return
        viewport = self.body.viewport()
        rects, scale = sc_placement_rects(
            self.super_chats._events, viewport.width(), viewport.height(),
            self.super_chats._scale, self.super_chats._position, panel=True,
            collapsed=self.super_chats.presentation.is_collapsed)
        if not rects:
            return
        bounds = QRectF(rects[0])
        for rect in rects[1:]:
            bounds = bounds.united(rect)
        bounds = bounds.toAlignedRect()
        self.super_chats._effective_scale = scale
        self.super_chats.resize(bounds.size())
        self.super_chats.move(self.body.mapTo(self, viewport.pos()) + bounds.topLeft())
        self.super_chats.set_events(self.super_chats._events, self._super_chat_limit())
        self.super_chats.raise_()

    def _scroll_state(self, removed_blocks: int = 0) -> tuple[bool, int, int]:
        scroll_bar = self.body.verticalScrollBar()
        value = scroll_bar.value()
        if removed_blocks and not self._follow_tail:
            document = self.body.document()
            remaining = document.findBlockByNumber(removed_blocks)
            if remaining.isValid():
                layout = document.documentLayout()
                removed_height = (layout.blockBoundingRect(remaining).top()
                                  - layout.blockBoundingRect(document.firstBlock()).top())
                # 字体行高可能有小数，逐条取整会让阅读位置不断漂移。
                offset = removed_height + self._scroll_trim_remainder
                pixels = round(offset)
                self._scroll_trim_remainder = offset - pixels
                value = max(0, value - pixels)
        return self._follow_tail, value, self._scroll_revision

    def _restore_scroll_state(self, state: tuple[bool, int, int]) -> None:
        """内容更新不能打断用户阅读；仍在末尾时才继续跟随。"""
        follow_tail, value, revision = state
        self._follow_tail = follow_tail
        self._scroll_restore_id += 1
        restore_id = self._scroll_restore_id

        def restore() -> None:
            if (not isValid(self) or revision != self._scroll_revision
                    or restore_id != self._scroll_restore_id):
                return
            scroll_bar = self.body.verticalScrollBar()
            if self._follow_tail:
                scroll_bar.setValue(scroll_bar.maximum())
            else:
                scroll_bar.setValue(min(value, scroll_bar.maximum()))

        restore()
        # QTextDocument 可能到下一轮事件循环才完成重新排版，再校正一次。
        QTimer.singleShot(0, restore)

    def jump_to_bottom(self) -> None:
        self._scroll_revision += 1
        self._scroll_trim_remainder = 0.0
        self._follow_tail = True
        self._scroll_to_bottom()
        self._update_bottom_button()

    def _update_bottom_button(self) -> None:
        self.bottom_button.setVisible(not self._follow_tail and self._has_content)
        self._position_bottom_button()

    def _scroll_to_bottom(self) -> None:
        if not self._follow_tail:
            return
        scroll_bar = self.body.verticalScrollBar()
        scroll_bar.setValue(scroll_bar.maximum())

    def _at_scroll_tail(self) -> bool:
        scroll_bar = self.body.verticalScrollBar()
        return scroll_bar.value() >= scroll_bar.maximum() - 1

    def _on_user_scroll(self) -> None:
        """用户滚轮/键盘查看旧内容时暂停自动跟随；回到底部后恢复。"""
        self._scroll_revision += 1
        self._scroll_trim_remainder = 0.0
        self._follow_tail = self._at_scroll_tail()
        self._update_bottom_button()

    def _on_scroll_pressed(self) -> None:
        self._scroll_revision += 1
        self._scroll_trim_remainder = 0.0
        self._scroll_dragging = True

    def _on_scroll_released(self) -> None:
        self._scroll_dragging = False
        self._follow_tail = self._at_scroll_tail()
        self._update_bottom_button()

    def _on_scroll_value_changed(self, _value: int) -> None:
        if self._scroll_dragging:
            self._follow_tail = self._at_scroll_tail()
            self._update_bottom_button()

    # ---- 渲染 ----
    def refresh_theme(self) -> None:
        self._layout_header()
        if self._blocks:
            self._render_all()
        else:
            old, new = ("#8a8f98", "#5e6a7d") if theme.is_light() else ("#5e6a7d", "#8a8f98")
            self.body.setHtml(self.body.toHtml().replace(old, new))

    def apply_style(self, font_family: str = "", font_size: int = BASE_FONT_SIZE) -> None:
        """设置里的字体和字号（字号也能在底部滑块上实时拖）。"""
        self._font_family = font_family or theme.danmaku_font_family()
        self._base_size = max(self.MIN_FONT_SIZE,
                              min(self.MAX_FONT_SIZE, int(font_size or self.BASE_FONT_SIZE)))
        font = QFont(self._font_family)
        font.setPixelSize(self._base_size)
        self.body.setFont(font)          # 具体字号在 HTML 里，这里给个底
        self.font_slider.blockSignals(True)
        self.font_slider.setValue(self._base_size)
        self.font_slider.blockSignals(False)
        self.font_value.setText(str(self._base_size))
        if self._blocks:
            self._render_all()

    def _font_size(self) -> int:
        return self._base_size

    def set_max_blocks(self, count: int) -> None:
        """最多留多少条弹幕：超了就从最早的那条开始丢。"""
        try:
            value = int(count)
        except (TypeError, ValueError):
            value = self.MAX_BLOCKS
        self.max_blocks = max(self.MIN_BLOCKS, value)
        scroll_state = self._scroll_state(max(0, len(self._blocks) - self.max_blocks))
        if len(self._blocks) > self.max_blocks:
            self._blocks = self._blocks[-self.max_blocks:]
        self.body.document().setMaximumBlockCount(self.max_blocks)
        self._restore_scroll_state(scroll_state)

    def _on_font_slider(self, value: int) -> None:
        """面板上拖字号：立刻重排，并通知外面存进配置。"""
        self._base_size = int(value)
        self.font_value.setText(str(self._base_size))
        if self._blocks:
            self._render_all()
        self.fontSizeChanged.emit(self._base_size)

    def _block_html(self, entry: dict) -> str:
        size = self._font_size()
        color = "#202630" if theme.is_light() else "#e6e9ee"
        name = (f'<span style="color:{entry["color"]}">{_escape(entry["uname"])}</span>')
        mark = (f'<span style="color:{theme.PINK};font-weight:700">▍</span> '
                if entry.get("self_sent") else "")
        return (f'<div style="font-size:{size}px;line-height:150%;margin:0 0 4px 0">'
                f'{mark}{self._medal_html(entry["medal"])}{name}'
                f'<span style="color:{color}">：{self._body_html(entry)}</span></div>')

    def _body_html(self, entry: dict) -> str:
        height = max(self.EMOTICON_HEIGHT // 2, round(self._font_size() * 1.7))
        return content_html(content_runs(entry), self._images, height)

    def _medal_html(self, medal: dict) -> str:
        """粉丝牌：有颜色就画成圆角小色块（图片），没有就退化成[名字等级]。"""
        name = str(medal.get("name") or "")
        if not name:
            return ""
        level = str(medal.get("level") or "")
        color = str(medal.get("color") or "")
        if not color:
            return f'<span style="color:#c792ea">[{_escape(name)}{_escape(level)}]</span>&#160;'
        size = self._font_size()
        key = f"medal:{name}|{level}|{color}|{size}"
        if key not in self._images:
            self._images[key] = _medal_chip(name, level, color, size)
        chip = self._images[key]
        self._register_image(key, chip)          # 不注册的话新到的弹幕会画成白块
        return (f'<img src="{key}" width="{chip.width()}" height="{chip.height()}">&#160;')

    def _register_image(self, key: str, image) -> None:
        """把图片挂到文本文档上，这样富文本里的 <img> 才画得出来。"""
        self.body.document().addResource(QTextDocument.ImageResource, QUrl(key), image)

    def _render_all(self) -> None:
        """整体重排（表情图下好、或者字体变化时用）。"""
        scroll_state = self._scroll_state()
        html = "".join(self._block_html(entry) for entry in self._blocks)
        self.body.setHtml(html or "")
        for url, image in self._images.items():       # 图片按 url 注册成文档资源
            self._register_image(url, image)
        self._has_content = bool(self._blocks)
        self._restore_scroll_state(scroll_state)

    # ---- 表情 ----
    def _ensure_emoticon(self, url: str) -> None:
        if url in self._images or url in self._loading_emoticons:
            return
        self._loading_emoticons.add(url)
        loader = AvatarLoader({url: url}, self, subdir="emoticons")
        loader.loaded.connect(self._on_emoticon_loaded)
        loader.finished.connect(lambda: self._loading_emoticons.discard(url))
        loader.finished.connect(loader.deleteLater)
        self._emoticon_loaders = [item for item in self._emoticon_loaders
                                  if _is_running(item)]
        self._emoticon_loaders.append(loader)
        loader.start()

    def _on_emoticon_loaded(self, url: str, pixmap) -> None:
        self._loading_emoticons.discard(url)
        image = pixmap.toImage()
        if image.isNull():
            return
        self._images[url] = image
        self._render_all()          # 之前显示成文字的那些，现在换成图

    def clear(self) -> None:
        self.set_placeholder("等待主画面的直播间…")

    def set_sample(self, messages: list[tuple[str, str, str]]) -> None:
        """预览用：塞几条示例弹幕，看看排版效果。"""
        for uname, text, color in messages:
            self.add_message(uname, text, color)


def _escape(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
