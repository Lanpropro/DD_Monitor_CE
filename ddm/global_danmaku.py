"""Twitch 匿名只读 IRC 与 YouTube 公开直播聊天。"""
import asyncio
from collections import deque
import json
import random
import re
from urllib.parse import urlsplit
from urllib.request import getproxies, proxy_bypass

import aiohttp

from .live_danmaku import LiveDanmakuClient, MAX_PACKET


def request_proxy(url):
    """与 requests 取流一致，遵循系统/环境代理，WebSocket 也使用 HTTPS 代理。"""
    parts = urlsplit(url)
    if proxy_bypass(parts.hostname):
        return None
    scheme = "https" if parts.scheme == "wss" else parts.scheme
    proxies = getproxies()
    return proxies.get(scheme) or proxies.get("all")


def page_json(page, name):
    match = re.search(r"\b" + re.escape(name) + r"\s*=\s*", page)
    if not match:
        return {}
    value, _ = json.JSONDecoder().raw_decode(page[match.end():].lstrip())
    return value if isinstance(value, dict) else {}


def renderers(value, name):
    if isinstance(value, dict):
        if isinstance(value.get(name), dict):
            yield value[name]
        for child in value.values():
            yield from renderers(child, name)
    elif isinstance(value, list):
        for child in value:
            yield from renderers(child, name)


def youtube_config(page):
    result = {}
    for match in re.finditer(r"\bytcfg\.set\(\s*(?=\{)", page):
        try:
            value, _ = json.JSONDecoder().raw_decode(page[match.end():].lstrip())
        except json.JSONDecodeError:
            continue  # 页面还会 set 含 window 变量的 JS 对象；它们不是访客配置。
        if isinstance(value, dict):
            result.update(value)
    return result


def text_runs(value):
    return value.get("simpleText", "") or "".join(
        run.get("text", "") or next(iter(run.get("emoji", {}).get("shortcuts", [])), "")
        for run in value.get("runs", []))


def irc_message(line):
    tags, prefix = {}, ""
    if line.startswith("@"):
        head, line = line[1:].split(" ", 1)
        escapes = {"s": " ", ":": ";", "\\": "\\", "r": "\r", "n": "\n"}
        for part in head.split(";"):
            key, _, value = part.partition("=")
            tags[key] = re.sub(r"\\(.)", lambda match: escapes.get(match[1], match[1]), value)
    if line.startswith(":"):
        prefix, line = line[1:].split(" ", 1)
    head, separator, tail = line.partition(" :")
    fields = head.split()
    if not fields:
        raise ValueError("Empty IRC message")
    return tags, prefix, fields[0], fields[1:], tail if separator else ""


def chat_page(page):
    player = page_json(page, "ytInitialPlayerResponse")
    data = page_json(page, "ytInitialData")
    renderer = next(renderers(data, "liveChatRenderer"), {})
    token, _ = chat_continuation(renderer)
    return player, youtube_config(page), token


def chat_continuation(data):
    for item in data.get("continuations", []):
        for name in ("timedContinuationData", "invalidationContinuationData", "reloadContinuationData"):
            value = item.get(name, {})
            if value.get("continuation"):
                return value["continuation"], max(.5, min(float(value.get("timeoutMs", 2000)) / 1000, 15))
    return "", 2


def youtube_events(data):
    for action in data.get("actions", []):
        item = action.get("addChatItemAction", {}).get("item", {}).get("liveChatTextMessageRenderer", {})
        text = text_runs(item.get("message", {}))
        if text and item.get("id"):
            yield item["id"], {"kind": "danmaku", "uname": text_runs(item.get("authorName", {})), "text": text}


