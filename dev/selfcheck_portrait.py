"""自查：竖屏布局。

竖屏不能用「行列等分」那套：主画面要 16:9，小画面也要接近 16:9，等分网格只能
满足一个。所以竖屏预设（portrait_mainN / portrait_dmN）由 WallGrid 单独摆放：
主画面整宽 + 按 16:9 固定高度，小画面在剩下的空间里按自动网格排。

这里断言的就是这件事：主画面比例、小画面数量与不重叠、超出的格子要隐藏、
弹幕贴底整宽。

不联网。
"""
import os
import sys
import time

from PySide6.QtCore import QMimeData, QPointF, Qt, QThread, Signal
from PySide6.QtWidgets import QApplication

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import bili, layouts, theme  # noqa: E402
from ddm import app as app_module  # noqa: E402
from ddm.app import MainWindow  # noqa: E402

# 竖屏：典型手机/竖屏显示器
PORTRAIT = (1080, 1920)
LANDSCAPE = (1600, 900)


class SilentPoller(QThread):
    updated = Signal(dict)

    def __init__(self, room_ids, parent=None):
        super().__init__(parent)
        self.room_ids = list(room_ids)

    def run(self) -> None:
        return


def boom(room_id, quality=250):        # noqa: ANN001, ANN201
    raise RuntimeError("selfcheck：不联网")


def rooms(count: int) -> list[dict]:
    return [{"room_id": str(8000 + index), "uname": f"主播{index + 1}",
             "title": "直播间标题", "live": True, "viewers": "1万",
             "muted": True, "volume": 42, "quality": 250}
            for index in range(count)]


def settle(app, seconds: float) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.03)


def ratio(widget) -> float:
    return widget.width() / max(1, widget.height())


def part_layouts() -> None:
    print("=== 1. 布局表：竖屏预设已注册、并且被标成 portrait ===")
    ids = [layout["id"] for layout in layouts.PORTRAIT_LAYOUTS]
    dm_ids = [layout["id"] for layout in layouts.PORTRAIT_DANMAKU_LAYOUTS]
    print(f"  普通竖屏: {ids}")
    print(f"  带弹幕: {dm_ids}")
    assert ids == ["portrait_main2", "portrait_main4", "portrait_main6"], ids
    assert dm_ids == ["portrait_dm2", "portrait_dm4", "portrait_dm6"], dm_ids
    for layout_id in ids + dm_ids:
        assert layout_id in layouts.BY_ID, f"{layout_id} 没进 BY_ID"
        assert layouts.is_portrait_layout(layout_id), f"{layout_id} 应该标成竖屏"
        # 缩略图能画出来（菜单里要用）
        assert not layouts.thumbnail(layouts.BY_ID[layout_id]["spec"]).isNull()
    # 横屏的布局不能被打上竖屏标记
    for layout_id in ("auto", "1x1", "2x2", "main3", "dm_main3"):
        assert not layouts.is_portrait_layout(layout_id), layout_id
    print(f"  自动布局在竖屏下用：{layouts.PORTRAIT_AUTO}")
    assert layouts.PORTRAIT_AUTO in layouts.BY_ID
    assert layouts.is_portrait_layout(layouts.PORTRAIT_AUTO)

    print("\n=== 2. 布局菜单多出「竖屏布局」一组 ===")
    names = [name for name, _group in layouts.GROUPS]
    print(f"  分组: {names}")
    assert names == ["普通布局", "弹幕布局", "竖屏布局"], names
    group = dict(layouts.GROUPS)["竖屏布局"]
    assert len(group) == 6, f"竖屏组应该 6 个预设，实际 {len(group)}"


