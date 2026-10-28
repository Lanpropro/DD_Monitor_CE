"""Bilibili Super Chat state shared by the danmaku panel and video overlays."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from copy import deepcopy
from urllib.parse import urlparse

import requests
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QColor

from . import bili


SUPER_CHAT_API = "https://api.live.bilibili.com/av/v1/SuperChat/getMessageList"
DEFAULT_DURATION = 60


def _text(value) -> str:
    return str(value or "").strip()


def _number(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _color(value, fallback: str) -> str:
    text = _text(value)
    if len(text) == 7 and text.startswith("#") and all(
            char in "0123456789abcdefABCDEF" for char in text[1:]):
        return text
    return fallback


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
        "background_color": _color(event.get("background_color"), "#f59e0b"),
        "background_bottom_color": _color(
            event.get("background_bottom_color"), "#d97706"),
        "background_price_color": _color(
            event.get("background_price_color"), "#b45309"),
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

    def expire(self, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        expired = [key for key, item in self.items.items()
                   if _number(item.get("end_time")) <= now]
        for key in expired:
            self.items.pop(key, None)
        return bool(expired)

    def active(self, now: float | None = None) -> list[dict]:
        now = time.time() if now is None else now
        chats = [deepcopy(item) for item in self.items.values()
                 if _number(item.get("end_time")) > now]
        return sorted(chats, key=lambda item: (
            _number(item.get("start_time")), item.get("super_chat_id", "")))


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
