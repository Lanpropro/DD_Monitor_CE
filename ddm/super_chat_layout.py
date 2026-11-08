"""Super Chat card measurement, placement and drawing primitives."""
from __future__ import annotations
import math
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QTextCharFormat, QTextCursor, QTextDocument, QTextOption
from .corner_geometry import continuous_path
from . import theme
from .super_chat_model import SC_CONTENT_COLOR, SC_BODY_PADDING


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
