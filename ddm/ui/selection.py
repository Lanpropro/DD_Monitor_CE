"""Shared painted selection controls; Qt owns input, focus and checked state."""
from PySide6.QtCore import QEvent, QRectF, QSize, Qt, Signal, QVariantAnimation
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractButton, QButtonGroup, QCheckBox, QHBoxLayout, QSizePolicy, QWidget

from .. import motion, theme


class ToggleSwitch(QCheckBox):
    def __init__(self, label='', parent=None):
        super().__init__(parent)
        self.setProperty('customControlSurface', True)
        self.setFixedSize(theme.SWITCH_WIDTH, theme.SWITCH_HEIGHT)
        self.setAccessibleName(label)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.PointingHandCursor)
        self._position = 0.
        self._pointer_toggle = False
        self._transition = QVariantAnimation(self)
        self._transition.setDuration(motion.SWITCH_TRANSITION_MS)
        self._transition.setEasingCurve(motion.SWITCH_TRANSITION_EASING)
        self._transition.valueChanged.connect(self._set_position)
        self.toggled.connect(self._retarget)
        theme.signals().changed.connect(self.update)

    def setChecked(self, checked):
        super().setChecked(checked)
        if self.signalsBlocked():
            # Loading a saved value suppresses business signals, not its paint state.
            self._retarget(self.isChecked())

    def _set_position(self, value):
        self._position = float(value)
        self.update()

    def _retarget(self, checked):
        self._transition.stop()
        target = float(checked)
        if self._pointer_toggle and self.isVisible() and motion.enabled():
            self._transition.setStartValue(self._position)
            self._transition.setEndValue(target)
            self._transition.start()
        else:
            self._set_position(target)

    def mouseReleaseEvent(self, event):
        self._pointer_toggle = event.button() == Qt.LeftButton
        try:
            super().mouseReleaseEvent(event)
        finally:
            self._pointer_toggle = False

    def hideEvent(self, event):
        self._transition.stop()
        self._set_position(float(self.isChecked()))
        super().hideEvent(event)

    def hitButton(self, position):
        return self.rect().contains(position)

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if not self.isEnabled():
            painter.setOpacity(0.45)
        if self.hasFocus():
            painter.setPen(QPen(theme.qcolor(theme.ACCENT), 1.5))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(.75, .75, -.75, -.75),
                                    self.height() / 2, self.height() / 2)
        track = QRectF(1, (self.height() - theme.SWITCH_TRACK_HEIGHT) / 2,
                       self.width() - 2, theme.SWITCH_TRACK_HEIGHT)
        from ..settings_material import base_color
        progress = max(0., min(1., self._position))
        off = theme.qcolor(base_color(self, 'control', theme.CONTENT_HOVER)).name()
        color = theme.qcolor(theme.mix(off, theme.ACCENT, progress))
        if self.isEnabled() and self.underMouse():
            color = color.darker(110) if self.isDown() else color.lighter(110)
        border = theme.qcolor(theme.BORDER_STRONG)
        accent = theme.qcolor(theme.ACCENT)
        painter.setPen(QPen(QColor.fromRgbF(*(a + (b - a) * progress
                          for a, b in zip(border.getRgbF(), accent.getRgbF()))), 1))
        painter.setBrush(color)
        painter.drawRoundedRect(track, track.height() / 2, track.height() / 2)
        inset = (track.height() - theme.SWITCH_THUMB_SIZE) / 2
        left = track.left() + inset + self._position * (track.width() - 2 * inset - theme.SWITCH_THUMB_SIZE)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(255, 255, 255))
        painter.drawEllipse(QRectF(left, track.top() + inset, theme.SWITCH_THUMB_SIZE, theme.SWITCH_THUMB_SIZE))


