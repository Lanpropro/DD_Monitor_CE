"""Built-in playback context menu choices, ordering and settings editor."""
from PySide6.QtCore import QEvent, QPointF, QRect, QRectF, QTimer, Qt, Signal
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QBoxLayout, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from . import motion, theme
from .row_motion import glide_to, advance_row_animations
from .corner_geometry import continuous_path

from .ui import ActionButton, ToggleSwitch


MENU_ITEMS = (
    ('volume', '音量'), ('quality', '画质'), ('live_catchup', '自动追帧'),
    ('codec', '当前窗口编解码设置'),
    ('stream_info', '直播流信息'), ('audio_channel', '声道'), ('mute', '静音／取消静音'),
    ('danmaku_settings', '弹幕观看设置'), ('danmaku_float', '打开弹幕浮窗'),
    ('reload', '刷新重连'), ('fullscreen', '全屏查看'),
    ('plugins', '插件扩展功能'), ('switch_danmaku', '切换为弹幕'), ('close', '关闭这一路'),
)


MENU_GROUPS = {'volume': 0, 'quality': 1, 'live_catchup': 1, 'codec': 1, 'stream_info': 1, 'audio_channel': 1,
               'mute': 2, 'danmaku_settings': 2, 'danmaku_float': 2, 'reload': 2, 'fullscreen': 2,
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
    """Editable rows with reversible drag feedback; values change only on release."""
    orderChanged = Signal(str, str)
    selectedChanged = Signal(str)
    enabledChanged = Signal(str, bool)

    def __init__(self, parent=None, *, items=MENU_ITEMS):
        super().__init__(parent)
        self.choices = []
        self.selected = ''
        self._labels = dict(items)
        self.checks = {}
        self.setMinimumWidth(200)
        self.setAccessibleName('右键菜单功能；拖动调整顺序，开关控制显示')
        self._init_drag()
        for key, label in items:
            check = ToggleSwitch(label, self)
            check.setToolTip('显示' + label)
            check.toggled.connect(lambda enabled, name=key: self.enabledChanged.emit(name, enabled))
            self.checks[key] = check

    def _init_drag(self):
        self._pressed = self._before = None
        self._dragging = False
        self._drag_order = None
        self._ghost = None
        self._positions = {}
        self._animations = {}
        self._animation_started = {}
        self._animation_clock = QTimer(self)
        self._animation_clock.setInterval(16)
        self._animation_clock.setTimerType(Qt.PreciseTimer)
        self._animation_clock.timeout.connect(self._advance_row_animations)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

    def _rects_for(self, keys):
        height = max(36, self.fontMetrics().height() + 16)
        return [(key, QRectF(0, index * height, self.width(), height)) for index, key in enumerate(keys)]

    def rows(self):
        return self._rects_for([entry['id'] for entry in self.choices])

    def _display_rows(self):
        return [(key, QRectF(self._positions[key].pos(), rect.size())) for key, rect in self.rows()]

    def _sync_positions(self):
        for key, rect in self.rows():
            if key not in self._positions:
                self._positions[key] = QWidget(self)
                self._positions[key].hide()
            glide_to(self, self._positions[key], round(rect.x()), round(rect.y()), False)
        self._position_switches()
        self.update()

    def set_choices(self, choices):
        self._cancel_drag()
        self.choices = choices
        for entry in self.choices:
            check = self.checks[entry['id']]
            check.blockSignals(True)
            check.setChecked(entry['enabled'])
            check.blockSignals(False)
        rows = self.rows()
        self.setFixedHeight(round(rows[-1][1].bottom()) if rows else 0)
        self._sync_positions()

    def _position_switches(self):
        for key, rect in self._display_rows():
            if key in self.checks:
                check = self.checks[key]
                check.move(self.width() - check.width() - 8,
                           round(rect.center().y() - check.height() / 2))
                check.setVisible(not (self._dragging and key == self._pressed))

    def _advance_row_animations(self, *, finish=False):
        advance_row_animations(self, finish=finish or not motion.enabled())
        self._position_switches()
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._dragging:
            self._cancel_drag()
        self._sync_positions()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.FontChange and self.choices:
            self.set_choices(self.choices)

    def _hit(self, position):
        return next((key for key, rect in self.rows() if rect.contains(position)), None)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            if any(check.isVisible() and check.geometry().contains(event.position().toPoint())
                   for check in self.checks.values()):
                return
            self.setFocus()
            self._pressed = self._hit(event.position())
            self._start = event.position()
            self._before = None
            if self._pressed:
                self.selected = self._pressed
                self.selectedChanged.emit(self._pressed)
                self.update()

    def _start_drag(self, position):
        rect = dict(self.rows())[self._pressed].toRect()
        snapshot = self.window().grab(QRect(self.mapTo(self.window(), rect.topLeft()), rect.size()))
        pixmap, hotspot = motion.lifted_drag(snapshot, self._start.toPoint() - rect.topLeft())
        self._ghost = QLabel(self.window())
        self._ghost.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._ghost.setPixmap(pixmap)
        self._ghost.resize(round(pixmap.width() / pixmap.devicePixelRatio()),
                           round(pixmap.height() / pixmap.devicePixelRatio()))
        self._ghost_hotspot = hotspot
        self._dragging = True
        self.grabMouse()
        self.setCursor(Qt.ClosedHandCursor)
        self._position_switches()
        self._ghost.show()
        self._ghost.raise_()
        self._move_ghost(position)

    def _move_ghost(self, position):
        self._ghost.move(self.mapTo(self.window(), position.toPoint()) - self._ghost_hotspot)

    def mouseMoveEvent(self, event):
        if self._pressed and (self._dragging or (event.position() - self._start).manhattanLength() >= 4):
            if not self._dragging:
                self._start_drag(event.position())
            self._move_ghost(event.position())
            remaining = [(key, rect) for key, rect in self.rows() if key != self._pressed]
            before = next((key for key, rect in remaining if event.position().y() < rect.center().y()), '')
            if before != self._before:
                self._before = before
                keys = [key for key, _rect in remaining]
                keys.insert(keys.index(before) if before else len(keys), self._pressed)
                self._drag_order = keys
                for key, rect in self._rects_for(keys):
                    if key != self._pressed:
                        glide_to(self, self._positions[key], round(rect.x()), round(rect.y()), motion.enabled())
                self._position_switches()
            self.update()
        else:
            key = self._hit(event.position())
            self.setCursor(Qt.OpenHandCursor if key else Qt.ArrowCursor)
            self.setToolTip(self._labels.get(key, ''))

    def _cancel_drag(self):
        self._pressed = self._before = None
        self._dragging = False
        self._drag_order = None
        if self._ghost is not None:
            self._ghost.hide()
            self._ghost.deleteLater()
            self._ghost = None
        if QWidget.mouseGrabber() is self:
            self.releaseMouse()
        for animation in self._animations.values():
            animation.stop()
            animation.deleteLater()
        self._animations.clear()
        self._animation_started.clear()
        self._animation_clock.stop()
        self.setCursor(Qt.ArrowCursor)
        self._sync_positions()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            key, before, order = self._pressed, self._before, self._drag_order
            original = [name for name, _rect in self.rows()]
            self._cancel_drag()
            if key and before is not None and order != original and self.rect().contains(event.position().toPoint()):
                self.orderChanged.emit(key, before)

    def event(self, event):
        if event.type() == QEvent.UngrabMouse and getattr(self, '_pressed', None):
            self._cancel_drag()
        return super().event(event)

    def hideEvent(self, event):
        self._cancel_drag()
        super().hideEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and self._pressed:
            self._cancel_drag()
            event.accept()
        elif not self._dragging and event.key() in (Qt.Key_Up, Qt.Key_Down):
            keys = [key for key, _rect in self.rows()]
            if keys:
                index = keys.index(self.selected) if self.selected in keys else 0
                index = max(0, min(len(keys) - 1, index + (-1 if event.key() == Qt.Key_Up else 1)))
                self.selectedChanged.emit(keys[index])
            event.accept()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        for key, rect in self._display_rows():
            if self._dragging and key == self._pressed:
                continue
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
            text = painter.fontMetrics().elidedText(self._labels[key], Qt.ElideRight, int(text_rect.width()))
            painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, text)


