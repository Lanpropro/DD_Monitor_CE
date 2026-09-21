"""回归自检：拖动卡片时滚轮可用（拖动期间临时装低级鼠标钩子）。

Windows 上 Qt 的 ``QDrag::exec()`` 走 OLE 的 ``DoDragDrop``，那期间滚轮不再派发给
Qt 控件（API 级限制，不是 Qt 的 bug）。``ddm/mouse_hook.py`` 用 ``WH_MOUSE_LL``
把这个缺口补上。这里钉住四件事：

1. 钩子装得上、卸得掉、重复装卸幂等（装不上时静默降级，拖动本身不受影响）；
2. 回调解析：正 / 负 delta 都认，别的鼠标消息和 HC_ACTION 之外一律不理会；
3. 收到滚轮真的把关注列表滚起来（往下 delta<0、往上 delta>0，按格换算）；
4. ``begin_drag_scroll`` / ``end_drag_scroll`` 装上、卸干净。

**不发系统级滚轮**（那会干扰桌面当前窗口）：直接给回调喂造出来的 MSLLHOOKSTRUCT。
"""
import ctypes
import os
import sys
import time

from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import mouse_hook, theme  # noqa: E402
from ddm.app import MainWindow  # noqa: E402

ROOMS = [{"room_id": str(1000 + i), "uname": f"主播{i}", "title": "标题", "live": True,
          "muted": True, "volume": 42, "quality": 250} for i in range(40)]


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

    print("=== 1. 钩子装得上、卸得掉、重复装卸幂等 ===")
    hook = mouse_hook.WheelHook(lambda _delta: None)
    assert hook.start() is True, "Windows 上应该能装上 WH_MOUSE_LL"
    assert hook.active
    hook.stop()
    assert not hook.active, "stop() 之后必须真的卸掉"
    hook.start()
    hook.start()
    hook.stop()
    hook.stop()
    assert not hook.active
    print("  装上 / 卸掉 / 重复装卸都正常")

    print("\n=== 2. 回调解析：正负 delta 都认，别的消息不理会 ===")
    seen: list = []
    probe = mouse_hook.WheelHook(seen.append)
    loaded = mouse_hook._load()                     # noqa: SLF001
    assert loaded is not None
    probe._struct = loaded[1]                       # noqa: SLF001  只要类型，不装钩子

    def fire(delta: int) -> int:
        data = probe._struct()                      # noqa: SLF001
        data.mouseData = (delta & 0xFFFF) << 16
        return probe._dispatch(                     # noqa: SLF001
            mouse_hook.HC_ACTION, mouse_hook.WM_MOUSEWHEEL, ctypes.addressof(data))

    print(f"  +120 -> {fire(120)}   -120 -> {fire(-120)}")
    assert seen == [120, -120], f"正负 delta 都要认出来，实际 {seen}"
    assert probe._dispatch(mouse_hook.HC_ACTION, 0x0201, 0) == 0, \
        "左键按下之类的消息不该理会"                 # noqa: SLF001
    assert probe._dispatch(3, mouse_hook.WM_MOUSEWHEEL, 0) == 0, \
        "HC_ACTION 之外不处理"                      # noqa: SLF001
    print("  非滚轮消息 / 非 HC_ACTION 都安静放过")

    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())
    window = MainWindow([dict(room) for room in ROOMS], [], layout_id="1x1")
    window.setGeometry(-9000, -9000, 1400, 800)
    window.show()
    settle(app, 1.0)

    sidebar = window.sidebar
    box = sidebar.list_box
    bar = sidebar.scroll.verticalScrollBar()
    assert bar.maximum() > 0, "自检要有能滚的列表"

    print("\n=== 3. 收到滚轮真的把列表滚起来 ===")
    start = bar.value()
    sidebar._scroll_from_wheel(-mouse_hook.WHEEL_DELTA)      # noqa: SLF001  往下
    down = bar.value()
    print(f"  往下：{start} -> {down}（一格 {box.WHEEL_PIXELS}px）")
    assert down == start + box.WHEEL_PIXELS, "往下滚一格要正好走 WHEEL_PIXELS"

    sidebar._scroll_from_wheel(mouse_hook.WHEEL_DELTA)       # noqa: SLF001  往上
    up = bar.value()
    print(f"  往上：{down} -> {up}")
    assert up == start, "往上滚一格要回到原位"

    sidebar._scroll_from_wheel(-mouse_hook.WHEEL_DELTA // 2)  # noqa: SLF001  半格
    print(f"  半格：{up} -> {bar.value()}（高精度滚轮/触控板）")
    assert bar.value() == start + box.WHEEL_PIXELS // 2

    print("\n=== 4. begin / end_drag_scroll 装上、卸干净 ===")
    sidebar.begin_drag_scroll()
    dragging = sidebar._wheel_hook                              # noqa: SLF001
    print(f"  拖动开始 -> 钩子 active={dragging is not None and dragging.active}")
    assert dragging is not None and dragging.active, "拖动开始要装上钩子"
    sidebar.end_drag_scroll()
    assert sidebar._wheel_hook is None, "拖动结束必须卸掉"       # noqa: SLF001
    sidebar.end_drag_scroll()                                   # 幂等
    print("  拖动结束 -> 钩子已卸掉，再调一次也不炸")

    window.close()
    settle(app, 0.3)
    print("\n全部通过")


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
