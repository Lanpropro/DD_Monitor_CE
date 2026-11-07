"""Bilibili Super Chat state shared by the danmaku panel and video overlays."""
from __future__ import annotations

import time
import math
from dataclasses import dataclass, field
from copy import deepcopy
from urllib.parse import urlparse

import requests
from PySide6.QtCore import QObject, QPointF, QRectF, QThread, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPainterPath, QPen, QTextCharFormat, QTextCursor, QTextDocument, QTextOption, QTransform
from PySide6.QtWidgets import QApplication

from .corner_geometry import continuous_path
from . import bili, motion, theme
from .images import AvatarLoader, load_cached_image
from .skin_preview import SkinPreview


SUPER_CHAT_API = "https://api.live.bilibili.com/av/v1/SuperChat/getMessageList"
DEFAULT_DURATION = 60
SC_PRICE_TIERS = (
    (30, '#EDF5FF', '#2A60B2', '#7497CD'),
    (50, '#DBFFFD', '#427D9E', '#7DA4BD'),
    (100, '#FFF1C5', '#E2B52B', '#ECCF75'),
    (500, '#FFEAD2', '#E09443', '#E8AF79'),
    (1000, '#FFE7E4', '#E54D4D', '#EE8B8B'),
    (2000, '#FFD8D8', '#AB1A32', '#C86A7A'),
)
SC_USER_COLOR = '#666666'
SC_PRICE_COLOR = '#333333'
SC_CONTENT_COLOR = '#FFFFFF'
SC_BODY_PADDING = 12


def super_chat_palette(price):
    amount = _number(price)
    tier = next((tier for tier in reversed(SC_PRICE_TIERS) if amount >= tier[0]), SC_PRICE_TIERS[0])
    return dict(zip(('background_color', 'background_bottom_color', 'background_price_color'), tier[1:]))


def sc_message_document(event, width, scale=1.0):
    font = QFont(theme.FONT_DEFAULT)
    font.setPixelSize(max(1, round(14 * scale)))
    document = QTextDocument()
    document.setDocumentMargin(0)
    document.setDefaultFont(font)
    option = document.defaultTextOption()
    option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
    document.setDefaultTextOption(option)
    document.setPlainText(str(event.get('message') or event.get('text') or ''))
    cursor = QTextCursor(document)
    cursor.select(QTextCursor.Document)
    style = QTextCharFormat()
    style.setForeground(QColor(SC_CONTENT_COLOR))
    cursor.mergeCharFormat(style)
    document.setTextWidth(max(1, math.floor(width) - 2 * math.ceil(11 * scale)))
    return document


def sc_card_height(event, width, scale=1.0, collapsed=False):
    if collapsed:
        return round(36 * scale)
    document = sc_message_document(event, width, scale)
    padding = round(56 * scale) + 2 * math.ceil(SC_BODY_PADDING * scale)
    return math.ceil(max(100 * scale, padding + document.size().height() + 1))


def sc_card_geometry(events, base_width, scale, available_width, available_height, collapsed=False):
    if not events:
        return 1, 1, scale, []
    scale = min(scale, max(1, available_width) / base_width)
    for attempt in range(8):
        width = base_width * scale
        heights = [sc_card_height(event, width, scale, collapsed(event) if callable(collapsed) else collapsed) for event in events]
        height = sum(heights) + 8 * scale * (len(heights) - 1)
        if height <= max(1, available_height) or attempt == 7:
            break
        scale *= max(1, available_height) / height * .98
    return width, height, scale, heights


def order_super_chats(chats):
    ordered = sorted(chats, key=lambda item: (-_number(item.get('price')),
                     _number(item.get('start_time')), str(item.get('id') or '')))
    return ordered


