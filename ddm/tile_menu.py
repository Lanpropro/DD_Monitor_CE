"""Built-in playback context menu choices, ordering and settings editor."""
from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QBoxLayout, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from . import theme
from .corner_geometry import continuous_path

from .ui import ActionButton, ToggleSwitch


MENU_ITEMS = (
    ('volume', '音量'), ('quality', '画质'), ('codec', '当前窗口编解码设置'),
    ('stream_info', '直播流信息'), ('audio_channel', '声道'), ('mute', '静音／取消静音'),
    ('danmaku_settings', '弹幕观看设置'), ('reload', '刷新重连'), ('fullscreen', '全屏查看'),
    ('plugins', '插件扩展功能'), ('switch_danmaku', '切换为弹幕'), ('close', '关闭这一路'),
)


MENU_GROUPS = {'volume': 0, 'quality': 1, 'codec': 1, 'stream_info': 1, 'audio_channel': 1,
               'mute': 2, 'danmaku_settings': 2, 'reload': 2, 'fullscreen': 2,
               'plugins': 3, 'switch_danmaku': 4, 'close': 4}

def menu_choices(value):
    choices = []
    known = dict(MENU_ITEMS)
    seen = set()
    for entry in value if isinstance(value, list) else ():
        if isinstance(entry, dict) and entry.get('id') in known and entry['id'] not in seen:
            seen.add(entry['id'])
            choices.append({'id': entry['id'], 'enabled': bool(entry.get('enabled', True))})
    choices.extend({'id': key, 'enabled': True} for key, _label in MENU_ITEMS if key not in seen)
    return choices


def arrange_menu(menu, choices):
    actions = [action for action in menu.actions() if not action.isSeparator()]
    for action in menu.actions():
        menu.removeAction(action)
    previous = None
    for entry in menu_choices(choices):
        if not entry['enabled']:
            continue
        selected = [action for action in actions if action.data() == entry['id']]
        if selected:
            group = MENU_GROUPS[entry['id']]
            if previous is not None and group != previous:
                menu.addSeparator()
            for action in selected:
                menu.addAction(action)
            previous = group


class MenuOrderList(QWidget):
    """Editable menu rows; all items remain available when hidden in playback."""
    orderChanged = Signal(str, str)
    selectedChanged = Signal(str)
    enabledChanged = Signal(str, bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.choices = []
        self.selected = ''
        self._pressed = self._before = None
        self.setMinimumWidth(200)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName('右键菜单功能；拖动调整顺序，开关控制显示')
        self.checks = {}
        for key, label in MENU_ITEMS:
            check = ToggleSwitch(label, self)
            check.setToolTip('显示' + label)
            check.toggled.connect(lambda enabled, name=key: self.enabledChanged.emit(name, enabled))
            self.checks[key] = check

    def rows(self):
        height = max(36, self.fontMetrics().height() + 16)
        return [(entry['id'], QRectF(0, index * height, self.width(), height))
                for index, entry in enumerate(self.choices)]

    def set_choices(self, choices):
        self.choices = choices
        for entry in self.choices:
            check = self.checks[entry['id']]
            check.blockSignals(True)
            check.setChecked(entry['enabled'])
            check.blockSignals(False)
        self.setFixedHeight(round(self.rows()[-1][1].bottom()))
        self._position_switches()
        self.update()

    def _position_switches(self):
        for key, rect in self.rows():
            check = self.checks[key]
            check.move(self.width() - check.width() - 8,
                       round(rect.center().y() - check.height() / 2))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_switches()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.FontChange and self.choices:
            self.setFixedHeight(round(self.rows()[-1][1].bottom()))
            self._position_switches()

    def _hit(self, position):
        return next((key for key, rect in self.rows() if rect.contains(position)), None)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.setFocus()
            self._pressed = self._hit(event.position())
            self._start = event.position()
            self._before = None
            if self._pressed:
                self.selectedChanged.emit(self._pressed)

    def mouseMoveEvent(self, event):
        if self._pressed and (event.position() - self._start).manhattanLength() >= 4:
            remaining = [(key, rect) for key, rect in self.rows() if key != self._pressed]
            self._before = next((key for key, rect in remaining
                                 if event.position().y() < rect.center().y()), '')
            self.update()
        else:
            key = self._hit(event.position())
            self.setCursor(Qt.OpenHandCursor if key else Qt.ArrowCursor)
            self.setToolTip(dict(MENU_ITEMS).get(key, ''))

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            key, before = self._pressed, self._before
            self._pressed = self._before = None
            if key and before is not None:
                self.orderChanged.emit(key, before)
            self.update()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Up, Qt.Key_Down):
            keys = [key for key, _rect in self.rows()]
            index = keys.index(self.selected) if self.selected in keys else 0
            index = max(0, min(len(keys) - 1, index + (-1 if event.key() == Qt.Key_Up else 1)))
            self.selectedChanged.emit(keys[index])
            event.accept()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        labels = dict(MENU_ITEMS)
        rows = self.rows()
        for key, rect in rows:
            if key == self.selected:
                painter.setPen(Qt.NoPen)
                painter.setBrush(theme.qcolor(theme.ACCENT_SOFT))
                painter.drawPath(continuous_path(rect.adjusted(0, 2, 0, -2), theme.RADIUS_SM))
            painter.setPen(QPen(theme.qcolor(theme.TEXT3), 1))
            for offset in (-2, 2):
                painter.drawLine(QPointF(8, rect.center().y() + offset),
                                 QPointF(15, rect.center().y() + offset))
            painter.setPen(theme.qcolor(theme.TEXT1 if self.checks[key].isChecked() else theme.TEXT3))
            text_rect = rect.adjusted(24, 0, -self.checks[key].width() - 20, 0)
            text = painter.fontMetrics().elidedText(labels[key], Qt.ElideRight, int(text_rect.width()))
            painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, text)
        if self._before is not None and self._pressed:
            y = next((rect.top() for key, rect in rows if key == self._before), rows[-1][1].bottom())
            painter.setPen(QPen(theme.qcolor(theme.ACCENT), 2))
            painter.drawLine(QPointF(0, y), QPointF(self.width(), y))


