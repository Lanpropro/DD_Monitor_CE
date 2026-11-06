"""Room image requests and delivery; the host owns Qt workers and UI lifetimes."""


class RoomImages:
    def __init__(self, host):
        self.host = host

    def load_cached_covers(self, loader_type) -> None:
        """先把「上次那张封面」摆上（纯本地读文件，不联网、不等状态轮询）。

        启动时 ``build_rooms`` 只给占位条目、主播没开播时接口也不给封面；靠
        ``cache/covers/room/<房间号>.png`` 里留的那张，卡片一出来就有图。等状态
        刷新拿到真 URL，``load_room_avatars`` / ``_on_status_updated`` 会换成最新的。
        """
        host = self.host
        rooms = host.sidebar.rooms()
        room_ids = [str(room.get("room_id")) for room in rooms
                    if room.get("room_id")]
        if not room_ids:
            return
        loader = loader_type(room_ids, host)
        loader.loaded.connect(host._on_room_cover)
        loader.finished.connect(loader.deleteLater)
        host._cover_cache_loader = loader
        loader.start()

    def load_cached_avatars(self, loader_type) -> None:
        """先把「上次那张头像」摆上（纯本地读文件，不联网、不等状态轮询）。

        头像比封面更等不得：收起的关注栏**整条只剩一个头像**（封面本来就不显示），
        而真实头像要等状态轮询（默认 1.2 秒）拿到 ``face`` 才开始下。这段空窗期
        以前就是一条空白 —— 现在先用 ``cache/avatars/room/<房间号>.png`` 顶住。
        """
        host = self.host
        room_ids = [str(room.get("room_id")) for room in host.sidebar.rooms()
                    if room.get("room_id")]
        if not room_ids:
            return
        loader = loader_type(room_ids, host)
        loader.loaded.connect(host._on_room_avatar)
        loader.finished.connect(loader.deleteLater)
        host._avatar_cache_loader = loader
        loader.start()

    def load_room_avatars(self) -> None:
        """把关注列表里的主播头像和封面缩略图换成真实的。"""
        host = self.host
        rooms = host.sidebar.rooms()
        faces = {str(room.get("room_id")): room.get("face")
                 for room in rooms if room.get("face")}
        covers = {str(room.get("room_id")): room.get("cover_url")
                  for room in rooms if room.get("cover_url")}
        # AvatarLoader already reads the URL cache before trying the network.
        # Keep that file I/O and decoding off the GUI thread during startup.
        host._room_avatar_loader = host._start_avatar_loader(faces, host._on_room_avatar)
        host._cover_loader = host._start_avatar_loader(covers, host._on_room_cover,
                                                       subdir="covers")
        host._load_room_banners(rooms)

    def load_avatars_for(self, rooms: list) -> None:
        """刚加进来的房间立刻取头像和封面，不用等下一轮状态刷新。"""
        host = self.host
        faces = {str(room.get("room_id")): room.get("face")
                 for room in rooms if room.get("face")}
        covers = {str(room.get("room_id")): room.get("cover_url")
                  for room in rooms if room.get("cover_url")}
        host._start_avatar_loader(faces, host._on_room_avatar)
        host._start_avatar_loader(covers, host._on_room_cover, subdir="covers")
        host._load_room_banners(rooms)

    def load_banners(self, rooms):
        host = self.host
        from .room_artwork import supports_banner
        requested = getattr(host, '_banner_requested', set())
        host._banner_requested = requested
        items = {}
        for room in rooms:
            identity = room.get('banner_url') or room.get('uid')
            key = (str(room.get('room_id', '')), str(identity))
            if identity and supports_banner(room) and key not in requested:
                requested.add(key)
                items[key[0]] = dict(room)
        if items:
            host._start_avatar_loader(items, host._on_room_banner, subdir='banners')

    def apply_banner(self, room_id, pixmap):
        host = self.host
        host._on_room_artwork(room_id, pixmap, 'banners')

    def apply_artwork(self, room_id, pixmap, kind):
        host = self.host
        for notice in getattr(host, '_notices', []):
            if hasattr(notice, 'set_room_artwork'):
                notice.set_room_artwork(room_id, pixmap, kind)
        center = host.sidebar.notification_button.center
        for row in center.rows.values():
            row.set_room_artwork(room_id, pixmap, kind)
        if kind == 'banners':
            for item in host.sidebar._items:
                if str(item.room.get('room_id')) == str(room_id):
                    item.thumb.set_banner(pixmap)

    def start_loader(self, items: dict, slot, loader_type, subdir: str = "avatars"):
        """统一的头像下载：线程都留个引用，关窗时好等它们收尾。"""
        host = self.host
        if not items:
            return None
        loader = loader_type(items, host, subdir=subdir)
        loader.loaded.connect(slot)
        loader.finished.connect(loader.deleteLater)
        host._avatar_loaders = [item for item in host._avatar_loaders
                                if host._loader_running(item)]
        host._avatar_loaders.append(loader)
        loader.start()
        return loader

    def apply_avatar(self, room_id: str, pixmap) -> None:
        host = self.host
        for notice in getattr(host, '_notices', []):
            if hasattr(notice, 'set_room_avatar'):
                notice.set_room_avatar(room_id, pixmap)
        for item in host.sidebar._items:            # noqa: SLF001
            if str(item.room.get("room_id")) == str(room_id):
                item.thumb.set_face(pixmap)
                # 竖屏顶部横栏的头像排用的是同一张图（那边不走 NavItem）
                host.sidebar.set_room_face(room_id, pixmap)
                return

    def apply_cover(self, room_id: str, pixmap) -> None:
        host = self.host
        host._on_room_artwork(room_id, pixmap, 'covers')
        for item in host.sidebar._items:            # noqa: SLF001
            if str(item.room.get("room_id")) == str(room_id):
                item.thumb.set_cover(pixmap)
                return
