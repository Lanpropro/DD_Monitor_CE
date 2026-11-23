"""Tab strip and pointer interaction shared by floating danmaku windows."""
from PySide6.QtCore import QEvent, QPoint, QSize, Qt
from PySide6.QtGui import QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QLabel, QSizePolicy, QTabBar, QToolButton
from shiboken6 import isValid

from . import theme
from .avatar_widgets import AVATAR_COLORS


class DanmakuFloatTabs(QTabBar):
    def __init__(self, window):
        super().__init__(window)
        self.floating = window
        self._press = None
        self._ghost = None
        self._target = None
        self._insertion = None
        self._sources = {}
        self.setAccessibleName('弹幕直播间标签')
        self.setFocusPolicy(Qt.StrongFocus)
        self.setIconSize(QSize(16, 16))
        self.setElideMode(Qt.ElideRight)
        self.setUsesScrollButtons(True)
        self.setExpanding(False)
        self.setDrawBase(False)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.refresh_theme()
        theme.signals().changed.connect(self.refresh_theme)

    def refresh_theme(self):
        self.setStyleSheet(f'''
            QTabBar::tab {{ color: {theme.TEXT2}; background: transparent; padding: 4px 6px;
                min-width: 35px; max-width: 112px; margin-right: 2px; border-radius: 6px;
                font-size: {theme.FONT_CAPTION}px; }}
            QTabBar::tab:hover {{ background: {theme.CONTENT_HOVER}; }}
            QTabBar::tab:selected {{ color: {theme.TEXT1}; background: {theme.ACCENT_SOFT}; }}
            QToolButton#DanmakuTabClose {{ color: {theme.TEXT2}; background: transparent; border: none;
                border-radius: 4px; padding: 0; font-size: 14px; }}
            QToolButton#DanmakuTabClose:hover {{ color: {theme.TEXT1}; background: {theme.CONTENT_HOVER}; }}
        ''')

    def panels(self):
        return [self.tabData(index) for index in range(self.count())]

    def refresh_close_button(self):
        for index in range(self.count()):
            button = self.tabButton(index, QTabBar.RightSide)
            if self.count() > 1 and index == self.currentIndex():
                if button is None:
                    button = QToolButton(self)
                    button.setObjectName('DanmakuTabClose')
                    button.setText('×')
                    button.setFixedSize(16, 16)
                    button.setToolTip('关闭当前标签')
                    button.setAccessibleName('关闭当前标签')
                    button.clicked.connect(lambda: self.tabCloseRequested.emit(self.currentIndex()))
                    self.setTabButton(index, QTabBar.RightSide, button)
            elif button is not None:
                self.setTabButton(index, QTabBar.RightSide, None)
                button.deleteLater()

    def refresh_source(self, panel):
        index = self.panels().index(panel)
        anchor = panel.source_picker.anchor
        room, name = anchor.identity or ('', '')
        name = name if room else '未关联'
        source = (room, name, anchor.face_key)
        if self._sources.get(panel) == source:
            return
        self._sources[panel] = source
        self.setTabText(index, name.replace('&', '&&'))
        self.setTabToolTip(index, name)
        if anchor.avatar is not None:
            icon = QIcon(anchor.avatar.pixmap())
        elif room:
            image = QPixmap(self.iconSize())
            image.fill(Qt.transparent)
            painter = QPainter(image)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(Qt.NoPen)
            painter.setBrush(theme.qcolor(AVATAR_COLORS[sum(map(ord, room)) % len(AVATAR_COLORS)]))
            painter.drawEllipse(image.rect())
            painter.setPen(Qt.white)
            painter.drawText(image.rect(), Qt.AlignCenter, name[0])
            painter.end()
            icon = QIcon(image)
        else:
            icon = QIcon()
        self.setTabIcon(index, icon)

    def tabRemoved(self, index):
        self._sources = {panel: self._sources[panel] for panel in self.panels() if panel in self._sources}
        super().tabRemoved(index)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            position = event.position().toPoint()
            index = self.tabAt(position)
            if index >= 0:
                self._press = (self.tabData(index), event.globalPosition().toPoint())
            else:
                self.floating.start_move()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._press is None or not event.buttons() & Qt.LeftButton:
            return super().mouseMoveEvent(event)
        panel, start = self._press
        point = event.globalPosition().toPoint()
        if self._ghost is None:
            if (point - start).manhattanLength() < QApplication.startDragDistance():
                return
            self._ghost = QLabel(self, Qt.ToolTip | Qt.WindowTransparentForInput | Qt.NoDropShadowWindowHint)
            self._ghost.setAttribute(Qt.WA_ShowWithoutActivating)
            rect = self.tabRect(self.panels().index(panel))
            self._ghost.setPixmap(self.grab(rect.intersected(self.rect())))
            self._ghost.setStyleSheet(f'background: {theme.ELEVATED}; border: 1px solid {theme.ACCENT};')
            self._ghost.adjustSize()
            self._ghost.move(point + QPoint(12, 12))
            self._ghost.show()
        else:
            self._ghost.move(point + QPoint(12, 12))
        self._show_destination(self.destination(point))
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton:
            return super().mouseReleaseEvent(event)
        if self._ghost is None:
            self._press = None
            return super().mouseReleaseEvent(event)
        panel, _ = self._press
        point = event.globalPosition().toPoint()
        destination = self.destination(point)
        self.cancel_drag()
        super().mouseReleaseEvent(event)
        if destination is not None:
            bar, index = destination
            self.floating.controller.move_floating_tab(panel, bar.floating, index)
        elif self.count() > 1 and not self.floating.frameGeometry().contains(point):
            self.floating.controller.split_floating_tab(panel, point)

    def destination(self, point):
        window = QApplication.topLevelAt(point)
        bar = getattr(window, 'tabs', None)
        if not isinstance(bar, DanmakuFloatTabs) or bar.floating.controller is not self.floating.controller:
            return None
        local = bar.mapFromGlobal(point)
        if not bar.rect().contains(local):
            return None
        index = next((i for i in range(bar.count()) if local.x() < bar.tabRect(i).center().x()), bar.count())
        return bar, index

    def _show_destination(self, destination):
        previous, self._target = self._target, destination[0] if destination is not None else None
        if previous is not None and isValid(previous) and previous is not self._target:
            previous._insertion = None
            previous.update()
        if destination is not None:
            bar, index = destination
            bar._insertion = index
            bar.update()

    def cancel_drag(self):
        self._press = None
        self._show_destination(None)
        if self._ghost is not None:
            self._ghost.hide()
            self._ghost.deleteLater()
            self._ghost = None

    def event(self, event):
        kind = event.type()
        if kind in (QEvent.Hide, QEvent.UngrabMouse, QEvent.WindowDeactivate) and self._press is not None:
            self.cancel_drag()
        if (kind in (QEvent.ShortcutOverride, QEvent.KeyPress) and self._press is not None
                and event.key() == Qt.Key_Escape):
            if kind == QEvent.KeyPress:
                self.cancel_drag()
            event.accept()
            return True
        return super().event(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        if self._insertion is None or not self.count():
            return
        index = self._insertion
        x = self.tabRect(index).left() if index < self.count() else self.tabRect(index-1).right() + 1
        x = min(self.width()-2, max(1, x))
        color = theme.qcolor(theme.ACCENT)
        shade = theme.qcolor(theme.ACCENT_SOFT)
        painter = QPainter(self)
        painter.fillRect(self.rect().adjusted(0, 1, 0, -1), shade)
        painter.setPen(QPen(color, 2))
        painter.drawLine(x, 3, x, self.height()-4)