def part_portrait(app) -> None:
    print("\n=== 3. 竖屏 main6：主画面 16:9 占满宽，六个小画面在下面 ===")
    window = MainWindow(rooms(7), rooms(7), layout_id="portrait_main6")
    window.setGeometry(-9000, -9000, *PORTRAIT)
    window.show()
    settle(app, 1.2)
    wall = window.wall
    main, small = wall.tiles[0], wall.tiles[1:]
    print(f"  窗口 {PORTRAIT[0]}x{PORTRAIT[1]}  画面墙 {wall.width()}x{wall.height()}")
    print(f"  主画面 {main.width()}x{main.height()}  视频区比例 {ratio(main.video):.3f}"
          f"（16:9 = {16/9:.3f}）")
    assert abs(ratio(main) - 16 / 9) < 0.06, \
        f"主画面应该保持 16:9，实际 {ratio(main):.3f}"
    assert main.width() > wall.width() * 0.85, "主画面应该占满整宽"

    widths = {tile.width() for tile in small if tile.isVisible()}
    heights = {tile.height() for tile in small if tile.isVisible()}
    print(f"  小画面：可见 {sum(1 for t in small if t.isVisible())}/6 "
          f"宽集合={sorted(widths)} 高集合={sorted(heights)}")
    assert len(widths) == 1 and len(heights) == 1, "小画面应该尺寸一致"
    assert main.height() > small[0].height(), "主画面要比小画面高"
    print(f"  主画面 {main.width()}x{main.height()} vs 小画面 "
          f"{small[0].width()}x{small[0].height()}")
    print(f"  小画面比例 {ratio(small[0]):.3f}")

    print("\n=== 4. 格子不重叠、且都在画面墙内 ===")
    rects = [tile.geometry() for tile in wall.tiles if tile.isVisible()]
    for index, first in enumerate(rects):
        for second in rects[index + 1:]:
            assert not first.intersects(second), f"格子重叠：{first} / {second}"
    for rect in rects:
        assert rect.left() >= 0 and rect.top() >= 0, f"格子跑到墙外：{rect}"
        assert rect.right() <= wall.width() + 2, f"格子超出右边界：{rect}"
        assert rect.bottom() <= wall.height() + 2, f"格子超出下边界：{rect}"
    # 主画面在最上面
    assert main.geometry().top() < min(t.geometry().top() for t in small), \
        "主画面应该在最上面"
    print(f"  主画面 top={main.geometry().top()} "
          f"小画面 top={sorted(t.geometry().top() for t in small)}")

    print("\n=== 5. 超出的格子要隐藏（布局严格按格子数走）===")
    window.wall.set_layout("portrait_main2")
    settle(app, 0.4)
    visible = [tile for tile in wall.tiles if tile.isVisible()]
    print(f"  切到 portrait_main2：可见 {len(visible)} 个（容量 "
          f"{wall._capacity()}）")
    assert len(visible) == wall._capacity(), \
        f"可见格子数应等于容量，实际 {len(visible)} vs {wall._capacity()}"
    window.wall.set_layout("portrait_main6")
    settle(app, 0.4)

    print("\n=== 6. window.close() 时不留悬挂 ===")
    window.close()
    settle(app, 0.4)


def part_portrait_danmaku(app) -> None:
    print("\n=== 7. 竖屏 + 弹幕：弹幕贴底、整宽；主画面仍是 16:9 ===")
    window = MainWindow(rooms(3), rooms(3), layout_id="portrait_dm2")
    window.setGeometry(-9000, -9000, *PORTRAIT)
    window.show()
    settle(app, 1.2)
    wall = window.wall
    danmaku = wall.danmaku
    main = wall.tiles[0]
    print(f"  弹幕 {danmaku.width()}x{danmaku.height()} @ "
          f"({danmaku.x()},{danmaku.y()})  可见={danmaku.isVisible()}")
    assert danmaku.isVisible(), "竖屏带弹幕的布局应该显示弹幕"
    assert danmaku.width() > wall.width() * 0.85, "弹幕应该占整宽"
    assert danmaku.geometry().bottom() >= wall.height() - wall.grid.contentsMargins().bottom() - 4, \
        "弹幕应该贴在底部"
    print(f"  主画面 {main.width()}x{main.height()} 比例 {ratio(main):.3f}")
    assert abs(ratio(main) - 16 / 9) < 0.06, f"主画面应保持 16:9，实际 {ratio(main):.3f}"
    assert main.geometry().bottom() < danmaku.geometry().top(), "主画面应该在弹幕上方"
    window.close()
    settle(app, 0.4)


def part_landscape_unchanged(app) -> None:
    print("\n=== 8. 横屏不受影响：等分布局照旧 ===")
    window = MainWindow(rooms(4), rooms(4), layout_id="2x2")
    window.setGeometry(-9000, -9000, *LANDSCAPE)
    window.show()
    settle(app, 1.2)
    wall = window.wall
    sizes = {(tile.width(), tile.height()) for tile in wall.tiles if tile.isVisible()}
    print(f"  layout={wall.layout_id} 方向={window.orientation} "
          f"格子={len(wall.tiles)} 可见={len(wall.visible_tiles())} "
          f"墙={wall.width()}x{wall.height()}")
    print(f"  2x2 在 {LANDSCAPE} 下的格子尺寸：{sizes}")
    assert len(sizes) == 1, f"横屏 2x2 应该四格等大，实际 {sizes}"
    tile_w, tile_h = sizes.pop()
    print(f"  单格比例 {tile_w / tile_h:.3f}")
    assert 1.2 < tile_w / tile_h < 2.4, "横屏 2x2 单格比例不该离谱"
    window.close()
    settle(app, 0.4)


