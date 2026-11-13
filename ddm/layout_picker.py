"""Layout selection widget without sidebar, player or main-window imports."""
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFontMetrics, QIcon
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QToolButton, QVBoxLayout
)

from . import layouts
from .widget_support import _repolish


class LayoutPicker(QFrame):
    """布局选择弹层：顶上按钮切组，下面是缩略图卡片。

    只列**当前方向能用**的布局：横屏不给竖屏预设、竖屏不给横屏预设 —— 两套摆放
    规则不一样，套错方向画面会被压变形（用户报的）。组里带 ``section`` 的布局
    表示换一段，上面插一行小标题（用户要求把平分布局和大带小布局分开）。
    """

    chosen = Signal(str)
    resetRequested = Signal()

    #: 一行摆几张卡片
    COLUMNS = 4
    #: 卡片图标尺寸（所有卡片统一，否则格子会错开）
    _icon_size = QSize(64, 42)
    #: 卡片最小宽度（名字都很短时也别挤成一条）
    _min_card_width = 108

    def __init__(self, current: str, parent=None, portrait: bool = False, *, presets_host=None):
        super().__init__(parent, Qt.Popup)
        self.setObjectName("LayoutPicker")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._cards: dict[str, list[QToolButton]] = {}
        self._sections: dict[str, list[QLabel]] = {}
        self._reset_layout_id = current
        self._can_reset_layout = layouts.capacity(current) > 1
        self.presets_page = None

        # 两组都列出来（横屏也能点竖屏预设）：选中另一个方向的预设时，本体
        # 会把**窗口**也改成那个方向（见 MainWindow._on_layout_changed /
        # _reshape_window），所以不会再出现「竖屏排布塞在横屏窗口里被压扁」。
        # 用户要的「切成竖屏后 alt+tab 的窗口预览也是竖的」就是靠这条路。
        groups = [(name, group) for name, group in layouts.GROUPS if group]
        if not groups:                       # 兜底：一张都没有就照旧全列
            groups = list(layouts.GROUPS)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)

        self._tabs: dict[str, QPushButton] = {}
        if len(groups) > 1:                  # 只剩一组时不用摆标签栏
            tabs = QHBoxLayout()
            tabs.setSpacing(6)
            for name, _group in groups:
                button = QPushButton(name)
                button.setObjectName("PickerTab")
                button.setFocusPolicy(Qt.TabFocus)
                button.setCheckable(True)
                button.setCursor(Qt.PointingHandCursor)
                button.clicked.connect(
                    lambda _checked=False, key=name: self.set_group(key))
                tabs.addWidget(button)
                self._tabs[name] = button
            tabs.addStretch(1)
            outer.addLayout(tabs)

        self._grid = QGridLayout()
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(6)
        outer.addLayout(self._grid)
        outer.addStretch(1)          # 各组行数不同，多出来的高度留在下面
        self.reset_button = QPushButton("恢复默认比例", self)
        self.reset_button.setObjectName("LayoutResetButton")
        self.reset_button.setToolTip("恢复当前布局的全部分隔线比例，保留直播间和音频设置")
        self.reset_button.clicked.connect(self._reset_ratios)
        outer.addWidget(self.reset_button)

        active = groups[0][0]
        for name, group in groups:
            cards: list[QToolButton] = []
            sections: list[QLabel] = []
            row, column, current_section = 0, 0, None
            for layout in group:
                section = layout.get("section")
                if section and section != current_section:
                    if column:              # 上一段没排满也换行
                        row, column = row + 1, 0
                    heading = QLabel(section)
                    heading.setObjectName("SectionLabel")
                    self._grid.addWidget(heading, row, 0, 1, self.COLUMNS)
                    sections.append(heading)
                    current_section = section
                    row += 1
                button = QToolButton(self)
                button.setObjectName("LayoutCard")
                button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
                button.setIcon(QIcon(layouts.thumbnail(layout["spec"],
                                                       size=(self._icon_size.width(), self._icon_size.height()),
                                                       danmaku=layout.get("danmaku"))))
                button.setIconSize(self._icon_size)
                button.setText(layout["name"])
                button.setCheckable(True)
                button.setChecked(layout["id"] == current)
                button.setProperty("layoutId", layout["id"])
                button.setToolTip(layout.get("hint") or layout["name"])
                if layout["id"] == current and self._can_reset_layout:
                    button.setToolTip(button.toolTip() + "\n再次点击恢复默认比例")
                button.setCursor(Qt.PointingHandCursor)
                button.clicked.connect(
                    lambda _checked=False, lid=layout["id"]: self._choose(lid))
                self._grid.addWidget(button, row, column)
                cards.append(button)
                column += 1
                if column >= self.COLUMNS:
                    row, column = row + 1, 0
            self._cards[name] = cards
            self._sections[name] = sections
            if any(item["id"] == current for item in group):
                active = name
        if presets_host is not None:
            from .room_presets_ui import RoomPresetsPage
            name = "直播间组合"
            button = QPushButton(name)
            button.setObjectName("PickerTab")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda: self.set_group(name))
            tabs.insertWidget(len(self._tabs), button)
            self._tabs[name] = button
            self._cards[name] = []
            self._sections[name] = []
            self.presets_page = RoomPresetsPage(presets_host, self)
            outer.insertWidget(2, self.presets_page, 1)
            self.presets_page.hide()
        self._even_cards()
        self.set_group(active)
        self._lock_size()

    def _even_cards(self) -> None:
        """把所有卡片做成一样大 —— 名字长短不一，不统一就会出现「大小不一样、
        上下没对齐」（用户报的）。宽度按最长的名字算，高度按图标 + 一行文字算。"""
        cards = [card for group in self._cards.values() for card in group]
        if not cards:
            return
        metrics = QFontMetrics(self.font())
        label = max(metrics.horizontalAdvance(card.text()) for card in cards)
        height = (self._icon_size.height() + metrics.height() + 14)
        self._card_size = QSize(max(self._min_card_width, label + 18), height)
        for card in cards:
            card.setFixedSize(self._card_size)
            card.setIconSize(self._icon_size)

    def set_group(self, name: str) -> None:
        """切到某一组布局（普通 / 弹幕 / 竖屏）。"""
        if name not in self._cards:
            return
        if self.presets_page is not None:
            self.presets_page.setVisible(name == "直播间组合")
            self.layout().setStretch(self.layout().count() - 2, 0 if name == "直播间组合" else 1)
            if name == "直播间组合":
                self.presets_page.refresh()
        for key, button in self._tabs.items():
            button.setChecked(key == name)
            _repolish(button)
        for key, cards in self._cards.items():
            for card in cards:
                card.setVisible(key == name)
        for key, headings in self._sections.items():
            for heading in headings:
                heading.setVisible(key == name)
        self.reset_button.setVisible(self._can_reset_layout and any(
            card.property("layoutId") == self._reset_layout_id for card in self._cards[name]))
        self._group = name
        self.adjustSize()
        # 宽度固定（右边对齐布局按钮），高度跟着这一组卡片走
        self.resize(getattr(self, "_width", self.width()), self.sizeHint().height())

    def group(self) -> str:
        return getattr(self, "_group", next(iter(self._cards)))

    def card_ids(self) -> list:
        """当前这一栏里列出来的布局 id（自检用来确认没把别方向的预设列出来）。"""
        return [card.property("layoutId") for card in self._cards.get(self.group(), [])]

    def _lock_size(self) -> None:
        """两组卡片行数不一样，尺寸锁成最大值，切换时不会向屏幕外增长。"""
        active = self.group()
        sizes = []
        for name in self._cards:
            self.set_group(name)
            sizes.append(self.sizeHint())
        self._width = max(size.width() for size in sizes)
        self._height = max(size.height() for size in sizes)
        self.setFixedSize(self._width, self._height)
        self.set_group(active)          # 量完尺寸要切回当前布局所在的那一栏

    def _choose(self, layout_id: str) -> None:
        self.chosen.emit(layout_id)
        self.close()

    def _reset_ratios(self) -> None:
        self.resetRequested.emit()
        self.close()
