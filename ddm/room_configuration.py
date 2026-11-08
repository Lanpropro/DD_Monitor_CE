"""Pure room-state reconciliation and startup placeholder construction; configuration IO stays in config."""
from copy import deepcopy


def _unique(values) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value)
        if text in ("", "0") or text in result:
            continue
        result.append(text)
    return result


def sync_platform_rooms(state: dict, active_platforms: set[str]) -> dict:
    """未启用的平台房间移入暂存；启用后恢复，已占用的格子不覆盖。"""
    state = deepcopy(state)
    storage = state.setdefault("suspended_platform_rooms", {})
    fields = ("rooms", "pinned", "import_order", "custom_order")
    metadata = state.setdefault("platform_rooms", {})
    wall = state.setdefault("wall", [])
    restored = [storage.pop(kind) for kind in list(storage) if kind in active_platforms]
    for saved in restored:
        metadata.update(saved.get("platform_rooms", {}))
    for key in fields:
        values = state.setdefault(key, [])
        records = [record for saved in restored for record in saved.get(key, [])]
        for record in sorted(records, key=lambda record: record["index"]):
            if record["room_id"] not in values:
                values.insert(min(record["index"], len(values)), record["room_id"])
    for saved in restored:
        for record in saved.get("wall", []):
            index, slot = record["index"], record["slot"]
            while index >= len(wall):
                wall.append({"room_id": ""})
            if not wall[index].get("room_id"):
                wall[index] = slot
            elif slot["room_id"] not in state["rooms"]:
                state["rooms"].append(slot["room_id"])

    def suspended(room_id):
        return ":" in room_id and room_id.split(":", 1)[0] not in active_platforms

    for key in fields:
        values = state.get(key, [])
        for index, room_id in enumerate(values):
            if suspended(room_id):
                saved = storage.setdefault(room_id.split(":", 1)[0], {})
                saved.setdefault(key, []).append({"index": index, "room_id": room_id})
        state[key] = [room_id for room_id in values if not suspended(room_id)]
    for index, slot in enumerate(wall):
        room_id = str(slot.get("room_id") or "")
        if suspended(room_id):
            saved = storage.setdefault(room_id.split(":", 1)[0], {})
            saved.setdefault("wall", []).append({"index": index, "slot": slot})
            wall[index] = dict(slot, room_id="")
    for room_id in list(metadata):
        if suspended(room_id):
            saved = storage.setdefault(room_id.split(":", 1)[0], {})
            saved.setdefault("platform_rooms", {})[room_id] = metadata.pop(room_id)
    return state


def build_rooms(state: dict) -> tuple[list[dict], list[dict]]:
    """(侧栏房间, 画面墙房间)。格子设置从配置里带。

    房间的实时信息（直播状态/标题/主播名/头像）**不在启动时同步拉**：以前这里
    对每个房间逐个同步请求（单个超时 10 秒），房间一多窗口就要在主线程上干等
    几十秒才出现。现在只造占位条目让窗口立刻出现，真实信息由启动后的
    ``refresh_status()``（后台线程、批量一次请求）补上，见 app 的
    ``_on_status_updated``。
    """
    from . import config as settings_api
    room_ids = _unique(state.get("rooms", []))
    wall_slots = state.get("wall", []) or []
    default_volume = int((state.get("settings") or {}).get("default_volume", settings_api.DEFAULT_VOLUME))

    def placeholder(room_id: str) -> dict:
        room = {
            "room_id": room_id, "uname": f"房间 {room_id}",
            "title": "", "live": False, "viewers": "",
            "face": "", "cover_url": "",
            # 直播状态还没拉过：第一次补上真实状态时不算「刚开播」，
            # 否则一打开软件，所有已开播的房间都会冒一遍开播提醒（见 app）。
            "live_known": False,
        }
        saved = ((state.get("platform_rooms") or {}).get(room_id) or
                 (state.get("browser_rooms") or {}).get(room_id) or {})
        if ":" in room_id:
            room.update(platform=room_id.split(":", 1)[0], playback_mode="stream")
        if saved.get("playback_mode") in ("browser", "stream"):
            for key in ("uname", "title", "platform", "playback_mode", "anchor_uid", "sec_uid", "resolved_room_id", "face", "display_room_id"):
                if isinstance(saved.get(key), str):
                    room[key] = saved[key]
            if saved.get("follow_account_ref") is True:
                room["follow_account_ref"] = True
        if room.get("platform") == "huya":
            room["playback_mode"] = "stream"     # 迁移旧版虎牙网页卡片
        return room

    sidebar = [placeholder(room_id) for room_id in room_ids]
    wall = []
    for slot in wall_slots:
        room_id = str(slot.get("room_id") or "")
        if not room_id:
            # 空格子也保留格子设置；之后拖入主播时音量应沿用这个位置的值。
            wall.append({
                "room_id": "",
                "muted": bool(slot.get("muted", True)),
                "volume": int(slot.get("volume", default_volume)),
                "quality": int(slot.get("quality", 250)),
                "audio_channel": int(slot.get("audio_channel", 0)),
                "video_danmaku_enabled": bool(slot.get("video_danmaku_enabled", False)),
                "video_danmaku_overrides": settings_api.video_danmaku_overrides(slot.get("video_danmaku_overrides")),
                "codec_overrides": settings_api.codec_overrides(slot.get("codec_overrides")),
            })
            continue
        room = placeholder(room_id)
        room["muted"] = bool(slot.get("muted", True))
        room["volume"] = int(slot.get("volume", default_volume))
        room["quality"] = int(slot.get("quality", 250))
        room["audio_channel"] = int(slot.get("audio_channel", 0))
        room["video_danmaku_enabled"] = bool(slot.get("video_danmaku_enabled", False))
        room["video_danmaku_overrides"] = settings_api.video_danmaku_overrides(slot.get("video_danmaku_overrides"))
        room["codec_overrides"] = settings_api.codec_overrides(slot.get("codec_overrides"))
        wall.append(room)
    return sidebar, wall