def part_orientation_roundtrip(app) -> None:
    """竖屏 ↔ 横屏 来回拖：排布、布局、头排、控件条都要跟着回到正确状态。

    这几条都是实际遇到过的问题：
    - 竖屏存了 portrait 预设，拖回横屏被原样套用，画面错位
    - 拖回横屏不重排，格子留着竖屏时的几何
    - 顶部横栏头像排没同步关注列表 / 展开键跟着标题行一起藏掉
    """
    print("\n=== 9. 竖屏 ↔ 横屏 来回拖 ===")
    window = MainWindow(rooms(8), rooms(8))
    window.setGeometry(-9000, -9000, *LANDSCAPE)
    window.show()
    settle(app, 1.2)
    sidebar = window.sidebar

    def check(tag, want_portrait):
        wall = window.wall
        main = wall.tiles[0]
        strip = sidebar._head_strip
        controls = main.controls
        main.set_controls_visible(True)
        settle(app, 0.2)
        expected = max(10, main.video.width() + 1 - controls.width() - 10)
        print(f"  [{tag}] 方向={window.orientation} 布局={wall.layout_id} "
              f"侧栏side={sidebar.side} collapsed={sidebar.collapsed} "
              f"头排可见={strip.isVisible()} 头排主播数={len(strip._rooms)}")
        print(f"        主画面 {main.width()}x{main.height()} "
              f"比例 {main.width() / max(1, main.height()):.3f} "
              f"控件条x={controls.x()} 期望={expected}")
        assert window.orientation == ("portrait" if want_portrait else "landscape"), tag
        assert sidebar.side == ("top" if want_portrait else "left"), tag
        assert layouts.is_portrait_layout(wall.layout_id) == want_portrait, \
            f"{tag}: 布局 {wall.layout_id} 和方向不符（这就是拖回横屏后错位的原因）"
        assert controls.x() == expected, f"{tag}: 控件条没贴住画面右上角"
        # 头排只在竖屏收起时露出来（展开后由卡片条承担）
        expected_strip = want_portrait and sidebar.collapsed
        assert strip.isVisible() == expected_strip, f"{tag}: 头排该显示/隐藏不对"
        assert sidebar.toggle_button.isVisible(), f"{tag}: 展开键必须一直在"
        # 左栏必须整条撑满、列表是竖排：竖屏留下的横向/高度约束没清掉的话，
        # 左栏会只剩一条、卡片还是横着排的（用户看到的就是这个）
        if not want_portrait:
            assert sidebar.height() > wall.height() * 0.9, \
                f"{tag}: 侧栏应该撑满高度，实际 {sidebar.height()} / {wall.height()}"
            assert not sidebar.list_box.horizontal, f"{tag}: 左栏列表应该是竖向的"
            assert sidebar.scroll.maximumHeight() > 10_000, \
                f"{tag}: 竖屏的滚动区高度上限没被解掉"
        return main

    check("横屏启动", False)

    window.resize(1080, 1920)
    settle(app, 1.0)
    # 竖屏默认收起（横栏只占一条），这时头排必须露出来
    sidebar.set_collapsed(True, animate=False)
    settle(app, 0.4)
    main = check("拖成竖屏（收起）", True)
    strip = sidebar._head_strip
    print(f"        头排头像数={strip._layout.count()} "
          f"（关注 {len(sidebar.rooms())} 个）")
    assert len(strip._rooms) == len(sidebar.rooms()), \
        "头排必须同步关注列表，否则竖屏下看不到关注的主播"
    assert main.width() > main.video.height(), "竖屏主画面应该是横的（16:9）"

    window.resize(1600, 900)
    settle(app, 1.0)
    check("拖回横屏", False)

    window.close()
    settle(app, 0.4)


