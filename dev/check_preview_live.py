"""联网验证悬停预览：停在真开播的房间上，等它起播，再抓一帧看看画面真的出来了。"""
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
                "title": info.get("title", ""), "live": True, "muted": True}
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


def settle(app, seconds):
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
    print(f"用 {room.get('uname')}（房间 {room['room_id']}）试悬停预览")

    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())
    window = MainWindow([dict(room)], [], layout_id="1x1")
    # 默认摆在屏幕外（不打扰）；加 --onscreen 才摆到屏幕里，方便截屏看效果
    if "--onscreen" in sys.argv:
        window.setGeometry(40, 40, 1080, 660)
    else:
        window.setGeometry(-8000, -8000, 1200, 700)
    window.show()
    settle(app, 1.5)

    item = window.sidebar.items()[0]
    centre = QPointF(item.rect().center())
    QApplication.sendEvent(item, QEnterEvent(centre, centre,
                                             QPointF(item.mapToGlobal(item.rect().center()))))
    print("已模拟鼠标停在条目上，等 2 秒触发 + 等起播…")
    settle(app, 12)

    widget = window.hover_preview.widget
    player = widget._player                      # noqa: SLF001
    print(f"小窗可见={widget.isVisible()} 悬停提示={widget.toolTip()!r}")
    if player is None:
        print("没建起播放器")
        return 1
    shot = os.path.join(REPO, "work", "preview", "preview_frame.png")
    result = player.player.video_take_snapshot(0, shot, 480, 270)
    settle(app, 1.0)
    width, colors = snapshot_stats(shot)
    print(f"抓帧返回={result} 尺寸={width} 不同颜色数={colors}")

    widget.grab().save(os.path.join(REPO, "work", "preview", "preview_window.png"), "PNG")
    print("小窗截图：work/preview/preview_window.png")
    print(f"整帧截图：{shot}")

    if "--onscreen" in sys.argv:
        # 从屏幕上抓一块（含 VLC 的原生画面），用来看圆角和实际观感
        screen = widget.screen()
        box = widget.frameGeometry()
        padding = 16
        on_screen = screen.grabWindow(0, box.x() - padding, box.y() - padding,
                                      box.width() + padding * 2, box.height() + padding * 2)
        on_screen_path = os.path.join(REPO, "work", "preview", "preview_on_screen.png")
        on_screen.save(on_screen_path, "PNG")
        print(f"屏幕截图（含画面）：{on_screen_path}")
    window.close()
    if width == 0:
        print("没有抓到画面")
        return 1
    if colors < 20:
        print("画面几乎是纯色，可能还没起播")
        return 1
    print("画面正常（颜色足够丰富，说明真的在放）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
