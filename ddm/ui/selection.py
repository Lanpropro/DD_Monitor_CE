"""Shared painted selection controls; Qt owns input, focus and checked state."""
import math

from PySide6.QtCore import QElapsedTimer, QEvent, QObject, QPointF, QRectF, QSize, Qt, QTimer, Signal, QVariantAnimation
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
        self._pointer_focus = False
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

    def focusInEvent(self, event):
        self._pointer_focus = event.reason() == Qt.MouseFocusReason
        super().focusInEvent(event)

    def mousePressEvent(self, event):
        self._pointer_focus = True
        super().mousePressEvent(event)
        self.update()

    def keyPressEvent(self, event):
        self._pointer_focus = False
        super().keyPressEvent(event)
        self.update()

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
        if self.hasFocus() and not self._pointer_focus:
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


class SegmentMotion(QObject):
    """One moving selection indicator for button groups and native tabs."""

    RESPONSE_SECONDS = .5
    DAMPING_RATIO = .84

    def __init__(self, surface, items, selected, choose):
        super().__init__(surface)
        self.surface = surface
        self.items = items
        self.selected = selected
        self.choose = choose
        self.rect = QRectF()
        self._target = QRectF()
        self._velocity = (0., 0.)
        self._press = None
        self._dragging = False
        self._committing = False
        self._pointer_clock = QElapsedTimer()
        self._frame_clock = QElapsedTimer()
        self._timer = QTimer(self, interval=16, timerType=Qt.PreciseTimer)
        self._timer.timeout.connect(self._step)

    def watch(self, widget):
        widget.installEventFilter(self)

    def enabled(self):
        from ..settings_material import segment_motion_enabled
        return segment_motion_enabled(self.surface) and motion.enabled()

    def _draw(self, rect):
        self.rect = QRectF(rect)
        self.surface.update()
        for widget in self.surface.findChildren(QAbstractButton, options=Qt.FindDirectChildrenOnly):
            widget.update()

    def _selected_rect(self):
        return self.items().get(self.selected(), QRectF())

    def sync(self):
        if not self._committing and self._press is None and self._selected_rect() != self._target:
            self.finish()

    def committing(self):
        return self._committing

    def dragging(self):
        return self._press is not None and self._dragging

    def pressed_inside(self, rect):
        return self._press is not None and not self._dragging and rect.contains(self._press[1])

    def finish(self):
        self._press = None
        self._timer.stop()
        self._velocity = (0., 0.)
        self._target = self._selected_rect()
        self._draw(self._target)

    def _settle(self, target):
        if target.isEmpty() or not self.enabled() or not self.surface.isVisible():
            self.finish()
            return
        self._target = target
        if self.rect == target and not any(self._velocity):
            return
        if not self._timer.isActive():
            self._frame_clock.start()
            self._timer.start()

    def _step(self):
        if not self.enabled() or not self.surface.isVisible():
            self.finish()
            return
        elapsed = min(.08, self._frame_clock.restart() / 1000)
        count = max(1, math.ceil(elapsed * 120))
        dt = elapsed / count
        omega = 2 * math.pi / self.RESPONSE_SECONDS
        stiffness = omega * omega
        damping = 2 * self.DAMPING_RATIO * omega
        x, width = self.rect.x(), self.rect.width()
        vx, vw = self._velocity
        for _ in range(count):
            vx += (-damping * vx - stiffness * (x - self._target.x())) * dt
            vw += (-damping * vw - stiffness * (width - self._target.width())) * dt
            x += vx * dt
            width += vw * dt
        if (abs(x - self._target.x()) + abs(width - self._target.width()) < .08
                and abs(vx) + abs(vw) < .8):
            self.finish()
        else:
            self._velocity = (vx, vw)
            self._draw(QRectF(x, self._target.y(), width, self._target.height()))

    def paint(self, painter):
        if not self.rect.isEmpty():
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(Qt.NoPen)
            painter.setBrush(theme.qcolor(theme.ACCENT_SOFT))
            painter.drawRoundedRect(self.rect, self.rect.height() / 2, self.rect.height() / 2)

    def eventFilter(self, watched, event):
        kind = event.type()
        if (kind in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick) and event.button() == Qt.LeftButton
                and self.enabled() and watched.isEnabled()):
            point = self.surface.mapFromGlobal(event.globalPosition().toPoint())
            key = next((key for key, rect in self.items().items() if rect.contains(point)), None)
            if key is not None:
                if self.rect.isEmpty():
                    self.finish()
                self._timer.stop()
                self._press = (key, point, QRectF(self.rect))
                self._dragging = False
                self._last_drag_x = point.x()
                self._pointer_clock.start()
                watched.setFocus(Qt.MouseFocusReason)
                self.surface.update()
                return True
        if self._press is None:
            return False
        if not self.enabled():
            self.finish()
            return kind in (QEvent.MouseButtonRelease, QEvent.MouseMove)
        if kind == QEvent.MouseMove and event.buttons() & Qt.LeftButton:
            self._drag(self.surface.mapFromGlobal(event.globalPosition().toPoint()))
            return True
        if kind == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            point = self.surface.mapFromGlobal(event.globalPosition().toPoint())
            self._release(point)
            return True
        if kind in (QEvent.UngrabMouse, QEvent.WindowDeactivate, QEvent.Hide, QEvent.EnabledChange):
            self.finish()
        elif kind == QEvent.KeyPress and event.key() == Qt.Key_Escape:
            self._press = None
            self.surface.update()
            self._settle(self._selected_rect())
            return True
        return False

    def _drag(self, point):
        _key, origin, original_rect = self._press
        offset = point - origin
        if not self._dragging and (abs(offset.x()) < 4 or abs(offset.x()) <= abs(offset.y())):
            return
        self._dragging = True
        items = self.items()
        if not items:
            return
        rect = QRectF(original_rect)
        centers = [item.center().x() for item in items.values()]
        raw = rect.center().x() + offset.x()
        edge = min(max(raw, min(centers)), max(centers))
        rect.moveCenter(QPointF(edge + (raw - edge) * .2, rect.center().y()))
        dt = max(self._pointer_clock.restart() / 1000, .008)
        self._velocity = (max(-1400., min(1400., (rect.x() - self.rect.x()) / dt)), 0.)
        self._last_drag_x = point.x()
        self._draw(rect)

    def _release(self, point):
        key, _origin, _rect = self._press
        items = self.items()
        if self._dragging and items:
            if point.x() != self._last_drag_x:
                self._drag(point)
            elif self._pointer_clock.elapsed() > 80:
                self._velocity = (0., 0.)
            key = min(items, key=lambda item: abs(items[item].center().x() - self.rect.center().x()))
        elif key not in items or not items[key].contains(point):
            key = None
        self._press = None
        self.surface.update()
        if key is not None:
            self._committing = True
            try:
                self.choose(key)
            finally:
                self._committing = False
        self._settle(self._selected_rect())


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
        self.parentWidget().update(self.geometry())
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.parentWidget().update(self.geometry())
        super().leaveEvent(event)

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
        sliding = self.parentWidget().sliding_enabled()
        if self.isChecked() and not sliding:
            painter.setPen(Qt.NoPen)
            from ..settings_material import base_color, shadows_enabled
            for offset, alpha in (((2, 12), (1, 26)) if shadows_enabled(self) else ()):
                painter.setBrush(QColor(0, 0, 0, alpha))
                painter.drawRoundedRect(rect.translated(0, offset), rect.height() / 2, rect.height() / 2)
            color = theme.qcolor(theme.mix(base_color(self, 'card', theme.CONTENT), theme.ACCENT, .20))
            if self.isDown():
                color = color.darker(110)
            fill = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            fill.setColorAt(0, color.lighter(108))
            fill.setColorAt(1, color.darker(108))
            painter.setBrush(fill)
            painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
            edge = QLinearGradient(rect.topLeft(), rect.bottomLeft())
            edge.setColorAt(0, QColor(255, 255, 255, 28))
            edge.setColorAt(.5, QColor(255, 255, 255, 0))
            edge.setColorAt(1, QColor(0, 0, 0, 20 if shadows_enabled(self) else 0))
            painter.setPen(QPen(edge, 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        pressed = self.isDown() or self.parentWidget()._selection.pressed_inside(self.geometry())
        if self.isEnabled() and (pressed or (self.isChecked() and self.underMouse())):
            tint = theme.qcolor(theme.ACCENT)
            tint.setAlpha(90 if pressed else 42)
            painter.setPen(Qt.NoPen)
            painter.setBrush(tint)
            painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        if self.hasFocus() and not self._pointer_focus:
            painter.setPen(QPen(theme.qcolor(theme.ACCENT), 1.5))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        text = self.fontMetrics().elidedText(self.text(), Qt.ElideRight,
                                            max(0, self.width() - 2 * theme.SEGMENT_ITEM_PADDING))
        painter.setPen(theme.qcolor(theme.ACCENT if self.isChecked() and not sliding else theme.TEXT2))
        painter.drawText(rect, Qt.AlignCenter, text)
        if sliding:
            indicator = self.parentWidget()._selection.rect.translated(-self.x(), -self.y())
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
        for key, label in options:
            button = _SegmentButton(label, self)
            button.pressed.connect(self.update)
            button.released.connect(self.update)
            self.buttons[key] = button
            self.group.addButton(button)
            box.addWidget(button, 1)
        self._selection = SegmentMotion(self, self._segment_rects, self.value, self._choose)
        for button in self.buttons.values():
            self._selection.watch(button)
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
            self._selection.sync()
            self.valueChanged.emit(self.value())

    def sliding_enabled(self):
        from ..settings_material import segment_motion_enabled
        return segment_motion_enabled(self)

    def _segment_rects(self):
        return {key: QRectF(button.geometry()).adjusted(1, 1, -1, -2) for key, button in self.buttons.items()
                if not button.isHidden() and (button.isEnabled() or button.isChecked())}

    def _choose(self, key):
        self.buttons[key].click()

    def finish_indicator(self):
        self._selection.finish()

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
        self._selection.sync()

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
        # Keep hover underneath the moving indicator while child buttons paint their labels above it.
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.qcolor(theme.CONTENT_HOVER))
        for button in self.buttons.values():
            if button.isVisible() and not button.isChecked() and (button.underMouse() or button.isDown()):
                rect = QRectF(button.geometry()).adjusted(1, 1, -1, -2)
                painter.setOpacity(1. if button.isEnabled() else .45)
                painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        painter.setOpacity(1. if self.isEnabled() else .45)
        if self.sliding_enabled():
            from ..settings_material import shadows_enabled
            rect = self._selection.rect
            if rect.isEmpty():
                return
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
