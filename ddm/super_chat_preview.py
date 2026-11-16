"""Settings preview and placement editing for video and panel Super Chats."""
from __future__ import annotations
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from .corner_geometry import continuous_path
from . import theme
from .skin_preview import SkinPreview
from .super_chat_model import super_chat_palette
from .super_chat_layout import sc_placement_rects, paint_sc_background


class SuperChatPlacementPreview(SkinPreview):
    """Edit independent video/panel positions and the shared live SC scale."""
    changed = Signal(dict)
    VIDEO_AREA = QRectF(10, 10, 540, 474)
    PANEL_AREA = QRectF(560, 332, 230, 178)

    def __init__(self, parent=None):
        super().__init__(parent, editable_parts=frozenset())
        self.selected = ''
        self.setMinimumWidth(300)
        self.setFixedHeight(300)
        self.setMouseTracking(True)
        self.setAccessibleName('SC 位置与大小预览')
        self.setToolTip('拖动卡片摆放，拖动右下角调整当前布局大小；位置是否同步由下方开关决定，双击恢复当前位置和大小')
        self._positions = {'video': None, 'panel': None}
        self.position_sync = True
        self._scales = {'video': 100, 'panel': 100}
        self.scale_with_video = False
        self.scale_strength = 35
        self.scale_curve = None
        self._opacities = {'video': 80, 'panel': 80}
        self.layout_mode = 'video'
        self.preview_context = {
            'video': {'size': [1280, 720], 'cards': [{'message': '', 'collapsed': False}]},
            'panel': {'size': [640, 400], 'outer_size': [640, 464], 'viewport_rect': [0, 32, 640, 400],
                      'cards': [{'message': '', 'collapsed': False}]}}
        self._gesture = None

    @property
    def position(self):
        return self._positions[self.layout_mode]

    @position.setter
    def position(self, value):
        self._positions[self.layout_mode] = value
        if self.position_sync:
            other = 'panel' if self.layout_mode == 'video' else 'video'
            self._positions[other] = None if value is None else list(value)

    @property
    def scale(self):
        return self._scales[self.layout_mode]

    @scale.setter
    def scale(self, value):
        value = max(75, min(200, int(value)))
        self._scales[self.layout_mode] = value
        if self.position_sync:
            other = 'panel' if self.layout_mode == 'video' else 'video'
            self._scales[other] = value

    @property
    def opacity(self):
        return self._opacities[self.layout_mode]

    @opacity.setter
    def opacity(self, value):
        value = max(0, min(100, int(value)))
        self._opacities[self.layout_mode] = value
        if self.position_sync:
            other = 'panel' if self.layout_mode == 'video' else 'video'
            self._opacities[other] = value

    def set_position_sync(self, enabled):
        self.position_sync = bool(enabled)
        if self.position_sync:
            self.position = self.position
            self._scales['panel'] = self._scales['video']
            self._opacities['panel'] = self._opacities['video']
        self.update()
        self.changed.emit(self.values())

    def values(self):
        return {'super_chat_position': None if self._positions['video'] is None else list(self._positions['video']),
                'super_chat_panel_position': None if self._positions['panel'] is None else list(self._positions['panel']),
                'super_chat_position_sync': self.position_sync,
                'super_chat_scale_with_video': self.scale_with_video,
                'super_chat_scale_strength': self.scale_strength,
                'super_chat_scale_curve': self.scale_curve,
                'super_chat_scale': self._scales['video'],
                'super_chat_video_scale': self._scales['video'],
                'super_chat_panel_scale': self._scales['panel'],
                'super_chat_opacity': self._opacities['video'],
                'super_chat_video_opacity': self._opacities['video'],
                'super_chat_panel_opacity': self._opacities['panel']}

    def apply_settings(self, settings):
        self.position_sync = bool(settings.get('super_chat_position_sync', True))
        for mode, key in (('video', 'super_chat_position'), ('panel', 'super_chat_panel_position')):
            position = settings.get(key)
            self._positions[mode] = list(position) if isinstance(position, (list, tuple)) and len(position) == 2 else None
        if self.position_sync:
            self._positions['panel'] = None if self._positions['video'] is None else list(self._positions['video'])
        shared_scale = int(settings.get('super_chat_scale', 100))
        self._scales = {
            'video': max(75, min(200, int(settings.get('super_chat_video_scale', shared_scale)))),
            'panel': max(75, min(200, int(settings.get('super_chat_panel_scale', shared_scale))))}
        self.scale_with_video = bool(settings.get('super_chat_scale_with_video', False))
        self.scale_strength = int(settings.get('super_chat_scale_strength', 35))
        self.scale_curve = settings.get('super_chat_scale_curve')
        shared_opacity = int(settings.get('super_chat_opacity', 80))
        self._opacities = {
            'video': max(10, min(100, int(settings.get('super_chat_video_opacity', shared_opacity)))),
            'panel': max(10, min(100, int(settings.get('super_chat_panel_opacity', shared_opacity))))}
        if self.position_sync:
            self._scales['panel'] = self._scales['video']
            self._opacities['panel'] = self._opacities['video']
        self.update()

    def set_opacity(self, value):
        self.opacity = max(10, min(100, int(value)))
        self.update()

    def set_scale(self, value):
        self.scale = value
        self.update()

    def set_preview_context(self, context):
        self.preview_context.update(context)
        self.update()

    def set_layout_mode(self, index):
        self._gesture = None
        self.layout_mode = 'panel' if index == 1 else 'video'
        self.update()

    def _scene_rect(self, rect):
        scale, offset = self._transform()
        return QRectF(offset.x() + rect.x() * scale, offset.y() + rect.y() * scale,
                      rect.width() * scale, rect.height() * scale)

    def stage_rect(self):
        if self.layout_mode == 'panel':
            context = self.preview_context['panel']
            panel = self._panel_rect()
            factor = panel.width() / context.get('outer_size', context['size'])[0]
            x, y, width, height = context.get('viewport_rect', [0, 0, *context['size']])
            return QRectF(panel.x() + x * factor, panel.y() + y * factor, width * factor, height * factor)
        return self.video_rect()

    def video_rect(self):
        return self._fit_viewport(self.VIDEO_AREA, self.preview_context['video']['size'])

    def _panel_rect(self):
        context = self.preview_context['panel']
        return self._fit_viewport(self.PANEL_AREA, context.get('outer_size', context['size']))

    def _fit_viewport(self, area, size):
        area = self._scene_rect(area)
        width, height = size
        scale = min(area.width() / width, area.height() / height)
        return QRectF(area.center().x() - width * scale / 2,
                      area.center().y() - height * scale / 2, width * scale, height * scale)

    def card_rects(self):
        context = self.preview_context[self.layout_mode]
        width, height = context['size']
        rects, scale = sc_placement_rects(context['cards'], width, height,
            self.scale / 100, self.position, self.layout_mode == 'panel', lambda card: card['collapsed'],
            scale_with_video=self.scale_with_video, scale_strength=self.scale_strength,
            scale_curve=self.scale_curve)
        stage = self.stage_rect()
        factor = stage.width() / width
        self._card_scale = scale * factor
        return [QRectF(stage.x() + rect.x() * factor, stage.y() + rect.y() * factor,
                       rect.width() * factor, rect.height() * factor) for rect in rects]

    def card_rect(self):
        rects = self.card_rects()
        bounds = QRectF(rects[0])
        for rect in rects[1:]:
            bounds = bounds.united(rect)
        return bounds

    def _main(self, painter):
        for index, rect in enumerate((QRectF(10, 10, 540, 500), QRectF(560, 10, 230, 151), QRectF(560, 171, 230, 151))):
            self._box(painter, '', rect, '主画面' if index == 0 else '画面', default='#D6151A22')
            bar = QRectF(rect.x(), rect.bottom() - 24, rect.width(), 24)
            self._box(painter, 'controls', bar, 'Ⅱ   ♪  ━━━   ⚙')
        self._box(painter, '', self.PANEL_AREA, default='#17202B')

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        panel = self._panel_rect()
        painter.setPen(QPen(theme.qcolor(theme.BORDER), 1))
        painter.setBrush(theme.qcolor('#EDF2F7' if self.light else '#17202B'))
        painter.drawPath(continuous_path(panel, 4))
        panel_context = self.preview_context['panel']
        factor = panel.width() / panel_context.get('outer_size', panel_context['size'])[0]
        header_height = panel_context.get('viewport_rect', [0, 0])[1] * factor
        font = painter.font()
        font.setPixelSize(max(1, round(header_height * .6)))
        painter.setFont(font)
        painter.setPen(theme.qcolor(theme.PINK))
        painter.drawText(QRectF(panel.x() + 2, panel.y(), panel.width() - 4, header_height), Qt.AlignVCenter, '● 弹幕')
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.qcolor(theme.BORDER))
        viewport_rect = panel_context.get('viewport_rect', [0, 0, *panel_context['size']])
        bottom = panel.y() + (viewport_rect[1] + viewport_rect[3]) * factor
        footer_height = max(0, panel.bottom() - bottom)
        painter.drawPath(continuous_path(QRectF(panel.x() + 2, bottom + footer_height * .25,
                                       panel.width() - 4, footer_height * .5), 2))
        stage = self.stage_rect()
        painter.setPen(QPen(theme.qcolor(theme.ACCENT), 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(continuous_path(stage, 3))
        palette = super_chat_palette(30)
        painter.save()
        painter.setOpacity(self.opacity / 100)
        factor = stage.width() / self.preview_context[self.layout_mode]['size'][0]
        for rect, card in zip(self.card_rects(), self.preview_context[self.layout_mode]['cards']):
            painter.save()
            painter.translate(rect.topLeft())
            painter.scale(factor, factor)
            paint_sc_background(painter, QRectF(0, 0, rect.width() / factor, rect.height() / factor),
                                palette['background_bottom_color'], palette['background_color'],
                                (36 if card['collapsed'] else 56) * self._card_scale / factor)
            painter.restore()
        painter.restore()
        rect = self.card_rect()
        painter.setPen(QColor('white'))
        painter.drawLine(rect.bottomRight() - QPointF(8, 2), rect.bottomRight() - QPointF(2, 8))
        painter.end()

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton or not self.card_rect().contains(event.position()):
            return super().mousePressEvent(event)
        rect = self.card_rect()
        self._gesture = 'resize' if (event.position() - rect.bottomRight()).manhattanLength() < 16 else 'move'
        self._start_point = event.position()
        self._start_rect = QRectF(rect)
        self._start_scale = self.scale
        event.accept()

    def mouseMoveEvent(self, event):
        if self._gesture is None:
            self.setCursor(Qt.SizeFDiagCursor if (event.position() - self.card_rect().bottomRight()).manhattanLength() < 16
                           else Qt.OpenHandCursor if self.card_rect().contains(event.position()) else Qt.ArrowCursor)
            return
        delta = event.position() - self._start_point
        if self._gesture == 'resize':
            self.scale = max(75, min(200, round(self._start_scale * (1 + delta.x() / self._start_rect.width()))))
        else:
            stage = self.stage_rect()
            factor = stage.width() / self.preview_context[self.layout_mode]['size'][0]
            margin = (8 if self.layout_mode == 'panel' else 10) * factor
            stage = stage.adjusted(margin, margin, -margin, -margin)
            position = []
            for value, span in ((self._start_rect.x() + delta.x() - stage.x(), stage.width() - self._start_rect.width()),
                                (self._start_rect.y() + delta.y() - stage.y(), stage.height() - self._start_rect.height())):
                ratio = max(0, min(1, value / max(1, span)))
                position.append(0.0 if ratio < .04 else 1.0 if ratio > .96 else round(ratio, 6))
            self.position = position
        self.update()
        self.changed.emit(self.values())
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._gesture is not None:
            self._gesture = None
            self.changed.emit(self.values())
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._gesture = None
            self.position, self.scale = None, 100
            self.update()
            self.changed.emit(self.values())
