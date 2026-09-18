"""自查：关注列表拖动排序（含置顶约束）、布局菜单的两个子菜单切换。不联网。"""
import os
import sys
import time

from PySide6.QtCore import QMimeData, QPointF, Qt
from PySide6.QtGui import QCursor, QDropEvent
from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import layouts, theme  # noqa: E402
from ddm.widgets import (  # noqa: E402
    NAV_ITEM_GAP, NAV_ITEM_HEIGHT, LayoutPicker, Sidebar,
)

ROOMS = [{"room_id": f"100{index}", "uname": f"主播{index}", "title": f"房间{index}",
          "live": index % 2 == 0}
         for index in range(1, 6)]


def order(sidebar):
    return [str(item.room.get("room_id")) for item in sidebar.items()]


def settle(app, seconds):
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.03)


def drop_at(sidebar, room_id: str, y: float):
    mime = QMimeData()
    mime.setData("application/x-ddm-nav", str(room_id).encode("utf-8"))
    event = QDropEvent(QPointF(20, y), Qt.MoveAction, mime, Qt.LeftButton, Qt.NoModifier)
    sidebar.list_box.dropEvent(event)


def main() -> None:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())

    print("=== 0. 新增关注项立即排版，不与第一项重叠 ===")
    added_sidebar = Sidebar([dict(ROOMS[0])])
    added_sidebar.setGeometry(-8000, -8000, 248, 300)
    added_sidebar.show()
    settle(app, 0.2)
    assert added_sidebar.add_room(dict(ROOMS[1]))
    positions = [item.y() for item in added_sidebar.items()]
    print("  新增后位置:", positions)
    assert positions == [0, NAV_ITEM_HEIGHT + NAV_ITEM_GAP]
    added_sidebar.close()

    print("\n=== 0b. 开播优先持续生效，且拖动不能跨直播状态组 ===")
    live_rooms = [
        {"room_id": "l1", "uname": "直播1", "live": True},
        {"room_id": "o1", "uname": "下播1", "live": False},
        {"room_id": "l2", "uname": "直播2", "live": True},
        {"room_id": "o2", "uname": "下播2", "live": False},
    ]
    live_sidebar = Sidebar([dict(room) for room in live_rooms])
    live_sidebar.set_sort_mode("live", notify=False)
    print("  初始分组:", order(live_sidebar))
    assert order(live_sidebar) == ["l1", "l2", "o1", "o2"]
    live_sidebar.reorder_item("l1", len(live_sidebar.items()))
    print("  直播项拖到最底部后:", order(live_sidebar), "模式:", live_sidebar.sort_mode)
    assert order(live_sidebar) == ["l2", "l1", "o1", "o2"]
    assert live_sidebar.sort_mode == "live", "拖动后不能退出开播优先模式"
    next(item for item in live_sidebar.items() if item.room["room_id"] == "o1").set_live(True)
    live_sidebar.resort(animate=False)
    print("  o1 开播后自动重排:", order(live_sidebar))
    assert order(live_sidebar) == ["l2", "l1", "o1", "o2"]
    next(item for item in live_sidebar.items() if item.room["room_id"] == "l2").set_live(False)
    live_sidebar.resort(animate=False)
    print("  l2 下播后自动重排:", order(live_sidebar))
    assert order(live_sidebar) == ["l1", "o1", "l2", "o2"]
    live_sidebar.close()

    sidebar = Sidebar([dict(room) for room in ROOMS])
    sidebar.setGeometry(-8000, -8000, 248, 700)
    sidebar.show()
    settle(app, 0.5)

    print("=== 1. 置顶后置顶的两个排在最上面 ===")
    sidebar.toggle_pin(sidebar.items()[2].room)      # 1003 置顶
    sidebar.toggle_pin(sidebar.items()[3].room)      # 1004 置顶
    print("  顺序:", order(sidebar), "置顶表:", sidebar.pinned)
    assert order(sidebar)[:2] == ["1003", "1004"]

    print("\n=== 2. 普通项拖不到置顶上方 ===")
    changed = sidebar.reorder_item("1001", 0)        # 想把 1001 拖到最上面
    print("  拖动结果:", changed, "顺序:", order(sidebar))
    assert order(sidebar)[0] == "1003" and order(sidebar)[1] == "1004"
    assert order(sidebar)[2] == "1001", "应该落在置顶区下面第一格"

    print("\n=== 3. 置顶项之间可以互相换顺序 ===")
    sidebar.reorder_item("1004", 0)
    print("  顺序:", order(sidebar), "置顶表:", sidebar.pinned)
    assert order(sidebar)[:2] == ["1004", "1003"]
    assert sidebar.pinned == ["1004", "1003"]

    print("\n=== 4. 置顶项拖不到下面（收回置顶区末尾）===")
    sidebar.reorder_item("1004", 5)
    print("  顺序:", order(sidebar), "置顶表:", sidebar.pinned)
    assert order(sidebar)[:2] == ["1003", "1004"], "置顶项只能落在置顶区里"
    assert order(sidebar)[2] == "1001", "普通项不会被推到置顶区"

    print("\n=== 5. 普通项之间可以排到末尾 ===")
    before = order(sidebar)
    sidebar.reorder_item("1001", len(before))
    print(f"  {before} -> {order(sidebar)}")
    assert order(sidebar)[-1] == "1001"
    assert order(sidebar)[:2] == ["1003", "1004"]

    print("\n=== 6. 列表真的接收拖动（模拟落点）===")
    assert sidebar.list_box.acceptDrops(), "列表容器要允许拖放"
    settle(app, 0.4)
    y = sidebar.list_box.content_height() + 10       # 落在所有卡片下面
    drop_at(sidebar, "1001", y)
    settle(app, 0.4)
    print(f"  落点 y={y:.0f} 之后顺序: {order(sidebar)}")
    assert order(sidebar)[-1] == "1001"
    assert order(sidebar)[:2] == ["1003", "1004"]

    print("\n=== 7. 抓起来拖动：卡片让位（空出一格）===")
    sidebar.show_drop_indicator("1001", 2)
    settle(app, 0.4)
    held = next(entry for entry in sidebar.items()
                if str(entry.room.get("room_id")) == "1001")
    others = [entry for entry in sidebar.items() if entry is not held]
    print(f"  被拖的卡片隐藏={not held.isVisible()}"
          f" 其余卡片位置={[entry.y() for entry in others]}"
          f" 列表高度={sidebar.list_box.minimumHeight()}")
    assert not held.isVisible(), "抓起来的那张要从列表里拿掉"
    pitch = NAV_ITEM_HEIGHT + NAV_ITEM_GAP
    assert others[1].y() >= others[0].y() + pitch - NAV_ITEM_GAP, "落点位置要空出一格"
    sidebar.show_drop_indicator(None, 0)
    settle(app, 0.4)
    print(f"  恢复后：全部可见={all(entry.isVisible() for entry in sidebar.items())}"
          f" 位置={[entry.y() for entry in sidebar.items()]}")
    assert all(entry.isVisible() for entry in sidebar.items())
    assert [entry.y() for entry in sidebar.items()] == [index * pitch
                                                       for index in range(5)]

    print("\n=== 8. 松手结算：列表内排序 / 列表外只放回去 ===")
    inside = sidebar.list_box.mapToGlobal(QPointF(20, sidebar.list_box.slot_height() * 1.2)
                                          .toPoint())
    before = order(sidebar)
    sidebar.finish_drag("1001", inside)
    settle(app, 0.4)
    print(f"  列表内松手：{before} -> {order(sidebar)}")
    assert order(sidebar)[:2] == ["1003", "1004"], "置顶区不能被顶掉"
    assert order(sidebar)[2] == "1001", "拖到列表里应该真的排到那个位置"

    sidebar.show_drop_indicator("1001", 3)
    settle(app, 0.3)
    outside = sidebar.list_box.mapToGlobal(QPointF(20, -400).toPoint())
    before = order(sidebar)
    sidebar.finish_drag("1001", outside)
    settle(app, 0.4)
    print(f"  列表外松手：{before} -> {order(sidebar)}"
          f" 全部可见={all(entry.isVisible() for entry in sidebar.items())}")
    assert order(sidebar) == before, "拖到列表外面不应该改顺序"
    assert all(entry.isVisible() for entry in sidebar.items()), "卡片要放回去"

    print("\n=== 9. 布局菜单：横屏只列横屏那两栏（不列竖屏预设）===")
    picker = LayoutPicker("dm_main3")
    picker.move(-8000, -8000)
    picker.show()
    settle(app, 0.5)
    tabs = list(picker._tabs)
    print(f"  子菜单: {tabs} 当前={picker.group()}")
    assert tabs == ["普通布局", "弹幕布局"], \
        "横屏不该列出竖屏预设（套上去画面会变形）"
    assert picker.group() == "弹幕布局", "当前布局在弹幕组里，默认应该停在这一栏"
    compact_size = picker.size()
    visible = [card.text() for card in picker._cards["弹幕布局"] if card.isVisible()]
    print(f"  弹幕布局可见: {len(visible)} 个 -> {visible[:3]} …")
    assert len(visible) == len(layouts.DANMAKU_LAYOUTS)
    assert not any(card.isVisible() for card in picker._cards["普通布局"])

    picker.set_group("普通布局")
    settle(app, 0.3)
    visible = [card.text() for card in picker._cards["普通布局"] if card.isVisible()]
    print(f"  切到普通布局：{len(visible)} 个可见，尺寸={picker.width()}x{picker.height()}"
          f"（切栏前后尺寸保持一致）")
    assert len(visible) == len(layouts.LAYOUTS)
    assert not any(card.isVisible() for card in picker._cards["弹幕布局"])
    assert picker._tabs["普通布局"].isChecked()
    assert picker.size() == compact_size, "切换到普通布局时弹层不能突然向屏幕外增长"
    # 用户报的：不同布局的卡片大小不一样、上下没对齐 —— 卡片尺寸必须统一
    sizes = {(card.width(), card.height())
             for group in picker._cards.values() for card in group}
    row_tops = sorted({card.y() for card in picker._cards["普通布局"]})
    row_heights = {card.y(): card.height() for card in picker._cards["普通布局"]}
    print(f"  卡片尺寸: {sizes} 各行 y={row_tops} 行高={sorted(set(row_heights.values()))}")
    assert len(sizes) == 1, f"布局卡片要一样大（用户报的错位）：{sizes}"
    card_height = sizes.pop()[1]
    step = card_height + picker._grid.spacing()
    heading = picker._sections["普通布局"][0]
    heading_step = step + heading.height() + picker._grid.spacing()
    pitches = {b - a for a, b in zip(row_tops, row_tops[1:])}
    print(f"  行间距: {sorted(pitches)}（正常 {step}、跨小标题那一行 {heading_step}）")
    assert all(pitch in (step, heading_step) for pitch in pitches), \
        f"行间距只该有「正常」和「跨小标题」两种，不然就是没对齐：{sorted(pitches)}"
    # 用户要求：主画面 + 2 小那里换行 + 小标题，把平分布局和大带小分开
    section_rows = [heading.text() for heading in picker._sections["普通布局"]]
    print(f"  普通布局里的小标题: {section_rows}")
    assert section_rows == ["大带小"], f"应该有且只有「大带小」这一段：{section_rows}"
    big_small = [card.text() for card in picker._cards["普通布局"]
                 if card.property("layoutId") in ("main2", "left2_right1")]
    print(f"  镜像对: {big_small}")
    assert len(big_small) == 2, "主画面 + 2 小 和它的镜像都要在"
    assert all("2 小" in text for text in big_small), big_small
    assert "主画面 + 6 小" not in [card.text() for card in picker._cards["普通布局"]], \
        "1+6 已经按用户要求去掉"
    # 用户 2026-09-18：把「自动」从菜单里去掉（切回自动会按上一个布局的行列走，误导）
    assert "自动" not in [card.text() for card in picker._cards["普通布局"]], \
        "「自动」已经从布局菜单里去掉"
    assert "auto" not in [card.property("layoutId") for card in picker._cards["普通布局"]]
    assert "auto" not in layouts.BY_ID and layouts.DEFAULT_LAYOUT in layouts.BY_ID, \
        "老配置里的 auto 要折算成 DEFAULT_LAYOUT"

    chosen: list[str] = []
    picker.chosen.connect(chosen.append)
    picker._cards["普通布局"][0].click()
    print(f"  点第一个卡片 -> chosen={chosen}")
    assert chosen == [layouts.LAYOUTS[0]["id"]]

    picker.close()
    print("  打开侧栏布局菜单时应自动限制在屏幕可用区域")
    sidebar.setGeometry(-8000, -8000, 248, 700)
    sidebar.open_layout_picker()
    popup = sidebar._picker
    settle(app, 0.2)
    rect = popup.frameGeometry()
    # 别拿 primaryScreen() 硬套：窗口在离屏位置时，选择器可能被摆到副屏上，
    # 这时用主屏的可用区域去断言必然失败。按它实际所在的屏幕来判。
    screen = (QApplication.screenAt(rect.center())
              or QApplication.screenAt(QCursor.pos())
              or QApplication.primaryScreen())
    if screen is not None:
        area = screen.availableGeometry()
        print(f"  菜单全局位置={rect.getRect()} 所在屏可用区域={area.getRect()}")
        assert rect.top() >= area.top() and rect.bottom() <= area.bottom(), \
            f"弹层纵向超出屏幕：{rect.getRect()} vs {area.getRect()}"
        assert rect.left() >= area.left() and rect.right() <= area.right(), \
            f"弹层横向超出屏幕：{rect.getRect()} vs {area.getRect()}"
        before = popup.frameGeometry()
        popup.set_group("普通布局")
        settle(app, 0.2)
        after = popup.frameGeometry()
        assert after.size() == before.size(), "切换普通布局后弹层尺寸必须保持不变"
        assert after.top() >= area.top() and after.bottom() <= area.bottom()
    popup.close()
    sidebar.close()
    print("\n全部通过")


if __name__ == "__main__":
    main()
    # 直接退出进程：Qt / VLC 在线程收尾时析构会偶发崩在退出瞬间（程序本体也是这么做的）
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
