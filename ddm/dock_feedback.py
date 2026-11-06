"""Dock icon feedback without moving buttons or changing their click targets."""
from PySide6.QtCore import QEvent, QObject, QRectF, Qt, QVariantAnimation
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QStyle, QStyleOptionToolButton, QToolButton

from . import motion, theme


def active(button):
    selected = button.property('dockActive')
    return button.isChecked() if selected is None else bool(selected)


def icon_color(button):
    if button.property('dockRail') and active(button):
        color = theme.qcolor('#ffffff' if theme.is_light() else theme.BG)
    else:
        color = theme.qcolor(theme.ACCENT if button.underMouse() else theme.TEXT2)
    if not button.isEnabled():
        color.setAlpha(90)
    return color


class DockFeedback(QObject):
    def __init__(self, button):
        super().__init__(button)
        self.button = button
        self.scale = 1.0
        self.keyboard = False
        self.animation = QVariantAnimation(self)
        self.animation.setDuration(160)
        self.animation.setEasingCurve(motion.THEME_WAVE_EASING)
        self.animation.valueChanged.connect(self._set_scale)
        button.installEventFilter(self)

    def _set_scale(self, value):
        self.scale = float(value)
        self.button.update()

    def transition(self, target, *, animate=True):
        target = float(target)
        self.animation.stop()
        if not self.button.property('dockRail') or self.keyboard or not motion.enabled():
            target, animate = 1.0, False
        if animate and self.button.isVisible() and self.scale != target:
            self.animation.setStartValue(self.scale)
            self.animation.setEndValue(target)
            self.animation.start()
        else:
            self._set_scale(target)

    def pulse(self):
        if not self.keyboard and motion.enabled():
            self._set_scale(.9)
            self.transition(1.1 if self.button.underMouse() else 1.0)

    def _keyboard_focus(self, enabled):
        self.keyboard = enabled
        if self.button.property('keyboardFocus') != enabled:
            self.button.setProperty('keyboardFocus', enabled)
        self.button.update()

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind == QEvent.FocusIn:
            self._keyboard_focus(event.reason() in (Qt.TabFocusReason, Qt.BacktabFocusReason, Qt.ShortcutFocusReason))
            if self.keyboard:
                self.transition(1.0, animate=False)
        elif kind == QEvent.FocusOut:
            self._keyboard_focus(False)
        elif kind == QEvent.MouseButtonPress:
            self._keyboard_focus(False)
            self.transition(.9, animate=False)
        elif kind == QEvent.MouseButtonRelease:
            self.transition(1.1 if watched.underMouse() else 1.0)
        elif kind == QEvent.Enter:
            self.transition(1.1)
        elif kind == QEvent.Leave:
            self.transition(1.0)
        elif kind == QEvent.KeyPress:
            self._keyboard_focus(True)
            self.transition(1.0, animate=False)
        elif kind == QEvent.Hide:
            self.transition(1.0, animate=False)
        elif kind == QEvent.Paint and isinstance(watched, QToolButton) and watched.property('dockRail'):
            option = QStyleOptionToolButton()
            watched.initStyleOption(option)
            option.icon = QIcon()
            option.text = ''
            option.state &= ~QStyle.State_HasFocus
            painter = QPainter(watched)
            watched.style().drawComplexControl(QStyle.CC_ToolButton, option, painter, watched)
            size = watched.iconSize()
            pixmap = watched.icon().pixmap(size, QIcon.Normal if watched.isEnabled() else QIcon.Disabled,
                                          QIcon.On if watched.isChecked() else QIcon.Off)
            tinted = QPixmap(pixmap.size())
            tinted.setDevicePixelRatio(pixmap.devicePixelRatioF())
            tinted.fill(Qt.transparent)
            tint = QPainter(tinted)
            tint.drawPixmap(0, 0, pixmap)
            tint.setCompositionMode(QPainter.CompositionMode_SourceIn)
            tint.fillRect(tinted.rect(), icon_color(watched))
            tint.end()
            width, height = size.width()*self.scale, size.height()*self.scale
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            painter.drawPixmap(QRectF((watched.width()-width)/2, (watched.height()-height)/2, width, height),
                               tinted, QRectF(tinted.rect()))
            painter.end()
            return True
        return False


def attach(button):
    if not hasattr(button, '_dock_feedback'):
        button._dock_feedback = DockFeedback(button)
    return button._dock_feedback
