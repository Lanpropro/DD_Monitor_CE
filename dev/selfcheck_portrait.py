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

from PySide6.QtCore import QMimeData, QPoint, QPointF, Qt, QThread, Signal
from PySide6.QtGui import QColor, QPixmap, QWheelEvent
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


def accent_pixels(image, rect: tuple) -> int:
    """数一块区域里的强调色像素——用来确认「画出来了」，而不是只看了标志位。"""
    accent = QColor(theme.ACCENT)
    hits = 0
    for y in range(rect[1], min(rect[3], image.height())):
        for x in range(rect[0], min(rect[2], image.width())):
            colour = image.pixelColor(x, y)
            if abs(colour.red() - accent.red()) < 40 \
                    and abs(colour.green() - accent.green()) < 40 \
                    and abs(colour.blue() - accent.blue()) < 40:
                hits += 1
    return hits


def ink_box(image, pad: int = 3) -> tuple:
    """图标内容的包围盒（相对最常见的底色）——检查图标正不正、有没有多画东西。"""
    counts: dict = {}
    for y in range(image.height()):
        for x in range(image.width()):
            colour = image.pixelColor(x, y).getRgb()
            counts[colour] = counts.get(colour, 0) + 1
    background = max(counts, key=counts.get)
    min_x, min_y, max_x, max_y = image.width(), image.height(), -1, -1
    for y in range(pad, image.height() - pad):
        for x in range(pad, image.width() - pad):
            colour = image.pixelColor(x, y).getRgb()
            if sum(abs(a - b) for a, b in zip(colour[:3], background[:3])) > 90:
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)
    return min_x, min_y, max_x, max_y


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