def part_strip_interaction(app) -> None:
    print("\n=== 10. 顶部横栏：头排内容 + 展开/收起 ===")
    window = MainWindow(rooms(6), rooms(6))
    window.setGeometry(-9000, -9000, *PORTRAIT)
    window.show()
    settle(app, 1.2)
    sidebar = window.sidebar
    strip = sidebar._head_strip
    sidebar.set_collapsed(True, animate=False)   # 竖屏默认收起，看头排
    settle(app, 0.4)
    rooms_now = sidebar.rooms()
    print(f"  收起：头排可见={strip.isVisible()} 账号头像="
          f"{strip.account_avatar() is not None} "
          f"同步关注={len(strip._rooms)}/{len(rooms_now)} "
          f"展开键可见={sidebar.toggle_button.isVisible()} "
          f"侧栏高={sidebar.height()}")
    assert strip.isVisible(), "竖屏收起时头排必须可见（它就是关注列表）"
    assert strip.account_avatar() is not None, "头排要有账号头像"
    assert len(strip._rooms) == len(rooms_now), "头排必须同步全部关注"
    assert sidebar.toggle_button.isVisible(), "没有展开键就没法展开了"
    # 一行头像 36 + 展开按钮 18 + 边距 16 + 间距 6 = 76px 是当前设计值；
    # 这里只保证它明显比展开态矮，别把横栏做成第二条侧栏
    assert sidebar.height() <= 90, f"收起时横栏应该很矮，实际 {sidebar.height()}"
    # 放不下时要有 +N 提示
    window.add_to_wall(dict(rooms_now[0])) if rooms_now else None
    settle(app, 0.3)

    print("\n=== 11. 点关注头像 = 选中该直播间 ===")
    picked: list = []
    sidebar.roomSelected.connect(lambda room: picked.append(room.get("room_id")))
    target = str(rooms_now[2].get("room_id")) if len(rooms_now) > 2 else ""
    sidebar._on_strip_room(target)
    settle(app, 0.2)
    print(f"  点第 3 个头像 -> roomSelected={picked}")
    assert picked == [target], f"头排点击应该选中对应直播间，实际 {picked}"

    print("\n=== 11b. 头排头像拖到画面墙 = 真的能换画布 ===")
    # 竖屏收起时没有列表可拖，唯一能拖的就是头排头像，所以这条必须通。
    # 无鼠标环境里不模拟 QDrag（会弹模态门），直接构造落点事件走同一条路径。
    from PySide6.QtGui import QDropEvent
    from ddm.widgets import ROOM_MIME

    def drop_room_on(tile, room_id: str) -> None:
        mime = QMimeData()
        mime.setData(ROOM_MIME, room_id.encode("utf-8"))
        event = QDropEvent(QPointF(20, 20), Qt.CopyAction, mime,
                           Qt.LeftButton, Qt.NoModifier)
        tile.dropEvent(event)

    wall = window.wall
    # 找一个空格子和一个已占用的格子
    empty = next((tile for tile in wall.visible_tiles() if not tile.room.get("room_id")), None)
    occupied = next((tile for tile in wall.visible_tiles()
                     if str(tile.room.get("room_id")) == target), None)
    print(f"  空格子={empty is not None} 目标格={occupied is not None} "
          f"（拖的是 {target}）")
    assert empty is not None, "竖屏布局应该留出空格子"
    assert occupied is not None, "示例房间应该在墙上的某一格"

    # 1) 拖到空格子上：填进去
    drop_room_on(empty, target)
    settle(app, 0.4)
    print(f"  拖到空格子后：该格房间={empty.room.get('room_id')}")
    assert str(empty.room.get("room_id")) == target, "拖到空格子上应该填进去"

    # 2) 再拖回原格子：两边交换，不会出现重复
    drop_room_on(occupied, target)
    settle(app, 0.4)
    landed = [str(tile.room.get("room_id") or "") for tile in wall.tiles]
    counted = [rid for rid in landed if rid == target]
    print(f"  拖回原格子后：墙上房间={landed} 其中 {target} 出现 {len(counted)} 次")
    assert len(counted) == 1, "同一个直播间不能同时占两格"

    print("\n=== 12. 竖屏展开：收起头排，换成横向卡片条 ===")
    sidebar.set_collapsed(False, animate=False)
    settle(app, 0.4)
    box = sidebar.list_box
    print(f"  展开：头排={strip.isVisible()} 搜索={sidebar.search.isVisible()} "
          f"布局按钮={sidebar.tool_row.isVisible()} "
          f"更多={sidebar.tool_row_more.isVisible()} "
          f"列表={sidebar.scroll.isVisible()} 高={sidebar.height()}")
    assert not strip.isVisible(), "展开后不保留头像排（用户要求）"
    assert sidebar.search.isVisible() and sidebar.tool_row.isVisible()
    assert sidebar.tool_row_more.isVisible(), "放不下的入口要在「⋯」里"
    assert box.horizontal, "展开后关注列表应该是横向卡片条"
    # 卡片横向排开：第一张在左边，第二张在它右边
    entries = sidebar.items()
    assert len(entries) >= 2, "至少要两张卡片才能验横向排列"
    first, second = entries[0], entries[1]
    print(f"  卡片位置：第1张 x={first.x()} 第2张 x={second.x()} "
          f"宽={first.width()} 高={first.height()} "
          f"滚动={sidebar.scroll.horizontalScrollBarPolicy().name}")
    assert second.x() > first.x(), "卡片要向右排"
    assert first.y() == second.y(), "卡片应该在同一行"
    assert sidebar.height() < 420, f"展开后横栏别太高，实际 {sidebar.height()}"
    # 竖向滚轮要能横向滚（竖屏没有横向滚轮的鼠标）
    assert sidebar.scroll.horizontal_only, "竖屏列表要靠竖向滚轮横向滚"
    sidebar.set_collapsed(True, animate=False)
    settle(app, 0.3)
    assert not sidebar.search.isVisible(), "收起后搜索框要收掉"
    assert strip.isVisible(), "收起后头排要回来"

    print("\n=== 13. 切布局不动窗口方向（摆放跟着窗口形状走）===")
    window.resize(1600, 900)
    settle(app, 0.8)
    window._on_layout_changed("portrait_main4")
    settle(app, 0.6)
    print(f"  横屏窗口里选竖屏预设：方向={window.orientation} side={sidebar.side} "
          f"布局={window.wall.layout_id}")
    assert window.orientation == "landscape", "套用预设不该把窗口方向改掉"
    assert sidebar.side == "left", "窗口还是横屏，侧栏就该在左边"
    # 竖屏预设套在横屏窗口上不好看，这是预期内的（提示用户去拖窗口），
    # 但主画面仍然要按整宽 16:9 —— 摆放规则跟着窗口形状走
    main = window.wall.tiles[0]
    print(f"  横屏里的竖屏预设：主画面 {main.width()}x{main.height()} "
          f"比例 {ratio(main):.3f}")
    assert abs(ratio(main) - 16 / 9) < 0.06, "竖屏摆放放在横屏窗口里主画面仍是 16:9"
    window._on_layout_changed("2x2")
    settle(app, 0.6)
    print(f"  改回横屏预设：方向={window.orientation} side={sidebar.side} "
          f"布局={window.wall.layout_id}")
    assert window.wall.layout_id == "2x2"
    window.close()
    settle(app, 0.4)


