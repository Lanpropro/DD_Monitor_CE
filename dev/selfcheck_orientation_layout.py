"""回归自检：横竖屏切换时，各方向的布局要各自记着。

用户报的：横屏切到竖屏（自动换了布局）之后，只要他没在竖屏动过布局，切回横屏
就该还是切之前那套 —— 以前不是。因为 `layouts.counterpart()` 是**按容量就近
折算**的：横屏「主画面 + 5 小环绕」和「六分」都是 6 路，从竖屏折回来时平手取到
排在前面那个（六分），横屏布局就被悄悄换掉了。

现在 `_apply_orientation()` 会把「切走之前在用的那套」记在原方向名下，切回来优先
还原；只有本次会话第一次进某个方向时才按容量折算 —— 这一条不能丢，用户报过
「横屏 1+2 拖成竖屏，结果用了以前在竖屏存过的 1+2+弹幕」。

这里钉住六件事：
  1. 横屏 corner -> 竖屏 -> 回横屏，还是 corner；
  2. 横屏 1+2 -> 竖屏 -> 回横屏，还是 1+2；
  3. 在竖屏手动换过布局：回横屏仍是横屏原来那套，再进竖屏用他换过的那套；
  4. 本次会话第一次进竖屏仍然「跟着横屏走」，不退成 PORTRAIT_AUTO；
  5. 来回切 5 轮不漂移；
  6. 在竖屏里选了横屏布局，窗口转过去后用的就是他选的那套（不能被还原逻辑顶掉）。
"""
import os
import sys
import time

from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import layouts, theme  # noqa: E402
from ddm.app import MainWindow  # noqa: E402

LANDSCAPE = (1400, 800)
PORTRAIT = (500, 1000)
ROOM = {"room_id": "selfcheck-9101", "uname": "自检主播", "title": "标题",
        "live": False, "muted": True, "volume": 40, "quality": 250}


def settle(app, seconds: float = 0.15) -> None:
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


def make_window(app) -> MainWindow:
    """干净状态的窗口：不传 layout_id、state 给空 dict，免得读到用户配置。"""
    window = MainWindow([dict(ROOM)], [], state={})
    window.setGeometry(-9000, -9000, *LANDSCAPE)
    window.show()
    settle(app)
    return window


def turn(app, window, size) -> str:
    """把窗口拧成指定方向，返回换完之后用的布局。"""
    window.resize(*size)
    settle(app, 0.25)
    return window.wall.layout_id


def main() -> None:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())
    window = make_window(app)
    try:
        print("=== 1. 横屏 corner -> 竖屏 -> 回横屏，还是 corner ===")
        assert window.wall.layout_id == layouts.FIRST_LAYOUT, window.wall.layout_id
        turned = turn(app, window, PORTRAIT)
        assert window.orientation == "portrait", window.orientation
        assert layouts.is_portrait_layout(turned), f"竖屏该给竖屏布局，得到 {turned}"
        back = turn(app, window, LANDSCAPE)
        print(f"  横屏 {layouts.FIRST_LAYOUT} -> 竖屏 {turned} -> 回横屏 {back}")
        assert window.orientation == "landscape"
        assert back == layouts.FIRST_LAYOUT, \
            f"回横屏该还是 {layouts.FIRST_LAYOUT}，实际 {back}（被容量折算换掉了）"

        print("\n=== 2. 横屏换成 1+2 再转一圈，回来还是 1+2 ===")
        window._on_layout_changed("1x2")            # noqa: SLF001  相当于在菜单里选
        settle(app)
        assert window.wall.layout_id == "1x2"
        mid = turn(app, window, PORTRAIT)
        back = turn(app, window, LANDSCAPE)
        print(f"  横屏 1x2 -> 竖屏 {mid} -> 回横屏 {back}")
        assert back == "1x2", f"回横屏该还是 1x2，实际 {back}"

        print("\n=== 3. 竖屏手动换过布局：横屏不受影响，竖屏记住他换的那套 ===")
        turn(app, window, PORTRAIT)
        chosen = "portrait_dm4"
        window._on_layout_changed(chosen)           # noqa: SLF001
        settle(app)
        assert window.wall.layout_id == chosen, window.wall.layout_id
        back = turn(app, window, LANDSCAPE)
        again = turn(app, window, PORTRAIT)
        print(f"  竖屏选 {chosen} -> 回横屏 {back} -> 再进竖屏 {again}")
        assert back == "1x2", f"横屏不该被竖屏的选择带跑，实际 {back}"
        assert again == chosen, f"竖屏自己选过的那套要留着，实际 {again}"

        print("\n=== 4. 第一次进竖屏：跟着横屏走（按容量对映），不退成 PORTRAIT_AUTO ===")
        # 清掉本次会话的记忆，就等价于「第一次进竖屏」；不另开窗口，少一份资源
        turn(app, window, LANDSCAPE)
        window._layout_by_orientation.clear()       # noqa: SLF001
        window._on_layout_changed("1x2")            # noqa: SLF001
        settle(app)
        got = turn(app, window, PORTRAIT)
        print(f"  横屏 1x2 -> 竖屏 {got}（PORTRAIT_AUTO={layouts.PORTRAIT_AUTO}）")
        assert got == layouts.counterpart("1x2", True), got
        assert got != layouts.PORTRAIT_AUTO, "不该一律退成「自动」那套"

        print("\n=== 5. 来回切 5 轮不漂移 ===")
        window._on_layout_changed("corner")         # noqa: SLF001
        settle(app)
        seen: list = []
        for _ in range(5):
            seen.append(turn(app, window, PORTRAIT))
            seen.append(turn(app, window, LANDSCAPE))
        portrait_seen = {seen[index] for index in range(0, len(seen), 2)}
        landscape_seen = {seen[index] for index in range(1, len(seen), 2)}
        print(f"  竖屏侧 {sorted(portrait_seen)}  横屏侧 {sorted(landscape_seen)}")
        assert landscape_seen == {"corner"}, f"横屏该一直是 corner，实际 {landscape_seen}"
        assert len(portrait_seen) == 1, f"竖屏侧也不该每轮变一个，实际 {portrait_seen}"

        print("\n=== 6. 在竖屏里选了横屏布局：窗口转过去后就是他选的那套 ===")
        turn(app, window, PORTRAIT)
        window._on_layout_changed("two_rows")       # noqa: SLF001  横屏布局
        settle(app, 0.3)
        print(f"  转成 {window.orientation}　布局={window.wall.layout_id}")
        assert window.orientation == "landscape", "选了横屏布局该把窗口也转成横屏"
        assert window.wall.layout_id == "two_rows", \
            f"用户刚选的那套不能被「还原记忆」顶掉，实际 {window.wall.layout_id}"
    finally:
        window.close()
        settle(app, 0.2)
    print("\n全部通过")


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
