"""自查：开播提醒与「开播优先」重排的先后顺序。

原来的做法是「先播动效、再重排」：水滴/气泡按卡片**挪走之前**的位置画，
而卡片已经被重排挪到上面，于是动效留在原来那一行，看起来两者错开了。
现在的约定是「先重排、再播动效」，所以断言两件事：

1. 状态更新的那一轮里，卡片已经在它该在的位置（开播优先时排到最前）；
2. 动效的落点（水滴砸的那个点）等于卡片**新位置**上徽标的顶边中点。

不联网。
"""
import os
import sys
import time

from PySide6.QtCore import QPoint, QPointF, QThread, Signal
from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import bili, theme  # noqa: E402
from ddm import app as app_module  # noqa: E402
from ddm.app import MainWindow  # noqa: E402
from ddm.widgets import NAV_ITEM_GAP  # noqa: E402


def boom(room_id, quality=250):        # noqa: ANN001, ANN201
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
    {"room_id": "3001", "uname": "没开播的甲", "title": "还没开", "live": False,
     "muted": True, "quality": 250},
    {"room_id": "3002", "uname": "待会儿开播", "title": "还没开", "live": False,
     "muted": True, "quality": 250},
    {"room_id": "3003", "uname": "已经在播", "title": "播着呢", "live": True,
     "muted": True, "quality": 250},
]


def settle(app, seconds):
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)


def wait_for(predicate, timeout: float = 4.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        QApplication.processEvents()
        time.sleep(0.02)
    return bool(predicate())


def item_top(sidebar, item) -> float:
    return item.mapTo(sidebar.list_box, QPoint(0, 0)).y()


def badge_target(host, item) -> QPointF:
    """卡片当前位置上，徽标顶边中点（= 动效该落的地方），在 host 坐标系里。"""
    origin = item.badge.mapTo(host, QPoint(0, 0))
    return QPointF(origin.x() + item.badge.width() / 2, origin.y())


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
    sidebar.set_sort_mode("live")
    settle(app, 0.3)
    items = {str(item.room.get("room_id")): item for item in sidebar.items()}
    going_live = items["3002"]

    print("=== 1. 开播优先下，未开播的排在开播的后面 ===")
    order_before = [str(item.room.get("room_id")) for item in sidebar.items()]
    print(f"  开播前顺序={order_before}")
    assert order_before == ["3003", "3001", "3002"], f"开播的应该在最前，实际 {order_before}"
    old_top = item_top(sidebar, going_live)
    print(f"  3002 开播前 y={old_top}")

    print("\n=== 2. 状态更新后：卡片先上移，再在**新位置**播动效 ===")
    window._on_status_updated({                       # noqa: SLF001
        "3002": {"live": True, "viewers": "3.2万", "title": "开了", "face": ""},
    })
    order_after = [str(item.room.get("room_id")) for item in sidebar.items()]
    print(f"  开播后顺序={order_after}")
    assert order_after == ["3002", "3003", "3001"], f"开播优先应把 3002 挪到最前，实际 {order_after}"
    new_top = item_top(sidebar, going_live)
    print(f"  3002 开播后 y={new_top}（开播前 {old_top}）")
    assert new_top != old_top, "开播后卡片应该换位置"
    assert new_top < old_top, "开播优先应该把卡片往上挪"

    # 动效是重排之后才建的，所以这里必须查 _alert，不能先取出来再判空
    if not wait_for(lambda: going_live._alert is not None      # noqa: SLF001
                    and going_live._alert.isVisible()):        # noqa: SLF001
        print(f"  [诊断] _alert={going_live._alert!r}")          # noqa: SLF001
    assert going_live._alert is not None, "重排之后仍然要播开播提醒"   # noqa: SLF001
    alert = going_live._alert                          # noqa: SLF001
    assert alert.isVisible(), "重排之后仍然要播开播提醒"

    host = alert.parentWidget()
    target = badge_target(host, going_live)
    anchor = alert._anchor                             # noqa: SLF001
    print(f"  动效落点 anchor=({anchor.x():.1f},{anchor.y():.1f}) "
          f"卡片新位置徽标顶边中点=({target.x():.1f},{target.y():.1f})")
    assert abs(anchor.y() - target.y()) <= 1.5, \
        f"动效应该落在卡片新位置的徽标上，而不是挪走前那一行（差 {anchor.y() - target.y():.1f}px）"
    assert abs(anchor.x() - target.x()) <= 1.5, "动效横向也应该对准徽标"

    print("\n=== 3. 动效落点不在卡片旧位置上 ===")
    # 旧位置 = 新位置 + 一格；确认落点不是旧位置（否则就是没跟着卡片走）
    slot = sidebar.list_box.slot_height()
    old_target_y = target.y() + slot
    print(f"  旧位置徽标顶边 y≈{old_target_y:.1f} 新位置 y≈{target.y():.1f} "
          f"落点 y={anchor.y():.1f}")
    assert abs(anchor.y() - old_target_y) > 10, "落点不能停在卡片挪走之前的位置"

    print("\n=== 4. 徽标仍由动效砸中时才切换 ===")
    alert._timer.stop()                                # noqa: SLF001
    alert._elapsed = 0                                 # noqa: SLF001
    alert.repaint()
    assert going_live.badge.text() == "未开播", "水滴还没落，徽标应仍是未开播"
    alert._elapsed = alert.DROP_MS - 5                 # noqa: SLF001
    alert._tick()                                      # noqa: SLF001
    settle(app, 0.1)
    print(f"  砸中后徽标={going_live.badge.text()!r}")
    assert going_live.badge.text() == "直播中", "砸中那一刻徽标要变成直播中"

    print("\n=== 5. 一次轮询里多个开播：都要播，且都落在各自位置上 ===")
    going_live.drop_live_alert()
    items["3003"].set_live(False)
    window._on_status_updated({                        # noqa: SLF001
        "3003": {"live": True, "viewers": "100", "title": "也开了", "face": ""},
    })
    third = items["3003"]
    assert wait_for(lambda: third._alert is not None and third._alert.isVisible()), \
        "第二个开播的也要播提醒"
    third_target = badge_target(third._alert.parentWidget(), third)
    print(f"  3003 落点 y={third._alert._anchor.y():.1f} "
          f"目标 y={third_target.y():.1f}")
    assert abs(third._alert._anchor.y() - third_target.y()) <= 1.5, \
        "第二个开播的动效也要落在它自己的位置上"

    print("\n=== 6. 关掉开关：只重排、不播动效 ===")
    fourth = {"room_id": "3004", "uname": "再一个", "title": "", "live": False,
              "muted": True, "quality": 250}
    sidebar.add_room(dict(fourth))
    settle(app, 0.3)
    new_item = next(item for item in sidebar.items()
                    if str(item.room.get("room_id")) == "3004")
    window.settings["live_alert"] = False
    window._on_status_updated({                        # noqa: SLF001
        "3004": {"live": True, "viewers": "1", "title": "", "face": ""},
    })
    settle(app, 0.3)
    print(f"  动效={new_item._alert} 徽标={new_item.badge.text()!r}")   # noqa: SLF001
    assert new_item._alert is None, "关掉开关就不该播动效"
    assert new_item.badge.text() == "直播中", "但状态还是要正常更新"
    assert new_item.room["live"] is True, "状态置位不受开关影响"

    window.close()
    print("\n全部通过")


if __name__ == "__main__":
    main()
    # 直接退出进程：Qt / VLC 在线程收尾时析构会偶发崩在退出瞬间（程序本体也是这么做）
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