def sc_placement_rects(events, viewport_width, viewport_height, scale=1.0,
                       position=None, panel=False, collapsed=False, scale_with_video=False,
                       scale_strength=35, scale_curve=None):
    if not events:
        return [], scale
    margin = 8 if panel else 10
    base_width = min(340, max(150 if panel else 168,
                             round(viewport_width * (.46 if panel else .30))))
    if scale_with_video and not panel:
        base_width = 340
        from .viewport_scale import viewport_scale
        scale *= viewport_scale(viewport_height, scale_strength, scale_curve)
    width, height, scale, heights = sc_card_geometry(
        events, base_width, scale, viewport_width - 2 * margin,
        viewport_height - 2 * margin, collapsed)
    spans = (max(0, viewport_width - 2 * margin - width),
             max(0, viewport_height - 2 * margin - height))
    if isinstance(position, (list, tuple)) and len(position) == 2:
        try:
            ratios = [max(0.0, min(1.0, float(value))) for value in position]
        except (TypeError, ValueError):
            ratios = [1.0, 0.0]
        left, top = [margin + (round(ratio * span) if panel else ratio * span)
                     for ratio, span in zip(ratios, spans)]
    else:
        left = margin + (round(spans[0]) if panel else spans[0])
        top = margin if panel else min(54 if viewport_height >= 320 else 10, margin + spans[1])
    if panel:
        width = max(1, round(width))
        heights = [sc_card_height(event, width, scale, collapsed(event) if callable(collapsed) else collapsed)
                   for event in events]
    rects = sc_stack_rects(width, height, len(events), scale=scale, card_heights=heights)
    return [rect.translated(left, top) for rect in rects], scale


def sc_stack_rects(width, height, count, card_height=100, scale=1.0, card_heights=None):
    if not count:
        return []
    if card_heights is not None:
        rects = []
        top = 0
        for item_height in card_heights:
            rects.append(QRectF(0, top, width, item_height))
            top += item_height + 8 * scale
        return rects
    card_height = min(card_height * scale, max(1, (height - 8 * scale * (count - 1)) / count))
    return [QRectF(0, i * (card_height + 8 * scale), width, card_height) for i in range(count)]


