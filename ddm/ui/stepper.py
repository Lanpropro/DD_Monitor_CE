"""One compact surface around an existing Qt numeric editor and step buttons."""
from PySide6.QtCore import QEvent, QRectF, Qt
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QAbstractSpinBox, QHBoxLayout, QSizePolicy, QToolButton, QWidget

from .. import theme
from ..settings_material import base_color


class StepperControl(QWidget):
    def __init__(self, spin, parent=None):
        super().__init__(parent)
        self.setObjectName('CompactStepper')
        self.setProperty('customControlSurface', True)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.setFixedHeight(theme.CONTROL_HEIGHT)
        self.spin = spin
        spin.setObjectName('StepperValue')
        spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
        spin.setAlignment(Qt.AlignCenter)
        spin.installEventFilter(self)
        self.setFocusProxy(spin)
        box = QHBoxLayout(self)
        box.setContentsMargins(2, 2, 2, 2)
        box.setSpacing(0)
        self.minus, self.plus = QToolButton(), QToolButton()
        for button, text, label, action in (
                (self.minus, '−', '调小', spin.stepDown), (self.plus, '+', '调大', spin.stepUp)):
            button.setObjectName('StepperButton')
            button.setText(text)
            button.setAccessibleName(spin.accessibleName() + label)
            button.setToolTip(label)
            button.setCursor(Qt.PointingHandCursor)
            button.setAutoRepeat(True)
            button.setFixedSize(theme.CONTROL_HEIGHT - 4, theme.CONTROL_HEIGHT - 4)
            button.clicked.connect(action)
            button.installEventFilter(self)
        box.addWidget(self.minus)
        box.addWidget(spin, 1)
        box.addWidget(self.plus)
        self.setStyleSheet('''
            #CompactStepper QSpinBox#StepperValue, #CompactStepper QDoubleSpinBox#StepperValue,
            #CompactStepper QLineEdit {background: transparent; border: none; padding: 0; min-height: 0;}
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

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.FocusIn, QEvent.FocusOut):
            self.update()
        return False

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if not self.isEnabled():
            painter.setOpacity(.45)
        focused = self.spin.hasFocus() or self.minus.hasFocus() or self.plus.hasFocus()
        painter.setBrush(theme.qcolor(base_color(self, 'control', theme.CONTENT)))
        painter.setPen(QPen(theme.qcolor(theme.ACCENT), 1) if focused else Qt.NoPen)
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5),
                                theme.RADIUS_MD, theme.RADIUS_MD)
