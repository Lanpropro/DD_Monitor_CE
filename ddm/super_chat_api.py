"""Bilibili Super Chat snapshot protocol and optional Qt worker."""
from __future__ import annotations
import requests
from PySide6.QtCore import QThread, Signal
from . import bili
from .super_chat_model import _text, normalize
from .super_chat_model import _text, normalize


SUPER_CHAT_API = "https://api.live.bilibili.com/av/v1/SuperChat/getMessageList"


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


class SuperChatSnapshot(QThread):
    """Load one room's current Super Chats away from the UI thread."""

    loaded = Signal(str, list)

    def __init__(self, room_id: str, parent=None):
        super().__init__(parent)
        self.room_id = _text(room_id)

    def run(self) -> None:
        try:
            from . import super_chat as api
            chats = api.snapshot_events(self.room_id)
        except Exception:  # noqa: BLE001 - optional endpoint, live events remain usable
            chats = []
        if not self.isInterruptionRequested():
            self.loaded.emit(self.room_id, chats)