class _SegmentButton(QAbstractButton):
    def __init__(self, text, parent):
        super().__init__(parent)
        self.setText(text)
        self.setAccessibleName(text)
        self.setToolTip(text)
        self.setCheckable(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setProperty('customControlSurface', True)
        self._pointer_focus = False
        theme.signals().changed.connect(self.update)

    def sizeHint(self):
        return QSize(self.fontMetrics().horizontalAdvance(self.text()) + 2 * theme.SEGMENT_ITEM_PADDING,
                     max(theme.CONTROL_HEIGHT - 2 * theme.SEGMENT_PADDING, self.fontMetrics().height() + 4))

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        self.parentWidget()._pointer_selection = event.button() == Qt.LeftButton
        try:
            super().mouseReleaseEvent(event)
        finally:
            self.parentWidget()._pointer_selection = False

    def mousePressEvent(self, event):
        self._pointer_focus = True
        super().mousePressEvent(event)

    def focusInEvent(self, event):
        self._pointer_focus = event.reason() == Qt.MouseFocusReason
        super().focusInEvent(event)

    def keyPressEvent(self, event):
        self._pointer_focus = False
        super().keyPressEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if not self.isEnabled():
            painter.setOpacity(0.45)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -2)
        if (self.isChecked() and not self.parentWidget().sliding_enabled()) or (
                not self.isChecked() and (self.underMouse() or self.isDown())):
            painter.setPen(Qt.NoPen)
            if self.isChecked():
                from ..settings_material import shadows_enabled
                for offset, alpha in (((2, 12), (1, 26)) if shadows_enabled(self) else ()):
                    painter.setBrush(QColor(0, 0, 0, alpha))
                    painter.drawRoundedRect(rect.translated(0, offset), rect.height() / 2, rect.height() / 2)
                from ..settings_material import base_color
                color = theme.qcolor(theme.mix(base_color(self, 'card', theme.CONTENT), theme.ACCENT, .20))
                if self.isDown():
                    color = color.darker(110)
                fill = QLinearGradient(rect.topLeft(), rect.bottomLeft())
                fill.setColorAt(0, color.lighter(108))
                fill.setColorAt(1, color.darker(108))
                painter.setBrush(fill)
            else:
                painter.setBrush(theme.qcolor(theme.CONTENT_HOVER))
            painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
            if self.isChecked():
                edge = QLinearGradient(rect.topLeft(), rect.bottomLeft())
                edge.setColorAt(0, QColor(255, 255, 255, 28))
                edge.setColorAt(.5, QColor(255, 255, 255, 0))
                edge.setColorAt(1, QColor(0, 0, 0, 20 if shadows_enabled(self) else 0))
                painter.setPen(QPen(edge, 1))
                painter.setBrush(Qt.NoBrush)
                painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        if self.hasFocus() and not self._pointer_focus:
            painter.setPen(QPen(theme.qcolor(theme.ACCENT), 1.5))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        sliding = self.parentWidget().sliding_enabled()
        text = self.fontMetrics().elidedText(self.text(), Qt.ElideRight,
                                            max(0, self.width() - 2 * theme.SEGMENT_ITEM_PADDING))
        painter.setPen(theme.qcolor(theme.ACCENT if self.isChecked() and not sliding else theme.TEXT2))
        painter.drawText(rect, Qt.AlignCenter, text)
        if sliding:
            indicator = self.parentWidget()._indicator.translated(-self.x(), -self.y())
            clip = QPainterPath()
            clip.addRoundedRect(indicator, indicator.height() / 2, indicator.height() / 2)
            painter.setClipPath(clip)
            painter.setPen(theme.qcolor(theme.ACCENT))
            painter.drawText(rect, Qt.AlignCenter, text)


