"""图片（头像）异步下载与本地缓存。"""
import hashlib
import os
import re
import shutil

import requests
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QPixmap

from . import bili
from . import config as config_module

#: 缓存也要落在程序旁边（源码运行时是仓库根，打包后是 exe 目录）。
#: 不能用 __file__：冻结后在 _internal 里面，头像会写进运行库目录，用户找不到、
#: 升级时也会被一起删掉。
REPO = config_module.REPO
CACHE_DIR = os.path.join(REPO, "cache", "avatars")


def _cache_path(url: str, subdir: str = "avatars") -> str:
    name = hashlib.md5(url.encode("utf-8")).hexdigest() + ".png"
    return os.path.join(REPO, "cache", subdir, name)


def _safe_name(name: str) -> str:
    """房间号可以带平台前缀（``douyin:123``），冒号这些不能进文件名。"""
    return re.sub(r"[^0-9A-Za-z_.-]", "_", str(name))


#: B 站图片 CDN 支持尺寸后缀，可卡片只有 206x116 —— 下原图纯属浪费。
#: 实测同一张关键帧：原图 52.8 KB，``@412w_232h.webp`` 只要 8.1 KB，还够 200% 缩放看。
#: 小了一个数量级，封面自然就快；留档下来的也是小图，不占用户磁盘。
CDN_SIZE = "@412w_232h.webp"
CDN_HOSTS = ("hdslb.com",)


def _cdn_url(url: str, size: str = "") -> str:
    """给 B 站图片 URL 挂上 CDN 缩放后缀；别的站、已经挂过、没给尺寸的都原样返回。"""
    if not url or not size or not any(host in url for host in CDN_HOSTS):
        return url
    head, sep, tail = url.partition("?")
    if "@" in head.rsplit("/", 1)[-1]:
        return url                              # 人家自带尺寸了，别叠加
    return f"{head}{size}{sep}{tail}"


def _cdn_size_for(subdir: str) -> str:
    """只有房间封面是 16:9 大图值得缩；头像本来就小，缩了反而糊。"""
    return CDN_SIZE if subdir == "covers" else ""


def room_cover_path(room_id: str) -> str:
    """这个房间「最后用过的封面」在缓存里的位置（按房间号，不按 URL）。"""
    return os.path.join(REPO, "cache", "covers", "room", _safe_name(room_id) + ".png")


def room_avatar_path(room_id: str) -> str:
    """按房间号保存头像，启动占位条目还没有头像 URL 时也能显示。"""
    return os.path.join(REPO, "cache", "avatars", "room", _safe_name(room_id) + ".png")


def load_room_avatar(room_id: str) -> QPixmap | None:
    path = room_avatar_path(room_id)
    if not os.path.isfile(path):
        return None
    pixmap = QPixmap(path)
    return pixmap if not pixmap.isNull() else None


def remember_room_avatar(room_id: str, url: str) -> None:
    source = _cache_path(url, "avatars") if room_id and url else ""
    if not source or not os.path.isfile(source):
        return
    target = room_avatar_path(room_id)
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(source, target)
    except Exception:  # noqa: BLE001
        pass


def load_room_cover(room_id: str) -> QPixmap | None:
    """读「这个房间上次那张封面」；没有就 None。

    启动时状态还没拉、主播没开播时接口也不给封面 —— 但只要以前显示过一张，
    这里就能立刻把它拿回来，卡片不至于空着等网络。
    """
    path = room_cover_path(room_id)
    if not os.path.isfile(path):
        return None
    pixmap = QPixmap(path)
    return pixmap if not pixmap.isNull() else None


def remember_room_cover(room_id: str, url: str, subdir: str = "covers") -> None:
    """把 URL 那张封面留一份到「按房间号」的位置，供下次启动 / 未开播时用。"""
    if not room_id or not url:
        return
    source = ""
    # 缩放版和原图都找一遍：万一 CDN 不认后缀、回退下载了原图，也得留得下档
    for candidate in (_cdn_url(url, _cdn_size_for(subdir)), url):
        path = _cache_path(candidate, subdir) if candidate else ""
        if path and os.path.isfile(path):
            source = path
            break
    if not source:
        return
    target = room_cover_path(room_id)
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(source, target)
    except Exception:  # noqa: BLE001
        pass


