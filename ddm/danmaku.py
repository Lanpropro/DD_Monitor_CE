"""弹幕接入：一路一个后台线程，用 blivedm 连 B 站的弹幕服务器。

blivedm 是异步库，这里把它放进 QThread 里跑一个独立的事件循环；
收到的消息通过 Qt 信号回到界面线程（跨线程发信号本身是安全的）。
"""
import asyncio
import http.cookies
import json
import logging
import sys
import threading

from PySide6.QtCore import QThread, Signal

from . import bili
from . import config as config_module
from .super_chat import normalize as normalize_super_chat

# blivedm 在原仓库根目录，独立版也放在项目根目录
if config_module.REPO not in sys.path:
    sys.path.insert(0, config_module.REPO)

try:
    import aiohttp
    import yarl
    import blivedm
    from blivedm.clients import ws_base as blivedm_ws_base
    IMPORT_ERROR = ""
    # blivedm 会把没处理的消息类型（LIKE_INFO_V3_CLICK、INTERACT_WORD_V2…）
    # 一条条写进 stderr，控制台会被刷屏，这里只留错误
    logging.getLogger("blivedm").setLevel(logging.ERROR)
    logging.getLogger("blivedm").propagate = False
except Exception as error:              # noqa: BLE001
    # aiohttp / brotli 没装时，弹幕用不了，但别让整个程序起不来
    aiohttp = None
    blivedm = None
    blivedm_ws_base = None
    IMPORT_ERROR = f"{type(error).__name__}: {error}"


class DanmakuClient(QThread):
    """某个直播间的弹幕连接。"""

    message = Signal(dict)              # {kind, uname, text, super_chat…}
    status = Signal(str)                # 给界面显示的状态文字

    def __init__(self, room_id: str, parent=None):
        super().__init__(parent)
        self.room_id = str(room_id)
        self._loop = None
        self._client = None
        self._stopped = threading.Event()

    # ---- 线程外控制 ----
    def stop(self) -> None:
        """让事件循环把客户端停掉（线程结束后调用也没关系）。"""
        self._stopped.set()
        loop, client = self._loop, self._client
        if loop is None or client is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(client.stop)
        except RuntimeError:            # 循环已经停了
            pass

    # ---- 线程里跑 ----
    def run(self) -> None:
        if self._stopped.is_set():
            return
        if blivedm is None:
            self.status.emit(f"弹幕组件不可用（{IMPORT_ERROR}）")
            return
        try:
            room_id = int(self.room_id)
        except ValueError:
            self.status.emit("这个直播间没有弹幕（房间号不是数字）")
            return
        try:
            asyncio.run(self._main(room_id))
        except Exception as error:      # noqa: BLE001
            self.status.emit(f"弹幕连接出错：{error}")

    async def _main(self, room_id: int) -> None:
        self._loop = asyncio.get_running_loop()
        try:
            cookies = http.cookies.SimpleCookie()
            for name, value in bili._cookies().items():
                cookies[name] = value
                cookies[name]["domain"] = "bilibili.com"
            async with aiohttp.ClientSession(
                    headers=bili.HEADERS,
                    timeout=aiohttp.ClientTimeout(total=None, connect=15)) as session:
                session.cookie_jar.update_cookies(cookies)
                try:
                    if self._stopped.is_set():
                        return
                    self.status.emit("连接中…")
                    client = _Client(room_id, session=session, on_status=self.status.emit)
                    client.set_handler(_Handler(self.message.emit))
                    self._client = client
                    client.start()
                    if self._stopped.is_set():
                        client.stop()
                    await client.join()
                finally:
                    client = self._client
                    self._client = None
                    if client is not None:
                        await client.stop_and_close()
        finally:
            self._loop = None


if blivedm is not None:
    _ClientBase = blivedm.BLiveClient
    _HandlerBase = blivedm.BaseHandler
else:                                     # 上游库缺失时的占位，保证模块能导入

    class _ClientBase:
        pass

    class _HandlerBase:
        pass


