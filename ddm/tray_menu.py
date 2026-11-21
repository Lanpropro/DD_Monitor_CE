"""Tray menu choices and a media-free settings preview."""
from PySide6.QtCore import QEvent, QRectF, Qt, Signal
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QWidget

from . import theme
from .corner_geometry import continuous_path


TRAY_MENU_ITEMS = (
    ('layout_preview', '布局示意'), ('streamer_monitor', '主播监控'), ('toggle', '显示/隐藏窗口'),
    ('pip', '画中画'), ('exit', '退出'),
)


def tray_menu_choices(value):
    choices, seen = [], set()
    known = dict(TRAY_MENU_ITEMS)
    for entry in value if isinstance(value, list) else ():
        if isinstance(entry, dict) and entry.get('id') in known and entry['id'] not in seen:
            key = entry['id']
            seen.add(key)
            choices.append({'id': key, 'enabled': bool(entry.get('enabled', key != 'streamer_monitor'))})
    choices.extend({'id': key, 'enabled': True} for key, _label in TRAY_MENU_ITEMS
                   if key not in seen and key != 'streamer_monitor')
    if 'streamer_monitor' not in seen:
        layout_index = next(index for index, entry in enumerate(choices) if entry['id'] == 'layout_preview')
        choices.insert(layout_index + 1, {'id': 'streamer_monitor', 'enabled': False})
    return choices


class TrayMenuPreview(QWidget):
    orderChanged = Signal(str, str)
    selectedChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.selected = ''
        self.setFixedWidth(260)
        self.setAccessibleName('托盘菜单示意，点击选择功能')
        self.set_choices(tray_menu_choices(None))

    def rows(self):
        rows, y = [], 12
        for entry in self.choices:
            if not entry['enabled']:
                continue
            height = 112 if entry['id'] == 'layout_preview' else max(30, self.fontMetrics().height() + 10)
            rows.append((entry['id'], QRectF(8, y, self.width() - 16, height)))
            y += height + 4
        return rows

    def set_choices(self, choices):
        self.choices = choices
        rows = self.rows()
        self.setFixedHeight(max(100, int(rows[-1][1].bottom()) + 12 if rows else 100))
        self.update()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.FontChange and hasattr(self, 'choices'):
            self.set_choices(self.choices)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            key = next((key for key, rect in self.rows() if rect.contains(event.position())), '')
            if key:
                self.selected = key
                self.selectedChanged.emit(key)
                self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(theme.qcolor(theme.BORDER_STRONG), 1))
        painter.setBrush(theme.qcolor(theme.ELEVATED))
        painter.drawPath(continuous_path(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), theme.RADIUS_MD))
        rows = self.rows()
        if not rows:
            painter.setPen(theme.qcolor(theme.TEXT3))
            painter.drawText(self.rect(), Qt.AlignCenter, '开启要显示的功能')
        labels = dict(TRAY_MENU_ITEMS)
        for key, rect in rows:
            if key == self.selected:
                painter.fillPath(continuous_path(rect, theme.RADIUS_SM), theme.qcolor(theme.ACCENT_SOFT))
            if key == 'layout_preview':
                canvas = rect.adjusted(8, 7, -8, -7)
                for x, y, w, h, color, label in (
                        (0, 0, .65, 1, theme.ACCENT_SOFT, '视频格'),
                        (.65, 0, .35, .5, theme.CONTENT, '空格'),
                        (.65, .5, .35, .5, theme.PINK, '弹幕格')):
                    pane = QRectF(canvas.x() + x * canvas.width(), canvas.y() + y * canvas.height(),
                                  w * canvas.width(), h * canvas.height()).adjusted(1, 1, -1, -1)
                    fill = theme.qcolor(color)
                    if color == theme.PINK:
                        fill.setAlpha(65)
                    painter.fillRect(pane, fill)
                    painter.setPen(theme.qcolor(theme.TEXT1))
                    text = painter.fontMetrics().elidedText(label, Qt.ElideRight, int(pane.width()) - 6)
                    painter.drawText(pane, Qt.AlignCenter, text)
            else:
                painter.setPen(theme.qcolor(theme.TEXT1))
                label_rect = rect.adjusted(10, 0, -10, 0)
                if key == 'streamer_monitor':
                    painter.drawText(label_rect, Qt.AlignRight | Qt.AlignVCenter, '›')
                    label_rect.adjust(0, 0, -14, 0)
                text = painter.fontMetrics().elidedText(labels[key], Qt.ElideRight, int(label_rect.width()))
                painter.drawText(label_rect, Qt.AlignLeft | Qt.AlignVCenter, text)
