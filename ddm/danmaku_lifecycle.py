"""Shared room subscriptions and worker retirement; MainWindow owns Qt lifetimes."""
import sys

from PySide6.QtCore import QTimer

from .super_chat_model import SuperChatStore
from PySide6.QtCore import QTimer
from . import bili
from . import config as config_module
from . import plugins as plugin_api
from .super_chat_model import SuperChatStore


class DanmakuLifecycle:
    def __init__(self, host):
        self.host = host

    def sync_danmaku(self) -> None:
        """弹幕格与每路画面按需订阅；同房间共用连接，隐藏的画面不另开连接。"""
        host = self.host
        if host._closing or not getattr(host, "plugins", None):
            return                     # 插件装载完成后 _sync_platform_rooms 会再次同步
        wall = host.wall
        panes = wall.pane_danmaku
        if wall.has_danmaku and wall.fullscreen_tile is None:
            widgets = panes.arrange(panes.rectangles, wall._preset_widgets())
            wall._sync_pane_borders(widgets, panes.dividers)
        wall.sync_sc_placement()
        targets = {}
        if wall.has_danmaku:
            for panel in wall.pane_danmaku.rendered():
                tile = wall.pane_danmaku.target(panel)
                targets[panel] = tile.room if tile is not None else {}
        wanted = {str(tile.room['room_id']) for tile in wall.tiles
                  if tile.isVisible() and (tile.danmaku_button.isChecked() or
                      wall.has_danmaku and host.settings.get('super_chat_enabled', True))
                  and tile.room.get('room_id') and (tile.room.get('live') or tile._player_active)}
        wanted.update(str(room['room_id']) for room in targets.values() if room.get('room_id'))
        primary = str(targets.get(wall.danmaku, {}).get('room_id') or '')
        if primary != host._danmaku_room:
            host._danmaku, host._danmaku_room = None, ''
        for panel in wall.pane_danmaku.all_panels():
            room = targets.get(panel, {})
            room_id = str(room.get('room_id') or '')
            previous = getattr(panel, '_linked_room_id', '')
            panel._linked_room_id = room_id
            panel.title.setText('弹幕')
            if not room_id:
                if previous or not panel._has_content:
                    panel.set_placeholder('点击上方头像选择关联画面')
                panel.set_status('未关联')
                continue
            if previous != room_id:
                panel.set_placeholder(f"正在连接 {room.get('uname') or room_id} 的弹幕…")
            if panel is wall.danmaku:
                if host._danmaku is None:
                    host.start_danmaku(room_id, room.get('uname', ''))
                client = host._danmaku
            else:
                client = host._ensure_danmaku_client(room_id)
            panel.set_status(host._danmaku_status.get(room_id, '连接中…') if client is not None else '暂不支持')
            if client is None:
                panel.set_placeholder('此平台弹幕尚未接入，直播画面可正常播放')
            host._publish_super_chats(room_id)
        wall.pane_danmaku.refresh_sources()
        for unused in set(host._danmaku_clients) - wanted:
            host._stop_danmaku_client(unused)
        for room_id in wanted - set(host._danmaku_clients):
            host._ensure_danmaku_client(room_id)

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

    def connect_danmaku_panel(self, panel):
        host = self.host
        panel.apply_style(str(host.settings.get('danmaku_font') or ''),
                          int(host.settings.get('danmaku_font_size') or 13))
        panel.set_max_blocks(int(host.settings.get('danmaku_max_blocks') or 3000))
        panel.apply_super_chat_settings(host.settings)
        panel.fontSizeChanged.connect(host._on_danmaku_font_size)
        panel.superChatDismissed.connect(lambda chat_id, p=panel:
            host._dismiss_super_chat(getattr(p, '_linked_room_id', ''), chat_id))

    def switch_tile_to_danmaku(self, cell=-1):
        host = self.host
        panes = host.wall.pane_danmaku
        if cell not in range(len(host.wall._cells())):
            return
        panes.request(cell, -1)
        panel = panes.panels.get(cell)
        if panel is not None:
            picker = panel.source_picker
            QTimer.singleShot(0, picker, lambda: picker.set_expanded(True))

    def apply_pane_menu(self, bindings):
        host = self.host
        try:
            host.configure_wall_panes(bindings)
        except ValueError as error:
            host._show_notice(str(error), kind='warning')

    def configure_wall_panes(self, bindings):
        host = self.host
        tiles = host.wall.pane_danmaku.cell_tiles()
        for cell in bindings:
            tile = tiles.get(cell)
            session = host.recorder.sessions.get(tile)
            if (session is not None and session.recording) or host._pending_capture.get(tile):
                raise ValueError('该格正在录制，请先结束录制后再改为弹幕栏。')
        host.wall.pane_danmaku.apply(bindings)
        host._pane_configuration_changed()

    def pane_configuration_changed(self):
        host = self.host
        host._sync_tile_playback(start_visible=True)
        host.sync_danmaku()
        host._refresh_meta()
        host._save_timer.start()

    def danmaku_target_room(self) -> dict:
        """弹幕格跟着主画面走；没有主画面就跟第一路有人的画面。"""
        host = self.host
        tile = host.wall.danmaku_target_tile()
        return tile.room if tile is not None else {}

    def on_video_danmaku_changed(self, enabled: bool) -> None:
        host = self.host
        host.sync_danmaku()
        host._save_timer.start()

    def on_video_danmaku_settings_changed(self, values: dict) -> None:
        host = self.host
        host.settings.update(values)
        host.apply_danmaku_settings()
        host._save_timer.start()

    def apply_danmaku_settings(self) -> None:
        """把设置里的弹幕字体、字号、保留条数交给弹幕格。"""
        host = self.host
        for panel in host.wall.pane_danmaku.all_panels():
            panel.apply_style(str(host.settings.get("danmaku_font") or ""),
                              int(host.settings.get("danmaku_font_size") or 13))
            panel.set_max_blocks(int(host.settings.get("danmaku_max_blocks") or 3000))
            panel.apply_super_chat_settings(host.settings)
        for tile in host.wall.tiles:
            tile.apply_video_danmaku_settings(host.settings)

    def on_danmaku_font_size(self, value: int) -> None:
        """面板上拖了字号：记住并延迟写盘（拖一次会发很多次信号）。"""
        host = self.host
        host.settings["danmaku_font_size"] = int(value)
        host._save_timer.start()

    def danmaku_blocked(self, text: str) -> bool:
        """命中屏蔽词就不显示这条弹幕（大小写不敏感）。"""
        host = self.host
        words = [str(word).strip() for word in (host.settings.get("danmaku_block_words") or [])]
        words = [word for word in words if word]
        if not words:
            return False
        lowered = str(text).lower()
        return any(word.lower() in lowered for word in words)

    def on_danmaku_message(self, source, event: dict) -> None:
        host = self.host
        room_id = next((rid for rid, client in host._danmaku_clients.items()
                        if client is source), "")
        if host._closing or not room_id:
            return                         # 已切换房间，忽略旧线程排队中的消息
        kind = event.get("kind") or "danmaku"
        if kind == "danmaku" and host._danmaku_blocked(event.get("text") or ""):
            return
        if kind == "super_chat":
            store = host._super_chats.setdefault(room_id, SuperChatStore())
            event = store.upsert(event)
            host._publish_super_chats(room_id)
        elif kind == "super_chat_delete":
            store = host._super_chats.setdefault(room_id, SuperChatStore())
            store.remove(event.get("ids") or ())
            host._publish_super_chats(room_id)
        if kind not in ("super_chat", "super_chat_delete"):
            for panel in host.wall.pane_danmaku.rendered():
                if getattr(panel, "_linked_room_id", "") == room_id:
                    panel.add_event(event)
        for tile in host.wall.tiles:
            if str(tile.room.get("room_id") or "") == room_id:
                if kind == "danmaku":
                    tile.video_danmaku.add_event(event)
        host.plugins.emit(plugin_api.EVENT_DANMAKU, room_id=room_id,
                          message=dict(event))

    def dismiss_super_chat(self, room_id: str, chat_id: str) -> None:
        host = self.host
        store = host._super_chats.get(room_id)
        if store is not None:
            for tile in host.wall.tiles:
                if str(tile.room.get('room_id') or '') == room_id:
                    tile.video_danmaku.super_chat_overlay.animate_dismiss(chat_id)
            for panel in host.wall.pane_danmaku.rendered():
                if getattr(panel, "_linked_room_id", "") == room_id:
                    panel.super_chats.animate_dismiss(chat_id)
            store.dismiss(chat_id)
            host._publish_super_chats(room_id)

    def publish_super_chats(self, room_id: str) -> None:
        host = self.host
        store = host._super_chats.get(room_id)
        chats = store.active() if store is not None else []
        for tile in host.wall.tiles:
            if str(tile.room.get("room_id") or "") == room_id:
                tile.video_danmaku.set_super_chats(chats)
        for panel in host.wall.pane_danmaku.rendered():
            if getattr(panel, "_linked_room_id", "") == room_id:
                panel.set_super_chats(chats)

    def tick_super_chats(self) -> None:
        host = self.host
        changed = False
        for room_id, store in list(host._super_chats.items()):
            if store.expire():
                changed = True
                host._publish_super_chats(room_id)
        if changed or any(store.items for store in host._super_chats.values()):
            for panel in host.wall.pane_danmaku.all_panels():
                panel.super_chats.tick()
            for tile in host.wall.tiles:
                if tile.video_danmaku.super_chats:
                    tile.video_danmaku.super_chat_overlay.set_chats(
                        tile.video_danmaku.super_chats,
                        int(host.settings.get(
                            "super_chat_opacity",
                            config_module.DEFAULT_SETTINGS["super_chat_opacity"])) / 100)

    def on_danmaku_status(self, source, text: str) -> None:
        host = self.host
        room_id = next((rid for rid, client in host._danmaku_clients.items()
                        if client is source), "")
        if host._closing or not room_id:
            return                         # 旧连接不能覆盖当前连接的状态
        host._danmaku_status[room_id] = text
        if text == "已连接" and host.state.get("buvid3", "") != bili.BUVID3:
            host.state["buvid3"] = bili.BUVID3
            host._save_timer.start()  # 旧配置首次补齐设备身份后自动持久化。
        for tile in host.wall.tiles:
            if str(tile.room.get("room_id") or "") == room_id:
                tile.danmaku_button.setToolTip(
                    f"画面弹幕：{text}\n显示参数在「设置 → 弹幕」调整")
        for panel in host.wall.pane_danmaku.rendered():
            if getattr(panel, "_linked_room_id", "") == room_id:
                panel.set_status(text)
        host.plugins.emit(plugin_api.EVENT_DANMAKU_STATUS,
                          room_id=room_id, status=text)
