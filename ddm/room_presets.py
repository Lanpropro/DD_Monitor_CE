"""Named wall snapshots: validate only the fields belonging to a room combination."""
from copy import deepcopy

from . import layouts, resize_layout


def collection(value):
    if not isinstance(value, dict):
        return {"version": 1, "items": []}
    items = value.get("items", [])
    result = [deepcopy(item) for item in items if isinstance(item, dict)] if isinstance(items, list) else []
    from uuid import uuid4
    seen = set()
    for item in result:
        key = item.get("id")
        if not isinstance(key, str) or not key or key in seen:
            item["id"] = uuid4().hex
        seen.add(item["id"])
    return {"version": value.get("version", 1), "items": result}


def partition(identifier):
    preset = layouts.BY_ID[identifier]
    if layouts.is_portrait_layout(identifier):
        small = len(preset["spec"][2]) - 1 - int(preset.get("danmaku") is not None)
        return resize_layout.portrait_partition(small, preset.get("danmaku") is not None,
                                               layouts.PORTRAIT_SMALL_COLUMNS)
    return resize_layout.build_partition(preset["spec"][2])


def validate(snapshot):
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("layout"), dict):
        raise ValueError("组合数据不完整")
    source = snapshot["layout"]
    identifier = source.get("id")
    if not isinstance(identifier, str) or identifier not in layouts.BY_ID:
        raise ValueError("该组合使用的布局暂不支持")
    count = layouts.capacity(identifier)
    default_dm = layouts.danmaku_cell(identifier)
    dm = source.get("danmaku_cell")
    if default_dm is None:
        if dm is not None:
            raise ValueError("当前布局不能放置弹幕格")
    elif type(dm) is not int or not 0 <= dm < count or (
            layouts.is_portrait_layout(identifier) and dm != default_dm):
        raise ValueError("弹幕格位置无效")
    ratios = source.get("ratios")
    if not isinstance(ratios, dict):
        raise ValueError("布局比例无效")
    if identifier == "corner":
        values = [ratios.get(key) for key in ("width", "height", "right")]
        bottom = ratios.get("bottom")
        if not isinstance(bottom, (list, tuple)) or len(bottom) != 2:
            raise ValueError("布局比例无效")
        if not all(type(v) in (int, float) and 0 < v < 1 for v in values + list(bottom)):
            raise ValueError("布局比例无效")
        if bottom[0] >= bottom[1]:
            raise ValueError("布局比例无效")
        ratios = dict(zip(("width", "height", "right"), values), bottom=list(bottom))
    else:
        weights = resize_layout.validated_weights(ratios, partition(identifier))
        if set(weights) != set(ratios):
            raise ValueError("布局比例无效")
        ratios = weights
    slots = snapshot.get("slots")
    cells = set(range(count)) - {dm}
    if not isinstance(slots, list) or len(slots) != len(cells):
        raise ValueError("直播格子数量与布局不一致")
    result, seen, rooms = [], set(), set()
    for slot in slots:
        if not isinstance(slot, dict):
            raise ValueError("直播格子数据无效")
        cell, rid = slot.get("cell"), slot.get("room_id")
        if type(cell) is not int or cell not in cells or cell in seen:
            raise ValueError("直播格子位置重复或越界")
        if not isinstance(rid, str) or (rid and rid in rooms):
            raise ValueError("直播间标识无效或重复")
        volume, channel, muted = slot.get("volume"), slot.get("audio_channel"), slot.get("muted")
        if type(volume) is not int or not 0 <= volume <= 100:
            raise ValueError("音量必须在 0～100 之间")
        if type(channel) is not int or channel not in range(6) or type(muted) is not bool:
            raise ValueError("声道或静音状态无效")
        seen.add(cell)
        if rid:
            rooms.add(rid)
        label = slot.get("label")
        result.append(dict(cell=cell, room_id=rid, volume=volume, muted=muted,
                           audio_channel=channel, label=label if isinstance(label, str) else rid))
    return {"layout": dict(id=identifier, ratios=deepcopy(ratios), danmaku_cell=dm),
            "slots": sorted(result, key=lambda slot: slot["cell"])}


def same(first, second):
    """Names and cached labels are presentation; compare the saved wall state only."""
    def canonical(value):
        if isinstance(value, dict):
            return {k: canonical(v) for k, v in value.items() if k not in ("label", "name", "id")}
        if isinstance(value, list):
            return [canonical(v) for v in value]
        return round(value, 10) if isinstance(value, float) else value
    # The layout ID must participate even though collection item IDs do not.
    return (first["layout"]["id"] == second["layout"]["id"]
            and canonical(first) == canonical(second))


def thumbnail_geometry(snapshot, area):
    """Use the same partition geometry as playback; no screenshot or player is created."""
    from PySide6.QtCore import QSize
    identifier = snapshot["layout"]["id"]
    ratios = snapshot["layout"]["ratios"]
    if identifier == "corner":
        bottom = ratios["bottom"]
        ratios = {"root": [ratios["height"], 1 - ratios["height"]],
                  "root/0": [ratios["width"], 1 - ratios["width"]],
                  "root/0/1": [ratios["right"], 1 - ratios["right"]],
                  "root/1": [bottom[0], bottom[1] - bottom[0], 1 - bottom[1]]}
    def defaults(node, rect):
        if node.key != "root" or not layouts.is_portrait_layout(identifier):
            return node.weights
        main = rect.width() * 9 / 16
        dm = rect.height() * .22 if snapshot["layout"]["danmaku_cell"] is not None else 0
        small = max(1, rect.height() - main - dm - 3 * (len(node.children) - 1))
        return [main, small, dm] if dm else [main, small]
    return resize_layout.geometry(partition(identifier), area, 3, lambda _: QSize(1, 1),
                                  ratios, defaults)[0]
