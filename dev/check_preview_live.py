"""联网验证：关注列表的封面缩略图 + 悬停后在缩略图里真的播起来（抓一帧看）。

用法：python work/check_preview_live.py [房间号]
"""
import os
import sys
import time

from PySide6.QtCore import QEvent, QPointF
from PySide6.QtGui import QEnterEvent, QImage
from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import bili, config as config_module, theme  # noqa: E402
from ddm.app import MainWindow  # noqa: E402


def pick_room() -> dict:
    if len(sys.argv) > 1:
        info = bili.room_info(sys.argv[1]) or {}
        return {"room_id": sys.argv[1], "uname": info.get("uname", ""),
                "title": info.get("title", ""), "live": True, "muted": True,
                "cover_url": info.get("cover_url", "")}
    state = config_module.load()
    best: dict = {}
    best_score = -1.0
    for room_id in (state.get("rooms") or [])[:20]:
        info = bili.room_info(str(room_id)) or {}
        if not info.get("live"):
            continue
        try:
            score = float(str(info.get("viewers") or "0").replace("万", "e4"))
        except ValueError:
            score = 0.0
        if score > best_score:
            best, best_score = info, score
    return best


def settle(app, seconds: float) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)


def snapshot_stats(path: str) -> tuple[int, int]:
    """返回 (宽, 高) 和不同颜色的数量，用来判断画面是不是真的在放。"""
    image = QImage(path)
    if image.isNull():
        return 0, 0
    colors = set()
    for y in range(0, image.height(), 7):
        for x in range(0, image.width(), 7):
            colors.add(image.pixel(x, y))
    return image.width(), len(colors)


def main() -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass
    state = config_module.load()
    bili.set_sessdata(state.get("sessdata", ""))
    room = pick_room()
    if not room or not room.get("live"):
        print("现在没有正在直播的房间，可以手动传房间号")
        return 1
    print(f"用 {room.get('uname')}（房间 {room['room_id']}）试缩略图预览")

    app = QApplication(sys.argv[:1])
    app.setStyleSheet(theme.qss())
    window = MainWindow([dict(room)], [], layout_id="1x1")
    window.setGeometry(-8000, -8000, 1200, 700)
    window.show()
    settle(app, 3.0)                      # 等封面下载

    item = window.sidebar.items()[0]
    thumb = item.thumb
    cover = thumb.cover.pixmap()
    print(f"缩略图 {thumb.width()}x{thumb.height()} 封面已加载="
          f"{bool(cover and not cover.isNull())}")

    centre = QPointF(item.rect().center())
    QApplication.sendEvent(item, QEnterEvent(centre, centre,
                                             QPointF(item.mapToGlobal(item.rect().center()))))
    print("已模拟鼠标停在条目上，等 1 秒触发 + 等起播…")
    deadline = time.time() + 15
    while time.time() < deadline and thumb._player is None:      # noqa: SLF001
        app.processEvents()
        time.sleep(0.05)
    settle(app, 8)

    player = thumb._player                                        # noqa: SLF001
    print(f"缩略图里画面可见={thumb.video.isVisible()} 播放器={player is not None}")
    if player is None:
        print("没建起播放器")
        return 1
    shot = os.path.join(REPO, "work", "preview", "thumb_frame.png")
    result = player.player.video_take_snapshot(0, shot, 320, 180)
    settle(app, 1.0)
    width, colors = snapshot_stats(shot)
    print(f"抓帧返回={result} 尺寸={width} 不同颜色数={colors}")

    window.sidebar.grab().save(
        os.path.join(REPO, "work", "preview", "sidebar_thumbs.png"), "PNG")
    print("侧栏截图：work/preview/sidebar_thumbs.png")
    print(f"缩略图抓帧：{shot}")
    window.close()
    if width == 0 or colors < 20:
        print("缩略图里没抓到有效画面")
        return 1
    print("缩略图里确实在播（颜色足够丰富）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
