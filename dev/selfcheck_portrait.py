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

from PySide6.QtCore import QThread, Signal
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
    # 等分布局本来就是按行列切，横屏下比例接近 16:9
    print(f"  单格比例 {tile_w / tile_h:.3f}")
    assert 1.2 < tile_w / tile_h < 2.4, "横屏 2x2 单格比例不该离谱"

    window.wall.set_layout("portrait_main4")
    settle(app, 0.5)
    print("  横屏也可以手动选竖屏布局（不拦），主画面比例 "
          f"{ratio(wall.tiles[0]):.3f}")
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
    print("\n全部通过")


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
