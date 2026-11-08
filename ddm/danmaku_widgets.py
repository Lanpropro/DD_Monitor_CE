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
from .super_chat_model import SC_BODY_PADDING, SC_CONTENT_COLOR, SC_PRICE_COLOR, SC_USER_COLOR, format_price, format_remaining, order_super_chats, remaining_seconds, super_chat_palette
from .super_chat_presentation import SuperChatAvatar, SuperChatPresentation, paint_sc_avatar, paint_sc_background, sc_card_height, sc_placement_rects, sc_stack_rects
from .widget_support import DANMAKU_MIME, TILE_BAR_HEIGHT, TILE_MIME, _repolish


from .danmaku_format import (_brightness, _medal_chip, _escape)


def _is_running(thread) -> bool:
    """QThread 已经被 Qt 回收时也算没在跑。"""
    try:
        return thread.isRunning()
    except RuntimeError:
        return False


class DanmakuTextBrowser(QTextBrowser):
    """能告诉面板“用户正在查看旧弹幕”的文本区。"""

    userScrolled = Signal()
    viewportScrolled = Signal()
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
        self.viewportScrolled.emit()
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


from .super_chat_widgets import (SuperChatAvatarView, SuperChatMessage, SuperChatCard, SuperChatStack)
from .danmaku_document import DanmakuDocument
from .danmaku_scrolling import DanmakuScrolling


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
        self.scroll_control = DanmakuScrolling(self)
        self.document_control = DanmakuDocument(self)
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
        self.body.viewportScrolled.connect(self._position_bottom_button)
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
        return self.document_control.add_message(uname, text, color)

    def add_event(self, event: dict) -> None:
        """一条消息：带粉丝牌、表情（表情图下好之后会补上）。"""
        return self.document_control.add_event(event)

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
        return self.scroll_control.scroll_state(removed_blocks)

    def _restore_scroll_state(self, state: tuple[bool, int, int]) -> None:
        """内容更新不能打断用户阅读；仍在末尾时才继续跟随。"""
        return self.scroll_control.restore_scroll_state(state)

    def jump_to_bottom(self) -> None:
        return self.scroll_control.jump_to_bottom()

    def _update_bottom_button(self) -> None:
        return self.scroll_control.update_bottom_button()

    def _scroll_to_bottom(self) -> None:
        return self.scroll_control.scroll_to_bottom()

    def _at_scroll_tail(self) -> bool:
        return self.scroll_control.at_scroll_tail()

    def _on_user_scroll(self) -> None:
        """用户滚轮/键盘查看旧内容时暂停自动跟随；回到底部后恢复。"""
        return self.scroll_control.on_user_scroll()

    def _on_scroll_pressed(self) -> None:
        return self.scroll_control.on_scroll_pressed()

    def _on_scroll_released(self) -> None:
        return self.scroll_control.on_scroll_released()

    def _on_scroll_value_changed(self, _value: int) -> None:
        return self.scroll_control.on_scroll_value_changed(_value)

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
        return self.document_control.apply_style(font_family, font_size)

    def _font_size(self) -> int:
        return self.document_control.font_size()

    def set_max_blocks(self, count: int) -> None:
        """最多留多少条弹幕：超了就从最早的那条开始丢。"""
        return self.document_control.set_max_blocks(count)

    def _on_font_slider(self, value: int) -> None:
        """面板上拖字号：立刻重排，并通知外面存进配置。"""
        return self.document_control.on_font_slider(value)

    def _block_html(self, entry: dict) -> str:
        return self.document_control.block_html(entry)

    def _body_html(self, entry: dict) -> str:
        return self.document_control.body_html(entry)

    def _medal_html(self, medal: dict) -> str:
        """粉丝牌：有颜色就画成圆角小色块（图片），没有就退化成[名字等级]。"""
        return self.document_control.medal_html(medal)

    def _register_image(self, key: str, image) -> None:
        """把图片挂到文本文档上，这样富文本里的 <img> 才画得出来。"""
        return self.document_control.register_image(key, image)

    def _render_all(self) -> None:
        """整体重排（表情图下好、或者字体变化时用）。"""
        return self.document_control.render_all()

    # ---- 表情 ----
    def _ensure_emoticon(self, url: str) -> None:
        return self.document_control.ensure_emoticon(url, loader_type=AvatarLoader, thread_running=_is_running)

    def _on_emoticon_loaded(self, url: str, pixmap) -> None:
        return self.document_control.on_emoticon_loaded(url, pixmap)

    def clear(self) -> None:
        return self.document_control.clear()

    def set_sample(self, messages: list[tuple[str, str, str]]) -> None:
        """预览用：塞几条示例弹幕，看看排版效果。"""
        return self.document_control.set_sample(messages)
