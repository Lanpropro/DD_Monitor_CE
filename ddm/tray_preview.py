"""An in-memory schematic of the last main-window pane arrangement."""
from PySide6.QtCore import QPoint, QRect, QRectF, QSignalBlocker, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QSizePolicy, QWidget

from . import theme
from .avatar_widgets import AVATAR_COLORS
from .ui import ElidedLabel, SettingsSlider, SettingsValueLabel, VolumeButton


def _room_title(room, empty):
    return next((str(room[key]) for key in ('uname', 'title', 'name', 'room_id')
                 if room.get(key)), empty)


def capture_layout(wall):
    """Copy visible pane geometry and labels, never a media frame or live object."""
    bounds = wall.rect()
    width, height = max(1, bounds.width()), max(1, bounds.height())
    panes = []

    def append(widget, kind, room, empty):
        if widget.isHidden() or not wall.isAncestorOf(widget):
            return
        rect = QRect(widget.mapTo(wall, QPoint()), widget.size()).intersected(bounds)
        if rect.isEmpty():
            return
        pane = dict(rect=(rect.x() / width, rect.y() / height,
                          rect.width() / width, rect.height() / height),
                    kind=kind, title=_room_title(room, empty), occupied=bool(room.get('room_id')))
        if pane['occupied']:
            pane['room_id'] = str(room['room_id'])
            if kind == 'video':
                pane['tile_key'] = id(widget)
        panes.append(pane)

    for tile in wall.tiles:
        append(tile, 'video', tile.room, '空视频格')
    for panel in wall.pane_danmaku.rendered():
        target = wall.pane_danmaku.target(panel)
        append(panel, 'danmaku', target.room if target is not None else {}, '未绑定')
    return dict(aspect=width / height, size=(width, height), panes=panes)


