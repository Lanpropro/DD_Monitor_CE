"""Bilibili Super Chat state shared by the danmaku panel and video overlays."""
from __future__ import annotations

import time
import math
from dataclasses import dataclass, field
from copy import deepcopy
from urllib.parse import urlparse

import requests
from PySide6.QtCore import QEasingCurve, QObject, QRectF, QThread, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QTextCharFormat, QTextCursor, QTextDocument, QTextOption, QTransform
from PySide6.QtWidgets import QApplication

from . import bili, motion, theme
from .images import AvatarLoader, load_cached_image


SUPER_CHAT_API = "https://api.live.bilibili.com/av/v1/SuperChat/getMessageList"
DEFAULT_DURATION = 60
SC_PRICE_TIERS = (
    (30, '#EDF5FF', '#2A60B2', '#7497CD'),
    (50, '#DBFFFD', '#427D9E', '#7DA4BD'),
    (100, '#FFF1C5', '#E2B52B', '#ECCF75'),
    (500, '#FFEAD2', '#E09443', '#E8AF79'),
    (1000, '#FFE7E4', '#E54D4D', '#EE8B8B'),
    (2000, '#FFD8D8', '#AB1A32', '#C86A7A'),
)
SC_USER_COLOR = '#666666'
SC_PRICE_COLOR = '#333333'
SC_CONTENT_COLOR = '#FFFFFF'


def super_chat_palette(price):
    amount = _number(price)
    tier = next((tier for tier in reversed(SC_PRICE_TIERS) if amount >= tier[0]), SC_PRICE_TIERS[0])
    return dict(zip(('background_color', 'background_bottom_color', 'background_price_color'), tier[1:]))


def sc_message_document(event, width, scale=1.0):
    font = QFont(theme.FONT_DEFAULT)
    font.setPixelSize(max(1, round(14 * scale)))
    document = QTextDocument()
    document.setDocumentMargin(0)
    document.setDefaultFont(font)
    option = document.defaultTextOption()
    option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
    document.setDefaultTextOption(option)
    document.setPlainText(str(event.get('message') or event.get('text') or ''))
    cursor = QTextCursor(document)
    cursor.select(QTextCursor.Document)
    style = QTextCharFormat()
    style.setForeground(QColor(SC_CONTENT_COLOR))
    cursor.mergeCharFormat(style)
    document.setTextWidth(max(1, math.floor(width) - 2 * math.ceil(11 * scale)))
    return document


def sc_card_height(event, width, scale=1.0, collapsed=False):
    if collapsed:
        return round(36 * scale)
    document = sc_message_document(event, width, scale)
    padding = max(61 * scale, round(56 * scale) + round(3 * scale) + round(2 * scale))
    return math.ceil(max(100 * scale, padding + document.size().height() + 1))


def sc_card_geometry(events, base_width, scale, available_width, available_height, collapsed=False):
    if not events:
        return 1, 1, scale, []
    scale = min(scale, max(1, available_width) / base_width)
    for attempt in range(8):
        width = base_width * scale
        heights = [sc_card_height(event, width, scale, collapsed) for event in events[:2]]
        height = heights[0] + 40 * scale if len(events) >= 3 else sum(heights) + 8 * scale * (len(heights) - 1)
        if height <= max(1, available_height) or attempt == 7:
            break
        scale *= max(1, available_height) / height * .98
    return width, height, scale, heights


def order_super_chats(chats, selected=''):
    ordered = sorted(chats, key=lambda item: (-_number(item.get('price')),
                     _number(item.get('start_time')), str(item.get('id') or '')))
    if len(ordered) >= 3 and selected:
        ordered.sort(key=lambda item: str(item.get('id')) != selected)
    return ordered


def sc_stack_rects(width, height, count, card_height=100, scale=1.0, card_heights=None):
    if not count:
        return []
    if count < 3:
        if card_heights is not None:
            rects = []
            top = 0
            for item_height in card_heights:
                rects.append(QRectF(0, top, width, item_height))
                top += item_height + 8 * scale
            return rects
        card_height = min(card_height * scale, max(1, (height - 8 * scale * (count - 1)) / count))
        return [QRectF(0, i * (card_height + 8 * scale), width, card_height) for i in range(count)]
    card_height = card_heights[0] if card_heights is not None else min(card_height * scale, max(1, height - 40 * scale))
    return [QRectF(i * 6 * scale, (2 - i) * 20 * scale, max(1, width - i * 12 * scale), card_height)
            for i in range(3)]