def _load_one(url: str, subdir: str) -> QPixmap | None:
    """单个 URL 的「读缓存，没有就下载并缓存」。"""
    path = _cache_path(url, subdir)
    if os.path.isfile(path):
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            return pixmap
    try:
        response = requests.get(url, headers=bili.HEADERS, timeout=10)
        if response.status_code != 200 or not response.content:
            return None
        pixmap = QPixmap()
        if not pixmap.loadFromData(response.content) or pixmap.isNull():
            return None                    # 解不开就别写缓存，省得下次读到一个坏文件
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(response.content)
        return pixmap
    except Exception:  # noqa: BLE001
        return None


def load_pixmap(url: str, subdir: str = "avatars",
                cdn_size: str | None = None) -> QPixmap | None:
    """先从本地缓存读，没有就下载并缓存。封面默认走 CDN 缩放，只有几 KB。

    ``subdir="covers"`` 自动套 :data:`CDN_SIZE`；显式传 ``cdn_size=""`` 可关掉。
    缩放版取不到（CDN 不认后缀，或本机缺 webp 解码插件）会自动退回原图 ——
    拿到哪张算哪张，不会因为抠尺寸把封面弄没。
    """
    if not url:
        return None
    if cdn_size is None:
        cdn_size = _cdn_size_for(subdir)
    candidates: list[str] = []
    for candidate in (_cdn_url(url, cdn_size), url):
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    for candidate in candidates:
        pixmap = _load_one(candidate, subdir)
        if pixmap is not None:
            return pixmap
    return None


class CachedCoverLoader(QThread):
    """把各房间「上次那张封面」从本地读出来（不联网、不用等状态）。

    只读本地文件，所以很快 —— 窗口一出来就能把封面摆上，不必等第一次状态轮询
    拿到 URL 再去下载。
    """

    loaded = Signal(str, QPixmap)

    def __init__(self, room_ids, parent=None):
        super().__init__(parent)
        self.room_ids = [str(room_id) for room_id in room_ids]

    def run(self) -> None:
        for room_id in self.room_ids:
            pixmap = load_room_cover(room_id)
            if pixmap is not None:
                self.loaded.emit(room_id, pixmap)


class CachedAvatarLoader(QThread):
    """启动时按房间号回填上次下载的主播头像。"""

    loaded = Signal(str, QPixmap)

    def __init__(self, room_ids, parent=None):
        super().__init__(parent)
        self.room_ids = [str(room_id) for room_id in room_ids]

    def run(self) -> None:
        for room_id in self.room_ids:
            pixmap = load_room_avatar(room_id)
            if pixmap is not None:
                self.loaded.emit(room_id, pixmap)


class AvatarLoader(QThread):
    """批量下载头像，下好一个发一个。"""

    loaded = Signal(str, QPixmap)

    def __init__(self, items: dict[str, str], parent=None, subdir: str = "avatars"):
        super().__init__(parent)
        self.items = dict(items)          # key -> url
        self.subdir = subdir

    def run(self) -> None:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        if not self.items:
            return
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(load_pixmap, url, self.subdir): key
                       for key, url in self.items.items()}
            for future in as_completed(futures):
                key = futures[future]
                try:
                    pixmap = future.result()
                except Exception:  # noqa: BLE001
                    continue
                if pixmap is not None and not pixmap.isNull():
                    if self.subdir == "covers":
                        # 顺手按房间号留一份，下次启动 / 未开播时直接用
                        remember_room_cover(key, self.items[key], self.subdir)
                    elif self.subdir == "avatars":
                        remember_room_avatar(key, self.items[key])
                    self.loaded.emit(key, pixmap)
