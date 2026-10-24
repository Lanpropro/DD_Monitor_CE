"""Thread-local Qt image preparation from immutable GUI style snapshots."""
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt, QUrl
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QImage, QPainter,
                          QPainterPath, QPen, QTextCharFormat, QTextCursor,
                          QTextDocument)

from .danmaku_content import content_html


@dataclass(frozen=True)
class RasterStyle:
    font_family: str
    pixel_size: int
    outline_width: float = 0
    logical_max_width: float = 1280
    dpr: float = 1
    sample_scale: float = 2

    def __post_init__(self) -> None:
        values = (self.outline_width, self.logical_max_width, self.dpr, self.sample_scale)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Raster dimensions must be finite")
        if (self.pixel_size <= 0 or self.outline_width < 0 or self.logical_max_width <= 0
                or self.dpr <= 0 or self.sample_scale <= 0):
            raise ValueError("Raster dimensions must be positive")


@dataclass(frozen=True)
class PreparedRaster:
    image: QImage
    logical_width: float
    logical_height: float
    pixel_width: int
    pixel_height: int
    stride: int
    bgra: bytes


def rasterize(text: str, color: str | QColor, runs: Sequence[tuple[str, str]],
              self_sent: bool, style: RasterStyle,
              images: Mapping[str, QImage] | None = None) -> PreparedRaster:
    renderer = _Rasterizer(style, images or {})
    foreground = QColor(color)
    if not foreground.isValid():
        foreground = QColor("#ffffff")
    image = renderer.render_content(text, foreground, runs, self_sent)
    scale = image.devicePixelRatio()
    return PreparedRaster(image, image.width() / scale, image.height() / scale,
                          image.width(), image.height(), image.bytesPerLine(),
                          bytes(image.constBits()))


class _Rasterizer:
    def __init__(self, style: RasterStyle, images: Mapping[str, QImage]) -> None:
        self.style = style
        self.images = {url: QImage(image) for url, image in images.items() if not image.isNull()}
        self.font = QFont(style.font_family)
        self.font.setPixelSize(style.pixel_size)
        self.font.setWeight(QFont.Weight.Medium)

    def render_content(self, text: str, color: QColor, runs: Sequence[tuple[str, str]],
                       self_sent: bool) -> QImage:
        if not any(url in self.images for _, url in runs if url):
            return self._render_text(text, color, self_sent)
        outline = self.style.outline_width
        pad = (9 if self_sent else 4) + math.ceil(outline)
        document = QTextDocument()
        document.setDefaultFont(self.font)
        document.setDocumentMargin(0)
        for _, url in runs:
            if url in self.images:
                document.addResource(QTextDocument.ResourceType.ImageResource, QUrl(url), self.images[url])
        body = content_html(runs, self.images, QFontMetrics(self.font).height())
        document.setHtml(f'<span style="color:{color.name()}">{body}</span>')
        style = QTextCharFormat()
        cursor = QTextCursor(document)
        if outline:
            style.setTextOutline(QPen(Qt.GlobalColor.black, outline * 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            cursor.select(QTextCursor.SelectionType.Document)
            cursor.mergeCharFormat(style)
            transparent = QImage(1, 1, QImage.Format.Format_ARGB32_Premultiplied)
            transparent.fill(Qt.GlobalColor.transparent)
            for _, url in runs:
                if url in self.images:
                    document.addResource(QTextDocument.ResourceType.ImageResource, QUrl(url), transparent)
        document.adjustSize()
        document.setTextWidth(-1)  # A rolling comment stays on one line.
        scale = self.style.dpr * self.style.sample_scale
        width = min(document.idealWidth(), int(max(128, self.style.logical_max_width))) + pad * 2
        image = QImage(math.ceil(width * scale), math.ceil((document.size().height() + pad * 2) * scale),
                       QImage.Format.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(scale)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.save()
        painter.translate(pad, pad)
        document.drawContents(painter)
        if outline:
            # Qt's text-outline pass covers thin glyph interiors; paint the
            # original colored text over it. Images are drawn only in this pass
            # so translucent emotes retain their original alpha.
            style.setTextOutline(QPen(Qt.PenStyle.NoPen))
            cursor.select(QTextCursor.SelectionType.Document)
            cursor.mergeCharFormat(style)
            for _, url in runs:
                if url in self.images:
                    document.addResource(QTextDocument.ResourceType.ImageResource, QUrl(url), self.images[url])
            document.drawContents(painter)
        painter.restore()
        if self_sent:
            self._draw_self_sent_box(painter, image)
        painter.end()
        return image

    @staticmethod
    def _draw_self_sent_box(painter: QPainter, image: QImage) -> None:
        scale = image.devicePixelRatioF()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(255, 255, 255, 225), 1.6))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(1.6, 1.6, image.width() / scale - 3.2,
                                     image.height() / scale - 3.2), 6, 6)

    def _render_text(self, text: str, color: QColor, self_sent: bool = False) -> QImage:
        font = self.font
        metrics = QFontMetrics(font)
        text = metrics.elidedText(text, Qt.TextElideMode.ElideRight, int(max(128, self.style.logical_max_width)))
        path = QPainterPath()
        path.addText(0, 0, font, text)
        bounds = path.boundingRect()
        left = min(0, bounds.left())
        top = min(-metrics.ascent(), bounds.top())
        outline = self.style.outline_width
        pad = (9 if self_sent else 4) + math.ceil(outline)
        width = max(metrics.horizontalAdvance(text), bounds.right()) - left + pad * 2
        height = max(metrics.descent(), bounds.bottom()) - top + pad * 2
        # 字形四周留出边距，避免默认字体的下沿、英文下伸部被裁切。
        scale = self.style.dpr * self.style.sample_scale
        image = QImage(math.ceil(width * scale), math.ceil(height * scale),
                       QImage.Format.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(scale)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if outline:
            painter.save()
            painter.translate(pad - left, pad - top)
            painter.strokePath(path, QPen(Qt.GlobalColor.black, outline * 2, Qt.PenStyle.SolidLine,
                                         Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.restore()
        # drawText keeps Qt's font fallback and colour Unicode emoji glyphs.
        painter.setPen(color)
        painter.setFont(font)
        painter.drawText(QPointF(pad - left, pad - top), text)
        if self_sent:
            self._draw_self_sent_box(painter, image)
        painter.end()
        return image
