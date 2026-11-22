"""An in-memory schematic of the last main-window pane arrangement."""
from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QPushButton, QSizePolicy

from . import theme


def _room_title(room, empty):
    return next((str(room[key]) for key in ('uname', 'title', 'name', 'room_id')
                 if room.get(key)), empty)


def capture_layout(wall):
    """Copy visible pane geometry and labels, never a media frame or live object."""
    bounds = wall.rect()
    width, height = max(1, bounds.width()), max(1, bounds.height())
    panes = []

    def append(widget, kind, room, empty):
        if widget.isHidden():
            return
        rect = QRect(widget.mapTo(wall, QPoint()), widget.size()).intersected(bounds)
        if rect.isEmpty():
            return
        panes.append(dict(rect=(rect.x() / width, rect.y() / height,
                                rect.width() / width, rect.height() / height),
                          kind=kind, title=_room_title(room, empty),
                          occupied=bool(room.get('room_id'))))

    for tile in wall.tiles:
        append(tile, 'video', tile.room, '空视频格')
    for panel in wall.pane_danmaku.rendered():
        target = wall.pane_danmaku.target(panel)
        append(panel, 'danmaku', target.room if target is not None else {}, '未绑定')
    return dict(aspect=width / height, panes=panes)


class TrayLayoutPreview(QPushButton):
    """Clickable layout diagram; ownership and restore wiring remain with the tray."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.snapshot = dict(aspect=16 / 9, panes=[])
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.setMinimumSize(160, 110)
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName('软件布局示意，点击恢复主窗口')
        self.set_snapshot(self.snapshot)

    def sizeHint(self):
        return QSize(260, 160)

    def set_snapshot(self, snapshot):
        snapshot = snapshot or dict(aspect=16 / 9, panes=[])
        self.snapshot = dict(aspect=snapshot['aspect'], panes=[
            dict(rect=tuple(pane['rect']), kind=pane['kind'], title=pane['title'],
                 occupied=pane['occupied']) for pane in snapshot['panes']])
        lines = ['最小化前的软件布局（示意）', '点击恢复主窗口']
        for pane in self.snapshot['panes']:
            kind = '视频格' if pane['kind'] == 'video' else '弹幕格'
            state = '有内容' if pane['occupied'] else '空格' if pane['kind'] == 'video' else '未绑定'
            lines.append(f"{kind} · {state}：{pane['title']}")
        self.setToolTip('\n'.join(lines))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(theme.qcolor(theme.ACCENT if self.hasFocus() else theme.BORDER), 1))
        painter.setBrush(theme.qcolor(theme.CONTENT_HOVER if self.underMouse() or self.isDown()
                                     else theme.ELEVATED))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), 8, 8)
        area = QRectF(self.rect()).adjusted(10, 10, -10, -30)
        aspect = self.snapshot['aspect']
        width = min(area.width(), area.height() * aspect)
        height = width / aspect
        layout = QRectF(area.center().x() - width / 2, area.center().y() - height / 2,
                        width, height)
        painter.fillRect(layout, theme.qcolor(theme.BG))
        font = painter.font()
        font.setPixelSize(11)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        for pane in self.snapshot['panes']:
            x, y, w, h = pane['rect']
            rect = QRectF(layout.x() + x * width, layout.y() + y * height,
                          w * width, h * height).adjusted(1, 1, -1, -1)
            if rect.isEmpty():
                continue
            color = theme.qcolor(theme.ACCENT if pane['kind'] == 'video' else theme.PINK)
            fill = QColor(color) if pane['occupied'] else theme.qcolor(theme.CONTENT)
            if pane['occupied']:
                fill.setAlpha(65)
            painter.fillRect(rect, fill)
            painter.fillRect(QRectF(rect.x(), rect.y(), min(3, rect.width()), rect.height()), color)
            painter.save()
            painter.setClipRect(rect)
            painter.setPen(theme.qcolor(theme.TEXT1 if pane['occupied'] else theme.TEXT3))
            kind = '视频' if pane['kind'] == 'video' else '弹幕'
            label = f"{kind} · {pane['title']}" if pane['occupied'] else (
                '空视频格' if pane['kind'] == 'video' else '弹幕 · 未绑定')
            if rect.width() < metrics.horizontalAdvance(kind) + 10:
                label = '视' if pane['kind'] == 'video' and pane['occupied'] else (
                    '空' if pane['kind'] == 'video' else '弹')
            else:
                label = metrics.elidedText(label, Qt.ElideRight, max(0, int(rect.width()) - 10))
            painter.drawText(rect.adjusted(5, 0, -3, 0), Qt.AlignCenter, label)
            painter.restore()
        painter.setPen(theme.qcolor(theme.TEXT2))
        painter.drawText(QRectF(10, self.height() - 25, self.width() - 20, 20),
                         Qt.AlignCenter, '蓝：视频   粉：弹幕   灰：空格')
