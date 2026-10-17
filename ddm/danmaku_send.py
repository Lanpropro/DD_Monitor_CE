"""B 站逐房间弹幕输入与表情选择；网络请求在后台执行。"""
import requests
from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QIcon, QPainter, QPen
from PySide6.QtWidgets import (
    QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton,
    QScrollArea, QSizePolicy, QToolButton, QVBoxLayout, QWidget, QWidgetAction,
)

from . import bili, theme
from .images import AvatarLoader


class EmoteButton(QPushButton):
    """表情入口：和底栏的暂停/刷新图标一样自己画，不用字形（字形大小对不齐）。"""

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        color = theme.icon_color(self)
        pen = QPen(color, 1.7)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        center = QPointF(self.width() / 2.0, self.height() / 2.0)
        radius = min(self.width(), self.height()) / 2 - 4.0
        face = QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2)
        painter.drawEllipse(face)
        eye = max(1.0, radius * 0.15)
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        for offset in (-radius * 0.36, radius * 0.36):
            painter.drawEllipse(QPointF(center.x() + offset, center.y() - radius * 0.24),
                                eye, eye)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        mouth = QRectF(center.x() - radius * 0.52, center.y() - radius * 0.12,
                       radius * 1.04, radius * 0.9)
        painter.drawArc(mouth, 200 * 16, 140 * 16)


# 关闭格子/浮窗不销毁仍在执行网络请求的线程；Qt 自动断开已销毁接收者。
_active_requests: set[QThread] = set()


def _start(worker):
    _active_requests.add(worker)
    worker.finished.connect(lambda: _active_requests.discard(worker))
    worker.finished.connect(worker.deleteLater)
    worker.start()


def _style_button(button, *, primary=False):
    # 发送按钮用本地主色按钮的样式，其余沿用底栏 TileCtrl 的透明按钮观感；
    # 样式统一由 theme.qss 提供，不在控件上重设局部样式（主题切换护栏会统计次数）。
    button.setObjectName("PrimaryButton" if primary else "TileCtrl")
    button.setCursor(Qt.PointingHandCursor)
    button.setAutoDefault(False)


class _Request(QThread):
    completed = Signal(object, object)
    failed = Signal(object, str)

    def __init__(self, context, task, *, timeout_message="请求超时，请稍后重试"):
        super().__init__()
        self.context, self.task = context, task
        self.timeout_message = timeout_message

    def run(self):
        try:
            result = self.task()
        except requests.Timeout:
            self.failed.emit(self.context, self.timeout_message)
        except requests.RequestException:
            self.failed.emit(self.context, "网络请求失败，请检查网络后重试")
        except Exception as error:  # noqa: BLE001
            self.failed.emit(self.context, str(error) or "请求失败，请重试")
        else:
            self.completed.emit(self.context, result)


