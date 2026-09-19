"""画面墙布局方案。

每个方案用 (rows, cols, cells) 描述，cells 是 [(row, col, rowspan, colspan), ...]，
cells 的数量就是这个方案一屏能放几路；多出来的窗口按同样的列数继续往下排。

竖屏方案多一个 ``"portrait": "stack"`` 标记：那些方案不按行列等分摆，而是
「主画面按 16:9 固定 + 小画面自动网格填满剩余」，具体摆放见 WallGrid。
"""
import math

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap

from . import theme


def even_cells(rows: int, cols: int) -> list[tuple[int, int, int, int]]:
    return [(row, col, 1, 1) for row in range(rows) for col in range(cols)]


def main_plus_side(count: int) -> tuple[int, int, list]:
    """左侧主画面 + 右侧一列小窗。"""
    rows = max(1, count)
    cells = [(0, 0, rows, 2)] + [(row, 2, 1, 1) for row in range(rows)]
    return rows, 3, cells


def danmaku_side(count: int) -> tuple[int, int, list]:
    """左侧主画面 + 右侧一列小窗（count 个，含弹幕那一格）。"""
    rows = max(2, count)
    cells = [(0, 0, rows, 2)] + [(row, 2, 1, 1) for row in range(rows)]
    return rows, 3, cells


LAYOUTS: list[dict] = [
    # 用户 2026-09-18 要求**去掉「自动」**：切回自动时它按上一个布局的行列走
    # （2 行 3 列 → 自动 → 3 行 2 列），跟当前有几路在播没关系，容易误解。
    # 配置里存着 "auto" 的会被折算成 DEFAULT_LAYOUT（见 app._saved_layout）。
    # ---- 平分布局：每格一样大 ----
    {"id": "1x1", "name": "单画面", "spec": (1, 1, even_cells(1, 1))},
    {"id": "2x1", "name": "上下两分", "spec": (2, 1, even_cells(2, 1))},
    {"id": "1x2", "name": "左右两分", "spec": (1, 2, even_cells(1, 2))},
    {"id": "2x2", "name": "四分", "spec": (2, 2, even_cells(2, 2))},
    {"id": "3x2", "name": "六分", "spec": (2, 3, even_cells(2, 3))},
    {"id": "3x3", "name": "九分", "spec": (3, 3, even_cells(3, 3))},
    # ---- 大带小：一（两）路主画面 + 若干小画面（菜单里在这一段前换行加小标题）----
    {"id": "main2", "name": "主画面 + 2 小", "spec": main_plus_side(2),
     "section": "大带小"},
    {"id": "left2_right1", "name": "2 小 + 主画面（镜像）",
     "hint": "主画面在右、两路小画面在左：和「主画面 + 2 小」左右相反",
     "spec": (2, 2, [(0, 0, 1, 1), (1, 0, 1, 1), (0, 1, 2, 1)])},
    {"id": "main3", "name": "主画面 + 3 小", "spec": main_plus_side(3)},
    {"id": "main4", "name": "主画面 + 4 小", "spec": main_plus_side(4)},
    {"id": "top1_2", "name": "上主画面 + 下 2 小",
     "spec": (2, 2, [(0, 0, 1, 2), (1, 0, 1, 1), (1, 1, 1, 1)])},
    {"id": "corner", "name": "主画面 + 5 小环绕",
     "spec": (3, 3, [(0, 0, 2, 2), (0, 2, 1, 1), (1, 2, 1, 1), (2, 0, 1, 1), (2, 1, 1, 1), (2, 2, 1, 1)])},
    {"id": "two_rows", "name": "双主画面 + 4 小",
     "spec": (4, 3, [(0, 0, 2, 2), (2, 0, 2, 2)] + [(row, 2, 1, 1) for row in range(4)])},
]