class MenuPreview(QWidget):
    orderChanged = Signal(str, str)
    selectedChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.choices = []
        self.selected = ''
        self._pressed = None
        self._before = None
        self.setFixedWidth(280)
        self.setMouseTracking(True)
        self.setAccessibleName('画面右键菜单缩略图；拖动功能行调整顺序')

    def rows(self):
        rows = []
        y = 12
        previous = None
        for entry in self.choices:
            if not entry['enabled']:
                continue
            group = MENU_GROUPS[entry['id']]
            if previous is not None and previous != group:
                y += 7
            height = max(27, self.fontMetrics().height() + 10)
            if entry['id'] == 'volume':
                height += 18
            rows.append((entry['id'], QRectF(8, y, self.width()-16, height)))
            y += height
            previous = group
        return rows

    def set_choices(self, choices):
        self.choices = choices
        width = max(260, min(300, self.fontMetrics().horizontalAdvance('当前窗口编解码设置') + 70))
        self.setFixedWidth(width)
        rows = self.rows()
        self.setFixedHeight(max(120, int(rows[-1][1].bottom()+12) if rows else 120))
        self.update()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.FontChange and self.choices:
            self.set_choices(self.choices)

    def _hit(self, position):
        return next((key for key, rect in self.rows() if rect.contains(position)), None)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._pressed = self._hit(event.position())
            self._start = event.position()
            self._before = None
            if self._pressed:
                self.selected = self._pressed
                self.selectedChanged.emit(self.selected)
                self.update()

    def mouseMoveEvent(self, event):
        if self._pressed and (event.position()-self._start).manhattanLength() >= 4:
            remaining = [(key, rect) for key, rect in self.rows() if key != self._pressed]
            self._before = next((key for key, rect in remaining if event.position().y() < rect.center().y()), '')
            self.update()
        else:
            self.setCursor(Qt.OpenHandCursor if self._hit(event.position()) else Qt.ArrowCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            key, before = self._pressed, self._before
            self._pressed = self._before = None
            if key and before is not None:
                self.orderChanged.emit(key, before)
            self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(theme.qcolor(theme.BORDER_STRONG), 1))
        painter.setBrush(theme.qcolor(theme.ELEVATED))
        painter.drawPath(continuous_path(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), theme.RADIUS_MD))
        rows = self.rows()
        if not rows:
            painter.setPen(theme.qcolor(theme.TEXT3))
            painter.drawText(self.rect(), Qt.AlignCenter, '开启要显示的功能')
        labels = dict(MENU_ITEMS)
        previous = None
        for key, rect in rows:
            group = MENU_GROUPS[key]
            if previous is not None and group != previous:
                painter.setPen(QPen(theme.qcolor(theme.BORDER_STRONG), 1))
                painter.drawLine(QPointF(14, rect.top()-4), QPointF(self.width()-14, rect.top()-4))
            if key == self.selected:
                painter.setPen(Qt.NoPen)
                painter.setBrush(theme.qcolor(theme.ACCENT_SOFT))
                painter.drawPath(continuous_path(rect, theme.RADIUS_SM))
            painter.setPen(theme.qcolor(theme.TEXT1))
            label = '音量 40' if key == 'volume' else labels[key]
            if key == 'plugins':
                label = '插件扩展功能…'
            text_rect = rect.adjusted(10, 0, -24, 0)
            if key == 'volume':
                text_rect.setHeight(rect.height() - 18)
            text = painter.fontMetrics().elidedText(label, Qt.ElideRight, int(text_rect.width()))
            painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, text)
            if key == 'volume':
                y = rect.bottom()-8
                painter.setPen(QPen(theme.qcolor(theme.BORDER_STRONG), 3))
                painter.drawLine(QPointF(29, y), QPointF(self.width()-25, y))
                painter.setPen(QPen(theme.qcolor(theme.ACCENT), 3))
                painter.drawLine(QPointF(29, y), QPointF(self.width()*.45, y))
            elif key in ('quality', 'audio_channel'):
                x, y = rect.right() - 10, rect.center().y()
                painter.setPen(QPen(theme.qcolor(theme.TEXT2), 1.5))
                painter.drawLine(QPointF(x - 3, y - 4), QPointF(x + 1, y))
                painter.drawLine(QPointF(x + 1, y), QPointF(x - 3, y + 4))
            previous = group
        if self._before is not None and self._pressed:
            y = next((rect.top() for key, rect in rows if key == self._before), rows[-1][1].bottom())
            painter.setPen(QPen(theme.qcolor(theme.ACCENT), 2))
            painter.drawLine(QPointF(8, y), QPointF(self.width()-8, y))


