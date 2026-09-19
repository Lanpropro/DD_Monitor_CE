"""自查：关注列表缩略图（封面）+ 悬停 1 秒在缩略图里放预览。不联网。"""
import io
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
from ddm.widgets import NAV_ITEM_HEIGHT, NAV_LIST_ITEM_HEIGHT, NavThumb  # noqa: E402


def boom(room_id, quality=250, **_kwargs):        # noqa: ANN001, ANN201
    raise RuntimeError("selfcheck：不联网取流")


class FakeResolver(QThread):
    """顶掉真的取流：不联网，直接给一个假地址。"""

    resolved = Signal(str, str, int, str, list)
    failed = Signal(str, str)

    started: list = []
    cancelled: list = []
    terminated: list = []
    slow = False                    # True 时挂住，模拟「取流还没回来」

    def __init__(self, room_id, quality=250, parent=None):
        super().__init__(parent)
        self.room_id = str(room_id)
        self.quality = int(quality)
        self._cancelled = False
        FakeResolver.started.append((self.room_id, self.quality))

    def cancel(self) -> None:       # 与 ddm.bili.StreamResolver 同一套协议
        self._cancelled = True
        FakeResolver.cancelled.append(self.room_id)

    def is_cancelled(self) -> bool:
        return self._cancelled

    def terminate(self) -> None:    # 自检里钉死：谁也不许再强杀取流线程
        FakeResolver.terminated.append(self.room_id)

    def run(self) -> None:
        if FakeResolver.slow:
            # 挂住不返回：模拟「网络慢，取流还没回来」，这时鼠标移开
            for _ in range(100):
                time.sleep(0.02)
            return
        time.sleep(0.05)
        if self._cancelled:
            return
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
    {"room_id": "1001", "uname": "示例主播A", "title": "示例直播标题", "live": True,
     "viewers": "3.1万", "muted": True, "quality": 250},
    {"room_id": "1002", "uname": "示例主播B", "title": "练习", "live": True,
     "muted": True, "quality": 250},
    {"room_id": "1003", "uname": "示例主播D", "title": "没在播", "live": False,
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


def thread_done(thread) -> bool:
    """线程是不是已经收工；对象被 Qt 回收（deleteLater 生效）也算收工。"""
    try:
        return not thread.isRunning()
    except RuntimeError:
        return True


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
    print(f"  条目数={len(thumbs)} 缩略图={live_item.thumb.width()}x{live_item.thumb.height()}"
          f" 行高={NAV_ITEM_HEIGHT}")
    assert len(thumbs) == len(ROOMS)
    assert live_item.thumb.height() == NavThumb.HEIGHT
    assert live_item.thumb.height() + 12 <= NAV_ITEM_HEIGHT, "行高要放得下缩略图"
    assert abs(live_item.thumb.width() / live_item.thumb.height() - 16 / 9) < 0.08, \
        "展开后的悬停预览应接近 16:9"
    live_item.thumb.set_cover(cover_pixmap("封面"))
    live_item.thumb.set_face(cover_pixmap("头像"))
    settle(app, 0.2)
    print(f"  封面已设置={'是' if live_item.thumb.cover.pixmap() else '否'}"
          f" 覆盖区={live_item.thumb.cover.size().width()}x"
          f"{live_item.thumb.cover.size().height()}")
    assert live_item.thumb.cover.pixmap() and not live_item.thumb.cover.pixmap().isNull()
    assert live_item.thumb.video.isVisible() is False, "没悬停时不该有画面"

    print("  头像：正圆，叠在封面左上角；文字和状态也都在封面内")
    face = live_item.thumb.face
    rect = face.geometry()                                  # 相对整行
    thumb_rect = live_item.thumb.geometry()                 # 缩略图在行里的位置
    local = rect.translated(-thumb_rect.x(), -thumb_rect.y())   # 相对缩略图
    thumb_w, thumb_h = live_item.thumb.width(), live_item.thumb.height()
    centre_y = local.y() + local.height() / 2
    print(f"    头像（相对缩略图）={local.getRect()} 缩略图={thumb_w}x{thumb_h}"
          f" 竖直中心={centre_y:.0f}")
    assert face.isVisible() and local.width() == local.height(), "头像必须是正方形（圆形裁切）"
    assert local.x() <= 12 and local.y() <= 12, "头像要完整叠在封面左上角"
    assert centre_y < thumb_h / 2, "头像应位于封面上半部分"
    assert live_item.name_label.parentWidget() is live_item.thumb
    assert live_item.sub.parentWidget() is live_item.thumb
    assert live_item.badge.parentWidget() is live_item.thumb
    row_w = live_item.width()
    print(f"    头像（相对整行）={rect.getRect()} 行宽={row_w}"
          f" 完整在行内={rect.x() >= 0 and rect.right() <= row_w}")
    assert rect.x() >= 0 and rect.right() <= row_w, "头像必须完整在行内（不能被裁）"
    assert face.parentWidget() is live_item, "头像要挂在行上，不能挂在缩略图里"
    # 头像是正圆：粉色宽度自上而下连续变化
    disc = face.pixmap().toImage()
    widths = []
    for y in range(0, disc.height()):
        xs = [x for x in range(disc.width())
              if (c := disc.pixelColor(x, y)).alpha() > 120]
        widths.append(len(xs))
    print(f"    头像圆形剖面：两端={widths[0]}/{widths[-1]} 最宽={max(widths)}"
          f"（正圆应两端窄、中间最宽）")
    assert widths[0] < max(widths) * 0.5 and widths[-1] < max(widths) * 0.5, \
        "头像要裁成正圆，不能是圆角方"
    assert widths[len(widths) // 2] >= max(widths) - 2
    # 封面现在是完整背景，不再为了头像挖孔。
    cover_img = live_item.thumb.cover.pixmap().toImage()
    centre = local.center()
    print(f"    头像下方封面 alpha={cover_img.pixelColor(centre.x(), centre.y()).alpha()}"
          f" 封面左侧 alpha={cover_img.pixelColor(3, thumb_h // 2).alpha()}")
    assert cover_img.pixelColor(centre.x(), centre.y()).alpha() > 200, "封面应完整铺底"
    assert cover_img.pixelColor(3, thumb_h // 2).alpha() > 200, "封面别的地方要在"

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
    assert not live_item.name_label.isVisible() and not live_item.sub.isVisible(), \
        "大卡片预览时不应把详细文字压在直播画面上"

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
    live_dot = sidebar.items()[0].live_dot
    offline_dot = item_of(window, "1003").live_dot
    print(f"  直播圆点：直播中={live_dot.isVisible()} 未开播={offline_dot.isVisible()}"
          f" 位置=({live_dot.x()},{live_dot.y()})")
    assert live_dot.isVisible(), "收起时直播中的头像应显示粉色圆点"
    assert not offline_dot.isVisible(), "未开播头像不应显示粉色圆点"
    assert live_dot.x() + live_dot.width() == live_item.thumb.face.width()
    assert live_dot.y() + live_dot.height() == live_item.thumb.face.height()
    hover(live_item, True)
    settle(app, 0.1)
    print(f"  从上往下移入头像：悬停状态={live_item.property('hovered')}")
    assert live_item.property("hovered") is True, "收起模式移入头像时条目必须进入悬停状态"
    hover(live_item, False)
    settle(app, 0.15)
    assert live_item.property("hovered") is False
    sidebar.set_collapsed(False, animate=False)
    settle(app, 0.4)
    assert not live_dot.isVisible(), "展开后继续使用文字徽标，不应重复显示圆点"
    expanded = sidebar.items()[0].thumb
    assert expanded.width() > NavThumb.WIDTH
    assert abs(expanded.width() / expanded.height() - 16 / 9) < 0.08

    print("\n=== 9. 简洁列表：只留头像和文字，也能悬停预览 ===")
    sidebar.set_card_mode(False)
    settle(app, 0.4)
    simple_item = sidebar.items()[0]
    print(f"  行高={simple_item.height()} 封面可见={simple_item.thumb.cover.isVisible()}"
          f" 头像={simple_item.thumb.face.isVisible()} 文字={simple_item.name_label.isVisible()}")
    assert simple_item.height() == NAV_LIST_ITEM_HEIGHT
    assert simple_item.thumb.height() == NavThumb.LIST_HEIGHT
    assert not simple_item.thumb.cover.isVisible(), "简洁列表不应常驻显示封面"
    assert simple_item.thumb.face.isVisible() and simple_item.name_label.isVisible()
    hover(simple_item, True)
    assert wait_for(lambda: simple_item.thumb.video.isVisible()), "简洁列表仍应支持悬停预览"
    assert simple_item.thumb.video.x() >= int(simple_item.thumb.width() * 0.64)
    assert simple_item.thumb.video.width() <= int(simple_item.thumb.width() * 0.37)
    hover(simple_item, False)
    assert wait_for(lambda: not simple_item.thumb.video.isVisible())
    sidebar.set_card_mode(True)
    settle(app, 0.3)

    print("\n=== 10. 悬停后马上移开：取流只作废、不强杀 ===")
    # 用户报的现象就是这一路：取流还在跑的时候鼠标移开，老代码 QThread.terminate()
    # 强杀线程，留下坏掉的线程本地存储 / 没释放的锁，主线程随后整个卡死。
    FakeResolver.slow = True
    FakeResolver.cancelled = []
    FakeResolver.terminated = []
    hover(live_item, True)
    assert wait_for(lambda: preview._resolver is not None, timeout=3.0), \
        "停够 1 秒应该开始取流"
    slow_resolver = preview._resolver                    # noqa: SLF001
    print(f"  取流中：running={slow_resolver.isRunning()}")
    assert slow_resolver.isRunning()
    hover(live_item, False)
    assert wait_for(lambda: preview._resolver is None, timeout=3.0), \
        "移开之后应该把这次取流交出去（等它自己结束）"
    print(f"  移开后：cancel 次数={len(FakeResolver.cancelled)}"
          f" terminate 次数={len(FakeResolver.terminated)}")
    assert FakeResolver.cancelled == ["1001"], "移开时要 cancel() 这次取流"
    assert not FakeResolver.terminated, "不许再强杀取流线程"
    assert not live_item.thumb.video.isVisible()
    # 作废之后迟到的结果不能再往卡片上播（编号已经翻页了）
    slow_resolver.resolved.emit("1001", "https://example.invalid/live.flv", 250, "web", [])
    settle(app, 0.4)
    print(f"  迟到结果：画面={live_item.thumb.video.isVisible()}"
          f" 播放器={live_item.thumb._player}")           # noqa: SLF001
    assert live_item.thumb._player is None, "作废的取流结果不该再起播放器"
    assert not live_item.thumb.video.isVisible()
    assert wait_for(lambda: thread_done(slow_resolver), timeout=6.0)
    FakeResolver.slow = False

    print("\n=== 11. 源码里不再有 QThread.terminate() ===")
    for name in ("preview.py", "app.py"):
        with io.open(os.path.join(REPO, "ddm", name), encoding="utf-8") as handle:
            text = handle.read()
        print(f"  ddm/{name}: terminate() 调用={text.count('.terminate(')}")
        assert ".terminate(" not in text, f"ddm/{name} 里不该再强杀取流线程"

    print("\n=== 12. 关窗会收掉预览 ===")
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
