"""回归自检：关注列表的搜索框（以前只有外壳，输入什么都不起作用）。

要钉住的：
  1. 按主播名 / 房间号 / 直播间标题都能搜到，大小写不敏感；
  2. 多个词（空格分开）要全部命中才算匹配；
  3. 过滤只「藏起来」：条目顺序、置顶、多选态都不动；
  4. 藏起来的条目**不占位**（下面的卡片要顶上来的位置连续）；
  5. 一条都不匹配时给一句空态提示，不留一片空白；
  6. 清空搜索（清空按钮 / search.clear()）之后全部恢复；
  7. 过滤中收到状态刷新（resort）后过滤依然生效，新标题也能被搜到；
  8. 竖屏顶部那排头像跟着过滤；
  9. 进多选态会把搜索清掉（免得批量删除选中看不见的条目）。
"""
import os
import sys
import time

from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import theme  # noqa: E402
from ddm.app import MainWindow  # noqa: E402

ROOMS = [
    {"room_id": "9101", "uname": "小明的直播间", "title": "今晚打游戏",
     "live": True, "muted": True, "volume": 40, "quality": 250},
    {"room_id": "9102", "uname": "Alice", "title": "Morning Coffee",
     "live": False, "muted": True, "volume": 40, "quality": 250},
    {"room_id": "9103", "uname": "老张", "title": "钓鱼直播",
     "live": True, "muted": True, "volume": 40, "quality": 250},
    {"room_id": "9104", "uname": "Bob", "title": "深夜电台",
     "live": False, "muted": True, "volume": 40, "quality": 250},
]


def settle(app, seconds: float = 0.15) -> None:
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


def ids(items) -> list:
    return [str(item.room.get("room_id")) for item in items]