DANMAKU_LAYOUTS: list[dict] = [
    {"id": "dm_pair", "name": "主画面 + 弹幕",
     "hint": "左边一路直播，右边整格给弹幕",
     "spec": (1, 2, even_cells(1, 2)), "danmaku": 1},
    {"id": "dm_top", "name": "上 1 大 + 小 + 弹幕",
     "spec": (2, 2, [(0, 0, 1, 2), (1, 0, 1, 1), (1, 1, 1, 1)]), "danmaku": 2},
    {"id": "dm_main2", "name": "主画面 + 1 小 + 弹幕",
     "spec": danmaku_side(2), "danmaku": 2},
    {"id": "dm_main3", "name": "主画面 + 2 小 + 弹幕",
     "spec": danmaku_side(3), "danmaku": 3},
    {"id": "dm_main4", "name": "主画面 + 3 小 + 弹幕",
     "spec": danmaku_side(4), "danmaku": 4},
    {"id": "dm_left", "name": "弹幕在左 + 主画面 + 2 小",
     "spec": (2, 3, [(0, 0, 2, 1), (0, 1, 2, 1), (0, 2, 1, 1), (1, 2, 1, 1)]),
     "danmaku": 0},
]


# ---------------------------------------------------------------- 竖屏布局
#
# 竖屏不能沿用上面「行列等分」那套：主画面要 16:9，小画面也要接近 16:9，
# 而等分网格只能满足其中一个（主画面占整宽 1 行时，小格子会被拉成 0.8 左右的
# 竖条）。所以竖屏预设带 "portrait": "stack"，由 WallGrid 单独摆放：
#   - 主画面：整宽、按 16:9 固定高度（所以不会变形）
#   - 小画面：用自动网格填满主画面下面剩下的空间
# 下面的 cells 仍然给出来，供缩略图和「哪一格是弹幕格」这类查询使用。
def portrait_main_cells(small: int) -> list:
    """主画面（第一格，整宽）+ small 个小画面，供缩略图/容量查询用。"""
    rows = 1 + max(1, math.ceil(small / 2))
    cells = [(0, 0, 1, 4)]
    for index in range(small):
        line, column = divmod(index, 2)
        cells.append((1 + line, column * 2, 1, 2))
    return rows, 4, cells


def portrait_danmaku_cells(small: int) -> tuple[int, int, list, int]:
    """竖屏 + 弹幕：主画面、small 个小画面，弹幕在最底下整宽一条。"""
    rows, columns, cells = portrait_main_cells(small)
    danmaku_index = len(cells)
    cells = cells + [(rows, 0, 1, columns)]
    return rows + 1, columns, cells, danmaku_index


def _portrait_layouts() -> tuple[list[dict], list[dict]]:
    plain, with_danmaku = [], []
    for small, name in ((2, "主画面 + 2 小"), (4, "主画面 + 4 小"), (6, "主画面 + 6 小")):
        rows, columns, cells = portrait_main_cells(small)
        plain.append({
            "id": f"portrait_main{small}",
            "name": name,
            "hint": "竖屏：主画面按 16:9 占满宽度，小画面填满下面",
            "spec": (rows, columns, cells),
            "portrait": "stack",
        })
        rows, columns, cells, danmaku_index = portrait_danmaku_cells(small)
        with_danmaku.append({
            "id": f"portrait_dm{small}",
            "name": f"{name} + 弹幕",
            "hint": "竖屏：主画面 + 小画面，弹幕占最底下一条",
            "spec": (rows, columns, cells),
            "portrait": "stack",
            "danmaku": danmaku_index,
        })
    return plain, with_danmaku


PORTRAIT_LAYOUTS, PORTRAIT_DANMAKU_LAYOUTS = _portrait_layouts()

#: 竖屏下「自动」布局用哪个（主画面 + 6 小，竖屏里最能把空间用满）
PORTRAIT_AUTO = "portrait_main6"

#: **第一次启动**（配置里还没存过布局）时的默认布局：1 主画面 + 5 小环绕。
#: 用户 2026-09-19 指定：新用户一打开就是一屏 6 路、主画面在角上、五路围着它。
FIRST_LAYOUT = "corner"

#: 没有可用布局时的兜底（以前是「自动」，用户要求去掉自动之后用它）：
#: 九分能一次摆下最多路，屏再小也只是格子变小。
DEFAULT_LAYOUT = "3x3"

# 布局菜单里的子菜单，用顶部的按钮来回切
GROUPS: list[tuple[str, list[dict]]] = [
    ("普通布局", LAYOUTS),
    ("弹幕布局", DANMAKU_LAYOUTS),
    ("竖屏布局", PORTRAIT_LAYOUTS + PORTRAIT_DANMAKU_LAYOUTS),
]

BY_ID = {layout["id"]: layout
         for layout in LAYOUTS + DANMAKU_LAYOUTS + PORTRAIT_LAYOUTS + PORTRAIT_DANMAKU_LAYOUTS}


