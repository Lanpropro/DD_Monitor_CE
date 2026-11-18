"""Layout presets and saved room combinations in one anchored popup."""
from PySide6.QtCore import QSignalBlocker, QSize, Qt, Signal
from PySide6.QtGui import QFontMetrics, QIcon
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QScrollArea, QSizePolicy, QStyle,
    QToolButton, QVBoxLayout, QWidget
)

from . import layouts, theme
from .ui import ActionButton, ElidedLabel, SegmentedControl, TitleLabel


class LayoutPicker(QFrame):
    chosen = Signal(str)
    resetRequested = Signal()

    COLUMNS = 4
    _icon_size = QSize(84, 46)
    _presets_key = '直播间组合'

    def __init__(self, current: str, parent=None, portrait: bool = False, *, presets_host=None):
        super().__init__(parent, Qt.Popup)
        self.setObjectName('LayoutPicker')
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._cards = {}
        self._sections = {}
        self._reset_layout_id = current
        self._can_reset_layout = layouts.capacity(current) > 1
        self.presets_page = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(10)
        self.header = QHBoxLayout()
        self.header.addWidget(TitleLabel('布局预设'))
        active_layout = layouts.BY_ID.get(current, layouts.BY_ID[layouts.DEFAULT_LAYOUT])
        self.current_label = ElidedLabel('当前 · ' + active_layout['name'])
        self.current_label.setObjectName('SettingsHint')
        self.current_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.header.addWidget(self.current_label, 1)
        outer.addLayout(self.header)

        groups = [(name, group) for name, group in layouts.GROUPS if group]
        active = next((name for name, group in groups if any(item['id'] == current for item in group)), groups[0][0])
        keys = [name for name, _group in groups]
        if presets_host is not None:
            keys.append(self._presets_key)
        self.tabs = SegmentedControl([(name, name) for name in keys], active, self)
        self.tabs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._tabs = self.tabs.buttons
        self.tabs.valueChanged.connect(self.set_group)
        outer.addWidget(self.tabs)

        self.scroll = QScrollArea(self)
        self.scroll.setObjectName('LayoutPresetScroll')
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setWidgetResizable(True)
        board = QWidget()
        board.setObjectName('LayoutPresetBoard')
        self._grid = QGridLayout(board)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(8)
        self._grid.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.scroll.setWidget(board)
        outer.addWidget(self.scroll, 1)

        if presets_host is not None:
            from .room_presets_ui import RoomPresetsPage
            self._cards[self._presets_key] = []
            self._sections[self._presets_key] = []
            self.presets_page = RoomPresetsPage(presets_host, self)
            outer.addWidget(self.presets_page, 1)
        self.reset_button = ActionButton('恢复默认比例', self)
        self.reset_button.setObjectName('LayoutResetButton')
        self.reset_button.setToolTip('恢复当前布局的全部分隔线比例，保留直播间和音频设置')
        self.reset_button.clicked.connect(self._reset_ratios)
        outer.addWidget(self.reset_button, 0, Qt.AlignRight)

        metrics = QFontMetrics(self.font())
        widest = max(metrics.horizontalAdvance(item['name']) for _, group in groups for item in group)
        self._card_size = QSize(max(118, widest + 18), self._icon_size.height() + metrics.height() + 16)
        available = self.screen().availableGeometry()
        margins = outer.contentsMargins()
        scrollbar = self.style().pixelMetric(QStyle.PM_ScrollBarExtent)
        chrome_width = margins.left() + margins.right() + scrollbar
        spacing = self._grid.spacing()
        columns = min(self.COLUMNS, max(1, (available.width() - 12 - chrome_width + spacing)
                                        // (self._card_size.width() + spacing)))

        for name, group in groups:
            self._add_group(name, group, columns, current)
        self._refresh_icons()
        theme.signals().changed.connect(self._refresh_icons)

        width = columns * self._card_size.width() + (columns - 1) * spacing + chrome_width
        if self.presets_page is not None:
            width = max(width, self.presets_page.minimumWidth() + chrome_width)
        heights = []
        for name in self._cards:
            self.set_group(name)
            self._grid.invalidate()
            outer.invalidate()
            height = outer.sizeHint().height()
            if name != self._presets_key:
                height += self._grid.sizeHint().height() - self.scroll.sizeHint().height() + 4
            heights.append(height)
        self.setFixedSize(min(width, available.width() - 12), min(max(heights), available.height() - 12))
        self.set_group(active)

    def _add_group(self, name, group, columns, current):
        cards, sections = [], []
        row, column = 0, 0
        for index, item in enumerate(group):
            section = item.get('section') or ('均分' if name == '普通布局' and index == 0 else '')
            if section:
                if column:
                    row, column = row + 1, 0
                heading = QLabel(section)
                heading.setObjectName('SectionLabel')
                self._grid.addWidget(heading, row, 0, 1, columns)
                sections.append(heading)
                row += 1
            button = QToolButton()
            button.setObjectName('LayoutCard')
            button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            button.setFixedSize(self._card_size)
            button.setIconSize(self._icon_size)
            button.setText(item['name'])
            button.setCheckable(True)
            button.setChecked(item['id'] == current)
            button.setProperty('layoutId', item['id'])
            button.setToolTip(item.get('hint') or item['name'])
            if item['id'] == current and self._can_reset_layout:
                button.setToolTip(button.toolTip() + '\n再次点击恢复默认比例')
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _checked, lid=item['id']: self._choose(lid))
            self._grid.addWidget(button, row, column)
            cards.append(button)
            column += 1
            if column == columns:
                row, column = row + 1, 0
        self._cards[name] = cards
        self._sections[name] = sections

    def _refresh_icons(self, *_args):
        for cards in self._cards.values():
            for card in cards:
                item = layouts.BY_ID[card.property('layoutId')]
                size = (32, self._icon_size.height()) if item.get('portrait') else self._icon_size.toTuple()
                card.setIcon(QIcon(layouts.thumbnail(item['spec'], size=size, danmaku=item.get('danmaku'), preset=True)))

    def set_group(self, name: str) -> None:
        if name not in self._cards:
            return
        self._group = name
        with QSignalBlocker(self.tabs):
            self.tabs.setValue(name)
        showing_presets = name == self._presets_key
        self.scroll.setVisible(not showing_presets)
        if self.presets_page is not None:
            self.presets_page.setVisible(showing_presets)
            if showing_presets:
                self.presets_page.refresh()
        for key, cards in self._cards.items():
            for card in cards:
                card.setVisible(key == name)
            for heading in self._sections[key]:
                heading.setVisible(key == name)
        self.reset_button.setVisible(self._can_reset_layout and any(
            card.property('layoutId') == self._reset_layout_id for card in self._cards[name]))
        self.scroll.verticalScrollBar().setValue(0)

    def group(self) -> str:
        return self._group

    def card_ids(self) -> list:
        return [card.property('layoutId') for card in self._cards[self.group()]]

    def _choose(self, layout_id: str) -> None:
        self.chosen.emit(layout_id)
        self.close()

    def _reset_ratios(self) -> None:
        self.resetRequested.emit()
        self.close()
