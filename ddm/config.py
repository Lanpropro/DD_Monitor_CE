"""配置读写。

状态（关注了哪些房间、画面墙上有哪些、每格的静音/音量/画质、界面状态）
写在仓库的 utils/config.json。新用户第一次打开时是空的，房间靠自己添加。
"""
import io
import json
import os
import shutil

from . import bili

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(REPO, "utils", "config.json")

DEFAULT_VOLUME = 42

# 全局设置默认值（设置菜单里可改，存在配置文件的 settings 段）
DEFAULT_SETTINGS = {
    "poll_minutes": 1,        # 关注列表直播状态轮询间隔（分钟）
    "auto_quality": True,     # 主画面自动原画、其余 720P
    "auto_reconnect": True,   # 断流自动重连
    "freeze_watch": True,     # 画面卡死检测（可能对静止画面误报）
    "default_muted": True,    # 新加进画面墙的直播间默认静音
    "default_volume": DEFAULT_VOLUME,
    "preview_on_hover": True,   # 鼠标停在关注列表的直播上 2 秒，弹个小画面预览
    "live_alert": True,         # 关注的主播开播时，列表上播水滴 + 「开播了」气泡
    "danmaku_font": "",       # 弹幕字体（空 = 跟主题默认字体）
    "danmaku_font_size": 13,  # 弹幕字号（面板上也能拖滑块实时改）
    "danmaku_max_blocks": 300,  # 弹幕最多留多少条（超了就从最早的开始丢）
    "danmaku_block_words": [],  # 屏蔽词：弹幕里包含这些词就不显示
}

STATE_VERSION = 1


def _read_json(path: str) -> dict:
    try:
        with io.open(path, "r", encoding="utf-8", errors="ignore") as handle:
            return json.loads(handle.read()) or {}
    except Exception as error:  # noqa: BLE001
        print(f"配置读取失败 {path}: {error}")
        return {}


def _unique(values) -> list[str]:
    result: list[str] = []
    for value in values:
        text = str(value)
        if text in ("", "0") or text in result:
            continue
        result.append(text)
    return result


def load() -> dict:
    """读取配置；没有配置文件就是全新的空状态。"""
    if os.path.isfile(CONFIG_PATH):
        state = _read_json(CONFIG_PATH)
        if state.get("version"):
            return state
    backup = CONFIG_PATH + ".bak"
    if os.path.isfile(backup):          # 主配置坏了就回退到上一次的备份
        state = _read_json(backup)
        if state.get("version"):
            print(f"主配置不可用，已回退到备份 {backup}")
            return state
    return {}


def save(state: dict) -> None:
    if os.environ.get("DDM_NO_SAVE"):   # 自检/预览脚本用这个开关，避免动到真实配置
        return
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    try:
        if os.path.isfile(CONFIG_PATH):
            shutil.copyfile(CONFIG_PATH, CONFIG_PATH + ".bak")   # 先留一份上一次的配置
        with io.open(CONFIG_PATH, "w", encoding="utf-8", errors="ignore") as handle:
            handle.write(json.dumps(state, ensure_ascii=False, indent=2))
    except Exception as error:  # noqa: BLE001
        print(f"配置写入失败: {error}")


def build_rooms(state: dict) -> tuple[list[dict], list[dict]]:
    """(侧栏房间, 画面墙房间)。房间信息实时拉取，格子设置从配置里带。"""
    room_ids = _unique(state.get("rooms", []))
    wall_slots = state.get("wall", []) or []
    wall_ids = _unique(slot.get("room_id", "") for slot in wall_slots)

    infos: dict[str, dict] = {}
    for room_id in _unique(room_ids + wall_ids):
        info = bili.room_info(room_id)
        infos[room_id] = info or {
            "room_id": room_id, "uname": f"房间 {room_id}",
            "title": "", "live": False, "viewers": "",
        }

    sidebar = [infos[room_id] for room_id in room_ids if room_id in infos]
    wall = []
    for slot in wall_slots:
        room_id = str(slot.get("room_id") or "")
        if not room_id:
            wall.append({"room_id": ""})        # 空格子：布局里保留位置
            continue
        room = dict(infos.get(room_id) or {})
        room["muted"] = bool(slot.get("muted", True))
        room["volume"] = int(slot.get("volume", DEFAULT_VOLUME))
        room["quality"] = int(slot.get("quality", 250))
        room["audio_channel"] = int(slot.get("audio_channel", 0))
        wall.append(room)
    return sidebar, wall
