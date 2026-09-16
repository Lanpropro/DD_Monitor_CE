"""自查：关注列表缩略图（封面）+ 悬停 1 秒在缩略图里放预览。不联网。"""
import os
import sys
import time

from PySide6.QtCore import QEvent, QPoint, QPointF, QThread, Qt, Signal
from PySide6.QtGui import QColor, QEnterEvent, QPixmap
from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import bili, theme  # noqa: E402
from ddm import app as app_module  # noqa: E402
from ddm import preview as preview_module  # noqa: E402
from ddm.app import MainWindow  # noqa: E402
from ddm.widgets import NAV_ITEM_HEIGHT, NavThumb  # noqa: E402


def boom(room_id, quality=250):        # noqa: ANN001, ANN201
    raise RuntimeError("selfcheck：不联网取流")


class FakeResolver(QThread):
    """顶掉真的取流：不联网，直接给一个假地址。"""

    resolved = Signal(str, str, int, str, list)
    failed = Signal(str, str)

    started: list = []

    def __init__(self, room_id, quality=250, parent=None):
        super().__init__(parent)
        self.room_id = str(room_id)
        self.quality = int(quality)
        FakeResolver.started.append((self.room_id, self.quality))

    def run(self) -> None:
        time.sleep(0.05)
        self.resolved.emit(self.room_id, "https://example.invalid/live.flv",
                           self.quality, "web", [])


class SilentPoller(QThread):
    """顶掉状态 / 人数轮询：有网络时假房间号会被查成"未开播"，把断言搞乱。"""

    updated = Signal(dict)

    def __init__(self, room_ids=None, parent=None):
        super().__init__(parent)
        self.room_ids = list(room_ids or [])

    def run(self) -> None:
        return


ROOMS = [
    {"room_id": "1001", "uname": "Asaki大人", "title": "随便玩玩战狗", "live": True,
     "viewers": "3.1万", "muted": True, "quality": 250},
    {"room_id": "1002", "uname": "七海Nana7mi", "title": "练习", "live": True,
     "muted": True, "quality": 250},
    {"room_id": "1003", "uname": "永雏塔菲", "title": "没在播", "live": False,
     "muted": True, "quality": 250},
]


def settle(app, seconds: float) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)