class DanmakuEdit(QLineEdit):
    """输入时接管单键快捷键，中文选词回车不触发发送。"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._composing = False

    def event(self, event):
        if event.type() == QEvent.ShortcutOverride and not (
                event.modifiers() & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier)):
            event.accept()
            return True
        return super().event(event)

    def inputMethodEvent(self, event):
        self._composing = bool(event.preeditString())
        super().inputMethodEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and self._composing:
            event.accept()
            return
        if event.key() == Qt.Key_Escape:
            self.clearFocus()
            event.accept()
            return
        super().keyPressEvent(event)


class EmoticonPopup(QMenu):
    selected = Signal(int, dict)
    retryRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("EmoticonPopup")
        holder = QWidget(self)
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(8, 8, 8, 8)
        header = QHBoxLayout()
        self.status = QLabel("正在加载表情…")
        self.status.setWordWrap(True)
        header.addWidget(self.status, 1)
        self.retry_button = QPushButton("重试")
        _style_button(self.retry_button)
        self.retry_button.setFixedSize(48, theme.TILE_CONTROL_HEIGHT)
        self.retry_button.setToolTip("重新获取当前直播间的表情列表")
        self.retry_button.clicked.connect(self.retryRequested)
        self.retry_button.hide()
        header.addWidget(self.retry_button)
        layout.addLayout(header)
        # 表情包分类：一行小图标，点哪个显示哪个包（和 B 站播放器的表情面板一样）。
        self.tab_scroll = QScrollArea()
        self.tab_scroll.setWidgetResizable(True)
        self.tab_scroll.setFrameShape(QScrollArea.NoFrame)
        self.tab_scroll.setFixedHeight(38)
        self.tab_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tab_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.tab_bar = QWidget()
        self.tab_layout = QHBoxLayout(self.tab_bar)
        self.tab_layout.setContentsMargins(0, 0, 0, 0)
        self.tab_layout.setSpacing(4)
        self.tab_layout.setAlignment(Qt.AlignLeft)
        self.tab_scroll.setWidget(self.tab_bar)
        self.tab_scroll.hide()
        layout.addWidget(self.tab_scroll)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        layout.addWidget(self.scroll, 1)
        self._images = {}
        self._tab_images = {}
        self._packages = []
        self._clear_body()
        action = QWidgetAction(self)
        action.setDefaultWidget(holder)
        self.addAction(action)
        self._holder = holder
        self._holder.setFixedSize(340, 300)

    def _clear_body(self):
        body = QWidget()
        self.grid = QGridLayout(body)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(4)
        self.grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.scroll.setWidget(body)
        self._images = {}

    def _clear_tabs(self):
        while self.tab_layout.count():
            item = self.tab_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def set_loading(self):
        self._clear_body()
        self._clear_tabs()
        self.tab_scroll.hide()
        self.status.setText("正在加载表情…")
        self.status.show()
        self.retry_button.setText("刷新")
        self.retry_button.setEnabled(False)
        self.retry_button.show()

    def set_error(self, message):
        self.status.setText(message)
        self.status.show()
        self.retry_button.setText("重试")
        self.retry_button.setEnabled(True)
        self.retry_button.show()

    def set_packages(self, packages):
        self._clear_body()
        self._clear_tabs()
        self._tab_images = {}
        self._packages = [package for package in packages
                          if isinstance(package, dict)
                          and package.get("pkg_type") in (1, 2, 3, 5)
                          and isinstance(package.get("emoticons"), list)]
        self.retry_button.setText("刷新")
        self.retry_button.setEnabled(True)
        self.retry_button.show()
        if not self._packages:
            self.tab_scroll.hide()
            self.status.setText("暂无可用表情")
            self.status.show()
            return
        for index, package in enumerate(self._packages):
            tab = QToolButton()
            tab.setObjectName("EmoticonTab")
            tab.setCheckable(True)
            tab.setAutoExclusive(True)
            tab.setFixedSize(32, 30)
            tab.setIconSize(QSize(22, 22))
            tab.setToolTip(str(package.get("pkg_name") or "表情"))
            tab.setAccessibleName(tab.toolTip())
            tab.setCursor(Qt.PointingHandCursor)
            tab.clicked.connect(lambda _checked=False, i=index: self._show_package(i))
            self.tab_layout.addWidget(tab)
            first = next((emote for emote in package.get("emoticons") or []
                          if isinstance(emote, dict)), None)
            url = (first or {}).get("url")
            if isinstance(url, str) and url.startswith(("https://", "http://")):
                self._tab_images.setdefault(url, []).append(tab)
            else:
                tab.setText(str(package.get("pkg_name") or "表")[:1])
        self.tab_layout.addStretch(1)
        self.tab_scroll.show()
        if self._tab_images:
            # 分类图标一次取齐，不用等逐个点开才显示
            loader = AvatarLoader({url: url for url in self._tab_images}, subdir="emoticons")
            loader.loaded.connect(self._image_loaded)
            _start(loader)
        self._show_package(0)

    def _show_package(self, index):
        """只摆当前选中的表情包，左上角那排图标负责切换。"""
        if not 0 <= index < len(self._packages):
            return
        package = self._packages[index]
        kind = package.get("pkg_type")
        tabs = [self.tab_layout.itemAt(i).widget() for i in range(self.tab_layout.count())
                if self.tab_layout.itemAt(i).widget() is not None]
        if index < len(tabs):
            tabs[index].setChecked(True)
        self._clear_body()
        urls = {}
        row, column, count = 0, 0, 0
        for emote in package.get("emoticons") or []:
            if not isinstance(emote, dict):
                continue
            text = str(emote.get("emoji") or "表情")
            button = QToolButton()
            button.setText(text)
            button.setAccessibleName(text)
            button.setObjectName("EmoticonButton")
            button.setFixedSize(56, 56)
            button.setIconSize(QSize(32, 32))
            button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            button.setCursor(Qt.PointingHandCursor)
            available = emote.get("perm") == 1 and bool(emote.get(
                "emoji" if kind == 3 else "emoticon_unique"))
            button.setEnabled(available)
            button.setToolTip(text if available else
                              f"{text}：{emote.get('unlock_show_text') or '当前账号尚未解锁'}")
            button.clicked.connect(lambda _checked=False, k=kind, e=dict(emote): self._choose(k, e))
            self.grid.addWidget(button, row, column)
            url = emote.get("url")
            if isinstance(url, str) and url.startswith(("https://", "http://")):
                self._images.setdefault(url, []).append(button)
                urls[url] = url
            count += 1
            column += 1
            if column == 5:
                row, column = row + 1, 0
        self.status.setText(str(package.get("pkg_name") or "表情") if count else "暂无可用表情")
        self.status.show()
        if urls:
            loader = AvatarLoader(urls, subdir="emoticons")
            loader.loaded.connect(self._image_loaded)
            _start(loader)

    def _image_loaded(self, url, pixmap):
        icon = QIcon(pixmap)
        for button in self._images.get(url, []):
            button.setIcon(icon)
        for tab in self._tab_images.get(url, []):
            tab.setIcon(icon)

    def _choose(self, kind, emote):
        self.hide()
        self.selected.emit(kind, emote)

    def open_at(self, button):
        screen = button.screen().availableGeometry()
        self._holder.setFixedSize(min(340, screen.width() - 16), min(300, screen.height() - 16))
        self.adjustSize()
        anchor = button.mapToGlobal(QPoint(button.width(), 0))
        x = max(screen.left(), min(anchor.x() - self.width(), screen.right() - self.width() + 1))
        y = anchor.y() - self.height() - 6
        if y < screen.top():
            y = button.mapToGlobal(button.rect().bottomLeft()).y() + 6
        self.popup(QPoint(x, max(screen.top(), min(y, screen.bottom() - self.height() + 1))))


class DanmakuComposer(QWidget):
    HEIGHT = theme.TILE_CONTROL_HEIGHT
    """与底栏其它按钮同高，输入区嵌在同一条信息条里。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DanmakuComposer")
        self.setCursor(Qt.ArrowCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumWidth(0)
        self.setFixedHeight(self.HEIGHT)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._room_id = ""
        self._generation = self._revision = 0
        self._pending = self._catalog_pending = None
        self._catalog_key = None
        self._packages = None
        self.popup = None
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(4)
        self.edit = DanmakuEdit()
        self.edit.setAccessibleName("发送到当前直播间的弹幕")
        self.edit.setPlaceholderText("输入弹幕，Enter 发送")
        self.edit.setMinimumWidth(0)
        self.edit.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.edit.setFixedHeight(self.HEIGHT)
        self.edit.textChanged.connect(self._text_changed)
        self.edit.returnPressed.connect(self.send_text)
        row.addWidget(self.edit, 1)
        self.emote_button = EmoteButton()
        self.emote_button.setAccessibleName("选择直播间表情")
        self.emote_button.setToolTip("选择表情；大表情点击后直接发送")
        self.emote_button.setFixedSize(self.HEIGHT, self.HEIGHT)
        self.emote_button.clicked.connect(self.open_emoticons)
        self.emote_button.setObjectName("TileCtrl")
        self.emote_button.setCursor(Qt.PointingHandCursor)
        self.emote_button.setAutoDefault(False)
        row.addWidget(self.emote_button)
        self.send_button = QPushButton("发送")
        self.send_button.setObjectName("PrimaryButton")
        self.send_button.setFixedSize(52, self.HEIGHT)
        self.send_button.clicked.connect(self.send_text)
        self.send_button.setCursor(Qt.PointingHandCursor)
        self.send_button.setAutoDefault(False)
        row.addWidget(self.send_button)
        self.feedback = QLabel("", self, Qt.ToolTip)
        self.feedback.setObjectName("DanmakuSendFeedback")
        self.feedback.setAttribute(Qt.WA_ShowWithoutActivating)
        self.feedback.setTextFormat(Qt.PlainText)
        self.feedback.setWordWrap(True)
        self.feedback.setMaximumWidth(380)
        self.feedback.setAccessibleName("弹幕发送状态")
        self.feedback.hide()
        # 没有主窗口可承接提示时，退回到浮动提示也要自己消失，不能一直挂着
        self._feedback_timer = QTimer(self)
        self._feedback_timer.setSingleShot(True)
        self._feedback_timer.setInterval(4000)
        self._feedback_timer.timeout.connect(self.feedback.hide)
        self._update_buttons()

    def mousePressEvent(self, event):
        # 点输入区的空白处也算点输入框：大格子收起时要靠这次点击展开。
        self.edit.setFocus(Qt.MouseFocusReason)
        super().mousePressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 小格保留输入和表情入口，回车仍可发送，不为单独按钮挤掉输入空间。
        self.send_button.setVisible(self.width() >= 144)
        # 显隐会弄脏布局：立刻重排，别让发送按钮停在上一个宽度的位置。
        self.layout().activate()

    def hideEvent(self, event):
        self.feedback.hide()
        if self.popup:
            self.popup.hide()
        super().hideEvent(event)

    @property
    def busy(self):
        return self._pending is not None

    @property
    def supported(self):
        return self._room_id.isascii() and self._room_id.isdigit() and int(self._room_id) > 0

    def set_room(self, room_id):
        room_id = str(room_id or "")
        if room_id != self._room_id:
            self._generation += 1
            self._room_id = room_id
            self._pending = self._catalog_pending = None
            self._packages = self._catalog_key = None
            self.edit.clear()
            self._feedback("")
            if self.popup:
                self.popup.hide()
        self.setVisible(self.supported)
        self._update_buttons()

    def _text_changed(self):
        self._revision += 1
        self.feedback.hide()
        self._update_buttons()

    def _update_buttons(self):
        self.send_button.setEnabled(bool(self.edit.text().strip()) and not self.busy)
        self.send_button.setText("…" if self.busy else "发送")

    def _context(self):
        return self._generation, self._room_id, bili._cookies()

    def send_text(self):
        if self.edit.text().strip():
            self._send(self.edit.text(), 0)

    def _send(self, message, dm_type):
        if self.busy or not self.supported:
            return
        cookies = bili._cookies()
        if not cookies.get("SESSDATA") or not cookies.get("bili_jct"):
            self._feedback("请先登录 B 站" if not cookies.get("SESSDATA") else
                           "登录缺少 bili_jct，请退出 B 站账号后重新登录")
            return
        context = (*self._context(), self._revision, dm_type)
        self._pending = context
        self._feedback("正在发送…")
        self._update_buttons()
        room_id = self._room_id
        worker = _Request(context, lambda: bili.send_danmaku(room_id, message, dm_type=dm_type, cookies=cookies),
                          timeout_message="发送请求超时，结果可能未确认，请确认后再试")
        worker.completed.connect(self._sent)
        worker.failed.connect(self._send_failed)
        _start(worker)

    def _feedback(self, text):
        self.feedback.setText(text)
        self.feedback.setToolTip(text)
        self.feedback.setAccessibleDescription(text)
        self.edit.setToolTip(text)
        self.feedback.hide()
        if not text or self.busy:
            return
        # 失败原因交给窗口顶部的提示条（会自动消失）；只有自检/预览这类
        # 没有主窗口的场景才退回到输入框上方的浮动提示。
        if self._notify_window(text):
            return
        if not self.isVisible():
            return
        self.feedback.adjustSize()
        anchor = self.edit.mapToGlobal(QPoint(0, 0))
        screen = self.screen().availableGeometry()
        x = max(screen.left(), min(anchor.x(), screen.right() - self.feedback.width() + 1))
        y = anchor.y() - self.feedback.height() - 4
        if y < screen.top():
            y = anchor.y() + self.edit.height() + 4
        self.feedback.move(x, min(y, screen.bottom() - self.feedback.height() + 1))
        self.feedback.show()
        self._feedback_timer.start()

    def _notify_window(self, message) -> bool:
        """把提示交给主窗口的顶部提示条；找不到宿主窗口就返回 False。"""
        window = self.window()
        show = getattr(window, "_show_notice", None)
        if not callable(show):
            return False
        try:
            show(message, kind="warning")
        except Exception:      # noqa: BLE001 - 顶部提示不可用时退回就地提示
            return False
        return True

    def _finish_send(self, context):
        if context != self._pending:
            return False
        self._pending = None
        self._update_buttons()
        if context[:3] != self._context():
            self._feedback("")
            return False
        return True

    def _sent(self, context, _result):
        if self._finish_send(context):
            if context[4] == 0 and context[3] == self._revision:
                self.edit.clear()
            self._feedback("")

    def _send_failed(self, context, error):
        if self._finish_send(context):
            self._feedback(error)

    def choose_emoticon(self, pkg_type, emote):
        if emote.get("perm") != 1:
            return
        if pkg_type == 3:
            self.edit.insert(str(emote.get("emoji") or ""))
        elif pkg_type in (1, 2, 5) and emote.get("emoticon_unique"):
            self._send(str(emote["emoticon_unique"]), 1)
        self.edit.setFocus(Qt.OtherFocusReason)

    def open_emoticons(self, _checked=False):
        self.feedback.hide()
        if not bili.SESSION_DATA:
            self._feedback("请先登录 B 站后选择表情")
            return
        if self.popup is None:
            self.popup = EmoticonPopup(self)
            self.popup.selected.connect(self.choose_emoticon)
            self.popup.retryRequested.connect(self._reload_emoticons)
        self.popup.open_at(self.emote_button)
        context = self._context()
        if self._catalog_key == context and self._packages is not None:
            return
        if self._catalog_pending == context:
            return
        self.popup.set_loading()
        self._catalog_pending = context
        room_id, cookies = self._room_id, bili._cookies()
        worker = _Request(context, lambda: bili.get_emoticons(room_id, cookies=cookies))
        worker.completed.connect(self._emoticons_loaded)
        worker.failed.connect(self._emoticons_failed)
        _start(worker)

    def _reload_emoticons(self):
        self._catalog_key = None
        self.open_emoticons()

    def _emoticons_loaded(self, context, packages):
        if context != self._context():
            return
        self._catalog_pending = None
        self._catalog_key, self._packages = context, packages
        self.popup.set_packages(packages)

    def _emoticons_failed(self, context, error):
        if context != self._context():
            return
        self._catalog_pending = None
        self.popup.set_error(error)
