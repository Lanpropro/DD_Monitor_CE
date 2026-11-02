"""Shared room subscriptions and worker retirement; MainWindow owns Qt lifetimes."""
import sys

from PySide6.QtCore import QTimer

from .super_chat import SuperChatStore


class DanmakuLifecycle:
    def __init__(self, host):
        self.host = host

    def sync_danmaku(self) -> None:
        """弹幕格与每路画面按需订阅；同房间共用连接，隐藏的画面不另开连接。"""
        host = self.host
        if host._closing or not getattr(host, "plugins", None):
            return                     # 插件装载完成后 _sync_platform_rooms 会再次同步
        panel = host.wall.danmaku
        host.wall.sync_sc_placement()
        room = host._danmaku_target_room() if host.wall.has_danmaku else {}
        room_id = str(room.get("room_id") or "")
        wanted = {str(tile.room["room_id"]) for tile in host.wall.tiles
                  if tile.isVisible() and (tile.danmaku_button.isChecked() or
                      host.wall.has_danmaku and host.settings.get('super_chat_enabled', True))
                  and tile.room.get("room_id") and (tile.room.get("live") or tile._player_active)}
        if host.wall.has_danmaku and host._danmaku is None and host._danmaku_room:
            wanted.add(host._danmaku_room)
        if room_id:
            wanted.add(room_id)
        if room_id != host._danmaku_room:
            host._danmaku, host._danmaku_room = None, ""
        for unused in set(host._danmaku_clients) - wanted:
            host._stop_danmaku_client(unused)
        if room_id and host._danmaku is None:
            host.start_danmaku(room_id, room.get("uname", ""))
        elif not room_id:
            panel.set_placeholder("把直播间拖到主画面，这里就会显示它的弹幕")
        elif host._danmaku is not None:
            host._publish_super_chats(room_id)
        for target in wanted - set(host._danmaku_clients) - {room_id}:
            host._ensure_danmaku_client(target)

    def start_danmaku(self, room_id: str, uname: str = "") -> None:
        host = self.host
        panel = host.wall.danmaku
        panel.set_placeholder(f"正在连接 {uname or room_id} 的弹幕…")
        panel.set_status(host._danmaku_status.get(str(room_id), "连接中…"))
        client = host._ensure_danmaku_client(str(room_id), for_panel=True)
        if client is None:
            panel.set_placeholder("此平台弹幕尚未接入，直播画面可正常播放")
            panel.set_status("暂不支持")
        else:
            host._publish_super_chats(str(room_id))

    def _ensure_danmaku_client(self, room_id: str, client_type, *, for_panel: bool = False):
        host = self.host
        client = host._danmaku_clients.get(room_id)
        new = client is None
        if new:
            if room_id.isdigit():
                client = client_type(room_id, host)
            else:
                platform = host.plugins.platform_for(room_id)
                client = platform.danmaku_client(room_id, host) if platform is not None else None
            if client is None:
                for tile in host.wall.tiles:
                    if str(tile.room.get("room_id") or "") == room_id:
                        tile.danmaku_button.setToolTip("此平台弹幕尚未接入")
                return None
            host._danmaku_clients[room_id] = client
            if room_id.isdigit():
                QTimer.singleShot(0, lambda rid=room_id, source=client:
                                  host._load_super_chat_snapshot(rid, source))
            client.message.connect(
                lambda event, source=client: host._on_danmaku_message(source, event))
            client.status.connect(
                lambda text, source=client: host._on_danmaku_status(source, text))
            client.finished.connect(
                lambda rid=room_id, source=client: host._on_danmaku_finished(rid, source))
            client.finished.connect(client.deleteLater)
        if for_panel:
            host._danmaku, host._danmaku_room = client, room_id
        if new:
            client.start()
            print(f"[弹幕] 开始接收房间 {room_id}", file=sys.stderr, flush=True)
        return client

    def _load_super_chat_snapshot(self, room_id: str, client=None, *, snapshot_type) -> None:
        host = self.host
        if host._danmaku_clients.get(room_id) is None:
            return
        if client is not None and host._danmaku_clients.get(room_id) is not client:
            return                      # 排队期间已换台，别为旧房间发请求
        running = host._super_chat_snapshots.get(room_id)
        if running is not None and running.isRunning():
            return
        loader = snapshot_type(room_id, host)
        loader.loaded.connect(lambda rid, events, source=loader:
                              host._on_super_chat_snapshot(rid, events, source=source))
        loader.finished.connect(lambda rid=room_id, source=loader:
                                host._on_super_chat_snapshot_finished(rid, source))
        loader.finished.connect(loader.deleteLater)
        host._super_chat_snapshots[room_id] = loader
        loader.start()

    def _on_super_chat_snapshot(self, room_id: str, events: list, *, source=None) -> None:
        host = self.host
        if host._closing or host._danmaku_clients.get(room_id) is None:
            return
        if source is not None and host._super_chat_snapshots.get(room_id) is not source:
            return
        store = host._super_chats.setdefault(room_id, SuperChatStore())
        for event in events:
            store.upsert(event)
        host._publish_super_chats(room_id)

    def _on_super_chat_snapshot_finished(self, room_id: str, source) -> None:
        host = self.host
        if host._super_chat_snapshots.get(room_id) is source:
            host._super_chat_snapshots.pop(room_id, None)
        if source in host._super_chat_retired:
            host._super_chat_retired.remove(source)

    def _on_danmaku_finished(self, room_id: str, source) -> None:
        host = self.host
        if source in host._danmaku_retired:
            host._danmaku_retired.remove(source)
        if host._danmaku_clients.get(room_id) is source:
            host._danmaku_clients.pop(room_id)
            if host._danmaku is source:
                host._danmaku, host._danmaku_room = None, ""

    def stop_danmaku(self) -> None:
        host = self.host
        host._danmaku, host._danmaku_room = None, ""
        for room_id in list(host._danmaku_clients):
            host._stop_danmaku_client(room_id)
        for tile in host.wall.tiles:
            tile.video_danmaku.clear()

    def _stop_danmaku_client(self, room_id: str) -> None:
        host = self.host
        client = host._danmaku_clients.pop(room_id)
        host._danmaku_status.pop(room_id, None)
        host._super_chats.pop(room_id, None)
        host._publish_super_chats(room_id)
        loader = host._super_chat_snapshots.pop(room_id, None)
        if loader is not None:
            loader.requestInterruption()
            host._super_chat_retired.append(loader)
        client.stop()
        try:
            if client.isRunning():
                # 取消取服务器信息时可能仍在等待 HTTP；换布局不阻塞，退出统一等待。
                host._danmaku_retired.append(client)
        except RuntimeError:
            pass