class SuperChatPresentation(QObject):
    changed = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.progress = 1.0
        self.delay = 7
        self.ids = set()
        self.collapsed_ids = set()
        self.deadlines = {}
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._expire)
        self.entrance = QVariantAnimation(self)
        self.entrance.setDuration(180)
        self.entrance.setEasingCurve(motion.THEME_WAVE_EASING)
        self.entrance.setStartValue(0.0)
        self.entrance.setEndValue(1.0)
        self.entrance.valueChanged.connect(self._reveal)

    @property
    def collapsed(self):
        return bool(self.ids) and self.ids <= self.collapsed_ids

    def is_collapsed(self, event):
        key = str(event.get('id') or event.get('super_chat_id') or '') if isinstance(event, dict) else str(event)
        return key in self.collapsed_ids

    def configure(self, settings):
        delay = max(1, min(60, _number(settings.get('super_chat_collapse_delay'), 7)))
        if self.delay != delay:
            self.delay = delay
            now = time.monotonic()
            self.deadlines = {key: now + delay for key in self.deadlines}
            self._schedule()

    def _schedule(self):
        self.timer.stop()
        if self.deadlines:
            self.timer.start(max(1, math.ceil((min(self.deadlines.values()) - time.monotonic()) * 1000)))

    def _expire(self):
        now = time.monotonic()
        expired = {key for key, deadline in self.deadlines.items() if deadline <= now}
        self.collapsed_ids.update(expired)
        for key in expired:
            self.deadlines.pop(key, None)
        self._schedule()
        if expired:
            self.changed.emit()

    def set_events(self, events):
        ids = {str(item.get('id') or item.get('super_chat_id') or '') for item in events}
        added = ids - self.ids
        self.ids = ids
        self.collapsed_ids.intersection_update(ids)
        self.deadlines = {key: deadline for key, deadline in self.deadlines.items() if key in ids}
        if not ids:
            self.entrance.stop()
            self.progress = 1.0
        for key in added:
            self.deadlines[key] = time.monotonic() + self.delay
        self._schedule()
        if added and motion.enabled():
            self.entrance.stop()
            self.entrance.start()

    def expand(self, chat_id=None, *, animate=False):
        keys = self.ids if chat_id is None else {str(chat_id)} & self.ids
        self.collapsed_ids.difference_update(keys)
        for key in keys:
            self.deadlines[key] = time.monotonic() + self.delay
        self._schedule()
        self.entrance.stop()
        self.progress = 1.0
        if animate and motion.enabled():
            self.entrance.start()
        self.changed.emit()

    def collapse(self, chat_id=None):
        self.entrance.stop()
        self.progress = 1.0
        keys = self.ids if chat_id is None else {str(chat_id)} & self.ids
        self.collapsed_ids.update(keys)
        for key in keys:
            self.deadlines.pop(key, None)
        self._schedule()
        self.changed.emit()

    def _reveal(self, value):
        self.progress = float(value)
        self.changed.emit()


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
        self.setToolTip('拖动卡片摆放，拖动右下角调整共用大小；位置是否同步由下方开关决定，双击恢复当前位置和共用大小')
        self._positions = {'video': None, 'panel': None}
        self.position_sync = True
        self.scale = 100
        self.scale_with_video = False
        self.scale_strength = 35
        self.scale_curve = None
        self.opacity = 80
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

    def set_position_sync(self, enabled):
        self.position_sync = bool(enabled)
        if self.position_sync:
            self.position = self.position
        self.update()
        self.changed.emit(self.values())

    def values(self):
        return {'super_chat_position': None if self._positions['video'] is None else list(self._positions['video']),
                'super_chat_panel_position': None if self._positions['panel'] is None else list(self._positions['panel']),
                'super_chat_position_sync': self.position_sync,
                'super_chat_scale_with_video': self.scale_with_video,
                'super_chat_scale_strength': self.scale_strength,
                'super_chat_scale_curve': self.scale_curve,
                'super_chat_scale': self.scale}

    def apply_settings(self, settings):
        self.position_sync = bool(settings.get('super_chat_position_sync', True))
        for mode, key in (('video', 'super_chat_position'), ('panel', 'super_chat_panel_position')):
            position = settings.get(key)
            self._positions[mode] = list(position) if isinstance(position, (list, tuple)) and len(position) == 2 else None
        if self.position_sync:
            self._positions['panel'] = None if self._positions['video'] is None else list(self._positions['video'])
        self.scale = max(75, min(200, int(settings.get('super_chat_scale', 100))))
        self.scale_with_video = bool(settings.get('super_chat_scale_with_video', False))
        self.scale_strength = int(settings.get('super_chat_scale_strength', 35))
        self.scale_curve = settings.get('super_chat_scale_curve')
        self.set_opacity(settings.get('super_chat_opacity', 80))
        self.update()

    def set_opacity(self, value):
        self.opacity = max(10, min(100, int(value)))
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


class SuperChatAvatar(QObject):
    changed = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.url = ''
        self.pixmap = None
        self._loaders = {}

    def set_url(self, url):
        url = str(url or '')
        if url == self.url:
            return
        self.url = url
        self.pixmap = load_cached_image(url, 'sc-avatars') if url else None
        self.changed.emit()
        if not url or self.pixmap is not None or url in self._loaders:
            return
        app = QApplication.instance()
        loader = AvatarLoader({url: url}, app, subdir='sc-avatars')
        self._loaders[url] = loader
        loader.loaded.connect(self._loaded)
        loader.finished.connect(lambda: self._loaders.pop(url, None))
        loader.finished.connect(loader.deleteLater)
        app.aboutToQuit.connect(loader.wait)
        loader.start()

    def _loaded(self, url, pixmap):
        if url == self.url and not pixmap.isNull():
            self.pixmap = pixmap
            self.changed.emit()


