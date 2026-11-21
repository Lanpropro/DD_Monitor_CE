"""Layout presets and saved room combinations in one anchored popup."""
from PySide6.QtCore import QEvent, QSignalBlocker, QSize, Qt, Signal
from PySide6.QtGui import QFontMetrics, QIcon, QWindow
from PySide6.QtWidgets import (
    QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QMenu, QScrollArea, QSizePolicy, QStyle,
    QStyleOptionToolButton, QStylePainter, QToolButton, QVBoxLayout, QWidget
)

from . import layouts, theme
from .panel_resize import resize_edges, resized_rect, set_resize_cursor
from .ui import ActionButton, ElidedLabel, SegmentedControl, TitleLabel


class _LayoutCard(QToolButton):
    def paintEvent(self, event):
        option = QStyleOptionToolButton()
        self.initStyleOption(option)
        option.text = self.fontMetrics().elidedText(option.text, Qt.ElideRight, max(0, self.width() - 16))
        QStylePainter(self).drawComplexControl(QStyle.CC_ToolButton, option)


class LayoutPicker(QFrame):
    chosen = Signal(str)
    resetRequested = Signal()
    sizeChanged = Signal(QSize)

    COLUMNS = 4
    DEFAULT_SIZE = QSize(456, 360)
    _icon_size = QSize(76, 42)
    _presets_key = '直播间组合'
    custom_layouts_key = '自定义布局'

    def __init__(self, current: str, parent=None, portrait: bool = False, *,
                 presets_host=None, preferred_size=None, available=None):
        super().__init__(parent, Qt.Popup)
        self.setObjectName('LayoutPicker')
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._cards = {}
        self._sections = {}
        self._columns = 0
        self._resize_gesture = None
        self._resize_area = (available or self.screen().availableGeometry()).adjusted(6, 6, -6, -6)
        self.setMouseTracking(True)
        self._reset_layout_id = current
        self._can_reset_layout = layouts.capacity(current) > 1
        self.presets_page = None
        self.custom_layouts_page = None
        self.layout_presets = getattr(presets_host, 'layout_presets', None)
        self.edit_button = None

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
        if self.layout_presets is not None and self.layout_presets.items:
            keys.append(self.custom_layouts_key)
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
        footer = QHBoxLayout()
        footer.addStretch(1)
        if self.custom_layouts_key in keys:
            from .layout_presets_ui import LayoutPresetsPage
            self._cards[self.custom_layouts_key] = []
            self._sections[self.custom_layouts_key] = []
            self.custom_layouts_page = LayoutPresetsPage(self, presets_host)
            outer.addWidget(self.custom_layouts_page, 1)
        if self.layout_presets is not None:
            self.edit_button = ActionButton('修改当前布局', self)
            self.edit_button.setToolTip('在画面墙预览并调整当前预设的比例')
            self.edit_button.clicked.connect(lambda: self._edit_layout(current))
            footer.addWidget(self.edit_button)
        self.reset_button = ActionButton('恢复默认比例', self)
        self.reset_button.setToolTip('恢复当前布局的全部分隔线比例，保留直播间和音频设置')
        self.reset_button.clicked.connect(self._reset_ratios)
        footer.addWidget(self.reset_button)
        outer.addLayout(footer)

        for name, group in groups:
            self._add_group(board, name, group, current)
        self._refresh_icons()
        theme.signals().changed.connect(self._refresh_icons)
        self.set_group(active)
        self.setMinimumSize(QSize(320, 245).boundedTo(self._resize_area.size()))
        size = (preferred_size or self.DEFAULT_SIZE).expandedTo(self.minimumSize()).boundedTo(self._resize_area.size())
        self.resize(size)
        self._reflow()

    @staticmethod
    def _section(name, index, item):
        return item.get('section') or ('均分' if name == '普通布局' and index == 0 else '')

    def _add_group(self, board, name, group, current):
        cards, sections = [], []
        for index, item in enumerate(group):
            section = self._section(name, index, item)
            if section:
                heading = QLabel(section, board)
                heading.setObjectName('SectionLabel')
                sections.append(heading)
            button = _LayoutCard(board)
            button.setObjectName('LayoutCard')
            button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            button.setIconSize(self._icon_size)
            button.setText(item['name'])
            button.setCheckable(True)
            button.setChecked(item['id'] == current)
            button.setProperty('layoutId', item['id'])
            button.setToolTip(item.get('hint') or item['name'])
            if item['id'] == current and self._can_reset_layout and not self._has_override(current):
                button.setToolTip(button.toolTip() + '\n再次点击恢复默认比例')
            if self.layout_presets is not None:
                shortcut = self.layout_presets.overrides.get(item['id'], {}).get('shortcut')
                if shortcut and self.layout_presets.shortcuts().get(shortcut) == item['id']:
                    button.setToolTip(button.toolTip() + '\n快捷键：' + shortcut)
                button.setContextMenuPolicy(Qt.CustomContextMenu)
                button.customContextMenuRequested.connect(lambda point, card=button: self._layout_menu(card, point))
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _checked, lid=item['id']: self._choose(lid))
            cards.append(button)
        self._cards[name] = cards
        self._sections[name] = sections

    def _reflow(self):
        margins = self.layout().contentsMargins()
        width = self.width() - margins.left() - margins.right() - self.style().pixelMetric(QStyle.PM_ScrollBarExtent)
        spacing = self._grid.spacing()
        columns = min(self.COLUMNS, max(1, (width + spacing) // (122 + spacing)))
        cell_width = max(1, (width - (columns - 1) * spacing) // columns)
        height = self._icon_size.height() + QFontMetrics(self.font()).height() + 14
        for cards in self._cards.values():
            for card in cards:
                card.setFixedSize(cell_width, height)
        if columns == self._columns:
            return
        self._columns = columns
        while self._grid.count():
            self._grid.takeAt(self._grid.count() - 1)
        for name, cards in self._cards.items():
            headings = iter(self._sections[name])
            row = column = 0
            for index, card in enumerate(cards):
                if self._section(name, index, layouts.BY_ID[card.property('layoutId')]):
                    if column:
                        row, column = row + 1, 0
                    self._grid.addWidget(next(headings), row, 0, 1, columns)
                    row += 1
                self._grid.addWidget(card, row, column)
                column += 1
                if column == columns:
                    row, column = row + 1, 0

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if event.size().width() != event.oldSize().width():
            self._reflow()

    def mousePressEvent(self, event):
        point = event.position().toPoint()
        if (event.button() == Qt.LeftButton and self.rect().contains(point)
                and (edges := resize_edges(self, point))):
            self._resize_gesture = (edges, event.globalPosition().toPoint(), self.geometry())
            event.accept()
            return
        super().mousePressEvent(event)

    def _drag_resize(self, point):
        edges, pressed, original = self._resize_gesture
        self.setGeometry(resized_rect(original, edges, point - pressed, self._resize_area, self.minimumSize()))

    def mouseMoveEvent(self, event):
        if self._resize_gesture is not None and event.buttons() & Qt.LeftButton:
            self._drag_resize(event.globalPosition().toPoint())
            event.accept()
            return
        set_resize_cursor(self, resize_edges(self, event.position().toPoint()))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._resize_gesture is not None and event.button() == Qt.LeftButton:
            original = self._resize_gesture[2]
            self._drag_resize(event.globalPosition().toPoint())
            self._resize_gesture = None
            if self.size() != original.size():
                self.sizeChanged.emit(self.size())
            set_resize_cursor(self, resize_edges(self, event.position().toPoint()))
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):
        if self._resize_gesture is None:
            self.unsetCursor()
        super().leaveEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        QApplication.instance().installEventFilter(self)

    def hideEvent(self, event):
        QApplication.instance().removeEventFilter(self)
        self._resize_gesture = None
        self.unsetCursor()
        super().hideEvent(event)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.MouseButtonPress, QEvent.NonClientAreaMouseButtonPress):
            # A popup grab can deliver clicks outside its bounds to the picker itself.
            if (self._resize_gesture is None
                    and not self.frameGeometry().contains(event.globalPosition().toPoint())
                    and not self._owns_click_target(watched)):
                self.close()
                return True
        return super().eventFilter(watched, event)

    def _owns_click_target(self, watched):
        # Rename and error dialogs can extend past the picker.
        if isinstance(watched, QWindow):
            window = watched.transientParent()
            while window is not None:
                if window is self.windowHandle():
                    return True
                window = window.transientParent()
        elif isinstance(watched, QWidget):
            return watched is not self and self.isAncestorOf(watched)
        return False

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
        showing_custom = name == self.custom_layouts_key
        self.scroll.setVisible(not (showing_presets or showing_custom))
        if self.custom_layouts_page is not None:
            self.custom_layouts_page.setVisible(showing_custom)
            if showing_custom:
                self.custom_layouts_page.refresh()
        if self.presets_page is not None:
            self.presets_page.setVisible(showing_presets)
            if showing_presets:
                self.presets_page.refresh()
        for key, cards in self._cards.items():
            for card in cards:
                card.setVisible(key == name)
            for heading in self._sections[key]:
                heading.setVisible(key == name)
        current_in_group = any(card.property('layoutId') == self._reset_layout_id for card in self._cards[name])
        self.reset_button.setVisible(self._can_reset_layout and current_in_group)
        if self.edit_button is not None:
            self.edit_button.setVisible(self._can_reset_layout and current_in_group)
        self.scroll.verticalScrollBar().setValue(0)

    def group(self) -> str:
        return self._group

    def card_ids(self) -> list:
        return [card.property('layoutId') for card in self._cards[self.group()]]

    def _choose(self, layout_id: str) -> None:
        self.chosen.emit(layout_id)
        self.close()

    def _has_override(self, layout_id):
        return self.layout_presets is not None and 'ratios' in self.layout_presets.overrides.get(layout_id, {})

    def _edit_layout(self, layout_id):
        self.close()
        self.layout_presets.edit(layout_id)

    def _layout_menu(self, card, point):
        from .layout_presets_ui import edit_shortcut
        base = card.property('layoutId')
        menu = QMenu(card)
        menu.aboutToHide.connect(menu.deleteLater)
        if layouts.capacity(base) > 1:
            menu.addAction('修改布局', lambda: self._edit_layout(base))
        menu.addAction('设置快捷键', lambda: edit_shortcut(self, self.layout_presets, base))
        menu.popup(card.mapToGlobal(point))

    def _reset_ratios(self) -> None:
        self.resetRequested.emit()
        self.close()
