"""自查：开播提醒动效（未开播 -> 直播中 才播，水滴 + 涟漪画得出来）。不联网。"""
import os
import sys
import time

from PySide6.QtCore import QPoint, QThread, Signal
from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import bili, theme  # noqa: E402
from ddm import app as app_module  # noqa: E402
from ddm.app import MainWindow  # noqa: E402
from ddm.widgets import LiveAlert  # noqa: E402


def boom(room_id, quality=250, **_kwargs):        # noqa: ANN001, ANN201
    raise RuntimeError("selfcheck：不联网取流")


class SilentPoller(QThread):
    """顶掉状态/人数轮询：自检里自己造状态，不联网。"""

    updated = Signal(dict)

    def __init__(self, room_ids, parent=None):
        super().__init__(parent)
        self.room_ids = list(room_ids)

    def run(self) -> None:
        return


ROOMS = [
    {"room_id": "2001", "uname": "刚开播的主播", "title": "开了", "live": False,
     "muted": True, "quality": 250},
    {"room_id": "2002", "uname": "一直在播的主播", "title": "播着呢", "live": True,
     "muted": True, "quality": 250},
]


def settle(app, seconds):
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)


def wait_for(predicate, timeout: float = 4.0) -> bool:
    """等条件成立；有网络时播放器释放可能拖慢事件循环，别死等固定时间。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        QApplication.processEvents()
        time.sleep(0.02)
    return bool(predicate())


def count_pixels(image, predicate) -> int:
    hits = 0
    for y in range(0, image.height(), 2):
        for x in range(0, image.width(), 2):
            colour = image.pixelColor(x, y)
            if predicate(colour):
                hits += 1
    return hits


def is_pink(colour) -> bool:
    return colour.red() > 140 and colour.red() - colour.green() > 50


def freeze(alert, milliseconds: float) -> None:
    """停住计时器，把动效定格在某个时刻，方便按阶段截图/断言。"""
    alert._timer.stop()                       # noqa: SLF001
    alert._elapsed = int(milliseconds)        # noqa: SLF001
    alert.repaint()


def grab_item(sidebar, item):
    """抓整个侧栏再裁出条目（单独抓条目时透明底会发白，看不出真实观感）。"""
    whole = sidebar.grab()
    ratio = whole.devicePixelRatio()          # 抓图是设备像素，坐标要乘这个比例
    top_left = item.mapTo(sidebar, QPoint(0, 0))
    return whole.copy(int(top_left.x() * ratio), int(top_left.y() * ratio),
                      int(item.width() * ratio), int(item.height() * ratio))


def main() -> None:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass
    bili.play_url = boom
    app_module.StatusPoller = SilentPoller
    app_module.StatsPoller = SilentPoller
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())

    window = MainWindow([dict(room) for room in ROOMS], [dict(room) for room in ROOMS],
                        layout_id="2x2")
    window.setGeometry(-8000, -8000, 1400, 800)
    window.show()
    settle(app, 1.0)
    sidebar = window.sidebar
    items = {str(item.room.get("room_id")): item for item in sidebar.items()}
    going_live = items["2001"]
    already_live = items["2002"]

    print("=== 1. 未开播 -> 直播中：播水滴提醒 ===")
    assert going_live._alert is None                       # noqa: SLF001
    window._on_status_updated({                            # noqa: SLF001
        "2001": {"live": True, "viewers": "3.2万", "title": "开了", "face": ""},
        "2002": {"live": True, "viewers": "1万", "title": "播着呢", "face": ""},
    })
    assert wait_for(lambda: going_live._alert is not None and going_live._alert.isVisible()), \
        "状态变化后应该播提醒"
    alert = going_live._alert                              # noqa: SLF001
    print(f"  动效可见={alert is not None and alert.isVisible()}"
          f" 计时器在跑={alert is not None and alert._timer.isActive()}")
    assert alert is not None and alert.isVisible(), "状态变化后应该播提醒"
    assert going_live.room["live"] is True

    print("\n=== 2. 已经在播的不会再播 ===")
    assert already_live._alert is None, "一直开播的不该播提醒"      # noqa: SLF001
    window._on_status_updated({                            # noqa: SLF001
        "2001": {"live": True, "viewers": "3.3万", "title": "开了", "face": ""},
    })
    # 重置成"未开播"，重新播一次，方便按阶段截图
    going_live.set_live(False)
    going_live.play_live_alert()
    settle(app, 0.2)

    print("\n=== 3. 四个阶段：下落 -> 砸中变直播中 -> 气泡弹出 -> 停住 ===")
    out_dir = os.path.join(REPO, "work", "preview")
    alert = going_live._alert                              # noqa: SLF001
    freeze(alert, LiveAlert.DROP_MS - 120)                 # 下落中
    settle(app, 0.05)
    print(f"  下落中：徽标={going_live.badge.text()!r}"
          f"（应该还是「未开播」）")
    assert going_live.badge.text() == "未开播", "水滴还没落到，徽标不该先变"
    drop_shot = grab_item(sidebar, going_live)
    drop_shot.save(os.path.join(out_dir, "live_alert_drop.png"), "PNG")
    pink = count_pixels(drop_shot.toImage(), is_pink)
    print(f"  下落中：粉色水滴像素={pink}")
    assert pink > 20, "应该能看到粉色水滴"

    alert._timer.start()                                   # noqa: SLF001
    alert._elapsed = LiveAlert.DROP_MS - 5                 # noqa: SLF001
    alert._tick()                                          # noqa: SLF001  越过临界点 = 砸中
    settle(app, 0.1)
    print(f"  砸中的瞬间：徽标={going_live.badge.text()!r}"
          f" 样式={going_live.badge.objectName()!r}"
          f" 详情提示={'有' if going_live.toolTip() else '无'}")
    assert going_live.badge.text() == "直播中", "砸中那一刻要变成「直播中」"
    assert going_live.badge.objectName() == "BadgeLive", "要变成粉色的直播中样式"
    assert not going_live.toolTip(), "鼠标停在缩略图上不应再弹出详细信息"
    assert going_live.room["live"] is True

    freeze(alert, LiveAlert.DROP_MS + LiveAlert.POP_MS * 0.5)      # 气泡正在弹出来
    settle(app, 0.05)
    pop_shot = grab_item(sidebar, going_live)
    pop_shot.save(os.path.join(out_dir, "live_alert_pop.png"), "PNG")
    print(f"  弹出中：气泡缩放={alert._pop_scale(0.5):.2f}")    # noqa: SLF001

    freeze(alert, LiveAlert.DROP_MS + LiveAlert.POP_MS + LiveAlert.HOLD_MS * 0.5)
    settle(app, 0.05)
    bubble = alert.bubble_rect()
    item_top = going_live.mapTo(sidebar.list_box, QPoint(0, 0)).y()
    print(f"  气泡停留：气泡={bubble.left():.0f},{bubble.top():.0f}"
          f" {bubble.width():.0f}x{bubble.height():.0f}"
          f" 文字={'开播了' in LiveAlert.HINT}"
          f" 盖到上面一行={bubble.top() < item_top}")
    ripple_shot = grab_item(sidebar, going_live)
    ripple_shot.save(os.path.join(out_dir, "live_alert_ripple.png"), "PNG")
    pink = count_pixels(ripple_shot.toImage(), is_pink)
    print(f"  气泡阶段：粉色像素={pink}")
    assert pink > 40, "应该能看到粉色气泡"
    print("  截图：work/preview/live_alert_drop.png / live_alert_pop.png / live_alert_ripple.png")

    print("\n=== 3b. 气泡会盖到上面那一行 ===")
    other = going_live if going_live.mapTo(sidebar.list_box, QPoint(0, 0)).y() > 0 else None
    second = items["2002"] if other is None else other
    second.play_live_alert()                              # 第二行：气泡应该能往上一行伸
    settle(app, 0.2)
    second_alert = second._alert                          # noqa: SLF001
    freeze(second_alert, LiveAlert.DROP_MS + LiveAlert.POP_MS + 200)
    settle(app, 0.05)
    second_top = second.mapTo(sidebar.list_box, QPoint(0, 0)).y()
    box = second_alert.bubble_rect()
    print(f"  第二行 y={second_top} 气泡顶={box.top():.0f}"
          f" 伸到上一行={box.top() < second_top}")
    assert box.top() < second_top, "气泡应该往上一行弹过去"
    second.drop_live_alert()

    print("\n=== 4. 播完自动收掉，徽标停在「直播中」 ===")
    alert._timer.start()                                   # noqa: SLF001
    alert._elapsed = LiveAlert.TOTAL_MS - 10               # noqa: SLF001
    alert._tick()                                          # noqa: SLF001
    settle(app, 0.1)
    print(f"  动效结束：可见={alert.isVisible()} 计时器在跑={alert._timer.isActive()}")
    assert not alert.isVisible() and not alert._timer.isActive()
    assert going_live.badge.text() == "直播中", "动效结束后徽标要停在「直播中」"

    print("\n=== 5. 设置里可以关掉开播提醒 ===")
    third = {"room_id": "2003", "uname": "又一个主播", "title": "", "live": False,
             "muted": True, "quality": 250}
    sidebar.add_room(dict(third))
    settle(app, 0.3)
    new_item = next(item for item in sidebar.items()
                    if str(item.room.get("room_id")) == "2003")
    window.settings["live_alert"] = False
    window._on_status_updated({                            # noqa: SLF001
        "2003": {"live": True, "viewers": "100", "title": "", "face": ""},
    })
    settle(app, 0.3)
    print(f"  关掉之后：动效={new_item._alert} 徽标={new_item.badge.text()!r}")   # noqa: SLF001
    assert new_item._alert is None, "关掉开关就不该播动效"      # noqa: SLF001
    assert new_item.badge.text() == "直播中", "但状态还是要正常更新"
    window.settings["live_alert"] = True

    print("\n=== 6. 右键「播放开播提醒（测试）」随时能看 ===")
    from ddm.widgets import LiveAlert as _LiveAlert
    target = items["2002"]                      # 一直在播的那个
    assert target._alert is None or not target._alert.isVisible()   # noqa: SLF001
    target.play_live_alert_demo()                # 右键菜单里点的就是这个
    assert wait_for(lambda: target._alert is not None and target._alert.isVisible()), \
        "演示应该能随时触发"
    demo_alert = target._alert                   # noqa: SLF001
    print(f"  触发现场：徽标={target.badge.text()!r}（动效开始时会先压回未开播）"
          f" 动效在跑={demo_alert is not None and demo_alert._timer.isActive()}")
    assert demo_alert is not None and demo_alert.isVisible(), "演示应该能随时触发"
    freeze(demo_alert, _LiveAlert.DROP_MS - 100)
    settle(app, 0.05)
    print(f"  下落中徽标={target.badge.text()!r}（应该是未开播）")
    assert target.badge.text() == "未开播"
    demo_alert._timer.start()                    # noqa: SLF001
    demo_alert._elapsed = _LiveAlert.DROP_MS - 5 # noqa: SLF001
    demo_alert._tick()                           # noqa: SLF001
    settle(app, 0.05)
    print(f"  砸中后徽标={target.badge.text()!r}，动效继续到自然结束")
    assert target.badge.text() == "直播中"
    demo_alert._elapsed = _LiveAlert.TOTAL_MS - 10   # noqa: SLF001
    demo_alert._tick()                           # noqa: SLF001
    settle(app, 0.1)
    assert not demo_alert.isVisible()

    window.close()
    print("\n全部通过")


if __name__ == "__main__":
    main()
    # 直接退出进程：Qt / VLC 在线程收尾时析构会偶发崩在退出瞬间（程序本体也是这么做的）
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