def paint_sc_avatar(painter, rect, pixmap, name):
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)
    painter.setPen(Qt.NoPen)
    if pixmap is not None:
        brush = QBrush(pixmap)
        factor = max(rect.width() / pixmap.width(), rect.height() / pixmap.height())
        transform = QTransform()
        transform.translate(rect.center().x() - pixmap.width() * factor / 2,
                            rect.center().y() - pixmap.height() * factor / 2)
        transform.scale(factor, factor)
        brush.setTransform(transform)
        painter.setBrush(brush)
    else:
        painter.setBrush(QColor('#64748b'))
    painter.drawEllipse(rect)
    if pixmap is None:
        painter.setPen(QColor('white'))
        painter.drawText(rect, Qt.AlignCenter, (name or '?')[0])
    painter.restore()


def paint_sc_background(painter, rect, background, header, header_height):
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)
    outline = QPainterPath()
    outline.addPath(continuous_path(rect, 7))
    painter.setClipPath(outline, Qt.IntersectClip)
    height = min(rect.height(), header_height)
    painter.fillRect(QRectF(rect.x(), rect.y(), rect.width(), height), QColor(header))
    painter.fillRect(QRectF(rect.x(), rect.y() + height, rect.width(), rect.height() - height), QColor(background))
    painter.setPen(QPen(QColor(background), 1))
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(outline)
    painter.restore()


def _text(value) -> str:
    return str(value or "").strip()


def _number(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def readable_text_color(background) -> QColor:
    """Pick WCAG-friendly text for a Bilibili Super Chat background."""
    color = (QColor(background) if isinstance(background, QColor)
             else QColor(str(background or "")))
    if not color.isValid():
        color = QColor("#f59e0b")
    channels = []
    for value in (color.redF(), color.greenF(), color.blueF()):
        channels.append(value / 12.92 if value <= 0.03928
                        else ((value + 0.055) / 1.055) ** 2.4)
    luminance = 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]
    dark = QColor("#20242c")
    light = QColor("#ffffff")
    dark_contrast = (luminance + 0.05) / (0.019 + 0.05)
    light_contrast = 1.05 / (luminance + 0.05)
    return dark if dark_contrast >= light_contrast else light


def _hosted_asset_url(value) -> str:
    url = _text(value)
    parsed = urlparse(url)
    return url if parsed.scheme in ("http", "https") and parsed.netloc else ""


def normalize(event: dict, *, source: str = "websocket") -> dict:
    """Turn either a blivedm message or an API entry into one event shape."""
    source = _text(source) or "websocket"
    user = event.get("user_info") if isinstance(event.get("user_info"), dict) else {}
    chat_id = _text(event.get("id") or event.get("super_chat_id"))
    message = _text(event.get("message") or event.get("text"))
    uname = _text(event.get("uname") or user.get("uname"))
    price = _number(event.get("price"))
    start = _number(event.get("start_time"))
    end = _number(event.get("end_time"))
    # SC 网页端按 start_time + time 推算结束时间；快照有时只给 time。
    duration = _number(event.get("time"))
    if end <= 0 and start > 0 and duration > 0:
        end = start + duration
    if end <= 0 and duration > 0:
        end = int(time.time()) + duration
    if end <= start:
        end = start + DEFAULT_DURATION if start else int(time.time()) + DEFAULT_DURATION
    return {
        "kind": "super_chat",
        "super_chat_id": chat_id,
        "id": chat_id,
        "uid": _text(event.get("uid") or user.get("uid")),
        "uname": uname,
        "text": message,
        "message": message,
        "price": price,
        "start_time": start,
        "end_time": end,
        "time": max(0, end - int(time.time())),
        "face": _text(event.get("face") or user.get("face")),
        "guard_level": _number(event.get("guard_level") or user.get("guard_level")),
        "user_level": _number(event.get("user_level") or user.get("user_level")),
        **super_chat_palette(price),
        "background_image": _hosted_asset_url(event.get("background_image")),
        "background_icon": _hosted_asset_url(event.get("background_icon")),
        "message_trans": _text(event.get("message_trans")),
        "source": source,
    }


