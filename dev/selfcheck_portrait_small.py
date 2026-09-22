"""回归自检：竖屏布局，小画面的排列要和缩略图一致。

用户报的：竖屏 1+2 布局，缩略图里那 2 个小画面是**左右**排的，真机却是**上下**。

根因：缩略图按 `layouts.portrait_main_cells()` 给的 cells 画（每行 2 个），而实际
摆放走 `WallGrid._relayout_portrait()` → `_place_auto()` → `best_columns()`，让它
自己挑「画面尽量大」的列数。竖屏那块又高又窄的区域在它眼里 **1 列画面更大**，
于是摆成了上下，和缩略图对不上。

现在「一行摆几个」只在 `layouts.PORTRAIT_SMALL_COLUMNS` 定义一处，缩略图和实际
摆放共用它。这里钉住的不是「必须是 2 列」，而是**两边算出来的是同一个数** ——
以后调整这个值也不会又对不上。
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

ROOMS = [{"room_id": f"97{index:02d}", "uname": f"主播{index}", "title": f"标题{index}",
          "live": True, "muted": True, "volume": 40, "quality": 250}
         for index in range(1, 8)]


def settle(app, seconds: float = 0.45) -> None:
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


def thumb_per_line(small: int) -> int:
    """缩略图那边：除主画面外，同一行画几个小格子。"""
    _rows, _columns, cells = layouts.portrait_main_cells(small)
    small_cells = cells[1:]
    first_line = small_cells[0][0]
    return sum(1 for cell in small_cells if cell[0] == first_line)


def actual_per_line(tiles: list) -> tuple[int, list]:
    """实际这边：小画面里最上面那一行有几个，返回 (个数, 几何)。"""
    if not tiles:
        return 0, []
    top = min(tile.y() for tile in tiles)
    line = [tile for tile in tiles if tile.y() == top]
    return len(line), sorted((tile.x(), tile.y(), tile.width(), tile.height())
                             for tile in tiles)


def main() -> None:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.qss())
    window = MainWindow([dict(room) for room in ROOMS],
                        [dict(room) for room in ROOMS],
                        layout_id="portrait_main2", state={})
    window.setGeometry(-9000, -9000, 520, 1000)
    window.show()
    settle(app, 0.6)
    try:
        assert window.orientation == "portrait", window.orientation
        tiles = [tile for tile in window.wall.tiles if tile.isVisible()]
        print(f"布局={window.wall.layout_id}　可见格子={len(tiles)}")
        main_tile, small = tiles[0], tiles[1:]
        print(f"  主画面 {main_tile.x()},{main_tile.y()} "
              f"{main_tile.width()}x{main_tile.height()}")
        for index, tile in enumerate(small):
            print(f"  小画面{index} {tile.x()},{tile.y()} "
                  f"{tile.width()}x{tile.height()}")

        expected = thumb_per_line(2)
        got, geometry = actual_per_line(small)
        print(f"\n  缩略图一行画 {expected} 个　实际一行摆 {got} 个")
        assert got == expected, \
            f"实际一行 {got} 个、缩略图是 {expected} 个：又对不上了"
        if expected > 1:
            assert geometry[0][1] == geometry[1][1] and geometry[0][0] != geometry[1][0], \
                f"一行多个时该是左右排（y 相同、x 不同），实际 {geometry}"
        # 小画面要整个落在主画面下方，不能盖住它
        assert all(tile.y() >= main_tile.y() + main_tile.height() for tile in small), \
            "小画面跑到主画面上去了"

        print("\n=== 换个更宽的竖屏窗口，结论要一致 ===")
        window.resize(620, 1180)
        settle(app, 0.5)
        tiles = [tile for tile in window.wall.tiles if tile.isVisible()]
        small = tiles[1:]
        got2, geometry2 = actual_per_line(small)
        print(f"  窗口 620x1180：缩略图 {expected} 个　实际 {got2} 个　{geometry2}")
        assert got2 == expected, f"换宽度后又对不上了：{got2} vs {expected}"
    finally:
        window.close()
        settle(app, 0.25)
    print("\n全部通过")


if __name__ == "__main__":
    main()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
