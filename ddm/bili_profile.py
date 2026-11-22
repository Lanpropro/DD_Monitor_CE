"""Public Bilibili account-to-live-room lookup, without account credentials."""
import requests


class BiliProfileError(ValueError):
    def __init__(self, message):
        super().__init__(message)
        self.user_message = message


def room_for_uid(uid: str) -> str:
    with requests.get('https://api.live.bilibili.com/room/v1/Room/getRoomInfoOld',
                      params={'mid': uid}, headers={'User-Agent': 'Mozilla/5.0',
                      'Referer': 'https://live.bilibili.com/'}, timeout=(3, 8)) as response:
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict) or payload.get('code') != 0:
        raise BiliProfileError('B 站个人主页查询失败，请稍后重试')
    data = payload.get('data')
    if not isinstance(data, dict):
        raise BiliProfileError('B 站个人主页未返回有效的直播间资料，请稍后重试')
    if data.get('roomStatus') == 0:
        raise BiliProfileError('该 B 站账号尚未开通直播间')
    room_id = str(data.get('roomid') or '')
    if room_id.isascii() and room_id.isdecimal() and room_id.strip('0'):
        return room_id.lstrip('0')
    raise BiliProfileError('B 站个人主页未返回有效的直播间号，请稍后重试')
