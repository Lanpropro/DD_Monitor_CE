"""弹幕接入：一路一个后台线程，用 blivedm 连 B 站的弹幕服务器。

blivedm 是异步库，这里把它放进 QThread 里跑一个独立的事件循环；
收到的消息通过 Qt 信号回到界面线程（跨线程发信号本身是安全的）。
"""
import asyncio
import http.cookies
import logging
import sys

from PySide6.QtCore import QThread, Signal

from . import bili
from . import config as config_module

# blivedm 在原仓库根目录，独立版也放在项目根目录
if config_module.REPO not in sys.path:
    sys.path.insert(0, config_module.REPO)

try:
    import aiohttp
    import blivedm
    IMPORT_ERROR = ""
    # blivedm 会把没处理的消息类型（LIKE_INFO_V3_CLICK、INTERACT_WORD_V2…）
    # 一条条写进 stderr，控制台会被刷屏，这里只留错误
    logging.getLogger("blivedm").setLevel(logging.ERROR)
    logging.getLogger("blivedm").propagate = False
except Exception as error:              # noqa: BLE001
    # aiohttp / brotli 没装时，弹幕用不了，但别让整个程序起不来
    aiohttp = None
    blivedm = None
    IMPORT_ERROR = f"{type(error).__name__}: {error}"


class DanmakuClient(QThread):
    """某个直播间的弹幕连接。"""

    message = Signal(str, str, str)     # 类型 / 用户名 / 内容
    status = Signal(str)                # 给界面显示的状态文字

    def __init__(self, room_id: str, parent=None):
        super().__init__(parent)
        self.room_id = str(room_id)
        self._loop = None
        self._client = None

    # ---- 线程外控制 ----
    def stop(self) -> None:
        """让事件循环把客户端停掉（线程结束后调用也没关系）。"""
        loop, client = self._loop, self._client
        if loop is None or client is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(client.stop)
        except RuntimeError:            # 循环已经停了
            pass

    # ---- 线程里跑 ----
    def run(self) -> None:
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
        cookies = http.cookies.SimpleCookie()
        if bili.SESSION_DATA:           # 带上登录态，用户名才不会被打码
            cookies["SESSDATA"] = bili.SESSION_DATA
            cookies["SESSDATA"]["domain"] = "bilibili.com"
        session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=None, connect=15))
        session.cookie_jar.update_cookies(cookies)

        self.status.emit("连接中…")
        # 官方 getDanmuInfo 被风控挡了，用 getConf 拿服务器和 token
        real_id, token, hosts = await asyncio.to_thread(bili.danmaku_conf, self.room_id)
        if not hosts:
            self.status.emit("拿不到弹幕服务器（网络或风控问题）")
            await session.close()
            return

        client = _Client(real_id or room_id, session=session,
                         on_status=self.status.emit, hosts=hosts, token=token)
        client.set_handler(_Handler(self.message.emit))
        self._client = client
        client.start()
        try:
            await client.join()
        finally:
            self._client = None
            await client.stop_and_close()
            await session.close()


if blivedm is not None:
    _ClientBase = blivedm.BLiveClient
    _HandlerBase = blivedm.BaseHandler
else:                                     # 上游库缺失时的占位，保证模块能导入

    class _ClientBase:
        pass

    class _HandlerBase:
        pass


class _Client(_ClientBase):
    """服务器地址和 token 自己给（走 getConf），顺便把连接状态报给界面。"""

    def __init__(self, room_id, *, session=None, hosts=None, token="", on_status=None):
        super().__init__(room_id, session=session)
        self._room_id = int(room_id)
        self._room_owner_uid = 0
        self._host_server_list = list(hosts or [])
        self._host_server_token = token or None
        self._on_status = on_status

    async def init_room(self) -> bool:
        """跳过官方的初始化流程（getDanmuInfo 会 403/-352），只用取好的服务器信息。"""
        if self._uid is None:
            try:
                await self._init_uid()          # 有 SESSDATA 才会真的发请求
            except Exception:                   # noqa: BLE001
                pass
            if self._uid is None:
                self._uid = 0
        return bool(self._host_server_list)

    async def _on_ws_connect(self):
        await super()._on_ws_connect()
        if self._on_status is not None:
            self._on_status("已连接")

    async def _on_before_ws_connect(self, retry_count):
        await super()._on_before_ws_connect(retry_count)
        if retry_count and self._on_status is not None:
            self._on_status(f"重连中…（第 {retry_count} 次）")


class _Handler(_HandlerBase):
    """把 blivedm 的回调转成一条条信号。"""

    def __init__(self, emit):
        super().__init__()
        self._emit = emit

    def _on_danmaku(self, client, message):
        self._emit("danmaku", message.uname, message.msg)

    def _on_gift(self, client, message):
        self._emit("gift", message.uname, f"投喂 {message.gift_name} ×{message.num}")

    def _on_buy_guard(self, client, message):
        self._emit("guard", message.username, f"开通了 {message.gift_name}")

    def _on_super_chat(self, client, message):
        self._emit("super_chat", message.uname, f"¥{message.price}　{message.message}")