class SegmentedControl(QWidget):
    valueChanged = Signal(str)

    def __init__(self, options, value=None, parent=None):
        super().__init__(parent)
        self.setProperty('customControlSurface', True)
        self.setFixedHeight(theme.CONTROL_HEIGHT)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        box = QHBoxLayout(self)
        box.setContentsMargins(*([theme.SEGMENT_PADDING] * 4))
        box.setSpacing(theme.SEGMENT_GAP)
        self.group = QButtonGroup(self)
        self.buttons = {}
        self._pointer_selection = False
        self._indicator = QRectF()
        self._indicator_animation = QVariantAnimation(self)
        self._indicator_animation.setDuration(motion.SWITCH_TRANSITION_MS)
        self._indicator_animation.setEasingCurve(motion.THEME_WAVE_EASING)
        self._indicator_animation.valueChanged.connect(self._move_indicator)
        for key, label in options:
            button = _SegmentButton(label, self)
            self.buttons[key] = button
            self.group.addButton(button)
            box.addWidget(button, 1)
        self.setValue(value if value is not None else next(iter(self.buttons)))
        self.group.buttonToggled.connect(self._selection_changed)
        theme.signals().changed.connect(self.update)

    def sizeHint(self):
        width = max(button.sizeHint().width() for button in self.buttons.values()) * len(self.buttons)
        return QSize(width + 2 * theme.SEGMENT_PADDING + (len(self.buttons) - 1) * theme.SEGMENT_GAP,
                     max(theme.CONTROL_HEIGHT, self.fontMetrics().height() + 2 * theme.SEGMENT_PADDING + 4))

    def minimumSizeHint(self):
        return QSize(min(180, self.sizeHint().width()), theme.CONTROL_HEIGHT)

    def _selection_changed(self, button, checked):
        if checked:
            target = self._target_rect()
            self._indicator_animation.stop()
            if (self.sliding_enabled() and self._pointer_selection and self.isVisible()
                    and motion.enabled() and not self._indicator.isEmpty()):
                self._indicator_animation.setStartValue(self._indicator)
                self._indicator_animation.setEndValue(target)
                self._indicator_animation.start()
            else:
                self._move_indicator(target)
            self.valueChanged.emit(self.value())

    def sliding_enabled(self):
        return bool(self.window().property('settings_segment_motion'))

    def _target_rect(self):
        return QRectF(self.buttons[self.value()].geometry()).adjusted(1, 1, -1, -2)

    def _move_indicator(self, rect):
        self._indicator = QRectF(rect)
        self.update()
        for button in self.buttons.values():
            button.update()

    def finish_indicator(self):
        self._indicator_animation.stop()
        self._move_indicator(self._target_rect())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.layout().activate()
        self.finish_indicator()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.FontChange and hasattr(self, 'buttons'):
            self.setFixedHeight(self.sizeHint().height())

    def showEvent(self, event):
        super().showEvent(event)
        self.layout().activate()
        self.finish_indicator()

    def hideEvent(self, event):
        self.finish_indicator()
        super().hideEvent(event)

    def value(self):
        return next(key for key, button in self.buttons.items() if button.isChecked())

    def setValue(self, value):
        self.buttons[value].setChecked(True)
        if not self._pointer_selection:
            self.finish_indicator()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if not self.isEnabled():
            painter.setOpacity(0.45)
        rect = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        fill = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        from ..settings_material import base_color
        background = base_color(self, 'control', None)
        fill.setColorAt(0, theme.qcolor(background) if background else theme.qcolor(theme.BG).darker(112))
        fill.setColorAt(1, theme.qcolor(background or theme.BG))
        edge = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        edge.setColorAt(0, QColor(0, 0, 0, 45))
        edge.setColorAt(1, theme.qcolor(theme.BORDER))
        painter.setPen(QPen(edge, 1))
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        if self.sliding_enabled():
            from ..settings_material import shadows_enabled
            rect = self._indicator if not self._indicator.isEmpty() else self._target_rect()
            if shadows_enabled(self):
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(0, 0, 0, 28))
                painter.drawRoundedRect(rect.translated(0, 2), rect.height() / 2, rect.height() / 2)
            color = theme.qcolor(theme.mix(base_color(self, 'card', theme.CONTENT), theme.ACCENT, .20))
            fill = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            fill.setColorAt(0, color.lighter(108))
            fill.setColorAt(1, color.darker(108))
            painter.setBrush(fill)
            painter.setPen(QPen(QColor(255, 255, 255, 28), 1))
            painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