class SuperChatPresentation(QObject):
    changed = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.collapsed = False
        self.progress = 1.0
        self.delay = 7
        self.ids = set()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.collapse)
        self.entrance = QVariantAnimation(self)
        self.entrance.setDuration(180)
        self.entrance.setEasingCurve(QEasingCurve.OutCubic)
        self.entrance.setStartValue(0.0)
        self.entrance.setEndValue(1.0)
        self.entrance.valueChanged.connect(self._reveal)

    def configure(self, settings):
        delay = max(1, min(60, _number(settings.get('super_chat_collapse_delay'), 7)))
        if self.delay != delay:
            self.delay = delay
            if self.ids and not self.collapsed:
                self.timer.start(delay * 1000)

    def set_events(self, events):
        ids = {str(item.get('id') or item.get('super_chat_id') or '') for item in events}
        added = ids - self.ids
        self.ids = ids
        if not ids:
            self.timer.stop()
            self.entrance.stop()
            self.collapsed = False
            self.progress = 1.0
        elif added:
            self.expand(animate=True)

    def expand(self, *, animate=False):
        self.collapsed = False
        self.timer.start(self.delay * 1000)
        if animate and motion.enabled():
            self.entrance.stop()
            self.entrance.start()
        else:
            self.entrance.stop()
            self.progress = 1.0
        self.changed.emit()

    def collapse(self):
        if not self.ids:
            return
        self.entrance.stop()
        self.progress = 1.0
        self.collapsed = True
        self.changed.emit()

    def _reveal(self, value):
        self.progress = float(value)
        self.changed.emit()


class SuperChatAvatar(QObject):
    changed = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.url = ''
        self.pixmap = None
        self._loaders = {}

    def set_url(self, url):
        url = str(url or '')
        if url == self.url:
            return
        self.url = url
        self.pixmap = load_cached_image(url, 'sc-avatars') if url else None
        self.changed.emit()
        if not url or self.pixmap is not None or url in self._loaders:
            return
        app = QApplication.instance()
        loader = AvatarLoader({url: url}, app, subdir='sc-avatars')
        self._loaders[url] = loader
        loader.loaded.connect(self._loaded)
        loader.finished.connect(lambda: self._loaders.pop(url, None))
        loader.finished.connect(loader.deleteLater)
        app.aboutToQuit.connect(loader.wait)
        loader.start()

    def _loaded(self, url, pixmap):
        if url == self.url and not pixmap.isNull():
            self.pixmap = pixmap
            self.changed.emit()


def paint_sc_avatar(painter, rect, pixmap, name):
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)
    painter.setPen(Qt.NoPen)
    if pixmap is not None:
        brush = QBrush(pixmap)
        factor = max(rect.width() / pixmap.width(), rect.height() / pixmap.height())
        transform = QTransform()
        transform.translate(rect.center().x() - pixmap.width() * factor / 2,
                            rect.center().y() - pixmap.height() * factor / 2)
        transform.scale(factor, factor)
        brush.setTransform(transform)
        painter.setBrush(brush)
    else:
        painter.setBrush(QColor('#64748b'))
    painter.drawEllipse(rect)
    if pixmap is None:
        painter.setPen(QColor('white'))
        painter.drawText(rect, Qt.AlignCenter, (name or '?')[0])
    painter.restore()


def paint_sc_background(painter, rect, background, header, header_height):
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(background))
    painter.drawRoundedRect(rect, 7, 7)
    top = QPainterPath()
    x, y, right = rect.left(), rect.top(), rect.right()
    bottom = min(rect.bottom(), y + header_height)
    if header_height >= rect.height():
        top.addRoundedRect(rect, 7, 7)
    else:
        top.moveTo(x, bottom)
        top.lineTo(x, y + 7)
        top.quadTo(x, y, x + 7, y)
        top.lineTo(right - 7, y)
        top.quadTo(right, y, right, y + 7)
        top.lineTo(right, bottom)
        top.closeSubpath()
    painter.fillPath(top, QColor(header))
    painter.setPen(QPen(QColor(background), 1))
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(top)
    painter.restore()


def _text(value) -> str:
    return str(value or "").strip()


def _number(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def readable_text_color(background) -> QColor:
    """Pick WCAG-friendly text for a Bilibili Super Chat background."""
    color = (QColor(background) if isinstance(background, QColor)
             else QColor(str(background or "")))
    if not color.isValid():
        color = QColor("#f59e0b")
    channels = []
    for value in (color.redF(), color.greenF(), color.blueF()):
        channels.append(value / 12.92 if value <= 0.03928
                        else ((value + 0.055) / 1.055) ** 2.4)
    luminance = 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]
    dark = QColor("#20242c")
    light = QColor("#ffffff")
    dark_contrast = (luminance + 0.05) / (0.019 + 0.05)
    light_contrast = 1.05 / (luminance + 0.05)
    return dark if dark_contrast >= light_contrast else light


def _hosted_asset_url(value) -> str:
    url = _text(value)
    parsed = urlparse(url)
    return url if parsed.scheme in ("http", "https") and parsed.netloc else ""