def part_layout_grow_keeps_slots_empty(app) -> None:
    """布局变大时，新格子必须是空的，不能自动补一个关注的主播。

    关注列表里留着第 4 个候选，墙上只放 3 个；把布局从 1+2 加到 1+3、1+4，
    多出来的位置必须显示「拖入直播间」。
    """
    print("\n=== 14. 布局变大：新格子保持空位 ===")
    names = ["恩骨", "纱依shayi", "三理mit3uri", "皮特174"]
    all_rooms = [{"room_id": str(2000 + index), "uname": name, "title": "标题",
                  "live": True, "muted": True, "quality": 250, "volume": 42}
                 for index, name in enumerate(names, start=1)]
    window = MainWindow([dict(room) for room in all_rooms],
                        [dict(room) for room in all_rooms[:3]], layout_id="main2")
    window.setGeometry(-9000, -9000, *LANDSCAPE)
    window.show()
    settle(app, 1.2)

    def occupants() -> list:
        return [str(tile.room.get("uname") or "") for tile in window.wall.tiles
                if tile.isVisible()]

    def empties() -> int:
        return sum(1 for tile in window.wall.tiles
                   if tile.isVisible() and not tile.room.get("room_id"))

    print(f"  main2：{occupants()}")
    assert occupants() == names[:3], f"初始应该是前三个，实际 {occupants()}"
    for layout_id, expected_count in (("main3", 4), ("main4", 5)):
        window._on_layout_changed(layout_id)
        settle(app, 0.5)
        print(f"  {layout_id}：{occupants()}  空位={empties()}")
        assert len(window.wall.visible_tiles()) == expected_count, \
            f"{layout_id} 应该有 {expected_count} 个格子"
        assert empties() == expected_count - 3, \
            f"{layout_id} 多出来的位置必须是空位，不能自动补主播：{occupants()}"
        assert names[3] not in occupants(), "第 4 个候选不该被自动填上墙"
    window.close()
    settle(app, 0.4)


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

    part_layouts()
    part_portrait(app)
    part_portrait_danmaku(app)
    part_landscape_unchanged(app)
    part_orientation_roundtrip(app)
    part_strip_interaction(app)
    part_layout_grow_keeps_slots_empty(app)
    print("\n全部通过")

if __name__ == "__main__":
    main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
