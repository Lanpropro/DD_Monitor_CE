"""Compact RGB picker using the application's shared settings controls."""
import re

from PySide6.QtCore import QPointF, QRectF, Qt, Signal, QVariantAnimation
from PySide6.QtGui import QColor, QConicalGradient, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractButton, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSlider, QSpinBox, QVBoxLayout, QWidget

from .. import motion, theme
from ..motion import AnimatedDialog
from .basics import ActionButton, page_header


class _ColorSwatch(QAbstractButton):
    def __init__(self, color, label, parent):
        super().__init__(parent)
        self.color = color
        self.pointer = False
        self._keyboard_focus = False
        self.setFixedSize(26, 30)
        self.setCheckable(True)
        self.setAccessibleName(label)
        self.setToolTip(label)
        self.setCursor(Qt.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        self.pointer = event.button() == Qt.LeftButton
        super().mouseReleaseEvent(event)
        self.pointer = False

    def focusInEvent(self, event):
        self._keyboard_focus = event.reason() in (Qt.TabFocusReason, Qt.BacktabFocusReason)
        super().focusInEvent(event)

    def mousePressEvent(self, event):
        self._keyboard_focus = False
        super().mousePressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        center = QRectF(self.rect()).center()
        color = self.color() if callable(self.color) else self.color
        if color is None:
            color = QConicalGradient(center, 30)
            for index, shade in enumerate(('#ff657e', '#c084fc', '#68b9ff', '#63e6ae', '#ffe079', '#ff657e')):
                color.setColorAt(index / 5, QColor(shade))
        else:
            color = theme.qcolor(color)
            if self.underMouse():
                color = color.lighter(110)
        painter.setOpacity(1 if self.isEnabled() else .5)
        painter.setPen(QPen(QColor(64, 64, 64, 90), 1))
        painter.setBrush(color)
        radius = 10 if self.isDown() else 11
        painter.drawEllipse(center, radius, radius)
        if self.hasFocus() and self._keyboard_focus and not self.isChecked():
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(self.palette().text().color(), 1.4))
            painter.drawEllipse(center, 12., 12.)


class _ColorRing(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.offset = 0.
        self.hide()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(25, 27, 32, 140), 3))
        center = QPointF(self.offset, self.height() / 2)
        painter.drawEllipse(center, 13., 13.)
        painter.setPen(QPen(QColor('#ffffff'), 1.7))
        painter.drawEllipse(center, 13., 13.)


class ColorPalette(QWidget):
    selected = Signal(str, bool)

    def __init__(self, entries, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(1, 0, 1, 0)
        row.setSpacing(5)
        self.buttons = {}
        for key, label, color in entries:
            button = _ColorSwatch(color, label, self)
            self.buttons[key] = button
            button.clicked.connect(lambda _checked=False, value=key, swatch=button: self._select(value, swatch))
            row.addWidget(button)
        self.ring = _ColorRing(self)
        self.current = None
        self._slide = QVariantAnimation(self, duration=150)
        self._slide.setEasingCurve(motion.THEME_WAVE_EASING)
        self._slide.valueChanged.connect(self._move_ring)
        theme.signals().changed.connect(self._refresh)

    def _select(self, key, button):
        button.setChecked(key == self.current)
        self.selected.emit(key, button.pointer)

    def _refresh(self, *_args):
        for button in self.buttons.values():
            button.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.layout().activate()
        self.ring.setGeometry(self.rect())
        self.finish_indicator()

    def finish_indicator(self):
        self._slide.stop()
        if self.current in self.buttons:
            self._move_ring(self._center(self.current))

    def _center(self, key):
        rect = self.buttons[key].geometry()
        return rect.x() + rect.width() / 2

    def _move_ring(self, value):
        self.ring.offset = float(value)
        self.ring.update()

    def set_current(self, key, *, animate=False):
        if key == self.current:
            return
        self.current = key
        for value, button in self.buttons.items():
            button.setChecked(value == key)
        was_visible = not self.ring.isHidden()
        self.ring.setVisible(key in self.buttons)
        self._slide.stop()
        if key not in self.buttons:
            return
        self.ring.raise_()
        target = float(self._center(key))
        if animate and was_visible and self.isVisible() and motion.enabled():
            self._slide.setStartValue(self.ring.offset)
            self._slide.setEndValue(target)
            self._slide.start()
        else:
            self._move_ring(target)


class _ColorField(QWidget):
    picked = Signal(float, float)

    def __init__(self, parent):
        super().__init__(parent)
        self.hue, self.saturation, self.value = 0., 0., 1.
        self.setMinimumHeight(124)
        self.setAccessibleName('饱和度与亮度')
        self.setCursor(Qt.CrossCursor)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect())
        clip = QPainterPath()
        clip.addRoundedRect(rect, 12, 12)
        painter.setClipPath(clip)
        saturation = QLinearGradient(rect.topLeft(), rect.topRight())
        saturation.setColorAt(0, QColor('#ffffff'))
        saturation.setColorAt(1, QColor.fromHsvF(self.hue, 1, 1))
        painter.fillRect(rect, saturation)
        value = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        value.setColorAt(0, QColor(0, 0, 0, 0))
        value.setColorAt(1, QColor('#000000'))
        painter.fillRect(rect, value)
        center = QPointF(self.saturation * rect.width(), (1 - self.value) * rect.height())
        painter.setBrush(Qt.NoBrush)
        for color, width in (('#222222', 4), ('#ffffff', 2)):
            painter.setPen(QPen(QColor(color), width))
            painter.drawEllipse(center, 6, 6)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._pick(event.position())

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self._pick(event.position())

    def _pick(self, point):
        self.picked.emit(min(1., max(0., point.x() / self.width())),
                         1 - min(1., max(0., point.y() / self.height())))


