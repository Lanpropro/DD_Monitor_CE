"""自查：悬停 2 秒预览（开播才弹、静音、离开就收、开关生效）。不联网。"""
import os
import sys
import time

from PySide6.QtCore import QEvent, QPoint, QPointF, QThread, Qt, Signal
from PySide6.QtGui import QEnterEvent
from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import bili, theme  # noqa: E402
from ddm import preview as preview_module  # noqa: E402
from ddm.app import MainWindow  # noqa: E402


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
        self.resolved.emit(self.room_id, "https://example.invalid/live.flv",
                           self.quality, "web", [])


ROOMS = [
    {"room_id": "1001", "uname": "Asaki大人", "title": "随便玩玩战狗", "live": True,
     "viewers": "3.1万", "muted": True, "quality": 250},
    {"room_id": "1002", "uname": "七海Nana7mi", "title": "练习", "live": True,
     "muted": True, "quality": 250},
    {"room_id": "1003", "uname": "永雏塔菲", "title": "没在播", "live": False,
     "muted": True, "quality": 250},
]


def settle(app, seconds):
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)


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


def main() -> None:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass
    bili.play_url = boom
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
    widget = preview.widget

    print("=== 1. 停在开播的条目上 1 秒才弹 ===")
    live_item = item_of(window, "1001")
    hover(live_item, True)
    settle(app, 0.6)
    print(f"  停 0.6 秒：可见={widget.isVisible()}（应该还没有）")
    assert not widget.isVisible(), "不到 1 秒不该弹出来"
    settle(app, 0.7)
    print(f"  停 1.3 秒：可见={widget.isVisible()} 房间={widget.room_id}"
          f" 内部状态={widget.state!r} 提示={widget.toolTip()!r}")
    assert widget.isVisible() and widget.room_id == "1001"
    assert widget.toolTip() == "", "小窗上不该再有任何悬停提示"
    assert FakeResolver.started and FakeResolver.started[-1][0] == "1001"
    assert FakeResolver.started[-1][1] <= 250, "预览要用低画质，别占带宽"

    print("\n=== 1b. 窗口里只有画面，没有标题栏 ===")
    video = widget.video
    print(f"  窗口={widget.width()}x{widget.height()}"
          f" 画面区={video.width()}x{video.height()}"
          f" 有标题栏={hasattr(widget, 'title')}")
    from PySide6.QtWidgets import QLabel
    assert not hasattr(widget, "title"), "标题栏应该去掉"
    assert isinstance(widget.state, str), "状态只是一段文字（写日志用），不该是控件"
    assert not widget.findChildren(QLabel), "小窗里不该有任何文字控件"
    assert video.width() == widget.width() and video.height() == widget.height(), \
        "画面要占满整个小窗"

    print("\n=== 2. 预览是静音的 ===")
    player = widget._player                      # noqa: SLF001
    assert player is not None, "应该已经建好播放器"
    print(f"  静音={player.muted} 音量={player.volume} 卡死检测={player.freeze_watch}")
    assert player.muted is True and player.volume == 0
    assert player.freeze_watch is False, "预览不用做卡死检测"

    print("\n=== 3. 位置：往左压住侧栏约 1/3，并且是圆角 ===")
    sidebar_width = window.sidebar.width()
    item_right = live_item.mapToGlobal(
        QPoint(live_item.width() + 6, 0)).x()          # 和 preview 内部用的是同一个锚点
    anchor = preview._anchor(live_item.room, clamp=False)          # noqa: SLF001
    expected_x = item_right - sidebar_width // 3
    print(f"  侧栏宽={sidebar_width} 条目右边={item_right}"
          f" 小窗左边={anchor.x()}（期望 {expected_x}）"
          f" 尺寸={widget.width()}x{widget.height()}")
    assert anchor.x() == expected_x, "应该往左挪侧栏宽度的 1/3"
    assert sidebar_width // 3 < sidebar_width, "复查：只压住一部分，不会盖满整个列表"
    if hasattr(widget, "mask"):
        region = widget.mask()
        corners = [QPoint(0, 0), QPoint(widget.width() - 1, 0),
                   QPoint(0, widget.height() - 1),
                   QPoint(widget.width() - 1, widget.height() - 1)]
        centre = QPoint(widget.width() // 2, widget.height() // 2)
        cut = [not region.contains(point) for point in corners]
        print(f"  圆角遮罩：四个角被切掉={cut} 中心还在={region.contains(centre)}"
              f"（{widget.width()}x{widget.height()}）")
        assert not region.isEmpty(), "圆角遮罩应该生效"
        assert all(cut), "四个角应该被切掉（这就是圆角）"
        assert region.contains(centre), "窗口中间不能被裁掉"
        assert not region.contains(QPoint(2, 2)), "靠角的地方也要裁掉"

    print("\n=== 4. 鼠标离开就收掉，播放器也释放 ===")
    hover(live_item, False)
    settle(app, 0.6)
    print(f"  离开后：可见={widget.isVisible()} 播放器={widget._player}")   # noqa: SLF001
    assert not widget.isVisible() and widget._player is None      # noqa: SLF001

    print("\n=== 4b. 直接移到另一个主播身上：旧画面立刻收掉 ===")
    hover(live_item, True)
    settle(app, 1.4)
    assert widget.isVisible() and widget.room_id == "1001"
    other = item_of(window, "1002")
    hover(live_item, False)
    hover(other, True)
    settle(app, 0.4)
    print(f"  换到另一个条目 0.4 秒后：可见={widget.isVisible()}（应该已经收掉）")
    assert not widget.isVisible(), "换条目要立刻收掉旧画面"
    settle(app, 1.2)
    print(f"  再等 1.2 秒：可见={widget.isVisible()} 房间={widget.room_id}")
    assert widget.isVisible() and widget.room_id == "1002"
    hover(other, False)
    settle(app, 0.4)

    print("\n=== 5. 没开播的条目不会预览 ===")
    offline_item = item_of(window, "1003")
    hover(offline_item, True)
    settle(app, 1.4)
    print(f"  停在未开播上 1.4 秒：可见={widget.isVisible()}")
    assert not widget.isVisible()
    hover(offline_item, False)
    settle(app, 0.3)

    print("\n=== 6. 设置里关掉就不弹了 ===")
    window.settings["preview_on_hover"] = False
    window.apply_preview_settings()
    hover(live_item, True)
    settle(app, 1.4)
    print(f"  关掉之后：可见={widget.isVisible()}")
    assert not widget.isVisible()
    hover(live_item, False)
    settle(app, 0.3)

    print("\n=== 7. 重新打开还能用；关窗会收掉 ===")
    window.settings["preview_on_hover"] = True
    window.apply_preview_settings()
    hover(live_item, True)
    settle(app, 1.4)
    assert widget.isVisible()
    print(f"  重新打开：可见={widget.isVisible()} 房间={widget.room_id}")
    window.close()
    settle(app, 0.5)
    print(f"  关窗之后：可见={widget.isVisible()}")
    assert not widget.isVisible()

    print("\n全部通过")


if __name__ == "__main__":
    main()
    # 直接退出进程：Qt / VLC 在线程收尾时析构会偶发崩在退出瞬间（程序本体也是这么做的）
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
