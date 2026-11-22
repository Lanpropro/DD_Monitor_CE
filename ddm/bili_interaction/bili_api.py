"""Bilibili HTTP operations; no global host credentials or automatic POST retry."""
import threading
import time
import requests

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36'
HEADERS = {'User-Agent': UA, 'Referer': 'https://live.bilibili.com/'}
_device_lock = threading.Lock()
_device = ''

class BiliAPIError(ValueError):
    def __init__(self,message,code=None):
        super().__init__(message)
        self.code=code
        self.login_required=code in (-101,-111)

def ensure_buvid3():
    global _device
    with _device_lock:
        if not _device:
            response = requests.get('https://api.bilibili.com/x/frontend/finger/spi', headers=HEADERS, timeout=10)
            data = api_result(response).get('data') or {}
            value = data.get('b_3')
            if not isinstance(value, str) or not value.strip():
                raise ValueError('无法取得 B 站浏览器标识')
            _device = value.strip()
        return _device

def prepare_cookies(cookies):
    snapshot = dict(cookies)
    if not snapshot.get('buvid3'):
        snapshot['buvid3'] = ensure_buvid3()
    return snapshot

def resolve_room(room_id, *, cookies):
    room_id = str(room_id or '').strip()
    if not room_id.isascii() or not room_id.isdigit() or not room_id.strip('0'):
        raise ValueError('仅支持有效的 B 站直播间')
    response = requests.get('https://api.live.bilibili.com/room/v1/Room/room_init',
        params={'id': room_id}, headers=HEADERS, cookies=dict(cookies), timeout=10)
    data = api_result(response).get('data') or {}
    real_id, uid = data.get('room_id'), data.get('uid')
    if not str(real_id or '').isdigit() or int(real_id) <= 0 or not str(uid or '').isdigit() or int(uid) <= 0:
        raise ValueError('直播间信息格式异常')
    return str(real_id), int(uid)

def api_result(response) -> dict:
    response.raise_for_status()
    if not 200 <= response.status_code < 300:
        raise ValueError("B 站接口未接受请求")
    payload = response.json()
    if not isinstance(payload, dict) or payload.get("code") != 0:
        reason = (payload.get("message") or payload.get("msg")) if isinstance(payload, dict) else None
        raise BiliAPIError(str(reason or "B 站接口返回异常"),payload.get("code") if isinstance(payload,dict) else None)
    return payload


def _sending_room_id(room_id: str, cookies: dict) -> str:
    room_id = str(room_id or "").strip()
    if not room_id.isascii() or not room_id.isdigit() or not room_id.strip("0"):
        raise ValueError("仅支持有效的 B 站直播间")
    return resolve_room(room_id, cookies=cookies)[0]


def send_danmaku(room_id: str, message: str, *, dm_type: int = 0,
                 cookies: dict, still_current=lambda: True) -> dict:
    """发送文字或完整大表情标识；POST 不自动重试，避免超时后重复发送。"""
    if not isinstance(message, str) or not message.strip() or dm_type not in (0, 1):
        raise ValueError("弹幕内容或类型无效")
    snapshot = dict(cookies)
    if not snapshot.get("SESSDATA"):
        raise ValueError("请先登录 B 站")
    if not snapshot.get("bili_jct"):
        raise ValueError("登录缺少 bili_jct，请退出 B 站账号后重新登录")
    real_id = _sending_room_id(room_id, snapshot)
    if not snapshot.get("buvid3"):
        snapshot["buvid3"] = ensure_buvid3()
    if not still_current():
        raise ValueError("请求上下文已改变，已取消发送")
    csrf = snapshot["bili_jct"]
    response = requests.post(
        "https://api.live.bilibili.com/msg/send",
        data={"roomid": real_id, "msg": message, "dm_type": str(dm_type),
              "rnd": str(int(time.time())), "fontsize": "25", "color": "16777215",
              "mode": "1", "bubble": "0", "csrf": csrf, "csrf_token": csrf},
        headers={**HEADERS, "Origin": "https://live.bilibili.com",
                 "Referer": f"https://live.bilibili.com/{real_id}"},
        cookies=snapshot, timeout=10, allow_redirects=False)
    payload = api_result(response)
    # 有些拒绝仍返回 code=0（包括 message="f"），不能据此清空草稿。
    data = payload.get("data")
    for section in (payload, data if isinstance(data, dict) else {}):
        for key in ("message", "msg"):
            reason = section.get(key)
            if reason not in (None, "", "0", 0):
                raise ValueError("发送未成功，请稍后重试" if reason == "f" else str(reason))
    return payload


def get_emoticons(room_id: str, *, cookies: dict) -> list[dict]:
    """保留服务端表情类型、完整标识和解锁权限；设备身份复用接收弹幕的缓存。"""
    snapshot = dict(cookies)
    real_id = _sending_room_id(room_id, snapshot)
    if not snapshot.get("buvid3"):
        snapshot["buvid3"] = ensure_buvid3()
    response = requests.get(
        "https://api.live.bilibili.com/xlive/web-ucenter/v2/emoticon/GetEmoticons",
        params={"platform": "pc", "room_id": real_id},
        headers=HEADERS, cookies=snapshot, timeout=10)
    data = api_result(response).get("data")
    packages = data.get("data") if isinstance(data, dict) else None
    if not isinstance(packages, list) or any(not isinstance(p, dict) for p in packages):
        raise ValueError("表情列表格式异常，请重试")
    for package in packages:
        emotes = package.get("emoticons")
        if emotes is not None and (not isinstance(emotes, list) or any(not isinstance(e, dict) for e in emotes)):
            raise ValueError("表情列表格式异常，请重试")
    return packages
