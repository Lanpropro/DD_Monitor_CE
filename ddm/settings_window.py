"""Frameless settings shell and its draggable, accessible window header."""
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractButton, QDialog, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from . import theme
from .corner_geometry import continuous_path
from .settings_backdrop import apply_backdrop
from .ui.settings_surface import _frosted_image


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
        self.setProperty('customControlSurface', True)
        self._native_glass = False
        self._native_corners = False
        self.window_header = SettingsTitleBar(self)
        self.body_layout = QHBoxLayout()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 8)
        outer.setSpacing(0)
        outer.addWidget(self.window_header)
        outer.addLayout(self.body_layout, 1)
        theme.signals().changed.connect(self._sync_backdrop)

    def _sync_backdrop(self):
        from .settings_material import properties
        if self.isVisible():
            self._native_glass = apply_backdrop(self, theme.is_light(), properties(self)['settings_glass_enabled'])
        self.update()

    def set_material(self, values):
        from .settings_material import apply_properties
        if apply_properties(self, values):
            self._sync_backdrop()

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_backdrop()

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
        from .settings_material import properties
        material = properties(self)
        glass = material['settings_glass_enabled']
        preview = getattr(self, '_settings_material_preview', None)
        values = resolve_values('settings', preview[1], preview[0]) if preview is not None else values_for('settings')
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        rect = QRectF(self.rect()).adjusted(.5, .5, -.5, -.5)
        if self._native_glass or self._native_corners:
            # DWM clips the whole material; another client curve exposes its backing.
            path = QPainterPath()
            path.addRect(QRectF(self.rect()))
        else:
            path = continuous_path(rect, 22)
        painter.setClipPath(path)
        image_path = values.get('image')
        image = None
        if image_path and glass:
            try:
                stat = Path(image_path).stat()
                image = _frosted_image(image_path, stat.st_mtime_ns, stat.st_size, material['settings_glass_blur'])
            except OSError:
                pass
        if image is not None:
            painter.drawPixmap(rect, image, QRectF(image.rect()))
        color = theme.qcolor(values.get('background', theme.BG))
        if not glass:
            color.setAlpha(255)
        elif 'background' not in values:
            color.setAlpha(round(material['settings_glass_opacity'] * 2.55)
                           if image is not None or self._native_glass else 248)
        painter.fillPath(path, color)
        sheen = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        sheen.setColorAt(0, QColor(255, 255, 255, 10 if theme.is_light() else 6))
        sheen.setColorAt(1, QColor(255, 255, 255, 0))
        painter.fillPath(path, sheen)
        if not (self._native_glass or self._native_corners):
            painter.setPen(QPen(theme.qcolor(theme.BORDER_STRONG), 1))
            painter.setBrush(Qt.NoBrush)
            painter.drawPath(path)
