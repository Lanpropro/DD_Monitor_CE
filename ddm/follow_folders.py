"""关注分组规则：保留手动归属，按来源及条件计算智能文件夹显示。"""
from copy import deepcopy

UNCLASSIFIED = "__unclassified__"
SORT_MODES = [("custom", "自定义顺序（拖动调整）"), ("live", "开播优先"),
              ("offline", "未开播优先"), ("imported", "导入顺序"), ("name", "主播名称")]
PLATFORM_NAMES = {"bilibili": "哔哩哔哩", "huya": "虎牙", "douyu": "斗鱼",
                  "douyin": "抖音", "twitch": "Twitch", "youtube": "YouTube"}


def normalize_folders(folders, default_sort="custom"):
    result, ids, assigned = [], set(), set()
    for source in folders or []:
        fid, name = str(source.get("id") or ""), str(source.get("name") or "").strip()
        if not fid or not name or fid in ids:
            continue
        kind = "unclassified" if fid == UNCLASSIFIED else (
            "smart" if source.get("type") == "smart" else "normal")
        rooms = list(dict.fromkeys(str(key) for key in source.get("rooms", [])
                                   if str(key) and str(key) not in assigned)) if kind == "normal" else []
        assigned.update(rooms)
        mode = source.get("sort", default_sort)
        folder = {"id": fid, "name": "未分类" if fid == UNCLASSIFIED else name,
                  "type": kind, "collapsed": bool(source.get("collapsed")), "rooms": rooms,
                  "sort": mode if mode in dict(SORT_MODES) else "custom"}
        if kind == "smart":
            rule = source.get("rule") or {}
            status = rule.get("status", "any")
            folder["rule"] = {"status": status if status in ("any", "live", "offline") else "any",
                              "platforms": list(dict.fromkeys(rule.get("platforms") or []))}
            if "sources" in rule:
                folder["rule"]["sources"] = list(dict.fromkeys(rule.get("sources") or []))
            if "display" in rule:
                folder["rule"]["display"] = "copy" if rule["display"] == "copy" else "move"
        result.append(folder)
        ids.add(fid)
    if UNCLASSIFIED not in ids:
        result.append({"id": UNCLASSIFIED, "name": "未分类", "type": "unclassified",
                       "collapsed": False, "rooms": [], "sort": default_sort})
    return result


def room_platform(room):
    platform = room.get("platform") or str(room.get("room_id", "")).partition(":")[0]
    if ":" not in str(room.get("room_id", "")) and not room.get("platform"):
        platform = "bilibili"
    return platform


def matches_rule(room, rule):
    platform = room_platform(room)
    platforms = rule.get("platforms") or []
    if platforms and platform not in platforms:
        return False
    status = rule.get("status", "any")
    if status == "any":
        return True
    if not room.get("live_known", True) or "live" not in room:
        return False
    return bool(room["live"]) == (status == "live")


def smart_members(rooms, folders, folder, pending=()):
    """来源是原来的普通文件夹；空来源表示全部，旧规则沿用未分类范围。"""
    manual = {rid: folder["id"] for folder in folders if folder["type"] == "normal"
              for rid in folder["rooms"]}
    rule = folder["rule"]
    sources = rule.get("sources", [UNCLASSIFIED])
    return {str(room["room_id"]) for room in rooms
            if str(room["room_id"]) not in pending
            and (not sources or manual.get(str(room["room_id"]), UNCLASSIFIED) in sources)
            and matches_rule(room, rule)}


def assign_folders(rooms, folders, pending=()):
    manual = {rid: folder["id"] for folder in folders if folder["type"] == "normal"
              for rid in folder["rooms"]}
    smart = [(folder, smart_members(rooms, folders, folder, pending)) for folder in folders
             if folder["type"] == "smart" and folder["rule"].get("display") != "copy"]
    result = {}
    for room in rooms:
        rid = str(room.get("room_id"))
        result[rid] = next((folder["id"] for folder, members in smart if rid in members),
                           manual.get(rid, UNCLASSIFIED))
    return result


def folder_state(folders):
    return deepcopy(folders)