def snapshot_events(room_id: str, *, timeout: float = 4.0) -> list[dict]:
    """Fetch currently displayed Super Chats; an unavailable endpoint is non-fatal."""
    room_id = _text(room_id)
    if not room_id.isdigit():
        return []
    # 页面配置里常见短号，SC 接口只认真实房间号。
    room_id = _text(bili._resolve_room_id(room_id))
    if not room_id.isdigit():
        return []
    response = requests.get(
        SUPER_CHAT_API,
        params={"room_id": room_id},
        headers=bili.HEADERS,
        cookies=bili._cookies(),
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or payload.get("code") != 0:
        return []
    data = payload.get("data") or {}
    items = data.get("list") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    return [normalize(item, source="snapshot") for item in items
            if isinstance(item, dict) and _text(item.get("id"))]


@dataclass
class SuperChatStore:
    """Room-local active chats, keyed by the Bilibili Super Chat ID."""

    items: dict[str, dict] = field(default_factory=dict)
    removed: set[str] = field(default_factory=set)
    dismissed: set[str] = field(default_factory=set)

    def upsert(self, event: dict) -> dict:
        source = _text(event.get("source")) or "websocket"
        item = normalize(event, source=source)
        if not item["super_chat_id"]:
            item["super_chat_id"] = item["id"] = f"{item['uid']}:{item['start_time']}"
        if item["super_chat_id"] in self.removed:
            return item
        if _number(item.get("end_time")) <= time.time():
            return item
        current = self.items.get(item["super_chat_id"])
        if current is not None:
            # 快照只补实时事件缺的字段，不能覆盖刚收到的内容。
            if source == "snapshot" and current.get("source") == "websocket":
                item = {**item, **deepcopy(current)}
            else:
                item = {**deepcopy(current),
                        **{key: value for key, value in item.items()
                           if value not in ("", 0)}}
        self.items[item["super_chat_id"]] = item
        return item

    def remove(self, ids) -> None:
        for chat_id in ids or ():
            chat_id = _text(chat_id)
            self.removed.add(chat_id)
            self.items.pop(chat_id, None)

    def dismiss(self, chat_id) -> None:
        """Hide one message locally without sending a moderation request."""
        self.dismissed.add(_text(chat_id))

    def expire(self, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        expired = [key for key, item in self.items.items()
                   if _number(item.get("end_time")) <= now]
        for key in expired:
            self.items.pop(key, None)
            self.dismissed.discard(key)
        return bool(expired)

    def active(self, now: float | None = None) -> list[dict]:
        now = time.time() if now is None else now
        chats = [deepcopy(item) for item in self.items.values()
                 if _number(item.get("end_time")) > now and item['id'] not in self.dismissed]
        return order_super_chats(chats)


def format_price(price) -> str:
    return f"¥{_number(price):,}"


def remaining_seconds(end_time, now: float | None = None) -> int:
    now = time.time() if now is None else now
    return max(0, _number(end_time) - int(now))


def format_remaining(seconds) -> str:
    seconds = max(0, _number(seconds))
    minutes, rest = divmod(seconds, 60)
    return f"{minutes}:{rest:02d}" if minutes else f"{rest}秒"


class SuperChatSnapshot(QThread):
    """Load one room's current Super Chats away from the UI thread."""

    loaded = Signal(str, list)

    def __init__(self, room_id: str, parent=None):
        super().__init__(parent)
        self.room_id = _text(room_id)

    def run(self) -> None:
        try:
            chats = snapshot_events(self.room_id)
        except Exception:  # noqa: BLE001 - optional endpoint, live events remain usable
            chats = []
        if not self.isInterruptionRequested():
            self.loaded.emit(self.room_id, chats)
