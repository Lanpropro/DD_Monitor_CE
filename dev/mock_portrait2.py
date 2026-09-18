"""竖屏原型 v2：按用户定的方向画。

定了两条：
  1. 布局单独新增竖屏预设 —— 「竖向一大带多小」，不做自动镜像
  2. 顶部横栏里，账号行和关注列表合成一个头像组：
     收起时只剩头像、对齐成一排；展开时只留一个按钮，其余（排序/多选/
     导入/+添加/布局/设置）收进「⋯」菜单；点头像再展开

用法：
    python dev\\mock_portrait2.py
输出：
    dev/preview/portrait_mock2.png
"""
import os
import sys

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import (
    QColor, QFont, QFontMetrics, QGuiApplication, QPainter, QPixmap, QPolygon,
)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
os.environ.setdefault("DDM_NO_SAVE", "1")

from ddm import theme  # noqa: E402

OUT = os.path.join(REPO, "dev", "preview", "portrait_mock2.png")

W, H = 1080, 1920
SCALE = 0.40
PAD = 12
GAP = 10
ROUND = 10
CTRL_BAR = 36          # 画面里的底部信息条

ROOMS = [
    ("示例主播A", "示例标题", True, "2.1万"),
    ("示例主播B", "最后练一次大米", True, "1.8万"),
    ("嘉然今天吃什么", "晚饭是火锅", True, "6.1万"),
    ("贝拉kira", "练舞日常", False, ""),
    ("向晚大魔王", "写歌中", True, "9.4万"),
    ("乃琳Queen", "深夜电台", False, ""),
]

DM_LINES = [
    ("示例账号 26", "安***", "哈哈哈哈，尖鼻位置很危险，要被炸了"),
    ("", "燕云冷墨", "传说炮手"),
    ("示例账号 27", "幸运值MAX", "打咩"),
    ("", "小***", "冲鸭"),
]


def count_small(n: int) -> range:
    return range(n)


def font(size: int, bold: bool = False) -> QFont:
    f = QFont(theme.FONT_DEFAULT)
    f.setPixelSize(size)
    f.setBold(bold)
    return f


def text(painter, rect: QRect, value: str, size: int = 15, colour: str = "",
         bold: bool = False, align=Qt.AlignLeft | Qt.AlignVCenter) -> None:
    painter.setFont(font(size, bold))
    painter.setPen(QColor(colour or theme.TEXT3))
    painter.drawText(rect, int(align), value)


def panel(painter, rect: QRect, fill: str, radius: int = ROUND) -> None:
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(fill))
    if radius:
        painter.drawRoundedRect(rect, radius, radius)
    else:
        painter.drawRect(rect)


