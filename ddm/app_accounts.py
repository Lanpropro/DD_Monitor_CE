"""Main window app accounts; window remains the only state and Qt lifetime owner."""
from copy import deepcopy
import os
import sys
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog, QMessageBox
from . import bili
from . import config as config_module
from . import theme


class AppAccounts:
    def __init__(self, host):
        self.host = host

    def follow_platforms(self) -> dict:
        host = self.host
        return {p.label or p.kind: p for p in host.plugins.platforms.values()
                if (p.follow_login_url and p.follow_cookie_domain)
                or getattr(p, "oauth_provider", "")}

    def account_dialog_platforms(self) -> dict:
        host = self.host
        providers = host._account_platforms()
        providers.update({p.label or p.kind: p for p in host.plugins.platforms.values()
                          if getattr(p, "account_login_notice", "")})
        return providers

    def login_choices(self) -> list:
        host = self.host
        choices = [] if bili.SESSION_DATA else ["B站"]
        return choices + [label for label, p in host._account_platforms().items()
                          if p.kind not in host._accounts or host._accounts[p.kind].get("_login_expired")]

    def account_platforms(self) -> dict:
        host = self.host
        return {p.label or p.kind: p for p in host.plugins.platforms.values()
                if callable(getattr(p, "account_info", None))
                and (getattr(p, "oauth_provider", "") or (
                    (getattr(p, "account_login_url", "") or p.follow_login_url)
                    and (getattr(p, "account_cookie_domain", "") or p.follow_cookie_domain)))}

    def account_kind(self) -> str:
        host = self.host
        return "bilibili" if bili.SESSION_DATA else next(
            (p.kind for p in host._account_platforms().values() if p.kind in host._accounts), "")

    def restore_platform_accounts(self) -> None:
        host = self.host
        if os.environ.get("DDM_NO_SAVE") != "1":
            from .account_store import AccountStore
            for platform in host._account_platforms().values():
                try:
                    account = AccountStore(platform.kind).load_account()
                    if account.get("uid"):
                        host._accounts[platform.kind] = account
                except (OSError, RuntimeError, ValueError):
                    pass  # 登录数据无法读取时，由用户重新登录。
            uid = str(host._accounts.get("douyin", {}).get("uid") or "")
            try:
                cache = AccountStore("douyin_follows").load_account()
                rooms = cache.get("rooms")
                if (uid and cache.get("uid") == uid and isinstance(rooms, list)
                        and all(isinstance(room, dict) and (
                            str(room.get("room_id", "")).startswith("douyin:") or
                            (not room.get("room_id") and str(room.get("anchor_uid", "")).isdigit()))
                                for room in rooms)):
                    host._douyin_follow_cache = cache
                    platform = host.plugins.platforms.get("douyin")
                    if callable(getattr(platform, "restore_follow_rooms", None)):
                        platform.restore_follow_rooms(rooms)
            except (OSError, RuntimeError, ValueError):
                pass
        host._render_account(load_avatar=False)

    def cache_douyin_follows(self, rooms, *, pending=None) -> None:
        host = self.host
        uid = str(host._accounts.get("douyin", {}).get("uid") or "")
        if not uid:
            return
        previous = host._douyin_follow_cache or {}
        if pending is None:
            pending = previous.get("pending", []) if previous.get("uid") == uid else []
        host._douyin_follow_cache = {"uid": uid, "rooms": deepcopy(rooms), "pending": deepcopy(pending)}
        platform = host.plugins.platforms.get("douyin")
        if callable(getattr(platform, "restore_follow_rooms", None)):
            platform.restore_follow_rooms(rooms)
        if os.environ.get("DDM_NO_SAVE") != "1":
            from .account_store import AccountStore
            store = AccountStore("douyin_follows")
            try:
                if host._platform_login_sessions.get("douyin", {}).get("remember", True):
                    # 只保存房间身份与显示信息；带签名的媒体地址始终重新获取。
                    keys = ("room_id", "platform", "uname", "title", "live", "live_known", "viewers",
                            "cover_url", "face", "playback_mode", "anchor_uid", "sec_uid",
                            "pending_folder_id", "pending_import", "follow_account_ref", "resolved_room_id")
                    store.save([], {"uid": uid, "rooms": [
                        {key: room[key] for key in keys if key in room} for room in rooms], "pending": [
                        {key: room[key] for key in keys if key in room} for room in pending]})
                else:
                    store.clear()
            except (OSError, RuntimeError):
                print("[账号] 抖音关注缓存保存失败，本次读取结果仍可使用", file=sys.stderr)

    def render_account(self, *, load_avatar=True, cached_avatar) -> None:
        host = self.host
        load_cached_avatar = cached_avatar
        if host._closing:
            return
        host.sidebar.can_login_other = bool(host._login_choices())
        kinds = (["bilibili"] if bili.SESSION_DATA else []) + [
            p.kind for p in host._account_platforms().values() if p.kind in host._accounts]
        host.sidebar.logged_accounts = [(kind, host._accounts.get(kind, {"uname": "B站账号"}))
                                       for kind in kinds]
        for account_kind, info in host.sidebar.logged_accounts:
            if "_pixmap" not in info:
                info["_pixmap"] = load_cached_avatar(info.get("face") or "")
            if load_avatar:
                host._load_account_avatar(account_kind, info)
        kind = host._account_kind()
        if not kind:
            host.sidebar.clear_account()
            from .online_ui import set_update_dot
            set_update_dot(host.sidebar.account_row, False)
            return
        account = host._accounts.get(kind, {"uname": "B站账号"})
        name = account.get("uname") or str(account.get("uid") or "已登录")
        face = account.get("face") or ""
        if "_pixmap" not in account:
            account["_pixmap"] = load_cached_avatar(face)
        host.sidebar.set_account(name, account.get("_pixmap"), platform=kind, uid=account.get("uid"))
        from .online_ui import set_update_dot
        expired = [p.label or p.kind for p in host._account_platforms().values()
                   if host._accounts.get(p.kind, {}).get("_login_expired")]
        set_update_dot(host.sidebar.account_row, bool(expired))
        host.sidebar.account_row.account_id.setStyleSheet(
            f"color: {theme.PINK};" if account.get("_login_expired") else "")
        if account.get("_login_expired"):
            host.sidebar.account_row.account_id.setText("登录已失效 · 请重新登录")
        if expired:
            host.sidebar.account_row.setToolTip("、".join(expired) + "登录已失效，请重新登录")

    def load_account_avatar(self, kind, account, *, avatar_type):
        host = self.host
        AvatarLoader = avatar_type
        face = account.get("face") or ""
        if not face or account.get("_pixmap") is not None or account.get("_avatar_requested"):
            return
        account["_avatar_requested"] = True
        session = bili.SESSION_DATA
        loader = AvatarLoader({"account": face}, host)
        def loaded(_key, pixmap):
            if (not host._closing and host._accounts.get(kind) is account
                    and (kind != "bilibili" or bili.SESSION_DATA == session)):
                account["_pixmap"] = pixmap
                host._render_account()
        loader.loaded.connect(loaded)
        loader.finished.connect(loader.deleteLater)
        host._account_avatar_loader = loader
        host._avatar_loaders = [item for item in host._avatar_loaders if host._loader_running(item)]
        host._avatar_loaders.append(loader)
        loader.start()

    def refresh_account(self, *, retry: bool = True, loader_type) -> None:
        """刷新侧栏底部的账号信息。"""
        host = self.host
        AccountLoader = loader_type
        if not bili.SESSION_DATA:
            host._render_account()
            return
        session = bili.SESSION_DATA
        current = lambda: not host._closing and bili.SESSION_DATA == session
        loader = AccountLoader(host)
        loader.loaded.connect(lambda account: host._on_account_loaded(account) if current() else None)
        if retry:
            loader.failed.connect(lambda: QTimer.singleShot(
                5000, lambda: host.refresh_account(retry=False) if current() else None))
        loader.finished.connect(loader.deleteLater)
        host._account_loader = loader
        loader.start()

    def on_account_loaded(self, account: dict) -> None:
        host = self.host
        host._accounts["bilibili"] = dict(account)
        host._render_account()

    def clear_platform_account(self, kind: str) -> None:
        host = self.host
        host._accounts.pop(kind, None)
        host._platform_login_sessions.pop(kind, None)
        if kind == "douyin":
            host._douyin_follow_cache = None
            if os.environ.get("DDM_NO_SAVE") != "1":
                from .account_store import AccountStore
                AccountStore("douyin_follows").clear()
        host._render_account()

    def logout(self, kind=None) -> None:
        host = self.host
        kind = kind or host.sidebar.account_row.platform or "bilibili"
        if kind == "bilibili":
            bili.set_sessdata("")
            host.state["sessdata"] = ""
            host.state["bili_jct"] = ""
            host.plugins.notify_credentials('bilibili')
            config_module.save(host.current_state())
            host.stop_danmaku()
            host.sync_danmaku()
        else:
            from .platform_login import clear_platform_login
            try:
                clear_platform_login(kind)
            except OSError:
                QMessageBox.warning(host, "退出登录", "登录状态清除失败，请检查文件权限后重试")
                return
        host._clear_platform_account(kind)
        print("已退出登录", file=sys.stderr, flush=True)

    def open_login(self, platform_kind=None, *, reauthenticate=False) -> None:
        host = self.host
        follow_loader = getattr(host, "_follow_loader", None)
        if host._closing or (follow_loader is not None and host._loader_running(follow_loader)):
            return
        choices = host._login_choices()
        if platform_kind is None and not choices:
            QMessageBox.information(host, "账号登录", "当前支持登录的平台均已成功登录。")
            return
        providers = host._account_dialog_platforms()
        if platform_kind is None:
            platform_kind = "bilibili" if choices[0] == "B站" else providers[choices[0]].kind
        host._open_account_dialog(providers, platform_kind=platform_kind,
                                  reauthenticate=reauthenticate)

    def open_account_dialog(self, providers, *, import_follows=False, platform_kind="bilibili",
                             reauthenticate=False):
        host = self.host
        from .account_dialog import AccountPlatformDialog
        dialog = AccountPlatformDialog(host, providers, import_follows=import_follows,
                                       platform_kind=platform_kind, reauthenticate=reauthenticate)
        try:
            result = dialog.exec()
            selected = dialog.rooms
            pending_count = dialog.pending_count
            folder_id = dialog.folder_id
            removed_ids = dialog.removed_ids
            move_existing = dialog.folder_changed
            folder_room_ids = dialog.folder_room_ids
        finally:
            dialog.deleteLater()
        if import_follows and result == QDialog.Accepted and not host._closing:
            host._import_selected_follows(selected, folder_id=folder_id,
                                          removed_ids=removed_ids, move_existing=move_existing,
                                          folder_room_ids=folder_room_ids, pending_count=pending_count)

    def update_bilibili_credentials(self, changes: dict) -> None:
        host = self.host
        if 'buvid3' in changes:
            host.state['buvid3'] = bili.remember_buvid3(changes['buvid3'])
            config_module.save(host.current_state())

    def on_login(self, sessdata: str) -> None:
        host = self.host
        bili.set_sessdata(sessdata)
        host.state["sessdata"] = sessdata
        host.plugins.notify_credentials('bilibili')
        config_module.save(host.current_state())
        host._render_account()
        host.refresh_account()
        # 之前是匿名连的弹幕，服务端会把用户名打码；登录后重连一次
        host.stop_danmaku()
        host.sync_danmaku()
        print(f"登录成功，已保存登录状态（{len(sessdata)} 字符）", file=sys.stderr, flush=True)

    def open_import_follows(self) -> None:
        host = self.host
        if getattr(host, "_follow_import_timer", None) is not None:
            return
        follow_loader = getattr(host, "_follow_loader", None)
        if follow_loader is not None and host._loader_running(follow_loader):
            return
        if host._closing:
            return
        host._open_account_dialog(host._follow_platforms(), import_follows=True)

    def import_selected_follows(self, selected: list, *, folder_id: str = "",
                                 removed_ids=(), move_existing=False, folder_room_ids=None, pending_count=0) -> None:
        host = self.host
        if host._closing or getattr(host, "_follow_import_timer", None) is not None:
            return
        selected_ids = {str(room["room_id"]) for room in selected}
        removing = set(removed_ids) - selected_ids
        for room in list(host.sidebar.rooms()):
            if str(room["room_id"]) in removing:
                host.remove_room(room)
        # Small imports finish immediately; large imports yield between bounded batches.
        added_rooms = []
        offset = 0
        timer = QTimer(host)
        host._follow_import_timer = timer

        def import_batch():
            nonlocal offset
            if host._closing:
                timer.stop()
                timer.deleteLater()
                host._follow_import_timer = None
                return
            added_rooms.extend(host.sidebar.add_rooms(selected[offset:offset + 8]))
            offset += 8
            if offset < len(selected):
                timer.start(0)
                return
            timer.stop()
            timer.deleteLater()
            host._follow_import_timer = None
            host._finish_follow_import(selected, added_rooms, folder_id=folder_id,
                                       move_existing=move_existing, folder_room_ids=folder_room_ids,
                                       pending_count=pending_count)

        timer.timeout.connect(import_batch)
        import_batch()

    def finish_follow_import(self, selected, added_rooms, *, folder_id, move_existing,
                              folder_room_ids=None, pending_count):
        host = self.host
        moving = selected if move_existing else added_rooms
        if move_existing and folder_room_ids is not None:
            folder_ids = set(folder_room_ids)
            moving = [room for room in selected if str(room["room_id"]) in folder_ids]
        if (folder_id or move_existing) and moving:
            host.sidebar.move_to_folder([str(room["room_id"]) for room in moving], folder_id)
        if not move_existing:
            pending_folders = {}
            for room in added_rooms:
                if room.get("pending_folder_id"):
                    pending_folders.setdefault(room["pending_folder_id"], []).append(str(room["room_id"]))
            for pending_folder, room_ids in pending_folders.items():
                host.sidebar.move_to_folder(room_ids, pending_folder)
        added = len(added_rooms)
        host.load_avatars_for(selected)          # 导入后立刻补头像
        host._refresh_meta()
        host._save_timer.start()
        message = f"导入完成：新增 {added} 个"
        if pending_count:
            message += f"，另保存 {pending_count} 个待识别账号"
        print(message)
        from .online_ui import show_result
        show_result(host, message, rooms=added_rooms)

    def refresh_meta(self) -> None:
        """只负责画面墙的显隐（右侧原来那行文字已经去掉，画面填满）。"""
        host = self.host
        host.sidebar.set_wall_rooms(
            str(tile.room.get("room_id") or "") for tile in host.wall.tiles
            if not tile.property('pictureInPictureTemporary'))
        # 替换后格子仍保持聚焦，卡片选择需跟随它当前的房间。
        focused = next((tile for tile in host.wall.tiles if tile.property("focused")), None)
        if focused is not None:
            host.sidebar.select_room(focused.room)
        host.wall.setVisible(bool(host.wall.tiles))
        host.empty_hint.setVisible(not host.wall.tiles)
        host.sync_danmaku()
