"""图片（头像）异步下载与本地缓存。"""
import hashlib
import os

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


def load_pixmap(url: str, subdir: str = "avatars") -> QPixmap | None:
    """先从本地缓存读，没有就下载并缓存。"""
    if not url:
        return None
    path = _cache_path(url, subdir)
    if os.path.isfile(path):
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            return pixmap
    try:
        response = requests.get(url, headers=bili.HEADERS, timeout=10)
        if response.status_code != 200 or not response.content:
            return None
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(response.content)
        pixmap = QPixmap()
        pixmap.loadFromData(response.content)
        return pixmap if not pixmap.isNull() else None
    except Exception:  # noqa: BLE001
        return None


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
                    self.loaded.emit(key, pixmap)
