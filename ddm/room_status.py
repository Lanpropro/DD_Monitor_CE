"""Status requests and updates; the host owns Qt thread and UI lifetimes."""
import sys

from . import plugins as plugin_api
from .qt_lifecycle import delete_requested


class RoomStatus:
    def __init__(self, host):
        self.host = host

    def refresh_stats(self, poller_type) -> None:
        """取画面墙上各房间的"看过"人数（wbi 签名接口，和网页显示一致）。"""
        host = self.host
        if host._closing:
            return
        try:
            if host._stats_poller is not None and host._stats_poller.isRunning():
                return
        except RuntimeError:
            host._stats_poller = None
        room_ids = [str(tile.room.get("room_id")) for tile in host.wall.tiles
                    if str(tile.room.get("room_id") or "").isdigit() and tile.room.get("live")]
        if not room_ids:
            return
        poller = poller_type(room_ids, host)
        poller.updated.connect(host._on_stats_updated)
        poller.finished.connect(lambda p=poller: host._on_stats_finished(p))
        host._stats_poller = poller
        poller.start()

    def stats_finished(self, poller) -> None:
        host = self.host
        # finished 可能在下一轮启动后才送达，只清理发出信号的线程。
        if host._stats_poller is poller:
            host._stats_poller = None
        delete_requested(poller)
        poller.deleteLater()

    def apply_stats(self, stats: dict) -> None:
        host = self.host
        for tile in host.wall.tiles:
            info = stats.get(str(tile.room.get("room_id") or ""))
            if info and info.get("online_text"):
                tile.set_watched(info["online_text"])

    def refresh_status(self, poller_type, *, force: bool = False) -> None:
        host = self.host
        if host._closing:
            return
        try:
            if host._poller is not None and host._poller.isRunning():
                if force:
                    host._refresh_queued = True
                return
        except RuntimeError:                 # 对象已被 Qt 回收
            host._poller = None
        room_ids = list(dict.fromkeys(str(room.get("room_id")) for room in
            host.sidebar.rooms() + [tile.room for tile in host.wall.tiles] if room.get("room_id")))
        if not room_ids:
            return
        platform_ids = [rid for rid in room_ids if ":" in rid]
        if platform_ids:
            poller = poller_type(room_ids, host, platforms=dict(host.plugins.platforms))
        else:
            poller = poller_type(room_ids, host)
        poller.updated.connect(host._on_status_updated)
        if hasattr(poller, "failed"):
            poller.failed.connect(host._on_status_failed)
        if hasattr(poller, "status_ready"):
            poller.status_ready.connect(lambda p=poller:
                host.sidebar.set_refreshing(False) if host._poller is p and not host._closing else None)
        poller.finished.connect(lambda p=poller: host._on_poller_finished(p))
        host._poller = poller
        poller.start()

    def status_finished(self, poller) -> None:
        host = self.host
        delete_requested(poller)
        poller.deleteLater()
        if host._poller is not poller:
            return
        host._poller = None
        if host._closing:
            return
        host._startup_status_complete = True
        if host._refresh_queued:
            host._refresh_queued = False
            host.refresh_status()
            host.sidebar.set_refreshing(host._poller is not None)
            if host._poller is not None:
                return
        host.sidebar.set_refreshing(False)

    def status_failed(self, reason: str) -> None:
        host = self.host
        print(f"[状态刷新失败] {reason}", file=sys.stderr, flush=True)
        host.sidebar.count_label.setText("状态刷新失败 · 点击重试")

    def refresh_follow(self) -> None:
        """侧栏的「刷新」：立刻拉一次直播状态，并把还没显示的头像补上。"""
        host = self.host
        host.sidebar.refresh_frequent_order()
        host.sidebar.set_refreshing(True)
        host.refresh_status(force=True)
        host.load_room_avatars()
        if host._poller is None:            # 列表是空的，没真的开轮询
            host.sidebar.set_refreshing(False)

    def apply_status(self, status: dict) -> None:
        host = self.host
        preview_status = status.get(host.hover_preview._room_id())
        if preview_status and not preview_status.get("live"):
            host.hover_preview.cancel()
        # 画面格可能直接持有侧栏条目的 room 字典。必须先记住两边旧状态，
        # 否则先更新画面格会让侧栏误以为状态没有变化，徽标仍停在“直播中”。
        tile_was_live = {tile: bool(tile.room.get("live")) for tile in host.wall.tiles}
        item_was_live = {item: bool(item.room.get("live")) for item in host.sidebar._items}
        item_was_known = {item: bool(item.room.get("live_known", True))
                          for item in host.sidebar._items}
        faces: dict[str, str] = {}
        covers: dict[str, str] = {}
        for tile in host.wall.tiles:
            info = status.get(str(tile.room.get("room_id") or ""))
            if not info:
                continue
            was_live = tile_was_live[tile]
            tile.room["live_known"] = info.get("live_known", True)
            tile.set_live(info["live"], info["viewers"])
            if info.get("uname") or info.get("title"):
                tile.set_uname_title(info.get("uname", ""), info.get("title", ""))
            if info["live"] and info.get("live_start_ts"):
                tile.room["live_start_ts"] = info["live_start_ts"]
                tile.start_elapsed_timer()
            elif not info["live"] and info.get("live_known", True):
                tile.room.pop("live_start_ts", None)
            if not info["live"] and tile.room["live_known"]:
                if (was_live or tile in host.players or tile in host._resolvers
                        or tile in host._retry_timers or tile._status_text not in ("未开播", "已下播")):
                    host._offline_tile(tile)
                if was_live:
                    host.plugins.emit(plugin_api.EVENT_ROOM_OFFLINE, tile=tile,
                                      room=dict(tile.room or {}))
                else:
                    tile.set_status("未开播")
            elif not was_live and info["live"]:
                print(f"[开播] {tile.room.get('uname')} 自动开始播放",
                      file=sys.stderr, flush=True)
                host.plugins.emit(plugin_api.EVENT_ROOM_LIVE, tile=tile,
                                  room=dict(tile.room or {}))
                if tile not in host._resolvers:
                    host.start_tile(tile)         # 已在取流的格子继续等待，不重复请求
        just_went_live: list = []
        for item in host.sidebar._items:            # noqa: SLF001
            info = status.get(str(item.room.get("room_id")))
            if not info:
                continue
            was_live = item_was_live[item]
            if info["title"]:
                item.set_title(info["title"])
            if info.get("uname"):
                item.set_uname(info["uname"])
            for key in ('uid', 'banner_url', 'display_room_id'):
                if key in info:
                    item.room[key] = info[key]
            if info["live"] and info.get("live_start_ts"):
                item.room["live_start_ts"] = info["live_start_ts"]
            elif not info["live"] and info.get("live_known", True):
                item.room.pop("live_start_ts", None)
            cover = info.get("cover_url") or ""
            if cover and cover != item.room.get("cover_url"):
                item.room["cover_url"] = cover      # 开播/下播后封面会变，缩略图跟着换
                covers[str(item.room.get("room_id"))] = cover
            if info["live"] and not was_live:
                # 刚开播：马上置位并重排，让「开播优先」先把卡片挪上去；
                # 动效等重排落地后再播，否则水滴会留在卡片原来的行上（两者错开）。
                # 只有**本来就知道是没开播**的才算「刚开播」：启动时占位条目
                # （live_known=False）第一次补上真实状态不算，否则一开软件满列表
                # 冒气泡／弹提醒 —— 用户要的是「开播时」的提示。
                if (host._startup_status_complete and host.settings.get("live_alert", True)
                        and item_was_known[item] and info.get("live_known", True)):
                    item.room["live"] = True        # 徽标由动效砸中时再换
                    just_went_live.append(item)
                else:
                    item.set_live(True)
            else:
                # 即使数据字典已被画面格更新，也要强制刷新侧栏徽标样式和文字。
                item.set_live(info["live"])
            face = info.get("face")
            if face and face != item.room.get("face"):
                item.room["face"] = face
                faces[str(item.room.get("room_id"))] = face
                # 缓存命中也由 AvatarLoader 后台读取，批量状态回调不在 UI 线程解码图片。
            item.room["live_known"] = info.get("live_known", True)
            host.sidebar._folder_pending.discard(str(item.room.get("room_id")))
        host.sidebar.resort()               # 「开播优先」要跟着开播状态重排
        host._sync_replay_scope()           # 回放范围设成「所有格子」时在这里补开缓存
        host.sync_danmaku()
        if just_went_live:                  # 排完再播动效：水滴落在卡片的新位置上
            host.sidebar.play_live_alerts(just_went_live)
            rooms = [dict(item.room) for item in just_went_live]
            for room in rooms:
                name = str(room.get("uname") or room["room_id"])
                host._show_notice(name + " 开播了", rooms=[room], kind="live")
        if covers:
            host._aside_cover_loader = host._start_avatar_loader(
                covers, host._on_room_cover, subdir="covers")
        if faces:
            host._status_avatar_loader = host._start_avatar_loader(faces, host._on_room_avatar)
        host._load_room_banners(host.sidebar.rooms())
