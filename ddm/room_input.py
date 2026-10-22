"""Extract mobile share URLs and resolve Bilibili live-room short links."""
import re
from urllib.parse import urljoin, urlsplit

import requests


def extract_room_input(text: str) -> str:
    text = text.strip()
    urls = re.findall(r'https?://[^\s<>"\'【】“”‘’]+', text, re.IGNORECASE)
    if len(urls) > 1:
        raise ValueError('检测到多个链接，请每次添加一个直播间')
    return urls[0].rstrip('.,;:!?)]}，。；：！？、）') if urls else text


def bili_room_id(text: str) -> str:
    if text.isascii() and text.isdecimal():
        return text
    parts = urlsplit(text if '://' in text else 'https://' + text)
    if parts.scheme not in ('http', 'https') or parts.hostname != 'live.bilibili.com':
        return ''
    match = re.fullmatch(r'/(?:blanc/)?([0-9]+)/?', parts.path)
    return match.group(1) if match else ''


def is_bili_short_url(text: str) -> bool:
    parts = urlsplit(text)
    return (parts.scheme in ('http', 'https') and parts.hostname in ('b23.tv', 'www.b23.tv')
            and bool(re.fullmatch(r'/[A-Za-z0-9]+/?', parts.path)))


def resolve_bili_share(text: str) -> str:
    """Called by InfoResolver, never by the dialog's GUI-thread validation."""
    current = text
    for _ in range(3):
        if room_id := bili_room_id(current):
            return room_id
        if not is_bili_short_url(current):
            raise ValueError('分享链接没有指向 B 站直播间')
        with requests.get(current, headers={'User-Agent': 'Mozilla/5.0'},
                          timeout=(3, 5), allow_redirects=False, stream=True) as response:
            response.raise_for_status()
            target = response.headers.get('Location', '')
            if response.status_code not in (301, 302, 303, 307, 308) or not target:
                raise ValueError('分享链接未能跳转，请检查链接或稍后重试')
            current = urljoin(current, target)
    room_id = bili_room_id(current)
    if not room_id:
        raise ValueError('分享链接没有指向 B 站直播间')
    return room_id