class TileMenuEditor(QWidget):
    changed = Signal()
    layoutChanged = Signal()

    def __init__(self, choices=None, parent=None):
        super().__init__(parent)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        hint = QLabel('拖动调整顺序，关闭开关可隐藏功能。')
        hint.setObjectName('SettingsHint')
        hint.setWordWrap(True)
        box.addWidget(hint)
        self.items = MenuOrderList(self)
        self.items.orderChanged.connect(self.move_before)
        self.items.selectedChanged.connect(self.select_item)
        self.items.enabledChanged.connect(self.set_enabled)
        self.checks = self.items.checks
        self.preview = MenuPreview(self)
        self.preview.orderChanged.connect(self.move_before)
        self.preview.selectedChanged.connect(self.select_item)
        self.columns = QBoxLayout(QBoxLayout.TopToBottom)
        self.columns.setSpacing(16)
        self.columns.addWidget(self.preview, 0, Qt.AlignLeft | Qt.AlignTop)
        self.columns.addWidget(self.items, 1, Qt.AlignTop)
        box.addLayout(self.columns)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        row = QHBoxLayout()
        for label, direction in (('上移', -1), ('下移', 1)):
            button = ActionButton(label)
            button.clicked.connect(lambda _checked=False, delta=direction: self.move_item(delta))
            row.addWidget(button)
        reset = ActionButton('恢复默认菜单')
        reset.clicked.connect(lambda: self.set_choices(None))
        row.addWidget(reset)
        row.addStretch(1)
        box.addLayout(row)
        self.set_choices(choices)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        needed = self.preview.width() + max(240, self.items.fontMetrics().horizontalAdvance('当前窗口编解码设置') + 90) + 16
        direction = QBoxLayout.LeftToRight if self.width() >= needed else QBoxLayout.TopToBottom
        if direction != self.columns.direction():
            self.columns.setDirection(direction)
            self.layout().invalidate()
            self.updateGeometry()
            self.layoutChanged.emit()

    def set_choices(self, choices):
        self._choices = menu_choices(choices)
        self.items.set_choices(self._choices)
        self.preview.set_choices(self._choices)
        self.select_item(self._choices[0]['id'])
        self.changed.emit()

    def select_item(self, key):
        self.items.selected = key
        self.items.update()
        self.preview.selected = key
        self.preview.update()

    def set_enabled(self, key, enabled):
        for entry in self._choices:
            if entry['id'] == key:
                entry['enabled'] = enabled
        self.items.set_choices(self._choices)
        self.preview.set_choices(self._choices)
        self.changed.emit()

    def move_before(self, key, before):
        entry = next(entry for entry in self._choices if entry['id'] == key)
        self._choices.remove(entry)
        index = next((i for i, other in enumerate(self._choices) if other['id'] == before), len(self._choices))
        self._choices.insert(index, entry)
        self.items.set_choices(self._choices)
        self.preview.set_choices(self._choices)
        self.select_item(key)
        self.changed.emit()

    def move_item(self, delta):
        keys = [entry['id'] for entry in self._choices]
        index = keys.index(self.items.selected)
        target = index + delta
        if 0 <= target < len(keys):
            self.move_before(keys[index], keys[target] if delta < 0 else (
                keys[target + 1] if target + 1 < len(keys) else ''))

    def values(self):
        return [dict(entry) for entry in self._choices]