class MenuPreview(MenuOrderList):
    def __init__(self, parent=None):
        QWidget.__init__(self, parent)
        self.choices = []
        self.selected = ''
        self.checks = {}
        self._labels = dict(MENU_ITEMS)
        self._init_drag()
        self.setFixedWidth(280)
        self.setAccessibleName('画面右键菜单缩略图；拖动功能行调整顺序')

    def _rects_for(self, keys):
        rows = []
        y = 12
        previous = None
        for key in keys:
            group = MENU_GROUPS[key]
            if previous is not None and previous != group:
                y += 7
            height = max(27, self.fontMetrics().height() + 10)
            if key == 'volume':
                height += 18
            rows.append((key, QRectF(8, y, self.width()-16, height)))
            y += height
            previous = group
        return rows

    def rows(self):
        return self._rects_for([entry['id'] for entry in self.choices if entry['enabled']])

    def set_choices(self, choices):
        self._cancel_drag()
        self.choices = choices
        width = max(260, min(300, self.fontMetrics().horizontalAdvance('当前窗口编解码设置') + 70))
        self.setFixedWidth(width)
        rows = self.rows()
        self.setFixedHeight(max(120, int(rows[-1][1].bottom()+12) if rows else 120))
        self._sync_positions()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(theme.qcolor(theme.BORDER_STRONG), 1))
        painter.setBrush(theme.qcolor(theme.ELEVATED))
        painter.drawPath(continuous_path(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), theme.RADIUS_MD))
        rows = self._display_rows()
        if not rows:
            painter.setPen(theme.qcolor(theme.TEXT3))
            painter.drawText(self.rect(), Qt.AlignCenter, '开启要显示的功能')
        labels = dict(MENU_ITEMS)
        previous = None
        for key, rect in rows:
            if self._dragging and key == self._pressed:
                continue
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


class TileMenuEditor(QWidget):
    changed = Signal()
    layoutChanged = Signal()

    def __init__(self, choices=None, parent=None, *, items=MENU_ITEMS,
                 normalize=menu_choices, preview_factory=MenuPreview):
        super().__init__(parent)
        self._normalize = normalize
        self._labels = dict(items)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        hint = QLabel('拖动调整顺序，关闭开关可隐藏功能。')
        hint.setObjectName('SettingsHint')
        hint.setWordWrap(True)
        box.addWidget(hint)
        self.items = MenuOrderList(self, items=items)
        self.items.orderChanged.connect(self.move_before)
        self.items.selectedChanged.connect(self.select_item)
        self.items.enabledChanged.connect(self.set_enabled)
        self.checks = self.items.checks
        self.preview = preview_factory(self)
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
        widest = max(self.items.fontMetrics().horizontalAdvance(label) for label in self._labels.values())
        needed = self.preview.width() + max(240, widest + 90) + 16
        direction = QBoxLayout.LeftToRight if self.width() >= needed else QBoxLayout.TopToBottom
        if direction != self.columns.direction():
            self.columns.setDirection(direction)
            self.layout().invalidate()
            self.updateGeometry()
            self.layoutChanged.emit()

    def set_choices(self, choices):
        self._choices = self._normalize(choices)
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
