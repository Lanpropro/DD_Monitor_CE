"""示例插件：演示插件接口能做的几件事。

它不是「样例代码」，是能直接用的：
- 把弹幕按天写到 ``plugins_user/_danmaku_log/<房间号>.log``（只读事件）
- 往画面格右键菜单加一项「复制流地址」，方便手动丢给播放器/VLC 验证
- 实现了**发弹幕**，所以本体会打开弹幕输入框（见 ``DanmakuSender``）

发弹幕的接口说明
----------------
B 站直播发弹幕走 ``POST https://api.live.bilibili.com/msg/send``，需要两个 cookie：

- ``SESSDATA``：登录票据，本项目已经会存（扫码/网页登录时抓的）
- ``bili_jct``：CSRF 票据，同时要作为表单里的 ``csrf`` / ``csrf_token`` 传过去

``bili_jct`` 本项目目前**没有**保存，所以这个插件开放了一个配置项
``bili_jct``，让你把浏览器里那个值填进来：

    打开 bilibili.com → F12 → Application → Cookies → 复制 bili_jct 的值
    写进 utils/config.json 的 plugins.danmaku_sender.bili_jct

发弹幕是高频风控动作：请求里带了 ``fontsize/color/mode/rnd`` 这些字段，
返回 ``code`` 不为 0 时以接口给的 ``message`` 为准（常见如 -412 被限流、
-101 未登录、-403 权限不足）。
"""
import os
import time

from ddm import bili
from ddm import plugins as plugin_api

SEND_API = "https://api.live.bilibili.com/msg/send"
LOG_DIR = os.path.join(plugin_api.REPO, "plugins_user", "_danmaku_log")


class DanmakuLogPlugin(plugin_api.Plugin):
    name = "弹幕记录 / 发弹幕"
    description = "把弹幕落盘，并提供发送弹幕的能力"
    version = "1.0"

    def on_load(self, context: plugin_api.PluginContext) -> None:
        os.makedirs(LOG_DIR, exist_ok=True)
        context.register_danmaku_sender(_Sender(context))
        context.log(f"弹幕日志目录：{LOG_DIR}")

    def on_event(self, event: str, payload: dict) -> None:
        if event != plugin_api.EVENT_DANMAKU:
            return
        room_id = str(payload.get("room_id") or "unknown")
        message = payload.get("message") or {}
        text = str(message.get("text") or "").replace("\n", " ")
        if not text:
            return
        stamp = time.strftime("%H:%M:%S")
        uname = str(message.get("uname") or "?")
        line = f"[{stamp}] {uname}: {text}\n"
        path = os.path.join(LOG_DIR, f"{room_id}.log")
        with open(path, "a", encoding="utf-8", errors="replace") as handle:
            handle.write(line)

    def tile_actions(self, tile) -> list:
        room = getattr(tile, "room", None) or {}
        url = str(getattr(tile, "stream_url", "") or "")
        if not url:
            return []

        def copy_url() -> None:
            from PySide6.QtWidgets import QApplication
            clipboard = QApplication.clipboard()
            if clipboard is not None:
                clipboard.setText(url)

        return [("复制流地址", copy_url)]


class _Sender(plugin_api.DanmakuSender):
    """按 B 站网页版的参数发一条弹幕。"""

    def __init__(self, context: plugin_api.PluginContext):
        self._context = context

    def available(self) -> tuple:
        if not bili.SESSION_DATA:
            return False, "需要先登录 B 站（设置里扫码登录）"
        token = str(self._context.setting("bili_jct", "") or "")
        if not token:
            return False, "缺少 bili_jct（见插件说明，填到配置的 plugins 段）"
        return True, ""

    def send(self, room_id: str, text: str) -> tuple:
        text = str(text or "").strip()
        if not text:
            return False, "弹幕不能为空"
        ok, reason = self.available()
        if not ok:
            return False, reason
        token = str(self._context.setting("bili_jct", "") or "")
        payload = {
            "bubble": 0,
            "msg": text,
            "color": 16777215,
            "mode": 1,
            "fontsize": 25,
            "rnd": int(time.time()),
            "roomid": room_id,
            "csrf": token,
            "csrf_token": token,
        }
        try:
            import requests
        except Exception as error:                # noqa: BLE001
            return False, f"requests 不可用：{error}"
        try:
            response = requests.post(
                SEND_API, data=payload,
                cookies={"SESSDATA": bili.SESSION_DATA, "bili_jct": token},
                headers={"User-Agent": bili.UA,
                         "Referer": f"https://live.bilibili.com/{room_id}"},
                timeout=10)
            data = response.json()
        except Exception as error:                # noqa: BLE001
            return False, f"发送失败：{error}"
        if data.get("code") != 0:
            return False, f"接口返回 {data.get('code')}：{data.get('message') or data.get('msg')}"
        return True, "已发送"


plugin = DanmakuLogPlugin()
