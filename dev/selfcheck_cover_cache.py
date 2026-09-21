"""回归自检：关注列表的封面缓存（启动时和未开播时都要有图）。

用户报的两件事：
  1. 封面获取有点慢 —— 启动时要等第一次状态轮询拿到 URL，才去下载；
  2. 主播没开播时没有封面 —— 那时接口不给封面，上一次那张就回不来了。

做法：除了按 URL 缓存（``cache/covers/<md5>.png``），再按**房间号**留一份
（``cache/covers/room/<房间号>.png``）。启动时先本地读这份顶上去（纯读文件、
不联网也不等状态），等状态刷新拿到真 URL 再换成最新的。

这里钉住五件事：
  1. remember_room_cover / load_room_cover 往返；
  2. 房间号里的冒号等要安全化成文件名（插件平台是 ``kind:id``）；
  3. CachedCoverLoader 能把本地那份读出来并只发有的那几个；
  4. AvatarLoader 下完封面会顺手按房间号留一份（喂现成缓存文件，不联网）；
另外封面本身也做了减法：卡片只有 206x116，下原图（50KB 上下）纯属浪费，走 B 站 CDN 的
缩放后缀只要几 KB，同时留着退回原图的路。

这里钉住六件事：
  1. remember_room_cover / load_room_cover 往返；
  2. 房间号里的冒号等要安全化成文件名（插件平台是 ``kind:id``）；
  3. CachedCoverLoader 能把本地那份读出来并只发有的那几个；
  4. AvatarLoader 下完封面会顺手按房间号留一份（喂现成缓存文件，不联网）；
  5. 窗口级：load_cached_covers() 之后卡片真的把封面设上了；
  6. CDN 缩放后缀只挂该挂的，而且先试小图、取不到才退回原图。
"""
import os
import sys
import time

from PySide6.QtGui import QColor, QImageReader, QPixmap
from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import images, theme  # noqa: E402
from ddm.app import MainWindow  # noqa: E402

ROOM_ID = "selftest-9001"
OTHER_ID = "selftest-9002"
URL = "https://example.invalid/selftest-cover.png"


def make_png(path: str, color: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    pixmap = QPixmap(16, 16)
    pixmap.fill(QColor(color))
    assert pixmap.save(path, "PNG"), f"造图失败: {path}"


def settle(app, seconds: float) -> None:
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.03)


