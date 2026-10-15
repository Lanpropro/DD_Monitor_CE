"""Clickable miniature scenes for the appearance editor."""
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QWidget, QToolTip

from . import theme
from .skin_parts import PARTS, resolve_values


class SkinPreview(QWidget):
    partSelected = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(420, 320)
        self.setMouseTracking(True)
        self.scene = 'main'
        self.selected = 'sidebar'
        self.hovered = ''
        self.personal = {}
        self.light = theme.is_light()
        self.state = ''
        self.background = None
        self.background_mask = 35
        self.regions = []
        self.protected = []
        self.setAccessibleName('可点击的界面分区预览')

    @staticmethod
    def scene_for(part):
        if part.startswith('settings') or part == 'buttons':
            return 'settings'
        return 'popups' if part in ('menus', 'dialogs', 'notices') else 'main'

    def select_part(self, part):
        self.selected = part
        scene = self.scene_for(part)
        if scene != self.scene:
            self.regions, self.protected = [], []
        self.scene = scene
        self.update()

    def _transform(self):
        scale = min(self.width()/800, self.height()/520)
        return scale, QPointF((self.width()-800*scale)/2, (self.height()-520*scale)/2)

    def point_for(self, part):
        """Widget coordinates for a visible hotspot (also used by Qt regression tests)."""
        scale, offset = self._transform()
        for key, rect in reversed(self.regions):
            if key == part:
                for point in (rect.center(), rect.topLeft()+QPointF(5, 5), rect.bottomRight()-QPointF(5, 5)):
                    mapped = (point*scale + offset).toPoint()
                    if self.part_at(mapped) == part:
                        return mapped
        raise ValueError(part)

    def part_at(self, position):
        scale, offset = self._transform()
        point = (QPointF(position)-offset)/scale
        for key, rect in reversed(self.regions):
            if rect.contains(point):
                # A card/video is not an entry point for its underlying panel.
                if key in ('sidebar', 'background') and any(r.contains(point) for r in self.protected):
                    return ''
                return key
        return ''

    def mouseMoveEvent(self, event):
        self.hovered = self.part_at(event.position())
        self.setCursor(Qt.PointingHandCursor if self.hovered else Qt.ArrowCursor)
        if self.hovered:
            QToolTip.showText(event.globalPosition().toPoint(),
                PARTS.get(self.hovered, '软件整体背景'), self)
        else:
            QToolTip.hideText()
        self.update()

    def leaveEvent(self, event):
        self.hovered = ''
        QToolTip.hideText()
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        part = self.part_at(event.position())
        if event.button() == Qt.LeftButton and part:
            self.partSelected.emit(part)
            event.accept()
        else:
            super().mousePressEvent(event)

    def _values(self, part):
        values = resolve_values(part, self.light, self.personal)
        if part == self.selected and self.state and part not in ('menus', 'settings.navigation'):
            values.update(values.get(self.state, {}))
        return values

    def _box(self, painter, part, rect, text='', default=None, foreground=None):
        values = self._values(part) if part else {}
        bg = values.get('background', default or ('#EDF2F7' if self.light else '#2A313B'))
        radius = values.get('radius', 7)
        painter.setPen(QPen(theme.qcolor(values.get('border_color', '#70839A')),
                            values.get('border_width', .6)))
        if values.get('border_width') == 0:
            painter.setPen(Qt.NoPen)
        painter.setBrush(theme.qcolor(bg))
        painter.drawRoundedRect(rect, radius, radius)
        if values.get('image'):
            painter.save()
            clip = QPainterPath()
            clip.addRoundedRect(rect, radius, radius)
            painter.setClipPath(clip)
            painter.drawPixmap(rect.toRect(), QPixmap(values['image']))
            painter.restore()
        fallback = '#26384C' if self.light else '#E6EEF7'
        if not part and default in ('#17202B', '#D6151A22'):
            fallback = '#9EADBE'
        painter.setPen(theme.qcolor(foreground or values.get('foreground', fallback)))
        if values.get('icon') and part and (part.startswith('buttons') or part == 'folders'):
            image = QPixmap(values['icon'])
            size = min(20, rect.height()-8)
            if not image.isNull():
                image = image.scaled(int(size), int(size), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                left = rect.x()+8 if part == 'folders' else rect.center().x()-image.width()/2
                painter.drawPixmap(int(left), int(rect.center().y()-image.height()/2), image)
                if part == 'folders':
                    painter.drawText(rect.adjusted(32, 0, -3, 0), Qt.AlignCenter, text)
        elif text:
            painter.drawText(rect, Qt.AlignCenter, text)
        if part:
            self.regions.append((part, QRectF(rect)))

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        scale, offset = self._transform()
        painter.translate(offset)
        painter.scale(scale, scale)
        font = painter.font()
        font.setPixelSize(12)
        painter.setFont(font)
        self.regions, self.protected = [], []
        self._box(painter, 'background' if self.scene == 'main' else '', QRectF(1, 1, 798, 518),
                  default='#E2E9F0' if self.light else '#1C2530')
        if self.scene == 'main':
            if self.background is not None and not self.background.isNull():
                painter.save()
                painter.setClipRect(QRectF(2, 2, 796, 516))
                ratio = max(796/self.background.width(), 516/self.background.height())
                width, height = self.background.width()*ratio, self.background.height()*ratio
                painter.drawImage(QRectF((800-width)/2, (520-height)/2, width, height), self.background)
                painter.restore()
                veil = theme.qcolor('#E2E9F0' if self.light else '#1C2530')
                veil.setAlpha(round(255*self.background_mask/100))
                painter.fillRect(QRectF(2, 2, 796, 516), veil)
            self._main(painter)
        elif self.scene == 'settings':
            self._settings(painter)
        else:
            self._popups(painter)
        # Highlight editable areas; leave protected video/card surfaces unmarked.
        for key, rect in self.regions:
            active = key == self.selected
            painter.setBrush(Qt.NoBrush)
            if active:
                painter.setPen(QPen(QColor(64, 210, 241, 55), 8))
                painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 7, 7)
            pen = QPen(QColor('#40D2F1') if active or key == self.hovered else QColor(64, 210, 241, 115),
                       2.5 if active else 1)
            if not active and key != self.hovered:
                pen.setStyle(Qt.DashLine)
            painter.setPen(pen)
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 7, 7)

    def _main(self, p):
        self._box(p, 'sidebar', QRectF(10, 10, 154, 500))
        self._box(p, '', QRectF(19, 18, 102, 25), 'DD监控室CE')
        self._box(p, 'buttons.sidebar_toggle', QRectF(130, 18, 25, 25), '«')
        for part, x, label in (('sort', 19, '排序'), ('appearance', 72, '◐'), ('refresh', 114, '↻')):
            self._box(p, 'buttons.'+part, QRectF(x, 51, 40, 25), label)
        self._box(p, 'folders', QRectF(19, 86, 136, 29), '文件夹 · 3')
        for y in (125, 223, 321):
            rect = QRectF(23, y, 128, 85)
            self._box(p, '', rect, '关注卡片', default='#17202B')
            self.protected.append(rect)
        for part, rect, text in (
                ('layout', QRectF(19, 425, 82, 29), '布局预设'),
                ('settings', QRectF(107, 425, 48, 29), '设置'),
                ('import', QRectF(19, 465, 62, 29), '导入关注'),
                ('add', QRectF(87, 465, 68, 29), '添加直播间')):
            self._box(p, 'buttons.'+part, rect, text)
        tiles = [QRectF(176, 10, 405, 324), QRectF(591, 10, 199, 157),
                 QRectF(591, 177, 199, 157), QRectF(176, 344, 199, 166),
                 QRectF(384, 344, 197, 166), QRectF(591, 344, 199, 166)]
        for index, rect in enumerate(tiles):
            self._box(p, '', rect, '直播画面', default='#D6151A22')
            if index == 0:
                self._box(p, '', QRectF(rect.x()+8, rect.y()+8, 98, 19), 'LIVE · 顶部浮标', default='#17202B')
            self.protected.append(QRectF(rect.x(), rect.y(), rect.width(), rect.height()-35))
            bar = QRectF(rect.x()+2, rect.bottom()-33, rect.width()-4, 31)
            self._box(p, 'controls', bar)
            if index == 0:
                self._box(p, '', QRectF(bar.x()+80, bar.y()+14, 88, 3), default='#667A8A')
                p.setBrush(QColor('#E6EEF7'))
                p.setPen(Qt.NoPen)
                p.drawEllipse(QPointF(bar.x()+115, bar.y()+15), 5, 5)
                p.setPen(theme.qcolor(self._values('controls').get('foreground', '#B8C8DB')))
                p.drawText(QRectF(bar.x()+174, bar.y()+3, 28, 25), Qt.AlignCenter, '40')
                for key, x, width, text in (('pause', 4, 30, 'Ⅱ'), ('volume', 40, 30, '♪'),
                        ('danmaku', 209, 45, '弹幕'), ('danmaku_settings', 260, 30, '⚙'),
                        ('recording', 296, 62, '● 录制'), ('fullscreen', 364, 30, '⛶')):
                    self._box(p, 'buttons.'+key, QRectF(bar.x()+x, bar.y()+3, width, 25), text)

    def _settings(self, p):
        self._box(p, 'settings', QRectF(25, 20, 750, 480))
        self._box(p, 'settings.navigation', QRectF(36, 34, 155, 452))
        for index, text in enumerate(('常规', '外观', '弹幕', '录制', '快捷键', '插件')):
            values = self._values('settings.navigation')
            state = values.get(self.state, {}) if index == 1 and self.selected == 'settings.navigation' else {}
            self._box(p, '', QRectF(47, 53+index*49, 132, 34), text,
                      default=state.get('background', '#00000000'),
                      foreground=state.get('foreground', values.get('foreground')))
        self._box(p, 'settings.content', QRectF(207, 34, 550, 388))
        for y, text in ((60, '设置页面'), (115, '颜色模式'), (170, '背景与美化'), (225, '常规设置')):
            self._box(p, '', QRectF(227, y, 505, 35), text, default='#00000000',
                      foreground=self._values('settings.content').get('foreground', self._values('settings').get('foreground')))
        self._box(p, 'buttons', QRectF(535, 442, 100, 32), '取消')
        self._box(p, 'buttons', QRectF(646, 442, 100, 32), '保存')

    def _popups(self, p):
        self._box(p, 'dialogs', QRectF(30, 60, 460, 390))
        self._box(p, '', QRectF(55, 84, 410, 40), '添加直播间／导入关注', default='#00000000',
                  foreground=self._values('dialogs').get('foreground'))
        for y, text in ((155, '房间号或直播间链接'), (215, '选择文件夹')):
            self._box(p, '', QRectF(55, y, 410, 40), text)
        self._box(p, 'menus', QRectF(520, 60, 245, 265))
        values = self._values('menus')
        for index, text in enumerate(('右键菜单', '账号菜单', '菜单选项')):
            state = values.get(self.state, {}) if index == 1 and self.selected == 'menus' else {}
            self._box(p, '', QRectF(532, 87+index*75, 221, 44), text,
                      default=state.get('background', '#00000000'),
                      foreground=state.get('foreground', values.get('foreground')))
        self._box(p, 'notices', QRectF(520, 355, 245, 95), '操作结果／顶部提示')
