"""Built-in playback context menu choices, ordering and settings editor."""
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from . import theme
from .corner_geometry import continuous_path

from .ui import ActionButton


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


class MenuPreview(QWidget):
    orderChanged = Signal(str, str)
    selectedChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.choices = []
        self.selected = ''
        self._pressed = None
        self._before = None
        self.setMinimumWidth(200)
        self.setMinimumHeight(360)
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
            height = 40 if entry['id'] == 'volume' else 27
            rows.append((entry['id'], QRectF(8, y, self.width()-16, height)))
            y += height
            previous = group
        return rows

    def set_choices(self, choices):
        self.choices = menu_choices(choices)
        rows = self.rows()
        self.setMinimumHeight(max(120, int(rows[-1][1].bottom()+12) if rows else 120))
        self.update()

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
            painter.drawText(self.rect(), Qt.AlignCenter, '右侧勾选要显示的功能')
        labels = dict(MENU_ITEMS)
        font = painter.font()
        font.setPixelSize(12)
        painter.setFont(font)
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
            painter.setPen(theme.qcolor(theme.TEXT3))
            for offset in (-2, 2):
                painter.drawLine(QPointF(14, rect.center().y()+offset), QPointF(19, rect.center().y()+offset))
            painter.setPen(theme.qcolor(theme.TEXT1))
            label = '音量 40' if key == 'volume' else labels[key]
            if key == 'plugins':
                label = '插件扩展功能…'
            text_rect = rect.adjusted(18, 0, -18, 0)
            if key == 'volume':
                text_rect.setHeight(22)
            text = painter.fontMetrics().elidedText(label, Qt.ElideRight, int(text_rect.width()))
            painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, text)
            if key == 'volume':
                y = rect.bottom()-8
                painter.setPen(QPen(theme.qcolor(theme.BORDER_STRONG), 3))
                painter.drawLine(QPointF(29, y), QPointF(self.width()-25, y))
                painter.setPen(QPen(theme.qcolor(theme.ACCENT), 3))
                painter.drawLine(QPointF(29, y), QPointF(self.width()*.45, y))
            elif key in ('quality', 'audio_channel'):
                painter.drawText(rect.adjusted(0, 0, -6, 0), Qt.AlignRight | Qt.AlignVCenter, '›')
            previous = group
        if self._before is not None and self._pressed:
            y = next((rect.top() for key, rect in rows if key == self._before), rows[-1][1].bottom())
            painter.setPen(QPen(theme.qcolor(theme.ACCENT), 2))
            painter.drawLine(QPointF(8, y), QPointF(self.width()-8, y))


class TileMenuEditor(QWidget):
    def __init__(self, choices=None, parent=None):
        super().__init__(parent)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        columns = QHBoxLayout()
        columns.setSpacing(16)
        left = QVBoxLayout()
        left.addWidget(QLabel('菜单预览 · 拖动排序'))
        self.preview = MenuPreview(self)
        self.preview.orderChanged.connect(self.move_before)
        self.preview.selectedChanged.connect(self.select_item)
        left.addWidget(self.preview)
        left.addStretch(1)
        columns.addLayout(left, 1)
        right = QVBoxLayout()
        right.addWidget(QLabel('显示的功能'))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setMinimumWidth(175)
        scroll.setMinimumHeight(330)
        options = QWidget()
        options.setObjectName('TileMenuOptions')
        options_box = QVBoxLayout(options)
        options_box.setContentsMargins(0, 0, 0, 0)
        options_box.setSpacing(8)
        self.checks = {}
        for key, label in MENU_ITEMS:
            check = QCheckBox(label)
            check.setToolTip(label)
            self.checks[key] = check
            check.toggled.connect(lambda enabled, name=key: self.set_enabled(name, enabled))
            options_box.addWidget(check)
        options_box.addStretch(1)
        scroll.setWidget(options)
        right.addWidget(scroll, 1)
        columns.addLayout(right, 1)
        box.addLayout(columns)
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
        self.ensurePolished()
        self.setMinimumHeight(box.minimumSize().height())

    def set_choices(self, choices):
        self._choices = menu_choices(choices)
        for entry in self._choices:
            check = self.checks[entry['id']]
            check.blockSignals(True)
            check.setChecked(entry['enabled'])
            check.blockSignals(False)
        self.preview.set_choices(self._choices)
        self.select_item(next((entry['id'] for entry in self._choices if entry['enabled']), ''))

    def select_item(self, key):
        self.preview.selected = key
        self.preview.update()
        for name, check in self.checks.items():
            check.setProperty('menuSelected', name == key)
            check.style().unpolish(check)
            check.style().polish(check)

    def set_enabled(self, key, enabled):
        for entry in self._choices:
            if entry['id'] == key:
                entry['enabled'] = enabled
        self.preview.set_choices(self._choices)

    def move_before(self, key, before):
        entry = next(entry for entry in self._choices if entry['id'] == key)
        self._choices.remove(entry)
        index = next((i for i, other in enumerate(self._choices) if other['id'] == before), len(self._choices))
        self._choices.insert(index, entry)
        self.preview.set_choices(self._choices)
        self.select_item(key)

    def move_item(self, delta):
        visible = [key for key, _rect in self.preview.rows()]
        if self.preview.selected in visible:
            index = visible.index(self.preview.selected)
            target = index+delta
            if 0 <= target < len(visible):
                self.move_before(visible[index], visible[target] if delta < 0 else (
                    visible[target+1] if target+1 < len(visible) else ''))

    def values(self):
        return [dict(entry) for entry in self._choices]
