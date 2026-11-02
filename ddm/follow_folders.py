"""关注分组规则：保留手动归属，按来源及条件计算智能文件夹显示。"""
from copy import deepcopy

UNCLASSIFIED = "__unclassified__"
SORT_MODES = [("custom", "自定义顺序（拖动调整）"), ("live", "开播优先"),
              ("frequent", "常看优先"),
              ("offline", "未开播优先"), ("imported", "导入顺序"), ("name", "主播名称")]
PLATFORM_NAMES = {"bilibili": "哔哩哔哩", "huya": "虎牙", "douyu": "斗鱼",
                  "douyin": "抖音", "twitch": "Twitch", "youtube": "YouTube"}
ICON_NAMES = ("folder", "star", "heart", "game", "music", "video")
ICON_COLORS = ("default", "blue", "pink", "green", "orange", "purple")


def normalize_icon(value):
    if not isinstance(value, dict):
        return None
    if value.get("type") == "builtin" and value.get("name") in ICON_NAMES and value.get("color") in ICON_COLORS:
        return {"type": "builtin", "name": value["name"], "color": value["color"]}
    path = value.get("path")
    if value.get("type") == "image" and isinstance(path, str):
        parts = path.split("/")
        if len(parts) == 3 and parts[:2] == ["utils", "folder-icons"] and parts[2].endswith(".png"):
            stem = parts[2][:-4]
            if len(stem) == 32 and all(c in "0123456789abcdef" for c in stem):
                return {"type": "image", "path": path}
    return None


def normalize_folders(folders, default_sort="custom"):
    default_id = next((str(source.get("id")) for source in folders or []
                       if source.get("type") == "unclassified" and source.get("id")), None)
    result, ids, assigned = [], set(), set()
    for source in folders or []:
        fid, name = str(source.get("id") or ""), str(source.get("name") or "").strip()
        if not fid or not name or fid in ids:
            continue
        kind = "unclassified" if fid == default_id or (
            default_id is None and fid == UNCLASSIFIED and source.get("type") != "normal") else (
            "smart" if source.get("type") == "smart" else "normal")
        rooms = list(dict.fromkeys(str(key) for key in source.get("rooms", [])
                                   if str(key) and str(key) not in assigned)) if kind != "smart" else []
        assigned.update(rooms)
        mode = source.get("sort", default_sort)
        folder = {"id": fid, "name": name,
                  "type": kind, "collapsed": bool(source.get("collapsed")), "rooms": rooms,
                  "sort": mode if mode in dict(SORT_MODES) else "custom"}
        icon = normalize_icon(source.get("icon"))
        if icon is not None:
            folder["icon"] = icon
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
    if not any(folder["type"] == "unclassified" for folder in result):
        fallback = next((folder for folder in result if folder["id"] == UNCLASSIFIED), None)
        if fallback is not None:
            fallback["type"] = "unclassified"
        else:
            result.append({"id": UNCLASSIFIED, "name": "未分类", "type": "unclassified",
                           "collapsed": False, "rooms": [], "sort": default_sort})
    for folder in result:
        if folder["type"] == "smart":
            folder["rule"].setdefault("sources", [default_folder(result)["id"]])
    return result


def default_folder(folders):
    return next((folder for folder in folders or [] if folder.get("type") == "unclassified"),
                {"id": UNCLASSIFIED, "name": "未分类", "type": "unclassified"})


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
    manual = {rid: folder["id"] for folder in folders if folder["type"] != "smart"
              for rid in folder["rooms"]}
    rule = folder["rule"]
    default_id = default_folder(folders)["id"]
    sources = rule.get("sources", [default_id])
    # 平台和来源在导入时已知，只有直播状态条件需要等待状态刷新。
    return {str(room["room_id"]) for room in rooms
            if (rule.get("status", "any") == "any" or str(room["room_id"]) not in pending)
            and (not sources or manual.get(str(room["room_id"]), default_id) in sources)
            and matches_rule(room, rule)}


def assign_folders(rooms, folders, pending=()):
    manual = {rid: folder["id"] for folder in folders if folder["type"] != "smart"
              for rid in folder["rooms"]}
    smart = [(folder, smart_members(rooms, folders, folder, pending)) for folder in folders
             if folder["type"] == "smart" and folder["rule"].get("display") != "copy"]
    default_id = default_folder(folders)["id"]
    result = {}
    for room in rooms:
        rid = str(room.get("room_id"))
        result[rid] = next((folder["id"] for folder, members in smart if rid in members),
                           manual.get(rid, default_id))
    return result


def folder_state(folders):
    return deepcopy(folders)
