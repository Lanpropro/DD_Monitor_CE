"""Frameless settings shell and its draggable, accessible window header."""
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractButton, QDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from . import theme
from .corner_geometry import continuous_path
from .settings_backdrop import apply_blur, apply_frame


class SettingsCloseButton(QAbstractButton):
    def __init__(self, parent):
        super().__init__(parent)
        self.setFixedSize(34, 34)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAccessibleName('关闭设置')
        self.setToolTip('关闭设置（修改自动保存）')
        self.setCursor(Qt.PointingHandCursor)
        self.setProperty('customControlSurface', True)

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        painter.setBrush(theme.qcolor(theme.CONTENT_HOVER if self.underMouse() or self.isDown() else theme.CONTENT))
        painter.setPen(QPen(theme.qcolor(theme.ACCENT if self.hasFocus() else theme.BORDER_STRONG), 1))
        painter.drawEllipse(rect)
        painter.setPen(QPen(theme.qcolor(theme.TEXT1), 1.6, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(12, 12, 22, 22)
        painter.drawLine(22, 12, 12, 22)


class SettingsTitleBar(QWidget):
    def __init__(self, window):
        super().__init__(window)
        self.setMinimumHeight(52)
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(20, 6, 16, 6)
        self.row.setSpacing(14)
        self.breadcrumb = QLabel('设置', self)
        self.breadcrumb.setObjectName('SettingsBreadcrumb')
        self.row.addWidget(self.breadcrumb)
        self.row.addStretch(1)
        self.close_button = SettingsCloseButton(self)
        self.close_button.clicked.connect(window.reject)
        self.row.addWidget(self.close_button)

    def set_search(self, search):
        search.setProperty('inSettingsHeader', True)
        search.setPlaceholderText('搜索设置')
        search.setMinimumWidth(120)
        search.setMaximumWidth(320)
        self.row.insertWidget(self.row.count() - 1, search, 1)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.window().windowHandle() is not None:
            if self.window().windowHandle().startSystemMove():
                event.accept()
                return
        super().mousePressEvent(event)


class SettingsWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent, Qt.Dialog | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setProperty('settingsGlassWindow', True)
        self.setProperty('appearanceLight', theme.is_light())
        self.setProperty('customControlSurface', True)
        self._native_corners = False
        self._native_glass = False
        from .settings_focus import SettingsInputFocus
        self.input_focus = SettingsInputFocus(self)
        self.window_header = SettingsTitleBar(self)
        self.body_layout = QHBoxLayout()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 8)
        outer.setSpacing(0)
        outer.addWidget(self.window_header)
        outer.addLayout(self.body_layout, 1)
        theme.signals().changed.connect(self._sync_frame)

    def _sync_frame(self):
        if self.isVisible():
            self._native_corners = apply_frame(self, theme.is_light())
            self._native_glass = apply_blur(self, self.property('settings_glass_enabled'))
        self.update()

    def set_material(self, values):
        from .settings_material import apply_properties
        previous = self.property('settings_card_layout')
        if apply_properties(self, values):
            if previous is not None and previous != self.property('settings_card_layout') and not self.isMaximized():
                if self.property('settings_card_layout') == 'vertical':
                    self._layout_restore_width = self.width()
                    self.resize(min(self.width(), 1040), self.height())
                elif getattr(self, '_layout_restore_width', None) is not None:
                    self.resize(min(self._layout_restore_width, self.screen().availableGeometry().width() - 48), self.height())
                    self._layout_restore_width = None
            self._sync_frame()

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_frame()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.windowHandle() is not None:
            point = event.position()
            edges = Qt.Edge(0)
            if point.x() < 8:
                edges |= Qt.LeftEdge
            if point.x() >= self.width() - 8:
                edges |= Qt.RightEdge
            if point.y() < 8:
                edges |= Qt.TopEdge
            if point.y() >= self.height() - 8:
                edges |= Qt.BottomEdge
            if edges and self.windowHandle().startSystemResize(edges):
                event.accept()
                return
        super().mousePressEvent(event)

    def paintEvent(self, event):
        from .skin_parts import resolve_values, values_for
        preview = getattr(self, '_settings_material_preview', None)
        values = resolve_values('settings', preview[1], preview[0]) if preview is not None else values_for('settings')
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        rect = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        if self._native_corners:
            # DWM clips the whole window; another client curve exposes its backing.
            path = QPainterPath()
            path.addRect(QRectF(self.rect()))
        else:
            path = continuous_path(rect, 22)
        painter.setClipPath(path)
        from .settings_material import base_color
        color = theme.qcolor(values.get('background', base_color(self, 'background', theme.BG)))
        from .settings_material_paint import glass_tint
        color = glass_tint(self, values.get('background')) if self._native_glass else color
        if not self._native_glass:
            color.setAlpha(255)
        painter.fillPath(path, color)
        if not self._native_corners:
            painter.setPen(QPen(theme.qcolor(theme.BORDER_STRONG), 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)
