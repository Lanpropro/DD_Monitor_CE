"""回归自检：关注栏头像（含收起后的窄条）。

用户报「关注栏的头像功能出现问题，包括收缩后的关注栏」。

根因是头像的**可见性散在三处、逻辑还不一致**：
  - `_render_face()` 末尾写「视频没在播就露脸」
  - `set_thumb_size()`（收起/展开切换）里写「有 pixmap 才露脸」
  - 初始化时写死 `False`
谁最后跑谁说了算，同一条目会随着布局变化在「露脸」和「不露」之间跳。
收起的关注栏**整条只剩一个头像**（封面本来就不显示），一旦走了后一条就整个空掉，
头像还没下到的那段时间（启动后到状态轮询拿到 face，默认 1.2 秒）尤其明显。

这里钉住三件事：两种模式下头像该不该露、露的是什么（图还是名字首字）、
以及两个入口给出的答案必须一致。
"""
import os
import sys
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import config as config_module  # noqa: E402
from ddm import images as images_module  # noqa: E402
from ddm import theme  # noqa: E402
from ddm.app import MainWindow  # noqa: E402

# 首字各不相同，才能验证占位字真的取自主播名
ROOMS = [{"room_id": f"97{index:02d}", "uname": f"{letter}某",
          "title": "t", "live": True, "muted": True, "volume": 40, "quality": 250}
         for index, letter in enumerate("ABC")]


def settle(app, seconds: float = 0.3) -> None:
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


def main() -> None:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())
    settings = dict(config_module.DEFAULT_SETTINGS)
    window = MainWindow([dict(room) for room in ROOMS],
                        [dict(room) for room in ROOMS],
                        layout_id="2x2", state={"settings": dict(settings)})
    window.setGeometry(-9000, -9000, 1200, 700)
    window.show()
    settle(app, 0.5)
    try:
        item = window.sidebar.items()[0]
        thumb = item.thumb
        face = thumb.face
        print(f"条目 {item.room.get('uname')!r}　头像控件={type(face).__name__}")

        print("\n=== 1. 收起（窄条）+ 还没下到头像：必须是可见的占位，不能空着 ===")
        item.set_compact(True)
        settle(app, 0.2)
        print(f"  可见={face.isVisible()}  文本={face.text()!r}  "
              f"尺寸={face.width()}x{face.height()}")
        assert thumb._compact_thumb(), "先决条件：这一条应该处于收起状态"  # noqa: SLF001
        assert face.isVisible(), "收起的关注栏只有头像可认，没下到图也必须露出来"
        assert face.text() == "A", f"该用主播名首字顶着，实际 {face.text()!r}"

        print("\n=== 2. 两个入口必须给出同一个答案 ===")
        # set_thumb_size 与 _render_face 都写过 setVisible，原来两处逻辑还不一样
        thumb.set_thumb_size(True)
        after_size = face.isVisible()
        thumb._render_face()                     # noqa: SLF001
        after_render = face.isVisible()
        print(f"  set_thumb_size 之后={after_size}　_render_face 之后={after_render}")
        assert after_size == after_render, \
            "头像可见性不能取决于哪个入口最后跑 —— 这正是原来出问题的地方"
        assert after_render, "收起状态下两个入口都该让它露着"

        print("\n=== 3. 拿到头像：收起时露的是图 ===")
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.red)
        thumb.set_face(pixmap)
        settle(app, 0.2)
        print(f"  可见={face.isVisible()}  有图={bool(face.pixmap())}")
        assert face.isVisible(), "收起且有头像时当然要露"
        assert face.pixmap() and not face.pixmap().isNull(), "该画上真实头像"

        print("\n=== 4. 展开成卡片：封面是主体，头像仍然在（叠在左上角）===")
        item.set_compact(False)
        settle(app, 0.3)
        print(f"  可见={face.isVisible()}  紧凑={thumb._compact_thumb()}")  # noqa: SLF001
        assert not thumb._compact_thumb()
        assert face.isVisible(), "卡片模式下已经拿到头像，头像该叠在封面左上角"

        print("\n=== 5. 收起/展开来回切：可见性不许抖 ===")
        for round_index in range(4):
            item.set_compact(round_index % 2 == 0)
            settle(app, 0.12)
            assert face.isVisible(), \
                f"第 {round_index + 1} 轮切换后头像不见了（紧凑={thumb._compact_thumb()}）"
        print("  4 轮来回切换后头像一直在")
        item.set_compact(True)
        settle(app, 0.15)

        print("\n=== 6. 按房间号留档：路径与回填 ===")
        path = images_module.room_avatar_path("9701")
        print(f"  room_avatar_path('9701') = {path}")
        assert path.endswith(os.path.join("avatars", "room", "9701.png")), path
        # 没留过档的房间读出来必须是 None，不能抛
        assert images_module.load_room_avatar("no-such-room-98765") is None
        loader = images_module.CachedAvatarLoader(["no-such-room-98765"])
        got: list = []
        loader.loaded.connect(lambda rid, _px: got.append(rid))
        loader.run()                       # 直接跑，不另起线程
        print(f"  没档的房间回填结果={got}（该是空）")
        assert got == [], "没有留过档就不该发信号"

        print("\n=== 7. 主播名取不到时也不能空着 ===")
        item.room["uname"] = ""
        thumb._face_source = None          # noqa: SLF001
        thumb._render_face()               # noqa: SLF001
        print(f"  无名字无图：可见={face.isVisible()} 文本={face.text()!r}")
        assert face.isVisible() and face.text() == "?", "取不到名字时用问号顶住"

        print("\n=== 8. 缓存命中就立刻显示（不等下载）===")
        # 用户报的「关注栏头像消失」根子在这：头像以前只有「下载成功回调」一条路，
        # CDN 一抽风就永远空着。现在拿到 face URL 先把本地那张摆上。
        item.room["uname"] = "A某"
        url = "https://i0.hdslb.com/bfs/face/selftest-avatar-probe.jpg"
        path = images_module._cache_path(url, "avatars")        # noqa: SLF001
        probe = QPixmap(24, 24)
        probe.fill(Qt.blue)
        assert probe.save(path, "PNG"), "先决条件：能往缓存目录写测试图"
        try:
            assert images_module.load_cached_avatar(url) is not None, \
                "缓存里有的 URL 该能直接读出来"
            room_id = str(item.room.get("room_id"))
            hit = window._prime_cached_avatars({room_id: url})   # noqa: SLF001
            print(f"  _prime_cached_avatars 命中 {hit} 张，"
                  f"条目有图={thumb._face_source is not None}")   # noqa: SLF001
            assert hit == 1, "该把缓存那张摆到对应条目上"
            assert thumb._face_source is not None, "条目的头像源该被设上"  # noqa: SLF001
            assert face.isVisible(), "缓存命中之后头像就该看得见"
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
        assert images_module.load_cached_avatar("https://example.invalid/none.jpg") is None, \
            "没缓存过的 URL 该老实返回 None"
    finally:
        window.close()
        settle(app, 0.25)
    print("\n全部通过")


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