def main() -> None:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())
    window = MainWindow([dict(room) for room in ROOMS], [], state={})
    window.setGeometry(-9000, -9000, 1200, 700)
    window.show()
    settle(app, 0.4)
    sidebar = window.sidebar
    box = sidebar.list_box
    try:
        print("=== 1. 按主播名搜（中文子串）===")
        sidebar.search.setText("小明")
        settle(app)
        print(f"  「小明」-> {ids(sidebar.visible_items())}")
        assert ids(sidebar.visible_items()) == ["9101"]

        print("\n=== 2. 按房间号搜 ===")
        sidebar.search.setText("910")
        settle(app)
        print(f"  「910」-> {ids(sidebar.visible_items())}")
        assert ids(sidebar.visible_items()) == ["9101", "9102", "9103", "9104"]

        print("\n=== 3. 按标题搜 + 大小写不敏感 ===")
        sidebar.search.setText("morning")
        settle(app)
        print(f"  「morning」-> {ids(sidebar.visible_items())}")
        assert ids(sidebar.visible_items()) == ["9102"]
        sidebar.search.setText("ALICE")
        settle(app)
        print(f"  「ALICE」-> {ids(sidebar.visible_items())}")
        assert ids(sidebar.visible_items()) == ["9102"]

        print("\n=== 4. 多个词要全部命中（空格分开）===")
        sidebar.search.setText("深夜 电台")
        settle(app)
        print(f"  「深夜 电台」-> {ids(sidebar.visible_items())}")
        assert ids(sidebar.visible_items()) == ["9104"]
        sidebar.search.setText("深夜 钓鱼")
        settle(app)
        print(f"  「深夜 钓鱼」-> {ids(sidebar.visible_items())}（互斥词就该是空）")
        assert ids(sidebar.visible_items()) == []

        print("\n=== 5. 一条不匹配：空态提示顶上来，而且真的看得见 ===")
        hint = box.empty_hint
        print(f"  提示文字={hint.text()!r} 可见={hint.isVisible()}"
              f" 位置={hint.pos().x()},{hint.pos().y()} 高={hint.height()}")
        assert hint.isVisible(), "该显示空态提示"
        assert "深夜" in hint.text() and "钓鱼" in hint.text()
        assert box.height() >= box.EMPTY_HINT_HEIGHT, \
            "内容高度要容得下提示，否则它会被压没"

        print("\n=== 6. 清空搜索：全部回来，提示收掉 ===")
        sidebar.search.clear()
        settle(app)
        print(f"  清空后 -> {ids(sidebar.visible_items())}　提示可见={hint.isVisible()}")
        assert ids(sidebar.visible_items()) == ["9101", "9102", "9103", "9104"]
        assert not hint.isVisible()

        print("\n=== 7. 过滤只藏不排：条目顺序和置顶都不动 ===")
        before = ids(sidebar._items)                       # noqa: SLF001
        sidebar.toggle_pin({"room_id": "9103"})
        sidebar.apply_pins(["9103"])
        sidebar.sort_mode = "live"
        sidebar.resort(animate=False)
        settle(app)
        ordered = ids(sidebar._items)                      # noqa: SLF001
        print(f"  排序前 {before} -> 置顶 9103 + 开播优先 {ordered}")
        pinned_visible = [rid for rid in ordered if rid == "9103"]
        assert pinned_visible and ordered.index("9103") == 0, "置顶该在最前"
        sidebar.search.setText("老张")
        settle(app)
        print(f"  过滤「老张」后：可见 {ids(sidebar.visible_items())}，"
              f"内部顺序仍是 {ids(sidebar._items)}")
        assert ids(sidebar.visible_items()) == ["9103"]
        assert ids(sidebar._items) == ordered, "过滤不该改变条目顺序"
        # 藏起来的不能还占着位置：留下的那张要顶到最上面，
        # 而且内容该多高要按可见数算（控件本身被 QScrollArea 拉到视口高，看 minimumHeight）
        shown = sidebar.visible_items()
        print(f"  第一张 y={shown[0].y()}；内容高 {box.minimumHeight()}，"
              f"一张 {box.slot_height()}px（共 {len(shown)} 张可见）")
        assert shown[0].y() == 0, f"可见的第一张该顶在最上面，实际 y={shown[0].y()}"
        assert box.minimumHeight() <= len(shown) * box.slot_height() + 1, \
            f"内容高度该只算可见的那 {len(shown)} 张，实际 {box.minimumHeight()}"

        print("\n=== 8. 过滤中收到状态刷新：过滤仍然生效，新标题也能搜到 ===")
        sidebar.search.setText("小明")
        settle(app)
        item = next(entry for entry in sidebar._items
                    if str(entry.room.get("room_id")) == "9101")
        item.room["title"] = "改成了新标题 ABC"
        sidebar.resort(animate=False)                      # 状态刷新的出口
        settle(app)
        print(f"  刷新后「小明」仍可见 {ids(sidebar.visible_items())}")
        assert ids(sidebar.visible_items()) == ["9101"], "状态刷新不该把过滤弄丢"
        sidebar.search.setText("abc")
        settle(app)
        print(f"  用新标题「abc」搜 -> {ids(sidebar.visible_items())}")
        assert ids(sidebar.visible_items()) == ["9101"], "新标题要能被搜到"

        print("\n=== 9. 竖屏顶部头像排跟着过滤 ===")
        sidebar.search.clear()
        window.setGeometry(-9000, -9000, 500, 1000)        # 转竖屏
        settle(app, 0.35)
        assert window.orientation == "portrait", window.orientation
        print(f"  竖屏　侧栏 side={sidebar.side}")
        sidebar.search.setText("老张")
        settle(app)
        strip_rooms = [str(room.get("room_id")) for room in sidebar._head_strip._rooms]  # noqa: SLF001
        print(f"  过滤「老张」后头像排={strip_rooms}")
        assert strip_rooms == ["9103"], "竖屏头像排也该只剩匹配的那几个"

        print("\n=== 10. 进多选态会把搜索清掉 ===")
        sidebar.search.setText("老张")
        settle(app)
        sidebar.set_select_mode(True)
        settle(app)
        print(f"  进多选后 搜索框={sidebar.search.text()!r}"
              f" 过滤词={sidebar.filter_text!r} 可见={len(sidebar.visible_items())}")
        assert sidebar.search.text() == "" and sidebar.filter_text == ""
        assert len(sidebar.visible_items()) == len(sidebar._items)   # noqa: SLF001
    finally:
        window.close()
        settle(app, 0.2)
    print("\n全部通过")


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
