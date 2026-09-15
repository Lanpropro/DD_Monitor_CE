"""联网验证表情链路：真的下一张 B 站表情图，进缓存，再在弹幕格里渲染成 img。"""
import os
import sys

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import images, theme  # noqa: E402
from ddm.widgets import DanmakuPanel  # noqa: E402

# B 站弹幕表情就是这种 png（blivedm 文档里给的示例地址）
URL = "https://i0.hdslb.com/bfs/live/a98e35996545509188fe4d24bd1a56518ea5af48.png"


def main() -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())

    pixmap = images.load_pixmap(URL, "emoticons")
    if pixmap is None or pixmap.isNull():
        print("下载失败")
        return 1
    print(f"下载成功：{pixmap.width()}x{pixmap.height()}")
    cache = images._cache_path(URL, "emoticons")          # noqa: SLF001
    exists = os.path.isfile(cache)
    print(f"缓存文件：{cache}")
    print(f"  存在={exists} 大小={os.path.getsize(cache) if exists else 0} 字节")

    panel = DanmakuPanel()
    panel.resize(320, 240)
    panel.set_status("已连接")
    panel.add_event({"kind": "danmaku", "uname": "表情党", "text": "[大笑]",
                     "emoticon": URL,
                     "medal": {"name": "绿冻", "level": "12", "color": "#8d8366"}})
    panel._on_emoticon_loaded(URL, pixmap)                # noqa: SLF001
    app.processEvents()
    out = os.path.join(REPO, "work", "preview", "danmaku_emoticon.png")
    panel.grab().save(out, "PNG")
    html = panel.body.toHtml()
    has_img = "<img" in html
    has_medal = "绿冻12" in panel.body.toPlainText()
    print(f"渲染结果：img={has_img} 粉丝牌={has_medal}")
    print(f"截图：{out}")
    return 0 if has_img else 1


if __name__ == "__main__":
    raise SystemExit(main())
