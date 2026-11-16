"""Super Chat normalization, expiry and room-local data; no Qt or network dependencies."""
from __future__ import annotations
import time
from dataclasses import dataclass, field
from copy import deepcopy
from urllib.parse import urlparse


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


SC_BODY_PADDING = 12


def super_chat_palette(price):
    amount = _number(price)
    tier = next((tier for tier in reversed(SC_PRICE_TIERS) if amount >= tier[0]), SC_PRICE_TIERS[0])
    return dict(zip(('background_color', 'background_bottom_color', 'background_price_color'), tier[1:]))


def order_super_chats(chats):
    ordered = sorted(chats, key=lambda item: (-_number(item.get('price')),
                     _number(item.get('start_time')), str(item.get('id') or '')))
    return ordered


def _text(value) -> str:
    return str(value or "").strip()


def _number(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


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