class GlobalDanmakuClient(LiveDanmakuClient):
    def __init__(self, room_id, platform, parent=None):
        super().__init__(room_id, platform, parent)
        self._recent = deque()
        self._seen = set()

    def _emit_once(self, identifier, event):
        if identifier and identifier in self._seen:
            return
        if identifier:
            self._seen.add(identifier)
            self._recent.append(identifier)
            if len(self._recent) > 2048:
                self._seen.remove(self._recent.popleft())
        self.message.emit(event)

    async def _websocket(self, session, retries):
        if self.platform.kind == "twitch":
            await self._twitch(session)
        else:
            await self._youtube(session)

    async def _twitch(self, session):
        channel = "#" + self.room_id.split(":", 1)[1]
        async with session.ws_connect("wss://irc-ws.chat.twitch.tv:443",
                proxy=request_proxy("wss://irc-ws.chat.twitch.tv:443"),
                timeout=aiohttp.ClientWSTimeout(ws_receive=300, ws_close=1), max_msg_size=MAX_PACKET) as ws:
            await ws.send_str("CAP REQ :twitch.tv/tags twitch.tv/commands\r\n")
            await ws.send_str(f"NICK justinfan{random.randrange(100000, 999999)}\r\n")
            buffer, connected = "", False
            async for packet in ws:
                if packet.type == aiohttp.WSMsgType.ERROR:
                    raise OSError("IRC receive error")
                if packet.type != aiohttp.WSMsgType.TEXT:
                    continue
                buffer += packet.data
                if len(buffer) > MAX_PACKET:
                    raise ValueError("IRC message too large")
                while "\r\n" in buffer:
                    line, buffer = buffer.split("\r\n", 1)
                    if not line:
                        continue
                    tags, prefix, command, params, tail = irc_message(line)
                    if command == "PING":
                        await ws.send_str("PONG :" + (tail or " ".join(params)) + "\r\n")
                    elif command == "001":
                        await ws.send_str(f"JOIN {channel}\r\n")
                    elif command in ("366", "ROOMSTATE") and channel in params and not connected:
                        self.status.emit("已连接")
                        connected = True
                    elif command == "PRIVMSG" and params == [channel] and tail:
                        self._emit_once(tags.get("id", ""), {"kind": "danmaku",
                            "uname": tags.get("display-name") or prefix.split("!", 1)[0], "text": tail})
                    elif command in ("RECONNECT", "464") or (command == "NOTICE" and
                            tags.get("msg-id") in ("msg_channel_suspended", "msg_banned", "msg_room_not_found")):
                        raise ValueError("IRC subscription rejected")
        raise OSError("IRC closed")

    async def _youtube(self, session):
        url = self.platform.room_url(self.room_id)
        async with session.get(url, params={"hl": "en"}, proxy=request_proxy(url)) as response:
            response.raise_for_status()
            player, config, token = chat_page(await response.text())
        details = player.get("videoDetails", {})
        if not details:
            raise ValueError("Missing YouTube player")
        if not details.get("isLive"):
            self.status.emit("主播未开播")
            await asyncio.sleep(30)
            return
        if not token:
            self.status.emit("该直播未启用聊天")
            await asyncio.sleep(30)
            return
        context = config["INNERTUBE_CONTEXT"]
        headers = {"Referer": url, "Origin": "https://www.youtube.com"}
        visitor = context.get("client", {}).get("visitorData")
        if visitor:
            headers["X-Goog-Visitor-Id"] = visitor
        connected = False
        while not self._stopped.is_set():
            async with session.post("https://www.youtube.com/youtubei/v1/live_chat/get_live_chat",
                    proxy=request_proxy("https://www.youtube.com"),
                    params={"key": config["INNERTUBE_API_KEY"]} if config.get("INNERTUBE_API_KEY") else {},
                    headers=headers, json={"context": context, "continuation": token}) as response:
                response.raise_for_status()
                payload = await response.json()
            data = payload.get("continuationContents", {}).get("liveChatContinuation")
            if not isinstance(data, dict):
                raise ValueError("Missing YouTube live chat response")
            first_response = not connected
            if first_response:
                self.status.emit("已连接")
                connected = True
            for identifier, event in youtube_events(data):
                self._emit_once(identifier, event)
            token, delay = chat_continuation(data)
            if first_response:
                # watch 页的筛选 token 仅用于 UI；首个 API 回包才提供可用的完整聊天 token。
                menu = next(renderers(data, "sortFilterSubMenuRenderer"), {})
                items = menu.get("subMenuItems", [])
                if len(items) > 1:
                    token = items[1].get("continuation", {}).get("reloadContinuationData", {}).get("continuation") or token
            if not token:
                raise ValueError("YouTube live chat ended")
            await asyncio.sleep(delay)
