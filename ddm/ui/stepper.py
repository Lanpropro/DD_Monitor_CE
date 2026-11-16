"""One compact surface around an existing Qt numeric editor and step buttons."""
from PySide6.QtCore import QEvent, QRectF, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import QApplication, QAbstractSpinBox, QHBoxLayout, QSizePolicy, QToolButton, QWidget

from .. import motion, theme
from ..settings_material import base_color, shadows_enabled


class StepperControl(QWidget):
    def __init__(self, spin, parent=None):
        super().__init__(parent)
        self.setObjectName('CompactStepper')
        self.setProperty('customControlSurface', True)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.setFixedHeight(theme.CONTROL_HEIGHT + 4)
        self.setFixedWidth(theme.SETTINGS_STEPPER_WIDTH)
        self._hover = 0.
        self._hover_animation = QVariantAnimation(self)
        self._hover_animation.setDuration(motion.CONTROL_FEEDBACK_MS)
        self._hover_animation.setEasingCurve(motion.THEME_WAVE_EASING)
        self._hover_animation.valueChanged.connect(self._set_hover)
        self.spin = spin
        spin.setObjectName('StepperValue')
        spin.setMinimumWidth(0)
        spin.setMaximumWidth(16777215)
        spin.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        spin.setAlignment(Qt.AlignCenter)
        spin.installEventFilter(self)
        spin.lineEdit().installEventFilter(self)
        spin.lineEdit().selectionChanged.connect(self._clear_inactive_selection)
        self.setFocusProxy(spin)
        box = QHBoxLayout(self)
        box.setContentsMargins(3, 1, 3, 5)
        box.setSpacing(0)
        self.minus, self.plus = QToolButton(), QToolButton()
        for button, text, label, action in (
                (self.minus, '−', '调小', self._step_down), (self.plus, '+', '调大', self._step_up)):
            button.setObjectName('StepperButton')
            button.setText(text)
            button.setAccessibleName(spin.accessibleName() + label)
            button.setToolTip(label)
            button.setCursor(Qt.PointingHandCursor)
            button.setFocusPolicy(Qt.NoFocus)
            button.setAutoRepeat(True)
            button.setFixedSize(theme.CONTROL_HEIGHT - 4, theme.CONTROL_HEIGHT - 4)
            button.clicked.connect(action)
            button.installEventFilter(self)
        box.addWidget(self.minus)
        box.addWidget(spin, 1)
        box.addWidget(self.plus)
        self.setStyleSheet('''
            #CompactStepper QSpinBox#StepperValue, #CompactStepper QDoubleSpinBox#StepperValue,
            #CompactStepper QLineEdit {background: transparent; border: none; padding: 0; min-height: 0;
                color: palette(window-text); font-weight: 700;}
            #CompactStepper QToolButton#StepperButton {background: transparent; border: none;
                border-radius: 6px; color: palette(text); padding: 0;}
            #CompactStepper QToolButton#StepperButton:hover {background: palette(midlight);}
            #CompactStepper QToolButton#StepperButton:pressed {background: palette(mid);}
            #CompactStepper QToolButton#StepperButton:disabled {color: palette(mid);}
        ''')
        spin.valueChanged.connect(self._sync_buttons)
        theme.signals().changed.connect(self.update)
        self._sync_buttons()

    def _sync_buttons(self):
        self.minus.setEnabled(self.spin.value() > self.spin.minimum())
        self.plus.setEnabled(self.spin.value() < self.spin.maximum())
        self._clear_inactive_selection()

    def _clear_inactive_selection(self):
        edit = self.spin.lineEdit()
        editing = self.spin.hasFocus() or edit.hasFocus()
        popup = QApplication.activePopupWidget()
        editing = editing or popup is not None and self.spin.isAncestorOf(popup)
        if edit.hasSelectedText() and (self.spin.isReadOnly() or not editing):
            edit.deselect()

    def _step_down(self):
        self.spin.clearFocus()
        self.spin.stepDown()
        self._clear_inactive_selection()

    def _step_up(self):
        self.spin.clearFocus()
        self.spin.stepUp()
        self._clear_inactive_selection()

    def _set_hover(self, value):
        self._hover = float(value)
        self.update()

    def _transition_hover(self, value):
        value = value if self.isEnabled() else 0.
        self._hover_animation.stop()
        if self.isVisible() and self.isEnabled() and motion.enabled():
            self._hover_animation.setStartValue(self._hover)
            self._hover_animation.setEndValue(float(value))
            self._hover_animation.start()
        else:
            self._set_hover(float(value))

    def enterEvent(self, event):
        self._transition_hover(1.)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._transition_hover(0.)
        super().leaveEvent(event)

    def hideEvent(self, event):
        self._hover_animation.stop()
        self._set_hover(0.)
        super().hideEvent(event)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.FocusIn, QEvent.FocusOut):
            if event.type() == QEvent.FocusOut and event.reason() != Qt.PopupFocusReason:
                self.spin.lineEdit().deselect()
            self.update()
        return False

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if not self.isEnabled():
            painter.setOpacity(.45)
        focused = self.spin.hasFocus() or self.spin.lineEdit().hasFocus()
        rect = QRectF(self.rect()).adjusted(2, 1, -2, -4)
        if shadows_enabled(self):
            painter.setPen(Qt.NoPen)
            for offset, alpha in ((3, 10), (2, 18), (1, 24)):
                painter.setBrush(QColor(0, 0, 0, alpha + round(6 * self._hover)))
                painter.drawRoundedRect(rect.translated(0, offset), theme.RADIUS_MD, theme.RADIUS_MD)
        color = theme.qcolor(base_color(self, 'control', theme.CONTENT)).lighter(100 + round(6 * self._hover))
        fill = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        fill.setColorAt(0, color.lighter(111))
        fill.setColorAt(1, color.darker(103))
        edge = QColor(0, 0, 0, 28) if theme.is_light() else QColor(255, 255, 255, 32)
        if focused:
            edge = theme.qcolor(theme.ACCENT)
        painter.setBrush(fill)
        painter.setPen(QPen(edge, 1))
        painter.drawRoundedRect(rect, theme.RADIUS_MD, theme.RADIUS_MD)
