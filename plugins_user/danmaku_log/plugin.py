"""记录弹幕，并在格子右键菜单中提供复制流地址。"""
import os
import time

from ddm import plugins as plugin_api

LOG_DIR = os.path.join(plugin_api.REPO, "plugins_user", "_danmaku_log")


class DanmakuLogPlugin(plugin_api.Plugin):
    name = "弹幕记录"
    description = "保存直播弹幕，并可从格子菜单复制流地址"
    version = "1.0"

    def on_load(self, context: plugin_api.PluginContext) -> None:
        os.makedirs(LOG_DIR, exist_ok=True)
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


plugin = DanmakuLogPlugin()