def wait_for(predicate, timeout: float = 4.0) -> bool:
    """等条件成立再返回（有网络时播放器释放可能拖慢事件循环，别死等固定时间）。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        QApplication.processEvents()
        time.sleep(0.02)
    return bool(predicate())


def item_of(window, room_id: str):
    return next((item for item in window.sidebar.items()
                 if str(item.room.get("room_id")) == str(room_id)), None)


def hover(item, entering: bool) -> None:
    """走真实事件，顺带验证 enterEvent / leaveEvent 接线。"""
    if entering:
        centre = QPointF(item.rect().center())
        QApplication.sendEvent(item, QEnterEvent(centre, centre,
                                                 QPointF(item.mapToGlobal(
                                                     item.rect().center()))))
    else:
        QApplication.sendEvent(item, QEvent(QEvent.Leave))


def cover_pixmap(text: str) -> QPixmap:
    pixmap = QPixmap(320, 180)
    pixmap.fill(QColor("#3d5a80"))
    return pixmap


def main() -> None:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass
    bili.play_url = boom
    app_module.StatusPoller = SilentPoller
    app_module.StatsPoller = SilentPoller
    preview_module.StreamResolver = FakeResolver
    FakeResolver.started = []
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())

    window = MainWindow([dict(room) for room in ROOMS], [dict(room) for room in ROOMS],
                        layout_id="2x2")
    window.setGeometry(-8000, -8000, 1400, 800)
    window.show()
    settle(app, 1.0)
    preview = window.hover_preview
    live_item = item_of(window, "1001")

    print("=== 1. 每一条都有封面缩略图 ===")
    thumbs = {str(item.room.get("room_id")): item.thumb for item in window.sidebar.items()}
    print(f"  条目数={len(thumbs)} 缩略图={NavThumb.WIDTH}x{NavThumb.HEIGHT}"
          f" 行高={NAV_ITEM_HEIGHT}")
    assert len(thumbs) == len(ROOMS)
    assert live_item.thumb.width() == NavThumb.WIDTH
    assert live_item.thumb.height() == NavThumb.HEIGHT
    assert live_item.thumb.height() + 12 <= NAV_ITEM_HEIGHT, "行高要放得下缩略图"
    live_item.thumb.set_cover(cover_pixmap("封面"))
    live_item.thumb.set_face(cover_pixmap("头像"))
    settle(app, 0.2)
    print(f"  封面已设置={'是' if live_item.thumb.cover.pixmap() else '否'}"
          f" 覆盖区={live_item.thumb.cover.size().width()}x"
          f"{live_item.thumb.cover.size().height()}")
    assert live_item.thumb.cover.pixmap() and not live_item.thumb.cover.pixmap().isNull()
    assert live_item.thumb.video.isVisible() is False, "没悬停时不该有画面"

    print("  头像：圆形、中间偏右、封面给它挖了孔")
    face = live_item.thumb.face
    rect = face.geometry()
    centre_y = rect.y() + rect.height() / 2
    print(f"    头像={rect.getRect()} 缩略图={live_item.thumb.width()}x"
          f"{live_item.thumb.height()} 竖直中心={centre_y:.0f}"
          f"（缩略图中心={live_item.thumb.height() / 2:.0f}）")
    assert face.isVisible() and rect.width() == rect.height(), "头像必须是正方形（圆形裁切）"
    assert rect.x() + rect.width() / 2 > live_item.thumb.width() / 2, "头像要在缩略图右半边"
    assert abs(centre_y - live_item.thumb.height() / 2) <= 1, "头像要竖直居中"
    hole = live_item.thumb.cover.mask()
    assert not hole.contains(rect.center()), "头像位置必须是镂空的（不然头像会被封面压住）"
    assert hole.contains(QPoint(2, live_item.thumb.height() // 2)), "封面别的地方还要在"
    print(f"    镂空中心在内={hole.contains(rect.center())} 封面其它位置在内="
          f"{hole.contains(QPoint(2, live_item.thumb.height() // 2))}")

    print("\n=== 2. 停够 1 秒，缩略图里直接放预览 ===")
    hover(live_item, True)
    settle(app, 0.6)
    print(f"  停 0.6 秒：画面可见={live_item.thumb.video.isVisible()}（应该还没有）")
    assert not live_item.thumb.video.isVisible()
    assert wait_for(lambda: live_item.thumb.video.isVisible()), "停够 1 秒应该开始播"
    player = live_item.thumb._player                       # noqa: SLF001
    print(f"  停 1 秒后：画面可见=True 播放器={player is not None}"
          f" 请求画质={FakeResolver.started[-1][1]}")
    assert player is not None
    assert FakeResolver.started and FakeResolver.started[-1][0] == "1001"
    assert FakeResolver.started[-1][1] <= 250, "预览要用低画质"

    print("\n=== 3. 预览是静音的 ===")
    print(f"  静音={player.muted} 音量={player.volume} 卡死检测={player.freeze_watch}")
    assert player.muted is True and player.volume == 0
    assert player.freeze_watch is False
    print(f"  播放时角标已收起={not live_item.thumb.face.isVisible()}")
    assert not live_item.thumb.face.isVisible(), "原生画面会盖住角标，播放时要藏起来"

    print("\n=== 4. 鼠标离开：回到封面，播放器释放 ===")
    hover(live_item, False)
    assert wait_for(lambda: not live_item.thumb.video.isVisible()
                    and live_item.thumb._player is None), \
        "离开后应该回到封面并释放播放器"
    print(f"  离开后：画面可见={live_item.thumb.video.isVisible()}"
          f" 播放器={live_item.thumb._player}")           # noqa: SLF001

    print("\n=== 5. 移到另一个主播：旧缩略图立刻回封面 ===")
    other = item_of(window, "1002")
    hover(live_item, True)
    assert wait_for(lambda: live_item.thumb.video.isVisible())
    hover(live_item, False)
    hover(other, True)
    assert wait_for(lambda: not live_item.thumb.video.isVisible(), timeout=1.5), \
        "换条目要立刻收掉旧画面"
    assert wait_for(lambda: other.thumb.video.isVisible()), "新条目停够 1 秒要开始播"
    print(f"  旧条目画面={live_item.thumb.video.isVisible()}"
          f" 新条目画面={other.thumb.video.isVisible()}")
    hover(other, False)
    settle(app, 0.4)

    print("\n=== 6. 没开播的条目不会预览 ===")
    offline = item_of(window, "1003")
    hover(offline, True)
    settle(app, 1.6)
    print(f"  停在未开播上 1.6 秒：画面可见={offline.thumb.video.isVisible()}")
    assert not offline.thumb.video.isVisible()
    hover(offline, False)
    settle(app, 0.3)

    print("\n=== 7. 设置里关掉就不播了 ===")
    window.settings["preview_on_hover"] = False
    window.apply_preview_settings()
    hover(live_item, True)
    settle(app, 1.6)
    print(f"  关掉之后：画面可见={live_item.thumb.video.isVisible()}")
    assert not live_item.thumb.video.isVisible()
    hover(live_item, False)
    settle(app, 0.3)
    window.settings["preview_on_hover"] = True
    window.apply_preview_settings()

    print("\n=== 8. 收起侧栏：缩略图缩小并居中 ===")
    sidebar = window.sidebar
    sidebar.set_collapsed(True, animate=False)
    settle(app, 0.5)
    compact = sidebar.items()[0].thumb
    left = compact.x()
    right = compact.parentWidget().width() - (compact.x() + compact.width())
    print(f"  收起后缩略图={compact.width()}x{compact.height()}"
          f" 左边距={left} 右边距={right}")
    assert compact.width() == NavThumb.COMPACT_SIZE
    assert abs(left - right) <= 2, "收起时缩略图要居中"
    sidebar.set_collapsed(False, animate=False)
    settle(app, 0.4)
    assert sidebar.items()[0].thumb.width() == NavThumb.WIDTH

    print("\n=== 9. 关窗会收掉预览 ===")
    hover(live_item, True)
    assert wait_for(lambda: live_item.thumb.video.isVisible())
    window.close()
    settle(app, 0.5)
    print(f"  关窗之后：画面可见={live_item.thumb.video.isVisible()}")
    assert not live_item.thumb.video.isVisible()

    print("\n全部通过")


if __name__ == "__main__":
    main()
    # 直接退出进程：Qt / VLC 在线程收尾时析构会偶发崩在退出瞬间（程序本体也是这么做的）
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
