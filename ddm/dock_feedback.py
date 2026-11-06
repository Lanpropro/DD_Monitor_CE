"""Dock icon feedback without moving buttons or changing their click targets."""
from PySide6.QtCore import QEvent, QObject, QRectF, Qt, QVariantAnimation
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QStyle, QStyleOptionToolButton, QToolButton

from . import motion, theme


# One-shot icon poses adapted from BewlyCat's favorites, home and edit motion.
# Each pose is (scale_x, scale_y, rotation, vertical_offset); hit targets stay fixed.
REST = (1.0, 1.0, 0.0, 0.0)
HOVER_POSES = {
    'follow': [(0, REST), (.3, (1.2, 1.2, 10, 0)), (.62, (.96, .96, -5, 0)), (1, REST)],
    'functions': [(0, REST), (1, (1, 1, 90, 0))],
    'appearance': [(0, REST), (1, (1, 1, 360, 0))],
    'notification': [(0, REST), (.22, (1, 1, -10, 0)), (.48, (1, 1, 8, 0)),
                     (.72, (1, 1, -4, 0)), (1, REST)],
    'pip': [(0, REST), (.4, (1.22, 1.22, 0, 0)), (.7, (.96, .96, 0, 0)), (1, REST)],
    'hop': [(0, REST), (.18, (1.06, .92, 0, 1.5)), (.48, (.96, 1.04, 0, -5)),
            (.68, (1.05, .95, 0, 1.5)), (.84, (.99, 1.01, 0, -1.5)), (1, REST)],
}
HOVER_POSES['settings'] = HOVER_POSES['notification']


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
        self.pose = REST
        self._poses = [(0, REST), (1, REST)]
        self.hover_animation = QVariantAnimation(self)
        self.hover_animation.setStartValue(0.0)
        self.hover_animation.setEndValue(1.0)
        self.hover_animation.valueChanged.connect(self._hover_frame)
        self.hover_animation.finished.connect(self._finish_hover)
        button.installEventFilter(self)

    def _hover_frame(self, progress):
        for (start, first), (end, last) in zip(self._poses, self._poses[1:]):
            if progress <= end:
                fraction = motion.THEME_WAVE_EASING.valueForProgress((progress-start)/(end-start))
                self.pose = tuple(a+(b-a)*fraction for a, b in zip(first, last))
                self.button.update()
                return

    def _finish_hover(self):
        # Full/quarter turns end at an equivalent orientation of their glyph.
        self.pose = REST
        self.button.update()

    def hover(self, *, entering=False, animate=True):
        self.hover_animation.stop()
        if not self.button.property('dockRail') or self.keyboard or not motion.enabled() or not animate:
            self._finish_hover()
            return
        kind = self.button.property('dockMotion') or getattr(self.button, 'kind', 'hop')
        frames = HOVER_POSES.get(kind, HOVER_POSES['hop']) if entering else [(0, REST), (1, REST)]
        self._poses = [(0, self.pose), *frames[1:]]
        if self.pose == REST and not entering:
            return
        self.hover_animation.setDuration(280 if entering else 160)
        self.hover_animation.start()

    def transform(self, painter):
        sx, sy, rotation, offset = self.pose
        painter.translate(0, offset)
        painter.rotate(rotation)
        painter.scale(self.scale*sx, self.scale*sy)

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
                self.hover(animate=False)
        elif kind == QEvent.FocusOut:
            self._keyboard_focus(False)
        elif kind == QEvent.MouseButtonPress:
            self._keyboard_focus(False)
            self.transition(.9, animate=False)
            self.hover()
        elif kind == QEvent.MouseButtonRelease:
            self.transition(1.1 if watched.underMouse() else 1.0)
        elif kind == QEvent.Enter:
            self.transition(1.1)
            self.hover(entering=True)
        elif kind == QEvent.Leave:
            self.transition(1.0)
            self.hover()
        elif kind == QEvent.KeyPress:
            self._keyboard_focus(True)
            self.transition(1.0, animate=False)
            self.hover(animate=False)
        elif kind == QEvent.Hide:
            self.transition(1.0, animate=False)
            self.hover(animate=False)
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
            width, height = size.width(), size.height()
            painter.translate(watched.width()/2, watched.height()/2)
            self.transform(painter)
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            painter.drawPixmap(QRectF(-width/2, -height/2, width, height),
                               tinted, QRectF(tinted.rect()))
            painter.end()
            return True
        return False


def attach(button):
    if not hasattr(button, '_dock_feedback'):
        button._dock_feedback = DockFeedback(button)
    return button._dock_feedback