class _ColorPreview(QLabel):
    def __init__(self, parent):
        super().__init__('这是一条弹幕预览', parent)
        self.setProperty('customControlSurface', True)
        self.setMinimumHeight(68)
        self.color = QColor('#ffffff')

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        painter.setBrush(theme.qcolor(theme.BASE))
        painter.setPen(QPen(theme.qcolor(theme.BORDER), 1))
        painter.drawRoundedRect(rect, 12, 12)
        font = painter.font()
        font.setPixelSize(26)
        painter.setFont(font)
        painter.setPen(self.color)
        painter.drawText(rect, Qt.AlignCenter, self.text())


class ColorDialog(AnimatedDialog):
    colorSelected = Signal(QColor)

    def __init__(self, color, parent=None, *, title='弹幕颜色', presets=True):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setFixedWidth(440)
        self._color = QColor(color)
        self._hue = max(0., self._color.hsvHueF())
        self._custom = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)
        layout.addLayout(page_header(title, '选择预设色，或打开 RGB 色板自定义。' if presets else '调整 RGB 或输入 HEX 色值，确认后应用。'))
        self.preview = _ColorPreview(self)
        if presets:
            layout.addWidget(self.preview)
            self.swatch_palette = ColorPalette((
                ('#ffffff', '白色', '#ffffff'), ('#ffd16a', '黄色', '#ffd16a'), ('#8de89b', '绿色', '#8de89b'),
                ('#72d8f7', '蓝色', '#72d8f7'), ('#c4a4ff', '紫色', '#c4a4ff'),
                ('#ff95b1', '粉色', '#ff95b1'), ('custom', '自定义 RGB 色板', None)), self)
            self.swatch_palette.selected.connect(self._choose_preset)
            layout.addWidget(self.swatch_palette, 0, Qt.AlignLeft)
        else:
            self.swatch_palette = None
            self.preview.hide()
        self.board = QWidget(self)
        board = QVBoxLayout(self.board)
        board.setContentsMargins(0, 0, 0, 0)
        board.setSpacing(9)
        self.field = _ColorField(self.board)
        self.field.picked.connect(self._pick_field)
        board.addWidget(self.field)
        self.hue = QSlider(Qt.Horizontal, self.board)
        self.hue.setAccessibleName('色相')
        self.hue.setCursor(Qt.PointingHandCursor)
        self.hue.setRange(0, 359)
        self.hue.setStyleSheet('QSlider::groove:horizontal, QSlider::sub-page:horizontal, QSlider::add-page:horizontal {'
                               'height: 8px; border-radius: 4px; background: qlineargradient(x1:0,y1:0,x2:1,y2:0,'
                               'stop:0 red,stop:0.167 yellow,stop:0.333 lime,stop:0.5 cyan,stop:0.667 blue,'
                               'stop:0.833 magenta,stop:1 red);}'
                               'QSlider::sub-page:horizontal, QSlider::add-page:horizontal {background: transparent;}')
        self.hue.valueChanged.connect(self._pick_hue)
        board.addWidget(self.hue)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(1, 1)
        self.sliders, self.channels = [], []
        for index, label in enumerate(('红 R', '绿 G', '蓝 B')):
            grid.addWidget(QLabel(label), index, 0)
            slider = QSlider(Qt.Horizontal, self.board)
            slider.setRange(0, 255)
            slider.setMinimumHeight(19)
            slider.setCursor(Qt.PointingHandCursor)
            slider.setAccessibleName(label)
            spin = QSpinBox(self)
            spin.setRange(0, 255)
            spin.setFixedWidth(80)
            spin.setAccessibleName(label + ' 数值')
            self.sliders.append(slider)
            self.channels.append(spin)
            for widget in (slider, spin):
                widget.valueChanged.connect(lambda value, i=index: self._set_channel(i, value))
            grid.addWidget(slider, index, 1)
            grid.addWidget(spin, index, 2)
        grid.addWidget(QLabel('HEX'), 3, 0)
        self.hex_edit = QLineEdit(self)
        self.hex_edit.setMaxLength(7)
        self.hex_edit.setPlaceholderText('#RRGGBB')
        self.hex_edit.setAccessibleName('HEX 色值')
        self.hex_edit.textChanged.connect(self._edit_hex)
        grid.addWidget(self.hex_edit, 3, 1, 1, 2)
        board.addLayout(grid)
        layout.addWidget(self.board)
        self.hint = QLabel(self)
        self.hint.setObjectName('SettingsHint')
        self.hint.setMinimumHeight(18)
        layout.addWidget(self.hint)
        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = ActionButton('取消', self)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        self.confirm = QPushButton('确定', self)
        self.confirm.setObjectName('PrimaryButton')
        self.confirm.setDefault(True)
        self.confirm.clicked.connect(self.accept)
        buttons.addWidget(self.confirm)
        layout.addLayout(buttons)
        theme.signals().changed.connect(self._refresh_preview)
        self.setCurrentColor(self._color)
        if self.swatch_palette and self._color.name() in self.swatch_palette.buttons:
            self.board.hide()
        else:
            self._custom = True

    def _choose_preset(self, key, _pointer):
        self._custom = key == 'custom'
        if self._custom:
            self.board.show()
            self.swatch_palette.set_current(key)
        else:
            self.setCurrentColor(QColor(key))
            self.board.hide()
        self.adjustSize()

    def _pick_field(self, saturation, value):
        self.setCurrentColor(QColor.fromHsvF(self._hue, saturation, value))

    def _pick_hue(self, value):
        self._hue = value / 360
        self._pick_field(self._color.hsvSaturationF(), self._color.valueF())

    def _set_channel(self, index, value):
        channels = list(self._color.getRgb()[:3])
        channels[index] = value
        self.setCurrentColor(QColor(*channels))

    def _edit_hex(self, text):
        valid = re.fullmatch(r'#?[0-9a-fA-F]{6}', text) is not None
        self.confirm.setEnabled(valid)
        self.hint.setText('' if valid else '请输入 6 位十六进制颜色，例如 #FFFFFF')
        if valid:
            self.setCurrentColor(QColor('#' + text.lstrip('#')))

    def setCurrentColor(self, color):
        self._color = QColor(color)
        hue = self._color.hsvHueF()
        if hue >= 0:
            self._hue = hue
        self.field.hue, self.field.saturation, self.field.value = (
            self._hue, self._color.hsvSaturationF(), self._color.valueF())
        self.field.update()
        previous = self.hue.blockSignals(True)
        self.hue.setValue(min(359, round(self._hue * 360)))
        self.hue.blockSignals(previous)
        if self.swatch_palette:
            name = self._color.name()
            self.swatch_palette.set_current(name if not self._custom and name in self.swatch_palette.buttons else 'custom')
        for index, value in enumerate(self._color.getRgb()[:3]):
            for widget in (self.sliders[index], self.channels[index]):
                widget.blockSignals(True)
                widget.setValue(value)
                widget.blockSignals(False)
        self.hex_edit.blockSignals(True)
        self.hex_edit.setText(self._color.name().upper())
        self.hex_edit.blockSignals(False)
        self.confirm.setEnabled(True)
        self.hint.clear()
        self._refresh_preview()

    def _refresh_preview(self):
        self.preview.color = self._color
        self.preview.update()

    def currentColor(self):
        return QColor(self._color)

    def accept(self):
        if self.confirm.isEnabled():
            self.colorSelected.emit(self.currentColor())
            super().accept()