def part_narrow_tile_badge(app) -> None:
    """格子被挤窄时，LIVE 浮标要跟着文字变长，不能把人数藏掉。

    用户实测报的：竖屏下左上角 LIVE 的人数被遮挡、浮标没有自适应变长。
    原来一挤不下就 `set_compact(True)` 把人数收起来；现在改成让控制条折到
    第二行，人数留着。
    """
    print("\n=== 6b. 窄格子里人数不被藏掉、浮标跟着变长 ===")
    window = MainWindow(rooms(7), rooms(7), layout_id="portrait_main6")
    window.setGeometry(-9000, -9000, 700, 1400)      # 小格子会被挤到 ~330 宽
    window.show()
    settle(app, 1.2)
    checked = 0
    for tile in window.wall.visible_tiles():
        badge = tile.stream_badge
        if not badge.isVisible():
            continue
        print(f"  格子 {tile.width()}x{tile.height()}：浮标宽={badge.width()} "
              f"人数={badge.viewers!r} 收起人数={getattr(badge, '_compact', False)} "
              f"需要={badge.full_width()} 控制条 y={tile.controls.y()}")
        assert not getattr(badge, "_compact", False), \
            f"格子 {tile.width()} 宽还收起了人数（用户报的就是这个）"
        assert badge.width() == badge.full_width(), \
            "浮标宽度要按人数文字算出来，不然人数会被截断"
        checked += 1
    assert checked >= 2, f"这一段要能测到格子，实际 {checked} 个"
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
            # 竖屏那套滚动轴状态（横排 + 竖条常关）也必须还原，否则回横屏后
            # 竖向滚动条一直藏着、滚轮还被 CarouselScroll 当成横滚吞掉 ——
            # 用户报的「从竖屏回横屏后滚动条失效」就是这两条没回滚
            assert not sidebar.scroll.horizontal_only, \
                f"{tag}: 竖屏的横滚模式没还原，滚轮会被当成横滚"
            assert sidebar.scroll.verticalScrollBarPolicy() == Qt.ScrollBarAsNeeded, \
                f"{tag}: 左栏竖向滚动条应该按需出现，实际 " \
                f"{sidebar.scroll.verticalScrollBarPolicy().name}"
            assert sidebar.scroll.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff, \
                f"{tag}: 左栏不该留横滚条"
            # 竖屏借走的三个按钮要各回各家、文字样式也要还原（别把横屏搞坏）
            assert sidebar.batch_button.text() == "多选", f"{tag}: 多选要还原成文字按钮"
            assert sidebar.sort_button.text() == "排序", f"{tag}: 排序要还原成文字按钮"
            assert sidebar.batch_button.parentWidget() is sidebar._header_row, \
                f"{tag}: 多选要回标题行"
            assert sidebar.sort_button.parentWidget() is sidebar.status_row, \
                f"{tag}: 排序要回状态行"
            assert sidebar.refresh_button.parentWidget() is sidebar.status_row, \
                f"{tag}: 刷新要回状态行"
            assert sidebar.settings_button.isVisible(), f"{tag}: 设置按钮要回来"
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

    # 把标志位改回去还不够：真的滚一下，确认左栏滚轮还能用
    # （用户报的失效现象就是这一步没有任何反应）
    from PySide6.QtGui import QWheelEvent

    viewport = sidebar.scroll.viewport()
    bar = sidebar.scroll.verticalScrollBar()
    center = viewport.rect().center()
    before = bar.value()
    QApplication.sendEvent(viewport, QWheelEvent(
        QPointF(center), QPointF(viewport.mapToGlobal(center)),
        QPoint(0, -120), QPoint(0, -120), Qt.NoButton, Qt.NoModifier,
        Qt.NoScrollPhase, False))
    settle(app, 0.3)
    print(f"  回横屏滚轮：{before} -> {bar.value()}（范围 {bar.maximum()}，"
          f"关注 {len(sidebar.rooms())} 个）")
    assert bar.maximum() > 0, "这个用例要能触发滚动（关注列表要长过视口）"
    assert bar.value() > before, "回横屏后左栏滚轮必须还能滚"

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
    sidebar.set_account("测试账号")              # 账号头像只在登录后才出现
    sidebar.set_collapsed(True, animate=False)   # 竖屏默认收起，看头排
    settle(app, 0.4)
    rooms_now = sidebar.rooms()
    print(f"  收起：头排可见={strip.isVisible()} 头排头像={len(strip._avatars)}/"
          f"{len(rooms_now)} 账号头像可见={sidebar.account_row.isVisible()} "
          f"展开键可见={sidebar.toggle_button.isVisible()} "
          f"侧栏高={sidebar.height()}")
    assert strip.isVisible(), "竖屏收起时头排必须可见（它就是关注列表）"
    assert len(strip._rooms) == len(rooms_now), "头排必须同步全部关注"
    # 头像不设上限：6 个关注就要有 6 个头像（原来硬编码最多 9 个、超出显示 +N）
    assert len(strip._avatars) == len(rooms_now), \
        f"头排要显示全部关注，实际 {len(strip._avatars)}/{len(rooms_now)}"
    assert sidebar._head_scroll.widget() is strip, "头像排要挂在滚动区里（放不下能横滚）"
    assert sidebar.toggle_button.isVisible(), "没有展开键就没法展开了"
    # 账号头像不在头排里（用户在报告里明确说「用户头像错误的出现在了左边」），
    # 它和展开键一起在横栏最右侧那一块
    assert sidebar.account_row.isVisible(), "收起时账号头像要留在横栏右侧"
    assert sidebar.account_row.avatar.isVisible(), "账号头像要露出来"
    assert strip.isAncestorOf(sidebar.account_row) is False, "账号头像不该混进头排"
    # 收起时横栏就是**一行**：头像排（36）+ 账号头像 + 展开键挤在同一行里，
    # 边距上下各 8，一共 52px。
    assert sidebar._head_scroll.parentWidget() is sidebar.toggle_button.parentWidget(), \
        "收起时头像排和展开键要在同一行（别再单独占一行）"
    assert sidebar.account_row.parentWidget() is sidebar.toggle_button.parentWidget(), \
        "账号头像也要在这同一行里"
    assert sidebar.height() <= 70, f"收起时横栏应该很矮，实际 {sidebar.height()}"

    print("\n=== 10b. 头排：真实头像 + 置顶角标 + 关注多了横向滚 ===")
    # 置顶角标：原来是方角按钮，会戳到圆头像外面；现在应该是一段贴着圆周的弧
    from ddm.widgets import PinnedArc

    first_id = str(rooms_now[0].get("room_id"))
    sidebar.apply_pins([first_id])               # 这一下会把头排整排重建
    settle(app, 0.3)
    shown = strip._avatars.get(first_id)         # 重建之后要重新拿控件
    mark = next((child for child in shown.children() if isinstance(child, PinnedArc)), None)
    corner = accent_pixels(shown.grab().toImage(), (0, 0, 20, 20))
    print(f"  置顶角标={type(mark).__name__ if mark else None} "
          f"左上 20x20 里的强调色像素={corner}")
    assert mark is not None, "置顶的主播头像上要有角标"
    assert mark.geometry().size() == shown.size(), "弧要铺满头像，才能贴着圆周画"
    assert corner > 20, "角标要真的画出来（贴着头像左上边缘的一段弧）"
    sidebar.apply_pins([])
    settle(app, 0.2)

    # 头像图：列表里下载好之后，头排那一张要跟着换（增量更新，不重建整排）
    face = QPixmap(64, 64)
    face.fill(QColor("#fb7299"))
    sidebar.set_room_face(first_id, face)
    settle(app, 0.3)
    shown = strip._avatars.get(first_id)
    pixmap = shown.pixmap() if shown is not None else None
    print(f"  换头像图：{first_id} -> {pixmap is not None and not pixmap.isNull()}")
    assert shown is not None and pixmap is not None and not pixmap.isNull(), \
        "横栏里的头像要能用列表里已下载的那张图"
    # 关注多到一行放不下时：头排横向可滚，滚轮也能滚（没有滚动条占位）
    for index in range(30):
        sidebar.add_room({"room_id": f"88{index:02d}", "uname": f"补{index}",
                          "title": "标题", "live": False, "muted": True,
                          "volume": 42, "quality": 250})
    settle(app, 0.5)
    viewport = sidebar._head_scroll.viewport()
    bar = sidebar._head_scroll.horizontalScrollBar()
    center = viewport.rect().center()
    before = bar.value()
    QApplication.sendEvent(viewport, QWheelEvent(
        QPointF(center), QPointF(viewport.mapToGlobal(center)),
        QPoint(0, -240), QPoint(0, -240), Qt.NoButton, Qt.NoModifier,
        Qt.NoScrollPhase, False))
    settle(app, 0.3)
    print(f"  关注 {len(sidebar.rooms())} 个：头像 {len(strip._avatars)} 个，"
          f"可滚范围={bar.maximum()} 滚轮 {before} -> {bar.value()}，"
          f"滚动条可见={bar.isVisible()}")
    assert len(strip._avatars) == len(sidebar.rooms()), "补进来的关注也要有头像"
    assert bar.maximum() > 0, "一行放不下时要能横向滚"
    assert bar.value() > before, "滚轮要能横向滚头排"
    assert not bar.isVisible(), "收起态不显示滚动条（不占头像那一行的高度）"
    assert sidebar.height() <= 70, f"加关注不能把横栏撑高，实际 {sidebar.height()}"
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
    sidebar.set_account("测试账号")          # 横栏右侧那一块要有账号头像
    sidebar.set_collapsed(False, animate=False)
    settle(app, 0.4)
    box = sidebar.list_box
    print(f"  展开：头排={strip.isVisible()} 搜索={sidebar.search.isVisible()} "
          f"布局按钮={sidebar.tool_row.isVisible()} "
          f"列表={sidebar.scroll.isVisible()} 高={sidebar.height()}")
    assert not strip.isVisible(), "展开后不保留头像排（用户要求）"
    assert sidebar.search.isVisible() and sidebar.tool_row.isVisible()
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
    # 横栏高度：原来「多选 / 布局预设 / ⋯ / 导入关注 + 添加直播间」好几行堆在
    # 下面，横栏 362px；现在并成一行，196px（多选搬到搜索那一行、标题行整行收掉，
    # 加上横向滚动条自己占的 8px —— 不留这 8px 卡片底边会被滚动条切掉）
    assert sidebar.height() < 300, f"展开后横栏要比 362px 那版矮，实际 {sidebar.height()}"
    assert sidebar.height() <= 210, f"多选搬下来之后横栏应该只有一行，实际 {sidebar.height()}"
    assert sidebar.scroll.viewport().height() >= first.height(), \
        f"卡片不能被横向滚动条切掉：视口 {sidebar.scroll.viewport().height()} " \
        f"< 卡片 {first.height()}"
    # 竖向滚轮要能横向滚（竖屏没有横向滚轮的鼠标）
    assert sidebar.scroll.horizontal_only, "竖屏列表要靠竖向滚轮横向滚"
    # 横向滚动条要和横屏那条竖向滚动条同一套风格：主题里两轴都要有规则、
    # 滑块同色、两端不带箭头的原生按钮；渲染出来的粗细也得是主题写的 8px
    # （掉回系统原生是 12px，还带左右箭头）
    qss = theme.qss()
    hbar = sidebar.scroll.horizontalScrollBar()
    print(f"  横向滚动条 {hbar.width()}x{hbar.height()}（原生 12px、带箭头）；"
          f"主题里 handle 同色出现 {qss.count('rgba(131, 131, 145, 0.35)')} 次")
    for rule in ("QScrollBar:horizontal", "QScrollBar::handle:horizontal",
                 "QScrollBar::add-line:horizontal", "QScrollBar::sub-line:horizontal",
                 "QScrollBar::add-page:horizontal", "QScrollBar::sub-page:horizontal"):
        assert rule in qss, f"主题里缺 {rule}，横向条会掉回系统原生样式"
    assert qss.count("rgba(131, 131, 145, 0.35)") == 2, \
        "横向和竖向滚动条的滑块要用同一种颜色（各一处）"
    assert hbar.height() <= 10, f"横向滚动条没走主题样式，实际 {hbar.height()}px"

    print("\n=== 12b. 横栏两行：图标在第一行，卡片右边单独一块放账号/布局预设/设置 ===")
    account = sidebar.account_row
    icons = [sidebar.batch_button, sidebar.sort_button, sidebar.refresh_button]
    block = sidebar._bar_right
    stacked = [account, sidebar.tool_row]
    print(f"  第一行：图标 x={[w.x() for w in icons]} 搜索框右边缘="
          f"{sidebar.search.x() + sidebar.search.width()} 展开键 x="
          f"{sidebar.toggle_button.x()}")
    print(f"  第二行：卡片条 {sidebar.scroll.width()}x{sidebar.scroll.height()} "
          f"右侧一块 x={block.x()} 宽={block.width()}；账号条 "
          f"{account.width()}x{account.height()} @y={account.y()} "
          f"布局预设/设置 x={sidebar.layout_button.x()} y="
          f"{sidebar.layout_button.y()}/{sidebar.settings_button.y()}")
    # 用户要求：多选这些图标留在搜索框旁边
    assert all(button.isVisible() for button in icons), "三个小图标都要露出来"
    assert min(button.x() for button in icons) > sidebar.search.x(), "图标在搜索框右边"
    assert all(button.parentWidget() is sidebar._bar_row for button in icons + [
        sidebar.toggle_button]), "图标和展开键在第一行"
    # 用户要求：缩短搜索框、左侧给 logo 留位置（标题行搬进横栏第一行当 logo）
    header = sidebar._header_row
    print(f"  第一行 logo：x={header.x()} 宽={header.width()} "
          f"标题可见={sidebar.title_label.isVisible()} "
          f"副标题可见={sidebar.subtitle_label.isVisible()} "
          f"搜索框 x={sidebar.search.x()} 宽={sidebar.search.width()}")
    assert header.isVisible() and header.parentWidget() is sidebar._bar_row, \
        "logo（标题行）要摆在横栏第一行左边"
    assert sidebar.title_label.isVisible() and not sidebar.subtitle_label.isVisible(), \
        "竖屏 logo 只露「DD 监控室」，副标题藏起来"
    assert header.x() < sidebar.search.x(), "logo 要在搜索框左边"
    assert header.x() + header.width() <= sidebar.search.x() + 2, "logo 不能压到搜索框"
    assert sidebar.search.width() < 900, \
        f"搜索框要让出 logo 那一段宽度，实际 {sidebar.search.width()}"
    print(f"  图标文字：多选={sidebar.batch_button.text()!r} "
          f"排序={sidebar.sort_button.text()!r} 尺寸="
          f"{sidebar.batch_button.width()}x{sidebar.batch_button.height()}")
    assert sidebar.batch_button.text() != "多选" and sidebar.sort_button.text() != "排序", \
        "横栏里这三个是图标按钮，不是文字按钮"
    # 三个图标要正（自绘的那两个 + 手绘圆环的刷新）：墨迹包围盒的中心得和按钮中心重合。
    # 这条能抓到两类问题：字形/图案本身偏，以及「排序」带菜单时 Qt 多画的那个下拉小三角
    for name, button in (("多选", sidebar.batch_button), ("排序", sidebar.sort_button),
                         ("刷新", sidebar.refresh_button)):
        image = button.grab().toImage()
        scale = image.width() / max(1, button.width())
        box = ink_box(image)
        center_x = (box[0] + box[2]) / 2 / scale
        center_y = (box[1] + box[3]) / 2 / scale
        print(f"  {name}图标：墨迹框={box} 中心=({center_x:.1f},{center_y:.1f}) "
              f"按钮中心=({button.width() / 2:.1f},{button.height() / 2:.1f})")
        assert abs(center_x - button.width() / 2) <= 2, f"{name}图标横向偏了"
        assert abs(center_y - button.height() / 2) <= 2, f"{name}图标纵向偏了"
    assert "BarIcon::menu-indicator" in theme.qss(), \
        "「排序」带菜单，得靠 #BarIcon::menu-indicator 去掉那个下拉小三角"
    # 用户要求：最后一张卡片右边单独开一块，账号 / 布局预设 / 设置 竖排；
    # 这一块只占卡片条那一行，三个按钮 + 两条分割线正好把那一行分完
    assert block.isVisible() and block.parentWidget() is sidebar._bar_row2, \
        "右侧那一块要和卡片条在同一行"
    assert block.x() >= sidebar.scroll.x() + sidebar.scroll.width(), \
        "这一块要在卡片条的右边"
    assert account.parentWidget() is block and sidebar.tool_row.parentWidget() is block, \
        "账号和工具行都要放进这一块"
    assert account.y() + account.height() <= sidebar.tool_row.y(), \
        f"账号要在布局预设上面（竖排）：账号 y={account.y()} 工具行 y={sidebar.tool_row.y()}"
    assert sidebar.settings_button.y() > sidebar.layout_button.y(), \
        "布局预设和设置也要竖排（设置在下）"
    assert abs(sidebar.settings_button.x() - sidebar.layout_button.x()) <= 2, \
        "竖排时两个按钮左边对齐"
    heights = [account.height(), sidebar.layout_button.height(),
               sidebar.settings_button.height()]
    dividers = [sidebar._bar_divider_label, sidebar._bar_divider_tool]
    # 两条「空白」= 账号下沿到工具行上沿、布局预设下沿到设置上沿（里面各含 1px 线）
    gap_label = sidebar.tool_row.y() - (account.y() + account.height())
    gap_tool = sidebar.settings_button.y() - (sidebar.layout_button.y()
                                              + sidebar.layout_button.height())
    print(f"  这一块：高={block.height()}（卡片条 {sidebar.scroll.height()}）"
          f" 三段高度={heights}（自身 {[account.sizeHint().height(), sidebar.layout_button.sizeHint().height(), sidebar.settings_button.sizeHint().height()]}）"
          f" 两条空白={gap_label}/{gap_tool} 分割线={[d.height() for d in dividers]}")
    assert abs(block.height() - sidebar.scroll.height()) <= 2, \
        f"这一块要和卡片条同高（不占别处）：块 {block.height()} vs 卡片条 {sidebar.scroll.height()}"
    assert block.y() >= sidebar.scroll.y() and \
        block.y() + block.height() <= sidebar.scroll.y() + sidebar.scroll.height() + 2, \
        "这一块不能超到卡片条那一行外面（比如爬上去挤搜索框）"
    # 用户要求：单个按钮高度用横屏那套（不去拉伸），最上面/最下面的按钮
    # 正好贴着卡片条那一行的上下沿，多出来的高度做成两条一样大的空白
    assert account.height() == theme.CONTROL_HEIGHT, \
        f"账号高度该是横屏那套，实际 {account.height()} / 期望 {theme.CONTROL_HEIGHT}"
    for name, button in (("布局预设", sidebar.layout_button), ("设置", sidebar.settings_button)):
        assert button.height() == button.sizeHint().height(), \
            f"{name}高度该是横屏那套，实际 {button.height()} / 自身 {button.sizeHint().height()}"
    assert account.y() == 0, f"最上面的按钮要贴着上沿，实际 y={account.y()}"
    bottom = sidebar.tool_row.y() + sidebar.settings_button.y() \
        + sidebar.settings_button.height()
    assert bottom == block.height(), \
        f"最下面的按钮要贴着下沿：底部 {bottom} vs 这一块 {block.height()}"
    assert gap_label > 2 and gap_tool > 2, f"两条空白要真的留出来：{gap_label}/{gap_tool}"
    assert abs(gap_label - gap_tool) <= 1, \
        f"两条空白要一样大（均匀），实际 {gap_label}/{gap_tool}"
    for name, divider, above, below in (
            ("账号下", dividers[0], account.y() + account.height(), sidebar.tool_row.y()),
            ("设置上", dividers[1], sidebar.layout_button.y() + sidebar.layout_button.height(),
             sidebar.settings_button.y())):
        upper = divider.y() - above
        lower = below - (divider.y() + divider.height())
        print(f"    {name}的分割线：上面留 {upper}px、下面留 {lower}px")
        assert divider.isVisible() and divider.height() == 1, "分割线在、且只有 1px"
        assert abs(upper - lower) <= 1, f"{name}的分割线要在空白正中间"
    # 这一块的按钮宽度不被动过（用户要求）
    print(f"  宽度：账号={account.width()} 布局预设={sidebar.layout_button.width()}"
          f"（自身 {sidebar.layout_button.sizeHint().width()}）"
          f" 设置={sidebar.settings_button.width()}"
          f"（自身 {sidebar.settings_button.sizeHint().width()}）"
          f" 分割线={[d.width() for d in dividers]}")
    assert sidebar.layout_button.width() == sidebar.layout_button.sizeHint().width(), \
        "布局预设的宽度不该被改（用户要求别调单个按钮的宽度）"
    assert sidebar.settings_button.width() == sidebar.settings_button.sizeHint().width(), \
        "设置的宽度不该被改"
    assert all(divider.width() >= account.width() for divider in dividers), \
        "两条分割线要横跨这一块"
    # 卡片上的置顶角标（用户要求：小三角改圆角，贴合圆角边框）
    pinned_item = sidebar.items()[0]
    sidebar.apply_pins([str(pinned_item.room.get("room_id"))])
    settle(app, 0.3)
    card_corner = accent_pixels(pinned_item.grab().toImage(), (0, 0, 20, 20))
    print(f"  卡片置顶角标：pinned={pinned_item.is_pinned} "
          f"左上 20x20 里的强调色像素={card_corner}")
    assert pinned_item.is_pinned
    assert card_corner > 20, "卡片的置顶角标要真的画出来（贴着圆角的那段弧）"
    sidebar.apply_pins([])
    settle(app, 0.2)
    # 「⋯」整个去掉了：导入关注 / 添加直播间 收进账号菜单
    labels = [action.text() for action in sidebar.account_menu().actions() if action.text()]
    print(f"  账号菜单里装着：{labels}")
    assert not hasattr(sidebar, "tool_row_more"), "「更多」按钮已经去掉"
    assert not sidebar.normal_bar.isVisible(), "导入/添加收进账号菜单，不该再占一行"
    assert "导入关注…" in labels and "+ 添加直播间…" in labels, labels
    assert "设置…" not in labels, "设置已经摆在右侧那一块上，展开态菜单里不用再来一份"

    sidebar.set_collapsed(True, animate=False)
    settle(app, 0.3)
    assert not sidebar.search.isVisible(), "收起后搜索框要收掉"
    assert strip.isVisible(), "收起后头排要回来"
    # 收起时账号头像回到第一行最右端，并且缩成和头排头像一样大的小圆点
    # （用户报的「不需要那么大的按钮 / 保持和横屏一样的小圆点」）
    assert account.isVisible() and account.avatar.isVisible(), \
        "收起后账号头像仍要在横栏右侧（账号菜单只有这一个入口）"
    assert account.parentWidget() is sidebar._bar_row, "收起时账号要回到头像排那一行"
    assert account.avatar.width() == strip.AVATAR, \
        f"收起时账号头像要和头排头像同尺寸，实际 {account.avatar.width()}"
    print(f"  收起态账号按钮 {account.width()}x{account.height()}（头排头像 "
          f"{strip.AVATAR}x{strip.AVATAR}）")
    assert abs(account.width() - account.height()) <= 6, \
        f"收起时账号按钮应该是个小圆点，不是长胶囊：{account.width()}x{account.height()}"
    assert not sidebar._bar_right.isVisible(), "收起时右侧那一块整块收掉"

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
    part_narrow_tile_badge(app)
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