class TrayLayoutPreview(QPushButton):
    """Clickable layout diagram; ownership and restore wiring remain with the tray."""
    paneSelected = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.snapshot = dict(aspect=16 / 9, panes=[])
        self.avatars = {}
        self.audio_panes = ()
        self.selected = None
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
                 occupied=pane['occupied'], **({'room_id': pane['room_id']} if 'room_id' in pane else {}))
            for pane in snapshot['panes']])
        lines = ['最小化前的软件布局（示意）', '点击恢复主窗口']
        for pane in self.snapshot['panes']:
            kind = '视频格' if pane['kind'] == 'video' else '弹幕格'
            state = '有内容' if pane['occupied'] else '空格' if pane['kind'] == 'video' else '未绑定'
            lines.append(f"{kind} · {state}：{pane['title']}")
        self.setToolTip('\n'.join(lines))
        self.update()

    def set_audio_selection(self, panes, selected):
        self.audio_panes = tuple(panes)
        self.selected = selected
        self.setAccessibleDescription('点选直播格可调节音量，也可用方向键切换直播间。'
                                      if self.audio_panes else '')
        self.update()

    def _diagram(self):
        area = QRectF(self.rect()).adjusted(10, 10, -10, -30)
        aspect = self.snapshot['aspect']
        width = min(area.width(), area.height() * aspect)
        height = width / aspect
        return QRectF(area.center().x() - width / 2, area.center().y() - height / 2, width, height)

    def _pane_rect(self, layout, pane):
        x, y, w, h = pane['rect']
        return QRectF(layout.x() + x * layout.width(), layout.y() + y * layout.height(),
                      w * layout.width(), h * layout.height()).adjusted(1, 1, -1, -1)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.isDown() and self.audio_panes:
            layout = self._diagram()
            for index in self.audio_panes:
                if self._pane_rect(layout, self.snapshot['panes'][index]).contains(event.position()):
                    self.setDown(False)
                    self.paneSelected.emit(index)
                    event.accept()
                    return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if self.audio_panes and event.key() in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
            index = self.audio_panes.index(self.selected)
            step = -1 if event.key() in (Qt.Key_Left, Qt.Key_Up) else 1
            self.paneSelected.emit(self.audio_panes[(index + step) % len(self.audio_panes)])
            event.accept()
            return
        super().keyPressEvent(event)

    def _draw_avatar(self, painter, rect, room_id, title):
        path = QPainterPath()
        path.addEllipse(rect)
        painter.setClipPath(path, Qt.IntersectClip)
        pixmap = self.avatars.get(room_id)
        if pixmap is not None and not pixmap.isNull():
            size = min(pixmap.width(), pixmap.height())
            painter.drawPixmap(rect, pixmap, QRectF((pixmap.width() - size) / 2,
                                                     (pixmap.height() - size) / 2, size, size))
        else:
            color = AVATAR_COLORS[sum(map(ord, room_id)) % len(AVATAR_COLORS)]
            painter.fillPath(path, theme.qcolor(color))
            font = painter.font()
            font.setPixelSize(max(6, round(rect.width() * .6)))
            painter.setFont(font)
            painter.setPen(Qt.white)
            painter.drawText(rect, Qt.AlignCenter, title[:1])

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        painter.setPen(QPen(theme.qcolor(theme.ACCENT if self.hasFocus() else theme.BORDER), 1))
        painter.setBrush(theme.qcolor(theme.CONTENT_HOVER if self.underMouse() or self.isDown()
                                     else theme.ELEVATED))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), 8, 8)
        layout = self._diagram()
        painter.fillRect(layout, theme.qcolor(theme.BG))
        font = painter.font()
        font.setPixelSize(11)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        for index, pane in enumerate(self.snapshot['panes']):
            rect = self._pane_rect(layout, pane)
            if rect.isEmpty():
                continue
            color = theme.qcolor(theme.ACCENT if pane['kind'] == 'video' else theme.PINK)
            fill = QColor(color) if pane['occupied'] else theme.qcolor(theme.CONTENT)
            if pane['occupied']:
                fill.setAlpha(65)
            painter.fillRect(rect, fill)
            painter.fillRect(QRectF(rect.x(), rect.y(), min(3, rect.width()), rect.height()), color)
            if index == self.selected:
                painter.setPen(QPen(color, 2))
                painter.setBrush(Qt.NoBrush)
                painter.drawRect(rect.adjusted(1, 1, -1, -1))
            painter.save()
            painter.setClipRect(rect)
            room_id = pane.get('room_id')
            size = min(18, int(rect.width()) - 4, int(rect.height()) - 4)
            if room_id and size >= 6:
                show_name = rect.width() >= size + 48
                icon = QRectF(rect.left() + 8 if show_name else rect.center().x() - size / 2,
                              rect.center().y() - size / 2, size, size)
                painter.save()
                self._draw_avatar(painter, icon, room_id, pane['title'])
                painter.restore()
                if show_name:
                    text = rect.adjusted(size + 13, 0, -5, 0)
                    painter.setPen(theme.qcolor(theme.TEXT1))
                    painter.drawText(text, Qt.AlignLeft | Qt.AlignVCenter,
                                     metrics.elidedText(pane['title'], Qt.ElideRight, int(text.width())))
                painter.restore()
                continue
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


class TrayPreviewAudio(QWidget):
    volumeChanged = Signal(int)
    muteChanged = Signal(bool)

    def __init__(self, parent):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 0, 10, 5)
        row.setSpacing(6)
        self.name = ElidedLabel(parent=self)
        self.name.setMaximumWidth(100)
        self.mute = VolumeButton(self, size=24)
        self.slider = SettingsSlider(self, fixed_width=False)
        self.slider.setRange(0, 100)
        self.slider.setMinimumWidth(60)
        self.value = SettingsValueLabel(parent=self)
        for widget in (self.name, self.mute, self.slider, self.value):
            row.addWidget(widget, 1 if widget is self.slider else 0)
        self.mute.clicked.connect(lambda: self.muteChanged.emit(not self.mute.muted))
        self.mute.volumeChanged.connect(self.volumeChanged)
        self.slider.valueChanged.connect(self.volumeChanged)

    def sync(self, tile):
        name = _room_title(tile.room, '')
        self.name.setText(name)
        self.name.setToolTip(name)
        self.mute.setAccessibleName(f'{name} · {"取消静音" if tile.muted else "静音"}')
        self.mute.set_state(tile.muted, tile.volume, tile.audio_channel)
        self.mute.setToolTip('点击取消静音，滚轮调音量' if tile.muted else '点击静音，滚轮调音量')
        self.slider.setAccessibleName(f'{name} · 音量')
        with QSignalBlocker(self.slider):
            self.slider.setValue(tile.volume)
        self.value.setText(f'{tile.volume}%')