def pill(painter, rect: QRect, fill: QColor) -> None:
    painter.setPen(Qt.NoPen)
    painter.setBrush(fill)
    painter.drawRoundedRect(rect, rect.height() // 2, rect.height() // 2)


def avatar(painter, circle: QRect, label: str, live: bool, account: bool = False,
           pinned: bool = False) -> None:
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#3b6ea5" if live or account else "#3a3f46"))
    painter.drawEllipse(circle)
    text(painter, circle, label, 14, "#ffffff" if (live or account) else theme.TEXT4,
         bold=True, align=Qt.AlignCenter)
    if pinned:
        painter.setBrush(QColor(theme.ACCENT))
        painter.setPen(Qt.NoPen)
        painter.drawPolygon(QPolygon([QPoint(circle.left(), circle.top()),
                                      QPoint(circle.left() + 14, circle.top()),
                                      QPoint(circle.left(), circle.top() + 14)]))
    if live:
        painter.setBrush(QColor(theme.PINK))
        painter.setPen(QColor(theme.SIDEBAR))
        painter.drawEllipse(QPoint(circle.right() - 2, circle.bottom() - 2), 7, 7)


def tile(painter, rect: QRect, index: int, label: str, big: bool = False) -> None:
    """一路画面：左上浮标 + 右上控制 + 底部音量条。"""
    panel(painter, rect, theme.TILE_BG, 8)
    painter.setFont(font(18 if big else 15))
    painter.setPen(QColor(theme.TEXT4))
    painter.drawText(rect.adjusted(PAD, PAD, -PAD, -PAD),
                     int(Qt.AlignCenter | Qt.TextWordWrap), label)

    y = rect.top() + 9
    circle_r = 5
    badge = QRect(rect.left() + 9, y, 116 if big else 96, 26)
    pill(painter, badge, QColor(12, 13, 16, 205))
    painter.setBrush(QColor(theme.PINK))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(QPoint(badge.left() + 14, badge.center().y()), circle_r, circle_r)
    text(painter, badge.adjusted(25, 0, 0, 0),
         f"{index + 1}.{index}万" if big else f"{index + 1}", 14 if big else 13,
         theme.TEXT2)

    if big:
        title = QRect(badge.right() + 8, y, min(430, rect.width() - 300), 26)
        pill(painter, title, QColor(12, 13, 16, 205))
        text(painter, title.adjusted(12, 0, -10, 0), "示例主播A · 示例标题", 14, theme.TEXT2)
        x = rect.right() - 9
        for label_text, width in (("×", 26), ("⟳", 32), ("原画", 74)):
            x -= width
            chip = QRect(x, y, width, 26)
            pill(painter, chip, QColor(12, 13, 16, 205))
            text(painter, chip, label_text, 13, theme.TEXT3, align=Qt.AlignCenter)
            x -= 6

    bar = QRect(rect.left(), rect.bottom() - CTRL_BAR + 1, rect.width(), CTRL_BAR - 1)
    panel(painter, bar, "#181a1e", 0)
    if rect.width() >= 260:
        text(painter, bar.adjusted(12, 0, 0, 0), "⏸", 15, theme.TEXT2)
    x = bar.right() - 12
    text(painter, QRect(x - 26, bar.top(), 26, bar.height()), "55", 13, theme.TEXT3,
         align=Qt.AlignRight | Qt.AlignVCenter)
    x -= 32
    sw = 70 if big else 52
    slider = QRect(x - sw, bar.center().y() - 2, sw, 4)
    painter.setBrush(QColor(70, 74, 80))
    painter.setPen(Qt.NoPen)
    painter.drawRoundedRect(slider, 2, 2)
    painter.setBrush(QColor(theme.ACCENT))
    painter.drawRoundedRect(QRect(slider.left(), slider.top(), int(sw * 0.55), 4), 2, 2)
    painter.setBrush(QColor(255, 255, 255))
    painter.drawEllipse(QPoint(slider.left() + int(sw * 0.55), slider.center().y()), 4, 4)
    if rect.width() >= 260:
        x -= sw + 10
        text(painter, QRect(x - 46, bar.top(), 46, bar.height()), "🔊 ×", 13, theme.TEXT3,
             align=Qt.AlignRight | Qt.AlignVCenter)


def danmaku(painter, rect: QRect, lines: list, head: str = "已连接 · 12") -> None:
    panel(painter, rect, "#12141a", 8)
    head_rect = QRect(rect.left(), rect.top(), rect.width(), 34)
    painter.setPen(QColor(255, 255, 255, 18))
    painter.drawLine(head_rect.bottomLeft(), head_rect.bottomRight())
    painter.setBrush(QColor(theme.PINK))
    painter.setPen(Qt.NoPen)
    painter.drawEllipse(QPoint(head_rect.left() + 16, head_rect.center().y()), 4, 4)
    text(painter, head_rect.adjusted(28, 0, 0, 0), "弹幕", 15, theme.TEXT1, bold=True)
    chip = QRect(head_rect.right() - 118, head_rect.center().y() - 12, 106, 24)
    pill(painter, chip, QColor(131, 131, 145, 40))
    text(painter, chip, head, 13, theme.TEXT3, align=Qt.AlignCenter)

    body = QRect(rect.left() + 12, head_rect.bottom() + 8, rect.width() - 24,
                 rect.height() - head_rect.height() - 16)
    y = body.top()
    for medal, name, words in lines:
        if y + 28 > body.bottom():
            break
        x = body.left()
        if medal:
            width = QFontMetrics(font(11, True)).horizontalAdvance(medal) + 12
            badge = QRect(x, y + 4, width, 18)
            panel(painter, badge, "#2b527a", 4)
            text(painter, badge, medal, 11, "#ffffff", bold=True, align=Qt.AlignCenter)
            x += width + 6
        painter.setFont(font(15))
        painter.setPen(QColor(theme.ACCENT))
        painter.drawText(QRect(x, y, 200, 26), int(Qt.AlignLeft | Qt.AlignVCenter),
                         f"{name}：")
        prefix = QFontMetrics(font(15)).horizontalAdvance(f"{name}：")
        painter.setPen(QColor(theme.TEXT2))
        painter.drawText(QRect(x + prefix, y, body.width() - (x - body.left()) - prefix, 26),
                         int(Qt.AlignLeft | Qt.AlignVCenter), words)
        y += 30


# ---------------------------------------------------------------- 顶部横栏两种状态

def topbar_collapsed(painter, rect: QRect) -> None:
    """收起：只剩一排头像（账号行跟关注列表合成一组），全部对齐。"""
    panel(painter, rect, theme.SIDEBAR, 0)
    row = QRect(rect.left() + PAD, rect.top() + (rect.height() - 36) // 2,
                rect.width() - 2 * PAD, 36)
    x = row.left()
    # 账号头像放第一位，和关注头像同一套尺寸、同一条基线
    avatar(painter, QRect(x, row.top() + 1, 34, 34), "我", True, account=True)
    x += 42
    for name, _title, live, _viewers in ROOMS:
        if x + 34 > row.right() - 40:
            break
        avatar(painter, QRect(x, row.top() + 1, 34, 34), name[0], live,
               pinned=(name.startswith("示例账号")))
        x += 42
    text(painter, QRect(row.right() - 34, row.top(), 34, row.height()), "≫", 18,
         theme.TEXT3, align=Qt.AlignCenter)


def topbar_expanded(painter, rect: QRect) -> None:
    """展开：头像排 + 下面一行只留一个「布局预设」，其余收进「⋯」。"""
    panel(painter, rect, theme.SIDEBAR, 0)
    strip = QRect(rect.left() + PAD, rect.top() + 8, rect.width() - 2 * PAD, 36)
    x = strip.left()
    avatar(painter, QRect(x, strip.top() + 1, 34, 34), "我", True, account=True)
    x += 42
    for name, _title, live, _viewers in ROOMS:
        if x + 34 > strip.right() - 40:
            break
        avatar(painter, QRect(x, strip.top() + 1, 34, 34), name[0], live,
               pinned=(name.startswith("示例账号")))
        x += 42
    text(painter, QRect(strip.right() - 34, strip.top(), 34, strip.height()), "≪", 18,
         theme.TEXT3, align=Qt.AlignCenter)

    row = QRect(rect.left() + PAD, strip.bottom() + 8, rect.width() - 2 * PAD, 30)
    search = QRect(row.left(), row.top(), row.width() - 90 - 44 - 16, 30)
    panel(painter, search, theme.CONTENT, 15)
    text(painter, search.adjusted(14, 0, 0, 0), "搜索主播 / 房间号", 13, theme.TEXT4)

    one = QRect(search.right() + 8, row.top(), 90, 30)
    panel(painter, one, theme.CONTENT, 15)
    text(painter, one, "布局预设", 13, theme.TEXT2, align=Qt.AlignCenter)

    more = QRect(one.right() + 8, row.top(), 44, 30)
    panel(painter, more, theme.CONTENT, 15)
    text(painter, more, "⋯", 16, theme.TEXT2, align=Qt.AlignCenter)
    text(painter, QRect(rect.left() + PAD, row.bottom() + 2, rect.width(), 16),
         "排序 · 多选 · 刷新 · 导入关注 · + 添加直播间 · 设置　都在「⋯」里", 11,
         theme.TEXT4)


BAR_COLLAPSED = 60
BAR_EXPANDED = 96


# ---------------------------------------------------------------- 场景

def scene(painter, origin: QRect, bar_h: int, grid: str, expanded: bool,
          danmaku_h: int = 0, title: str = "") -> None:
    panel(painter, origin, theme.BG, 12)
    inner = origin.adjusted(PAD, PAD, -PAD, -PAD)
    bar = QRect(inner.left(), inner.top(), inner.width(), bar_h)
    (topbar_expanded if expanded else topbar_collapsed)(painter, bar)

    y = bar.bottom() + GAP
    area = QRect(inner.left(), y, inner.width(), inner.bottom() - y)
    dm = QRect()
    if danmaku_h:
        dm = QRect(area.left(), area.bottom() - danmaku_h, area.width(), danmaku_h)
        area = QRect(area.left(), area.top(), area.width(), area.height() - danmaku_h - GAP)

    if grid == "big3":
        # 一大 + 三小横排
        big_h = int(area.width() * 9 / 16) + CTRL_BAR + 2 * PAD
        tile(painter, QRect(area.left(), area.top(), area.width(), big_h), 0,
             "主画面 · 16:9 · 占满宽", big=True)
        rest = QRect(area.left(), area.top() + big_h + GAP, area.width(),
                     area.height() - big_h - GAP)
        count = 3
        cell_w = (rest.width() - GAP * (count - 1)) // count
        cell_h = rest.height()
        for index in range(count):
            cell = QRect(rest.left() + index * (cell_w + GAP), rest.top(), cell_w, cell_h)
            ratio = (cell_w - 2 * PAD) / max(1, cell_h - CTRL_BAR)
            tile(painter, cell, index + 1,
                 f"小 {index + 1}\n{cell_w}×{cell_h}\n画面比例 {ratio:.2f}（16:9 要 1.78）")
    elif grid == "big3_split":
        # 一大 + 三小竖排（高度按 16:9 封顶，不拉长）
        big_h = int(area.width() * 9 / 16) + CTRL_BAR + 2 * PAD
        tile(painter, QRect(area.left(), area.top(), area.width(), big_h), 0,
             "主画面 · 16:9 · 占满宽", big=True)
        rest = QRect(area.left(), area.top() + big_h + GAP, area.width(),
                     area.height() - big_h - GAP)
        native = int(area.width() * 9 / 16) + CTRL_BAR + 2 * PAD
        cell_h = min((rest.height() - GAP * 2) // 3, native)
        for index in count_small(3):
            top = rest.top() + index * (cell_h + GAP)
            if top + cell_h > rest.bottom():
                break
            cell = QRect(rest.left(), top, rest.width(), cell_h)
            ratio = (cell.width() - 2 * PAD) / max(1, cell.height() - CTRL_BAR)
            tile(painter, cell, index + 1,
                 f"小 {index + 1} · {cell.width()}×{cell.height()} · 比例 {ratio:.2f}")
        text(painter, QRect(rest.left(), rest.bottom() - 26, rest.width(), 24),
             f"（三小竖排只占 {3 * (cell_h + GAP)}px，下面还空 "
             f"{rest.height() - 3 * (cell_h + GAP)}px）", 13, theme.TEXT4)
    elif grid == "big4":
        # 一大 + 四小 2x2（余下空间最贴合）
        big_h = int(area.width() * 9 / 16) + CTRL_BAR + 2 * PAD
        tile(painter, QRect(area.left(), area.top(), area.width(), big_h), 0,
             "主画面 · 16:9 · 占满宽", big=True)
        rest = QRect(area.left(), area.top() + big_h + GAP, area.width(),
                     area.height() - big_h - GAP)
        # 小画面按 16:9 封顶，避免被拉长
        native = int(((rest.width() - GAP) // 2) * 9 / 16) + CTRL_BAR + 2 * PAD
        cell_w = (rest.width() - GAP) // 2
        cell_h = min((rest.height() - GAP) // 2, native)
        for index in range(4):
            row, col = divmod(index, 2)
            cell = QRect(rest.left() + col * (cell_w + GAP),
                         rest.top() + row * (cell_h + GAP), cell_w, cell_h)
            ratio = (cell_w - 2 * PAD) / max(1, cell_h - CTRL_BAR)
            tile(painter, cell, index + 1,
                 f"小 {index + 1} · {cell_w}×{cell_h} · 比例 {ratio:.2f}")
        used = 2 * (cell_h + GAP)
        leftover = rest.height() - used
        text(painter, QRect(rest.left(), rest.bottom() - 74, rest.width(), 24),
             f"四小占 {used}px，下面空 {leftover}px", 13, theme.TEXT4)
        text(painter, QRect(rest.left(), rest.bottom() - 48, rest.width(), 24),
             "（再添一路就变 2×3，能填满）", 13, theme.TEXT4)
    elif grid == "feed":
        count = 4
        cell_h = int(area.width() * 9 / 16) + CTRL_BAR + 2 * PAD
        for index in range(count):
            top = area.top() + index * (cell_h + GAP)
            if top + cell_h > area.bottom():
                break
            tile(painter, QRect(area.left(), top, area.width(), cell_h), index,
                 f"画面 {index + 1}", big=(index == 0))
    elif grid == "stack":
        count = 3
        cell_h = int(area.width() * 9 / 16) + CTRL_BAR + 2 * PAD
        for index in range(count):
            top = area.top() + index * (cell_h + GAP)
            if top + cell_h > area.bottom():
                break
            tile(painter, QRect(area.left(), top, area.width(), cell_h), index,
                 f"画面 {index + 1}", big=(index == 0))

    if danmaku_h:
        danmaku(painter, dm, DM_LINES)

    if title:
        pass


def main() -> None:
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass
    QGuiApplication(sys.argv)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)

    scenes = [
        ("① 一大 + 三小横排（小画面会被拉窄）",
         dict(bar_h=BAR_COLLAPSED, grid="big3", expanded=False)),
        ("② 一大 + 三小竖排（高度按 16:9 封顶）",
         dict(bar_h=BAR_COLLAPSED, grid="big3_split", expanded=False)),
        ("③ 一大 + 四小 2×2（余下空间最贴合）",
         dict(bar_h=BAR_COLLAPSED, grid="big4", expanded=False)),
        ("横栏展开态 · 只留一个按钮 + ⋯",
         dict(bar_h=BAR_EXPANDED, grid="big4", expanded=True)),
        ("④ 纯竖向堆叠（每路 16:9，一屏 2 路）",
         dict(bar_h=BAR_COLLAPSED, grid="stack", expanded=False)),
    ]

    margin, title_h = 28, 52
    width = margin + len(scenes) * (W + margin)
    height = margin + title_h + H + margin
    image = QPixmap(width, height)
    image.fill(QColor("#0e0f11"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    for index, (title, kwargs) in enumerate(scenes):
        left = margin + index * (W + margin)
        text(painter, QRect(left, margin, W, title_h), title, 30, theme.TEXT1, bold=True)
        scene(painter, QRect(left, margin + title_h, W, H), **kwargs)
    painter.end()

    scaled = image.scaledToWidth(int(width * SCALE), Qt.SmoothTransformation)
    scaled.save(OUT, "PNG")
    print(f"已保存 {OUT} ({scaled.width()}x{scaled.height()})")


if __name__ == "__main__":
    main()
