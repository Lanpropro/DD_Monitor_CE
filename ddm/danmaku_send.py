"""B 站逐房间弹幕输入与表情选择；网络请求在后台执行。"""
import requests
from PySide6.QtCore import QEvent, QPoint, QSize, Qt, QThread, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton,
    QScrollArea, QToolButton, QVBoxLayout, QWidget, QWidgetAction,
)

from . import bili, theme
from .images import AvatarLoader


# 关闭格子/浮窗不销毁仍在执行网络请求的线程；Qt 自动断开已销毁接收者。
_active_requests: set[QThread] = set()


def _start(worker):
    _active_requests.add(worker)
    worker.finished.connect(lambda: _active_requests.discard(worker))
    worker.finished.connect(worker.deleteLater)
    worker.start()


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
        self.setStyleSheet(f"""
            #EmoticonButton {{border: 1px solid transparent; border-radius: {theme.RADIUS_SM}px;
                color: {theme.TEXT1}; font-size: 11px; padding: 1px;}}
            #EmoticonButton:hover, #EmoticonButton:focus {{background: {theme.CONTENT_HOVER};
                border-color: {theme.ACCENT};}}
            #EmoticonButton:disabled {{color: {theme.TEXT3};}}
        """)
        holder = QWidget(self)
        layout = QVBoxLayout(holder)
        layout.setContentsMargins(8, 8, 8, 8)
        header = QHBoxLayout()
        self.status = QLabel("正在加载表情…")
        self.status.setWordWrap(True)
        header.addWidget(self.status, 1)
        self.retry_button = QPushButton("重试")
        self.retry_button.setObjectName("IconButton")
        self.retry_button.setCursor(Qt.PointingHandCursor)
        self.retry_button.clicked.connect(self.retryRequested)
        self.retry_button.hide()
        header.addWidget(self.retry_button)
        layout.addLayout(header)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        layout.addWidget(self.scroll, 1)
        self._images = {}
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

    def set_loading(self):
        self._clear_body()
        self.status.setText("正在加载表情…")
        self.status.show()
        self.retry_button.hide()

    def set_error(self, message):
        self.status.setText(message)
        self.status.show()
        self.retry_button.show()

    def set_packages(self, packages):
        self._clear_body()
        self.retry_button.hide()
        row, count = 0, 0
        urls = {}
        for package in packages:
            kind = package.get("pkg_type")
            if kind not in (1, 2, 3, 5):
                continue
            label = QLabel(str(package.get("pkg_name") or "表情"))
            label.setObjectName("AppSubtitle")
            self.grid.addWidget(label, row, 0, 1, 5)
            row += 1
            column = 0
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
            if column:
                row += 1
        self.status.setText("暂无可用表情" if not count else "")
        self.status.setVisible(not count)
        if urls:
            loader = AvatarLoader(urls, subdir="emoticons")
            loader.loaded.connect(self._image_loaded)
            _start(loader)

    def _image_loaded(self, url, pixmap):
        for button in self._images.get(url, []):
            button.setIcon(QIcon(pixmap))

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
    HEIGHT = 54

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DanmakuComposer")
        self.setCursor(Qt.ArrowCursor)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            #DanmakuComposer {{background: {theme.CONTENT}; border: none;
                border-bottom-left-radius: {theme.RADIUS_MD}px; border-bottom-right-radius: {theme.RADIUS_MD}px;}}
            #DanmakuComposer QLineEdit {{padding: 3px 6px; font-size: {theme.FONT_CONTROL}px;}}
            #DanmakuComposer #IconButton {{padding: 0; min-height: 26px; max-height: 26px;}}
            #DanmakuComposer #IconButton[danmakuRole="emote"] {{min-width: 26px; max-width: 26px;}}
            #DanmakuComposer #IconButton[danmakuRole="send"] {{min-width: 42px; max-width: 42px;}}
            #DanmakuSendFeedback {{color: {theme.TEXT2}; font-size: {theme.FONT_CAPTION}px;}}
        """)
        self._room_id = ""
        self._generation = self._revision = 0
        self._pending = self._catalog_pending = None
        self._catalog_key = None
        self.popup = None
        self._packages = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 3, 6, 3)
        layout.setSpacing(1)
        row = QHBoxLayout()
        row.setSpacing(4)
        self.edit = DanmakuEdit()
        self.edit.setAccessibleName("发送到当前直播间的弹幕")
        self.edit.setPlaceholderText("输入弹幕，Enter 发送")
        self.edit.setMinimumWidth(0)
        self.edit.setFixedHeight(28)
        self.edit.textChanged.connect(self._text_changed)
        self.edit.returnPressed.connect(self.send_text)
        row.addWidget(self.edit, 1)
        self.emote_button = QPushButton("☺")
        self.emote_button.setProperty("danmakuRole", "emote")
        self.emote_button.setAccessibleName("选择直播间表情")
        self.emote_button.setToolTip("选择表情；大表情点击后直接发送")
        self.emote_button.setFixedSize(28, 28)
        self.emote_button.clicked.connect(self.open_emoticons)
        row.addWidget(self.emote_button)
        self.send_button = QPushButton("发送")
        self.send_button.setProperty("danmakuRole", "send")
        self.send_button.setFixedSize(44, 28)
        self.send_button.clicked.connect(self.send_text)
        row.addWidget(self.send_button)
        for button in (self.emote_button, self.send_button):
            button.setObjectName("IconButton")
            button.setCursor(Qt.PointingHandCursor)
            button.setAutoDefault(False)
        layout.addLayout(row)
        self.feedback = QLabel("")
        self.feedback.setObjectName("DanmakuSendFeedback")
        self.feedback.setFixedHeight(16)
        self.feedback.setAccessibleName("弹幕发送状态")
        layout.addWidget(self.feedback)
        self._update_buttons()

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
            self.feedback.clear()
            if self.popup:
                self.popup.hide()
        self.setVisible(self.supported)
        self._update_buttons()

    def _text_changed(self):
        self._revision += 1
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

    def _finish_send(self, context):
        if context != self._pending:
            return False
        self._pending = None
        self._update_buttons()
        if context[:3] != self._context():
            self.feedback.clear()
            return False
        return True

    def _sent(self, context, _result):
        if self._finish_send(context):
            if context[4] == 0 and context[3] == self._revision:
                self.edit.clear()
            self.feedback.clear()

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