def is_portrait_layout(layout_id: str) -> bool:
    """这个布局是不是那种「主画面固定 16:9 + 小画面自动排」的竖屏预设。"""
    layout = BY_ID.get(layout_id)
    return bool(layout and layout.get("portrait") == "stack")


def capacity(layout_id: str) -> int:
    """这一套一屏能放几路（cells 数量）；「自动」没有固定规格，返回 0。"""
    layout = BY_ID.get(layout_id)
    spec = (layout or {}).get("spec")
    return len(spec[2]) if spec else 0


def counterpart(layout_id: str, portrait: bool) -> str | None:
    """换方向时找**最相似**的那一套：按「能放几路」比，最接近的胜；平手取大的。

    横屏的等分/大带小和竖屏的「主画面 16:9 + 小画面」是两套摆放规则，切方向时
    既不能把别的那套硬套过去（画面会变形），也不该一律退到「自动」—— 用户要的是
    对映，例如横屏「主画面 + 2 小」↔ 竖屏「主画面 + 2 小」。
    带不带弹幕也要跟着：弹幕布局只找弹幕布局。

    自己已经是对应方向的那一套时，返回它自己，绝不拿等容量的另一套顶掉：
    横屏「主画面 + 5 小环绕」和「六分」都是 6 路，早先按顺序取第一个，
    结果一启动就被悄悄换成六分（用户选的「双主画面 + 4 小」同理会变成六分）。
    """
    source = BY_ID.get(layout_id)
    if source is None or source.get("spec") is None:
        return None
    wanted_danmaku = source.get("danmaku") is not None
    target = capacity(layout_id)
    candidates = [item for item in BY_ID.values()
                  if item.get("spec") is not None
                  and is_portrait_layout(item["id"]) == bool(portrait)
                  and (item.get("danmaku") is not None) == wanted_danmaku]
    if not candidates:
        return None
    if any(item["id"] == layout_id for item in candidates):
        return layout_id                    # 方向本来就对，不用映射
    best = min(candidates, key=lambda item: (abs(capacity(item["id"]) - target),
                                             -capacity(item["id"])))
    return best["id"]



def danmaku_cell(layout_id: str) -> int | None:
    """这个布局里哪一格是弹幕格；普通布局返回 None。"""
    layout = BY_ID.get(layout_id)
    return None if not layout else layout.get("danmaku")


def thumbnail(spec, size=(52, 34), danmaku: int | None = None) -> QPixmap:
    """把布局画成缩略图。spec 为 None 时画成虚线自动网格，danmaku 是弹幕格下标。"""
    width, height = size
    pixmap = QPixmap(width, height)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)

    cells, rows, cols = [], 2, 2
    if spec:
        rows, cols, cells = spec
    else:
        cells = even_cells(2, 2)

    padding = 2.0
    gap = 2.0
    cell_width = (width - padding * 2 - gap * (cols - 1)) / cols
    cell_height = (height - padding * 2 - gap * (rows - 1)) / rows
    for index, (row, col, rowspan, colspan) in enumerate(cells):
        x = padding + col * (cell_width + gap)
        y = padding + row * (cell_height + gap)
        w = cell_width * colspan + gap * (colspan - 1)
        h = cell_height * rowspan + gap * (rowspan - 1)
        if spec and index == danmaku:
            # 弹幕格：主题色描边 + 三道横线
            painter.setBrush(theme.qcolor(theme.ACCENT_SOFT))
            painter.setPen(QPen(theme.qcolor(theme.ACCENT), 1))
            painter.drawRoundedRect(QRectF(x, y, w, h), 2.0, 2.0)
            painter.setPen(QPen(theme.qcolor(theme.TEXT3), 1))
            for line in range(3):
                line_y = y + h * (0.3 + line * 0.2)
                painter.drawRect(QRectF(x + 2, line_y, max(1.0, w - 4), 1.0))
            continue
        if spec:
            painter.setBrush(theme.qcolor(theme.CONTENT_HOVER))
            painter.setPen(QPen(theme.qcolor(theme.BORDER), 1))
        else:
            painter.setBrush(theme.qcolor(theme.ACCENT_SOFT))
            pen = QPen(theme.qcolor(theme.ACCENT), 1, Qt.DashLine)
            painter.setPen(pen)
        painter.drawRoundedRect(QRectF(x, y, w, h), 2.0, 2.0)
    painter.end()
    return pixmap
