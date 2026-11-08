"""Qt image workers; image API owns canonical cache paths, generation tokens and loaders."""
import requests
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QPixmap
from . import image_cache


class CachedCoverLoader(QThread):
    """把各房间「上次那张封面」从本地读出来（不联网、不用等状态）。

    只读本地文件，所以很快 —— 窗口一出来就能把封面摆上，不必等第一次状态轮询
    拿到 URL 再去下载。
    """

    loaded = Signal(str, QPixmap)

    def __init__(self, room_ids, parent=None):
        super().__init__(parent)
        self.room_ids = [str(room_id) for room_id in room_ids]
        self._stamp = image_cache.ticket()

    def run(self) -> None:
        from . import images as api
        from .cover_focus import prepare_cover
        for room_id in self.room_ids:
            pixmap = api.load_room_cover(room_id)
            if pixmap is not None:
                prepared = prepare_cover(pixmap)
                if prepared.cacheKey() != pixmap.cacheKey() or not pixmap.toImage().text(api._COVER_STORAGE_KEY):
                    api._store_image(prepared, api.room_cover_path(room_id), 'covers', self._stamp, room_id)
                self.loaded.emit(room_id, prepared)


class CachedAvatarLoader(QThread):
    """启动时按房间号回填并压缩旧头像（本地处理，不联网）。"""

    loaded = Signal(str, QPixmap)

    def __init__(self, room_ids, parent=None):
        super().__init__(parent)
        self.room_ids = [str(room_id) for room_id in room_ids]
        self._stamp = image_cache.ticket()

    def run(self) -> None:
        from . import images as api
        for room_id in self.room_ids:
            pixmap = api.load_room_avatar(room_id)
            if pixmap is not None:
                prepared = api._compact_avatar(pixmap, api.room_avatar_path(room_id), self._stamp, room_id)
                self.loaded.emit(room_id, prepared)


class AvatarLoader(QThread):
    """批量下载头像，下好一个发一个。"""

    loaded = Signal(str, QPixmap)

    def __init__(self, items: dict[str, str], parent=None, subdir: str = "avatars"):
        super().__init__(parent)
        self.items = dict(items)          # key -> url
        self.subdir = subdir
        self._stamp = image_cache.ticket()

    def run(self) -> None:
        from . import images as api
        from concurrent.futures import ThreadPoolExecutor, as_completed
        if not self.items:
            return
        if self.subdir in image_cache.KINDS:
            requests = {str(key): api._image_candidates(url, self.subdir) for key, url in self.items.items()}
            if not image_cache.begin(api.REPO, self.subdir, requests, self._stamp):
                return
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {}
            for key, url in self.items.items():
                if self.subdir == 'banners':
                    future = pool.submit(api.load_banner, url)
                elif self.subdir == 'covers':
                    future = pool.submit(api.load_cover, url, stamp=self._stamp, room=key)
                elif self.subdir == 'avatars':
                    future = pool.submit(api.load_pixmap, url, self.subdir, stamp=self._stamp, room=key)
                else:
                    future = pool.submit(api.load_pixmap, url, self.subdir)
                futures[future] = key
            for future in as_completed(futures):
                key = futures[future]
                try:
                    pixmap = future.result()
                except Exception:  # noqa: BLE001
                    continue
                if self.subdir == 'banners':
                    # An empty result must also clear an already visible/cached banner.
                    self.loaded.emit(key, pixmap if pixmap is not None else QPixmap())
                    continue
                if pixmap is not None and not pixmap.isNull():
                    if self.subdir == "covers":
                        # 顺手按房间号留一份，下次启动 / 未开播时直接用
                        if not api.remember_room_cover(key, self.items[key], self.subdir, stamp=self._stamp):
                            continue
                    elif self.subdir == "avatars":
                        # 头像同理：收起的关注栏只有头像可认，启动时不能空着
                        if not api.remember_room_avatar(key, self.items[key], stamp=self._stamp):
                            continue
                    self.loaded.emit(key, pixmap)