class _Client(_ClientBase):
    """共用持久化的浏览器身份，初始化和重连时刷新签名凭据。"""

    def __init__(self, room_id, *, session=None, hosts=None, token="", on_status=None):
        super().__init__(room_id, session=session)
        self._room_id = int(room_id)
        self._room_owner_uid = 0
        self._host_server_list = list(hosts or [])
        self._host_server_token = token or None
        self._on_status = on_status
        self._authenticated = False
        self._auth_failed = False
        self._stopping = False

    async def init_room(self) -> bool:
        """UID、设备 Cookie、token 和 WebSocket 来自同一个会话快照。"""
        if self._uid is None:
            try:
                ready = await self._init_uid()
            except (aiohttp.ClientError, OSError, ValueError, KeyError, TypeError) as error:
                raise aiohttp.ClientConnectionError("Unable to initialize danmaku user") from error
            if not ready:
                raise aiohttp.ClientConnectionError("Unable to initialize danmaku user")
        if not self._get_buvid():
            await self._init_buvid()
        cookies = {name: cookie.value for name, cookie in
                   self._session.cookie_jar.filter_cookies(yarl.URL(blivedm.clients.web.UID_INIT_URL)).items()}
        try:
            real_id, token, hosts = await asyncio.to_thread(
                bili.danmaku_conf, str(self._tmp_room_id), cookies=cookies,
                user_agent=self._session.headers.get("User-Agent", bili.UA))
        except (OSError, ValueError) as error:
            raise aiohttp.ClientConnectionError("Unable to load danmaku servers") from error
        if not hosts:
            if self._on_status is not None:
                self._on_status("拿不到弹幕服务器，准备重试…（网络或风控问题）")
            raise aiohttp.ClientConnectionError("No danmaku servers available")
        self._room_id = real_id or self._tmp_room_id
        self._host_server_list = list(hosts)
        self._host_server_token = token or None
        return True

    async def _init_buvid(self):
        try:
            value = await asyncio.to_thread(bili.ensure_buvid3)
        except (OSError, ValueError) as error:
            raise aiohttp.ClientConnectionError("Unable to initialize browser identity") from error
        cookies = http.cookies.SimpleCookie()
        cookies["buvid3"] = value
        cookies["buvid3"]["domain"] = "bilibili.com"
        self._session.cookie_jar.update_cookies(cookies)
        return True

    async def _on_ws_connect(self):
        self._authenticated = False
        self._auth_failed = False
        if self._on_status is not None:
            self._on_status("连接中…")
        await super()._on_ws_connect()

    async def _parse_business_message(self, header, body):
        """必须等服务端鉴权响应成功，才能向界面报告“已连接”。"""
        try:
            await super()._parse_business_message(header, body)
        except blivedm_ws_base.AuthError:
            self._auth_failed = True
            if self._on_status is not None:
                self._on_status("弹幕鉴权失败，准备切换服务器…")
            raise
        if header.operation == blivedm_ws_base.Operation.AUTH_REPLY:
            self._authenticated = True
            if self._on_status is not None:
                self._on_status("已连接")

    async def _on_ws_close(self):
        was_authenticated = self._authenticated
        await super()._on_ws_close()
        self._authenticated = False
        if self._stopping or self._on_status is None or self._auth_failed:
            return
        if was_authenticated:
            self._on_status("弹幕连接中断，准备重连…")
        else:
            self._on_status("弹幕连接失败，准备切换服务器…")

    def stop(self):
        self._stopping = True
        super().stop()

    async def _on_before_ws_connect(self, retry_count):
        self._authenticated = False
        if retry_count:
            self._need_init_room = True  # 普通断线也刷新凭据，不等到鉴权拒绝后才换 token。
        if self._on_status is not None:
            self._on_status(f"重连中…（第 {retry_count} 次）" if retry_count else "连接中…")
        await super()._on_before_ws_connect(retry_count)


class _Handler(_HandlerBase):
    """把 blivedm 的回调转成一条条信号（带粉丝牌和表情信息）。"""

    def __init__(self, emit):
        super().__init__()
        self._emit = emit

    def _on_danmaku(self, client, message):
        emoticon = message.emoticon_options_dict if message.dm_type == 1 else {}
        # Text messages can contain several inline emotes in mode_info.extra.
        mode_info = getattr(message, "mode_info", {})
        extra = mode_info.get("extra", {}) if isinstance(mode_info, dict) else {}
        if isinstance(extra, str):
            try:
                extra = json.loads(extra)
            except (ValueError, TypeError):
                extra = {}
        emotes = extra.get("emots", {}) if isinstance(extra, dict) else {}
        emotes = emotes if isinstance(emotes, dict) else {}
        self._emit({
            "kind": "danmaku",
            "uname": message.uname,
            "text": message.msg,
            "self_sent": bool(getattr(client, "uid", 0)) and str(client.uid) == str(
                getattr(message, "uid", "")),
            "medal": _medal_info(message),
            "emoticon": emoticon.get("url", "") if isinstance(emoticon, dict) else "",
            "emoticons": {text: item["url"] for text, item in emotes.items()
                          if isinstance(item, dict) and isinstance(item.get("url"), str)},
        })

    def _on_gift(self, client, message):
        self._emit({
            "kind": "gift",
            "uname": message.uname,
            "text": f"投喂 {message.gift_name} ×{message.num}",
        })

    def _on_buy_guard(self, client, message):
        self._emit({
            "kind": "guard",
            "uname": message.username,
            "text": f"开通了 {message.gift_name}",
        })

    def _on_super_chat(self, client, message):
        self._emit_open_super_chat(message)

    def _on_open_live_super_chat(self, client, message):
        self._emit_open_super_chat(message)

    def _emit_open_super_chat(self, message):
        data = dict(vars(message))
        if not data.get("message"):
            data["message"] = getattr(message, "msg", "")
        if "rmb" in data:
            data["price"] = data.get("rmb")
        if "uface" in data:
            data["face"] = data.get("uface")
        if "message_id" in data and not data.get("id"):
            data["id"] = data.get("message_id")
        self._emit(normalize_super_chat(data, source="websocket"))

    def _on_super_chat_delete(self, client, message):
        ids = (message.ids if hasattr(message, "ids")
               else getattr(message, "message_ids", ()))
        self._emit_super_chat_delete(ids)

    def _on_open_live_super_chat_delete(self, client, message):
        self._emit_super_chat_delete(getattr(message, "message_ids", ()))

    def _emit_super_chat_delete(self, ids):
        self._emit({
            "kind": "super_chat_delete",
            "ids": [str(chat_id) for chat_id in (ids or [])],
        })


def _medal_info(message) -> dict:
    """粉丝牌（舰队/粉丝勋章）：名字、等级、颜色，没有就返回空。"""
    name = str(getattr(message, "medal_name", "") or "")
    if not name:
        return {}
    color = int(getattr(message, "mcolor", 0) or 0)
    return {
        "name": name,
        "level": str(getattr(message, "medal_level", "") or ""),
        "color": f"#{color & 0xFFFFFF:06x}" if color else "",
    }