def normalize(event: dict, *, source: str = "websocket") -> dict:
    """Turn either a blivedm message or an API entry into one event shape."""
    source = _text(source) or "websocket"
    user = event.get("user_info") if isinstance(event.get("user_info"), dict) else {}
    chat_id = _text(event.get("id") or event.get("super_chat_id"))
    message = _text(event.get("message") or event.get("text"))
    uname = _text(event.get("uname") or user.get("uname"))
    price = _number(event.get("price"))
    start = _number(event.get("start_time"))
    end = _number(event.get("end_time"))
    # SC 网页端按 start_time + time 推算结束时间；快照有时只给 time。
    duration = _number(event.get("time"))
    if end <= 0 and start > 0 and duration > 0:
        end = start + duration
    if end <= 0 and duration > 0:
        end = int(time.time()) + duration
    if end <= start:
        end = start + DEFAULT_DURATION if start else int(time.time()) + DEFAULT_DURATION
    return {
        "kind": "super_chat",
        "super_chat_id": chat_id,
        "id": chat_id,
        "uid": _text(event.get("uid") or user.get("uid")),
        "uname": uname,
        "text": message,
        "message": message,
        "price": price,
        "start_time": start,
        "end_time": end,
        "time": max(0, end - int(time.time())),
        "face": _text(event.get("face") or user.get("face")),
        "guard_level": _number(event.get("guard_level") or user.get("guard_level")),
        "user_level": _number(event.get("user_level") or user.get("user_level")),
        **super_chat_palette(price),
        "background_image": _hosted_asset_url(event.get("background_image")),
        "background_icon": _hosted_asset_url(event.get("background_icon")),
        "message_trans": _text(event.get("message_trans")),
        "source": source,
    }


def snapshot_events(room_id: str, *, timeout: float = 4.0) -> list[dict]:
    """Fetch currently displayed Super Chats; an unavailable endpoint is non-fatal."""
    room_id = _text(room_id)
    if not room_id.isdigit():
        return []
    # 页面配置里常见短号，SC 接口只认真实房间号。
    room_id = _text(bili._resolve_room_id(room_id))
    if not room_id.isdigit():
        return []
    response = requests.get(
        SUPER_CHAT_API,
        params={"room_id": room_id},
        headers=bili.HEADERS,
        cookies=bili._cookies(),
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or payload.get("code") != 0:
        return []
    data = payload.get("data") or {}
    items = data.get("list") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    return [normalize(item, source="snapshot") for item in items
            if isinstance(item, dict) and _text(item.get("id"))]


@dataclass
class SuperChatStore:
    """Room-local active chats, keyed by the Bilibili Super Chat ID."""

    items: dict[str, dict] = field(default_factory=dict)
    removed: set[str] = field(default_factory=set)
    dismissed: set[str] = field(default_factory=set)

    def upsert(self, event: dict) -> dict:
        source = _text(event.get("source")) or "websocket"
        item = normalize(event, source=source)
        if not item["super_chat_id"]:
            item["super_chat_id"] = item["id"] = f"{item['uid']}:{item['start_time']}"
        if item["super_chat_id"] in self.removed:
            return item
        if _number(item.get("end_time")) <= time.time():
            return item
        current = self.items.get(item["super_chat_id"])
        if current is not None:
            # 快照只补实时事件缺的字段，不能覆盖刚收到的内容。
            if source == "snapshot" and current.get("source") == "websocket":
                item = {**item, **deepcopy(current)}
            else:
                item = {**deepcopy(current),
                        **{key: value for key, value in item.items()
                           if value not in ("", 0)}}
        self.items[item["super_chat_id"]] = item
        return item

    def remove(self, ids) -> None:
        for chat_id in ids or ():
            chat_id = _text(chat_id)
            self.removed.add(chat_id)
            self.items.pop(chat_id, None)

    def dismiss(self, chat_id) -> None:
        """Hide one message locally without sending a moderation request."""
        self.dismissed.add(_text(chat_id))

    def expire(self, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        expired = [key for key, item in self.items.items()
                   if _number(item.get("end_time")) <= now]
        for key in expired:
            self.items.pop(key, None)
            self.dismissed.discard(key)
        return bool(expired)

    def active(self, now: float | None = None) -> list[dict]:
        now = time.time() if now is None else now
        chats = [deepcopy(item) for item in self.items.values()
                 if _number(item.get("end_time")) > now and item['id'] not in self.dismissed]
        return order_super_chats(chats)


def format_price(price) -> str:
    return f"¥{_number(price):,}"


def remaining_seconds(end_time, now: float | None = None) -> int:
    now = time.time() if now is None else now
    return max(0, _number(end_time) - int(now))


def format_remaining(seconds) -> str:
    seconds = max(0, _number(seconds))
    minutes, rest = divmod(seconds, 60)
    return f"{minutes}:{rest:02d}" if minutes else f"{rest}秒"


class SuperChatSnapshot(QThread):
    """Load one room's current Super Chats away from the UI thread."""

    loaded = Signal(str, list)

    def __init__(self, room_id: str, parent=None):
        super().__init__(parent)
        self.room_id = _text(room_id)

    def run(self) -> None:
        try:
            chats = snapshot_events(self.room_id)
        except Exception:  # noqa: BLE001 - optional endpoint, live events remain usable
            chats = []
        if not self.isInterruptionRequested():
            self.loaded.emit(self.room_id, chats)