def main() -> None:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())

    url_path = images._cache_path(URL, "covers")           # noqa: SLF001
    make_png(url_path, "#3366ff")

    print("=== 1. 按房间号留一份：存得进、读得回 ===")
    images.remember_room_cover(ROOM_ID, URL)
    kept = images.room_cover_path(ROOM_ID)
    assert os.path.isfile(kept), "remember 之后要真的留下文件"
    pixmap = images.load_room_cover(ROOM_ID)
    assert pixmap is not None and not pixmap.isNull(), "load_room_cover 要能读回来"
    print(f"  存到 {os.path.relpath(kept, REPO)}，读回 {pixmap.width()}x{pixmap.height()}")

    print("\n=== 2. 房间号里的冒号要安全化 ===")
    weird = os.path.basename(images.room_cover_path("douyin:123"))
    print(f"  douyin:123 -> {weird}")
    assert ":" not in weird and weird.endswith(".png")

    print("\n=== 3. CachedCoverLoader 只读本地那份，不联网 ===")
    got: list = []
    loader = images.CachedCoverLoader([ROOM_ID, "never-cached-xx"], None)
    loader.loaded.connect(lambda rid, _pm: got.append(rid))
    loader.run()                                   # 直接同步跑，省一层等待
    print(f"  读出来 {got}")
    assert got == [ROOM_ID], "有缓存的那个要读出来，没缓存的不发信号"

    print("\n=== 4. AvatarLoader 下完封面顺手按房间号留一份 ===")
    other_path = images.room_cover_path(OTHER_ID)
    if os.path.isfile(other_path):
        os.remove(other_path)
    assert images.load_room_cover(OTHER_ID) is None, "先确保没有留档"
    loader2 = images.AvatarLoader({OTHER_ID: URL}, None, subdir="covers")
    hits: list = []
    loader2.loaded.connect(lambda rid, _pm: hits.append(rid))
    loader2.run()                                  # 命中已有缓存，不联网
    print(f"  处理 {hits}，留档存在={os.path.isfile(other_path)}")
    assert hits == [OTHER_ID]
    assert images.load_room_cover(OTHER_ID) is not None, \
        "AvatarLoader 要顺手留一份，不然未开播时又没图了"

    print("\n=== 5. 窗口级：窗口一出来卡片就自动有封面（不等状态轮询）===")
    rooms = [{"room_id": ROOM_ID, "uname": "自检主播", "title": "标题",
              "live": False, "muted": True, "volume": 42, "quality": 250}]
    window = MainWindow([dict(room) for room in rooms], [], layout_id="1x1")
    window.setGeometry(-9000, -9000, 900, 600)
    window.show()
    settle(app, 0.6)
    item = window.sidebar._items[0]                # noqa: SLF001
    shown = item.thumb.cover.pixmap()
    print(f"  构造后 0.6s：封面来源={item.thumb._cover_source is not None}"
          f" 画布={shown.width()}x{shown.height() if shown is not None else 0}")
    assert item.thumb._cover_source is not None, \
        "窗口一出来就该拿本地留档顶上（load_cached_covers 是构造时自动排的）"  # noqa: SLF001
    assert shown is not None and not shown.isNull(), "卡片上要真的画出封面"

    window.close()
    settle(app, 0.3)

    print("\n=== 6. 封面走 CDN 缩放：后缀只挂该挂的，且先试小图 ===")
    live = "https://i0.hdslb.com/bfs/live-key-frame/keyframe-abc.jpg"
    assert images._cdn_url(live, images.CDN_SIZE) == live + images.CDN_SIZE, \
        "B 站图要挂缩放后缀"  # noqa: SLF001
    assert images._cdn_url(live, "") == live, "不给尺寸就原样返回"
    assert images._cdn_url(live + "?x=1", images.CDN_SIZE) == \
        live + images.CDN_SIZE + "?x=1", "后缀要挂在 query 前面"  # noqa: SLF001
    assert images._cdn_url(live + "@100w.jpg", images.CDN_SIZE) == live + "@100w.jpg", \
        "人家自带尺寸了就别叠加"  # noqa: SLF001
    assert images._cdn_url("https://example.com/a.png", images.CDN_SIZE) == \
        "https://example.com/a.png", "不是 B 站图别乱挂"  # noqa: SLF001
    assert images._cdn_size_for("covers") == images.CDN_SIZE
    assert images._cdn_size_for("avatars") == "", "头像本来就小，缩了反而糊"

    formats = {bytes(item).decode("ascii", "replace")
               for item in QImageReader.supportedImageFormats()}
    print(f"  后缀 {images.CDN_SIZE}，本机能解 webp={('webp' in formats)}")
    assert "webp" in formats, "本机 Qt 缺 webp 解码插件，小图会解不开"

    tried: list = []
    original = images._load_one
    images._load_one = lambda url, subdir: (tried.append(url), None)[1]
    try:
        images.load_pixmap(live, "covers")         # 两个候选都取不到，用来观察顺序
    finally:
        images._load_one = original
    print(f"  候选顺序：{tried}")
    assert tried == [live + images.CDN_SIZE, live], "先试缩放版，取不到再退回原图"

    for path in (url_path, kept, other_path):      # 别把自检的垃圾留在缓存里
        try:
            if os.path.isfile(path):
                os.remove(path)
        except Exception:  # noqa: BLE001
            pass
    print("\n全部通过")


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
