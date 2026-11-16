"""Caption move/resize gestures and desktop-lyrics style quick actions."""
from dataclasses import replace
from PySide6.QtCore import QEvent, QObject, QPoint, QRect, Qt
from PySide6.QtGui import QColor, QPen
from PySide6.QtWidgets import QMenu
from .caption_geometry import caption_rect, edit_rect, placement_values


class CaptionInteraction(QObject):
    def __init__(self, caption):
        super().__init__(caption)
        self.caption = caption
        self.gesture = None
        self.hovered = False
        caption.setMouseTracking(True)
        caption.installEventFilter(self)

    def _resize_handle(self):
        return QRect(self.caption.width() - 18, self.caption.height() - 18, 18, 18)

    def apply(self, **values):
        caption = self.caption
        caption.set_caption(caption._original, caption._translated,
                            style=replace(caption._style, **values).as_dict(),
                            visible=caption._visible_requested)
        caption.styleChanged.emit(caption._style.as_dict())

    def menu(self):
        caption = self.caption
        menu = QMenu(caption)
        lock = menu.addAction('锁定位置')
        lock.setCheckable(True)
        lock.setChecked(caption._style.locked)
        lock.triggered.connect(lambda checked: self.apply(locked=checked))
        modes = menu.addMenu('显示内容')
        for title, mode in (('原文 + 译文', 'both'), ('仅原文', 'original'), ('仅译文', 'translation')):
            action = modes.addAction(title)
            action.setCheckable(True)
            action.setChecked(caption._style.mode == mode)
            action.triggered.connect(lambda checked=False, value=mode: self.apply(mode=value))
        menu.addAction('增大字号', lambda: self.apply(font_size=min(64, caption._style.font_size + 2)))
        menu.addAction('减小字号', lambda: self.apply(font_size=max(10, caption._style.font_size - 2)))
        menu.addAction('恢复位置与大小', lambda: self.apply(x=50, y=100, width=80, height=18))
        return menu

    def eventFilter(self, watched, event):
        caption = self.caption
        if caption._style.locked:
            self.gesture = None
            return False
        kind = event.type()
        if kind in (QEvent.Enter, QEvent.Leave):
            self.hovered = kind == QEvent.Enter
            caption.update()
        elif kind == QEvent.MouseButtonDblClick and event.button() == Qt.LeftButton:
            self.apply(x=50, y=100, width=80, height=18)
            return True
        elif kind == QEvent.MouseButtonPress:
            if event.button() == Qt.RightButton:
                menu = self.menu()
                menu.exec(event.globalPosition().toPoint())
                menu.deleteLater()
                return True
            if event.button() == Qt.LeftButton:
                area = caption._safe_rect()
                if area is None:
                    return False
                self.gesture = (event.globalPosition().toPoint(), area,
                                caption_rect(area, caption._style),
                                self._resize_handle().contains(event.position().toPoint()))
                return True
        elif kind == QEvent.MouseMove:
            if self.gesture is None:
                caption.setCursor(Qt.SizeFDiagCursor if self._resize_handle().contains(event.position().toPoint())
                                  else Qt.SizeAllCursor)
            else:
                point, area, start, resize = self.gesture
                rect = edit_rect(area, start, event.globalPosition().toPoint() - point, resize)
                caption._style = replace(caption._style, **placement_values(area, rect))
                caption.sync_geometry()
                caption.update()
            return self.gesture is not None
        elif kind == QEvent.MouseButtonRelease and self.gesture is not None:
            self.gesture = None
            caption.styleChanged.emit(caption._style.as_dict())
            return True
        return False

    def paint(self, painter):
        if self.caption._style.locked or not (self.hovered or self.gesture or self.caption._embedded):
            return
        painter.setPen(QPen(QColor('#A8C9EF'), 1, Qt.DashLine))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(self.caption.rect().adjusted(1, 1, -2, -2), 6, 6)
        corner = self.caption.rect().bottomRight() - QPoint(3, 3)
        painter.drawLine(corner - QPoint(9, 0), corner - QPoint(0, 9))
