"""Per-tile drafts and send2 composer, backed by captured credentials."""
import requests
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QIcon, QPainter, QPainterPath, QPen, QPixmap, QRegion
from PySide6.QtWidgets import (
    QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton,
    QScrollArea, QSizePolicy, QStyle, QStyleOptionTab, QStylePainter, QTabBar, QToolButton,
    QVBoxLayout, QWidget, QWidgetAction,
)

from ddm import theme
from . import bili_api as bili
from .emoticons import EmoticonButton, EmoticonPopup, _style_button
from .gift_popup import GiftButton, GiftPopup
from .gift_controller import GiftController, GiftCoordinator
from .catalog_cache import CatalogCache, preview_packages
from .notifications import needs_login
from .workers import Request, start_worker, request_message, _active_requests, wait_for_requests

class DanmakuEdit(QLineEdit):
    """输入时接管单键快捷键，中文选词回车不触发发送。"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._composing = False

    def event(self, event):
        if event.type() in (QEvent.DragEnter, QEvent.DragMove, QEvent.Drop):
            if any(event.mimeData().hasFormat(format) for format in (
                    'application/x-ddm-room', 'application/x-ddm-nav', 'application/x-ddm-tile')):
                event.ignore()
                return True
        if event.type() == QEvent.ShortcutOverride and not (
                event.modifiers() & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier)):
            event.accept()
            return True
        return super().event(event)

    def inputMethodEvent(self, event):
        self._composing = bool(event.preeditString())
        super().inputMethodEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and (self._composing or event.isAutoRepeat()):
            event.accept()
            return
        if event.key() == Qt.Key_Escape:
            self.clearFocus()
            event.accept()
            return
        super().keyPressEvent(event)


class DanmakuComposer(QWidget):
    deviceCookieReady = Signal()
    HEIGHT = 26

    def __init__(self, session, parent=None, *, coordinator=None, catalog_cache=None, notifier=None):
        super().__init__(parent)
        self.coordinator = coordinator if coordinator is not None else GiftCoordinator(self)
        self.gift_controller = self.gift_popup = None
        self.session = session
        self.catalog_cache = catalog_cache if catalog_cache is not None else CatalogCache()
        self._requests = set()
        self.session.changed.connect(self._session_changed)
        self.setObjectName("DanmakuComposer")
        self.setCursor(Qt.ArrowCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumWidth(0)
        self.setFixedHeight(self.HEIGHT)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            #DanmakuComposer {{background: transparent; border: none;}}
            #DanmakuComposer QLineEdit {{padding: 3px 6px; font-size: {theme.FONT_CONTROL}px;}}
            #DanmakuSendFeedback {{background: palette(tooltip-base); color: palette(window-text);
                border: 1px solid palette(mid); border-radius: {theme.RADIUS_SM}px;
                padding: 6px 8px; font-size: {theme.FONT_CAPTION}px;}}
        """)
        self._room_id = ""
        self._closing = False
        self.notifier=notifier
        self._room_info={}
        self._generation = self._revision = 0
        self._auth = self._auth_identity(self._cookies())
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
        self.emote_button = EmoticonButton()
        self.emote_button.setAccessibleName("选择直播间表情")
        self.emote_button.setToolTip("选择表情；大表情点击后直接发送")
        self.emote_button.clicked.connect(self.open_emoticons)
        row.addWidget(self.emote_button)
        self.gift_button = GiftButton()
        self.gift_button.clicked.connect(self.open_gifts)
        row.addWidget(self.gift_button)
        self.send_button = QPushButton("发送")
        self.send_button.setFixedSize(44, self.HEIGHT)
        self.send_button.clicked.connect(self.send_text)
        row.addWidget(self.send_button)
        _style_button(self.send_button)
        self.feedback = QLabel("", self, Qt.ToolTip)
        self.feedback.setObjectName("DanmakuSendFeedback")
        self.feedback.setAttribute(Qt.WA_ShowWithoutActivating)
        self.feedback.setTextFormat(Qt.PlainText)
        self.feedback.setWordWrap(True)
        self.feedback.setMaximumWidth(380)
        self.feedback.setAccessibleName("弹幕发送状态")
        self.feedback.hide()
        self._update_buttons()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 小格保留输入和表情入口，回车仍可发送，不为单独按钮挤掉输入空间。
        self.send_button.setVisible(self.width() >= 176)

    def hideEvent(self, event):
        if self.gift_popup:
            self.gift_popup.hide()
        if self.gift_controller:
            self.gift_controller.set_active(False)
        self.feedback.hide()
        if self.popup:
            self.popup.hide()
        super().hideEvent(event)

    @property
    def busy(self):
        return self._pending is not None

    def shutdown(self):
        if self._closing:
            return
        self._closing = True
        if self.notifier:self.notifier.close()
        if self.gift_popup:
            self.gift_popup.shutdown()
        if self.gift_controller:
            self.gift_controller.shutdown()
        self._cancel_requests()
        self._generation += 1
        self._pending = self._catalog_pending = None
        self._packages = self._catalog_key = None
        self.feedback.hide()
        if self.popup:
            self.popup.shutdown()
        self.setEnabled(False)

    @property
    def supported(self):
        return self._room_id.isascii() and self._room_id.isdigit() and bool(self._room_id.strip("0"))

    @staticmethod
    def _auth_identity(cookies):
        return cookies.get("SESSDATA", ""), cookies.get("bili_jct", "")

    def sync_credentials(self):
        cookies = self._cookies()
        identity = self._auth_identity(cookies)
        if identity != self._auth:
            if self.gift_popup:
                self.gift_popup.hide()
            if self.gift_controller:
                self.gift_controller.set_context(self._room_id, self.session.snapshot())
            self._cancel_requests()
            self._auth = identity
            self._generation += 1
            self._pending = self._catalog_pending = None
            self._packages = self._catalog_key = None
            self._feedback("")
            if self.popup:
                self.popup.set_loading(clear=True)
                self.popup.hide()
            self._update_buttons()
        return cookies

    def set_room(self, room_id, *, room=None):
        room_id = str(room_id or "")
        self._room_info={**dict(room or {}),'room_id':room_id}
        if room_id != self._room_id:
            if self.gift_popup:
                self.gift_popup.hide()
            if self.gift_controller:
                self.gift_controller.set_context(room_id, self.session.snapshot())
            self._cancel_requests()
            self._generation += 1
            self._room_id = room_id
            self._pending = self._catalog_pending = None
            self._packages = self._catalog_key = None
            self.edit.clear()
            self._feedback("")
            if self.popup:
                self.popup.set_loading(clear=True)
                self.popup.hide()
        self.setVisible(self.supported)
        self._update_buttons()

    def _text_changed(self):
        self._revision += 1
        self.feedback.hide()
        self._update_buttons()

    def _update_buttons(self):
        self.edit.setEnabled(not self.busy)
        self.send_button.setEnabled(bool(self.edit.text().strip()) and not self.busy)
        self.send_button.setText("…" if self.busy else "发送")

    def _context(self):
        self.sync_credentials()
        # buvid3 的按需初始化不代表账号变化，不能使首次表情请求失效。
        return self._generation, self._room_id, self._auth

    def send_text(self):
        if self.edit.text().strip():
            self._send(self.edit.text(), 0)

    def _send(self, message, dm_type, *, check_emoticon=False):
        cookies = self.sync_credentials()
        if self._closing or self.busy or not self.supported:
            return
        if not cookies.get("SESSDATA") or not cookies.get("bili_jct"):
            self._feedback("请先登录 B 站" if not cookies.get("SESSDATA") else
                           "登录缺少 bili_jct，请退出 B 站账号后重新登录", error="请重新登录 B 站", login_required=True)
            return
        context = (*self._context(), self._revision, dm_type)
        self._pending = context
        self._feedback("正在检测表情权限…" if check_emoticon else "正在发送…")
        self._update_buttons()
        room_id = self._room_id
        def send(local):
            if check_emoticon:
                try:
                    packages = bili.get_emoticons(room_id, cookies=local)
                except (ValueError, requests.RequestException) as error:
                    raise ValueError("无法检测表情权限，未发送：" + request_message(error)) from error
                if not worker.still_current():
                    return
                # Only the current account's live response can authorize a repeat.
                emote = next((emote for package in packages
                              for emote in (package.get("emoticons") or [])
                              if emote.get("emoticon_unique") == message), None)
                if emote is None:
                    raise ValueError("当前账号在该直播间无法使用此表情，未发送")
                if emote.get("perm") != 1:
                    raise ValueError("当前账号未解锁该表情，未发送")
            return bili.send_danmaku(room_id, message, dm_type=dm_type, cookies=local,
                                     still_current=worker.still_current)
        worker = Request(context, send,
                         cookies=cookies, account_generation=self._account_generation(), require_device=True)
        worker.completed.connect(self._sent)
        worker.failed.connect(self._send_failed)
        self._start_request(worker)

    def _feedback(self, text, *, error=None, login_required=None):
        self.feedback.setText(text)
        self.feedback.setToolTip(text)
        self.feedback.setAccessibleDescription(text)
        self.edit.setToolTip(text)
        self.feedback.hide()
        if error is not None and self.notifier:
            login = needs_login(error) if login_required is None else login_required
            if self.notifier.error(text,room=self._room_info,login_required=login):return
        if text and not self.busy and self.isVisible():
            self.feedback.adjustSize()
            anchor = self.edit.mapToGlobal(QPoint(0, 0))
            screen = self.screen().availableGeometry()
            x = max(screen.left(), min(anchor.x(), screen.right() - self.feedback.width() + 1))
            y = anchor.y() - self.feedback.height() - 4
            if y < screen.top():
                y = anchor.y() + self.edit.height() + 4
            self.feedback.move(x, min(y, screen.bottom() - self.feedback.height() + 1))
            self.feedback.show()

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
        self.deviceCookieReady.emit()
        if self._finish_send(context):
            if context[4] == 0 and context[3] == self._revision:
                self.edit.clear()
            self._feedback("")

    def _send_failed(self, context, error):
        self.deviceCookieReady.emit()
        if self._finish_send(context):
            self._feedback(request_message(error, sending=True),error=error)

    def repeat_message(self, event):
        identifier = event.get("emoticon_unique")
        if (event.get("dm_type") != 1 or not identifier or self._closing or
                self.busy or not self.supported):
            return False
        self._send(str(identifier), 1, check_emoticon=True)
        return self._pending is not None

    def choose_emoticon(self, pkg_type, emote):
        if self._closing:
            return
        self.sync_credentials()
        if emote.get("perm") != 1:
            return
        if pkg_type == 3:
            self.edit.insert(str(emote.get("emoji") or ""))
        elif pkg_type in (1, 2, 5) and emote.get("emoticon_unique"):
            self._send(str(emote["emoticon_unique"]), 1)
        self.edit.setFocus(Qt.OtherFocusReason)

    def open_emoticons(self, _checked=False,*,force=False):
        if self.gift_popup:
            self.gift_popup.hide()
        cookies = self.sync_credentials()
        self.feedback.hide()
        if self._closing or not self.supported:
            return
        if not cookies.get("SESSDATA"):
            self._feedback("请先登录 B 站后选择表情",error="请先登录 B 站后选择表情",login_required=True)
            return
        if self.popup is None:
            self.popup = EmoticonPopup(self)
            self.popup.selected.connect(self._choose_cached_emoticon)
            self.popup.retryRequested.connect(self._reload_emoticons)
        if not force or not self.popup.isVisible():self.popup.open_at(self.emote_button)
        context = self._context()
        if not force and self._catalog_key == context and self._packages is not None:
            return
        if self._catalog_pending == context:
            return
        if self._packages is None:
            cached=self.catalog_cache.load(self._room_id,cookies)
            if cached is not None:
                self._packages=cached
                self.popup.set_packages(preview_packages(cached))
        self.popup.set_loading()
        self._catalog_pending = context
        room_id = self._room_id
        worker = Request(context, lambda local: bili.get_emoticons(room_id, cookies=local),
                         cookies=cookies, account_generation=self._account_generation(), require_device=True)
        worker.completed.connect(self._emoticons_loaded)
        worker.failed.connect(self._emoticons_failed)
        self._start_request(worker)

    def _choose_cached_emoticon(self, kind, emote):
        # 菜单打开后可能退出/切换账号，旧的权限结果不能沿用。
        if self._catalog_key == self._context():
            self.choose_emoticon(kind, emote)

    def _reload_emoticons(self):
        self.open_emoticons(force=True)

    def _emoticons_loaded(self, context, packages):
        self.deviceCookieReady.emit()
        if context != self._context():
            return
        self._catalog_pending = None
        self._catalog_key, self._packages = context, packages
        self.catalog_cache.save(self._room_id,self._cookies(),packages)
        self.popup.set_packages(packages)

    def _emoticons_failed(self, context, error):
        self.deviceCookieReady.emit()
        if context != self._context():
            return
        self._catalog_pending = None
        self.popup.set_error(request_message(error))
        if getattr(error,'login_required',False):
            self._catalog_key=None
            self.popup.set_packages(preview_packages(self._packages or []))
            self.popup.set_error(request_message(error))
        self._feedback(request_message(error),error=error)

    def _cookies(self):
        snapshot = self.session.snapshot()
        return dict(snapshot.values) if snapshot else {}

    def _account_generation(self):
        snapshot = self.session.snapshot()
        return snapshot.generation if snapshot else 0

    def _session_changed(self, _snapshot):
        if not self._closing:
            self.sync_credentials()

    def _cancel_requests(self):
        for worker in tuple(self._requests):
            worker.cancel()

    def _start_request(self, worker):
        self._requests.add(worker)
        worker.deviceReady.connect(self.session.publish_device)
        worker.finished.connect(lambda: self._requests.discard(worker))
        start_worker(worker)

    def interaction_active(self):
        return (self.edit.hasFocus() or self.edit._composing or
                bool(self.popup and self.popup.isVisible()) or
                bool(self.gift_popup and self.gift_popup.interaction_active()))

    def open_gifts(self, _checked=False):
        cookies=self.sync_credentials()
        if self._closing or not self.supported:
            return
        if not cookies.get('SESSDATA') or not cookies.get('bili_jct'):
            self._feedback('请先登录 B 站' if not cookies.get('SESSDATA') else '登录缺少 bili_jct，请重新登录',error='请重新登录 B 站',login_required=True)
            return
        self.feedback.hide()
        if self.popup:
            self.popup.hide()
        if self.gift_controller is None:
            self.gift_controller=GiftController(self.session,self.coordinator,self)
            self.gift_popup=GiftPopup(self)
            self.gift_controller.stateChanged.connect(self.gift_popup.set_state)
            self.gift_controller.errorRaised.connect(self._gift_error)
            self.gift_controller.sent.connect(self.gift_popup.mark_sent)
            self.gift_popup.sendRequested.connect(self.gift_controller.send)
            self.gift_popup.refreshRequested.connect(self._refresh_gifts)
            self.gift_popup.closed.connect(self._gifts_closed)
        self.gift_controller.set_context(self._room_id,self.session.snapshot())
        self.gift_popup.set_state(self.gift_controller.state)
        self.gift_popup.open_at(self.gift_button)
        if self.gift_popup.isVisible():
            self.gift_controller.load()

    def _gift_error(self,error,sending=False):
        if not self._closing:self._feedback(request_message(error,sending=sending),error=error)

    def _refresh_gifts(self):
        if self.gift_controller:
            self.gift_controller.load(force=True)

    def _gifts_closed(self):
        if self.gift_controller:
            self.gift_controller.set_active(False)
