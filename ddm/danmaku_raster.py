"""Thread-local image painting for video comments; no QWidget or QPixmap access."""
import math

from PySide6.QtCore import QObject, QPointF, QRectF, QRunnable, Qt, QUrl, Signal
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QFontMetricsF, QImage, QPainter, QPainterPath,
                          QPen, QTextCharFormat, QTextCursor, QTextDocument)

from .danmaku_content import content_html
from .corner_geometry import continuous_path
from . import theme


class CommentRaster:
    def __init__(self, font, outline, scale, limit, images):
        self.font, self.outline = theme.danmaku_font(str(font.family())), outline
        self.font.setPixelSize(font.pixelSize())
        self.scale, self.limit = scale, limit
        self._images = {url: QImage(image) for url, image in images.items()}

    def key(self, text, color, runs, self_sent):
        loaded = tuple((url, self._images[url].cacheKey()) for _, url in runs if url in self._images)
        content = (text, tuple(runs), loaded, self.limit) if loaded else (
            QFontMetrics(self.font).elidedText(text, Qt.ElideRight, self.limit),)
        return self.font.toString(), self.outline, self.scale, color.rgba(), self_sent, content

    def _render_content(self, text, color, runs, self_sent=False) -> QImage:
        if not any(url in self._images for _, url in runs if url):
            return self._render_text(text, color, self_sent)
        outline = self.outline
        pad = (9 if self_sent else 4) + math.ceil(outline)
        document = QTextDocument()
        document.setDefaultFont(self.font)
        document.setDocumentMargin(0)
        for _, url in runs:
            if url in self._images:
                document.addResource(QTextDocument.ImageResource, QUrl(url), self._images[url])
        body = content_html(runs, self._images, QFontMetrics(self.font).height())
        document.setHtml(f'<span style="color:{color.name()}">{body}</span>')
        if outline:
            style = QTextCharFormat()
            style.setTextOutline(QPen(Qt.black, outline * 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            cursor = QTextCursor(document)
            cursor.select(QTextCursor.Document)
            cursor.mergeCharFormat(style)
            transparent = QImage(1, 1, QImage.Format_ARGB32_Premultiplied)
            transparent.fill(Qt.transparent)
            for _, url in runs:
                if url in self._images:
                    document.addResource(QTextDocument.ImageResource, QUrl(url), transparent)
        document.adjustSize()
        document.setTextWidth(-1)  # A rolling comment stays on one line.
        scale = self.scale
        width = min(document.idealWidth(), self.limit) + pad * 2
        image = QImage(math.ceil(width * scale), math.ceil((document.size().height() + pad * 2) * scale), QImage.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(scale)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        painter.save()
        painter.translate(pad, pad)
        document.drawContents(painter)
        if outline:
            # Qt's text-outline pass covers thin glyph interiors; paint the
            # original colored text over it. Images are drawn only in this pass
            # so translucent emotes retain their original alpha.
            style.setTextOutline(QPen(Qt.NoPen))
            cursor.select(QTextCursor.Document)
            cursor.mergeCharFormat(style)
            for _, url in runs:
                if url in self._images:
                    document.addResource(QTextDocument.ImageResource, QUrl(url), self._images[url])
            document.drawContents(painter)
        painter.restore()
        if self_sent:
            self._draw_self_sent_box(painter, image)
        painter.end()
        return image

    @staticmethod
    def _draw_self_sent_box(painter, image):
        scale = image.devicePixelRatioF()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor(255, 255, 255, 225), 1.6))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(continuous_path(QRectF(1.6, 1.6, image.width() / scale - 3.2,
                                              image.height() / scale - 3.2), 6))

    def _render_text(self, text: str, color: QColor, self_sent=False) -> QImage:
        font = self.font
        metrics = QFontMetrics(font)
        text = metrics.elidedText(text, Qt.ElideRight, self.limit)
        runs = theme.danmaku_font_runs(text, font)
        paths = []
        advance = 0.0
        bounds = QRectF()
        descent = 0
        for run_text, run_font in runs:
            path = QPainterPath()
            path.addText(advance, 0, run_font, run_text)
            paths.append((advance, run_text, run_font, path))
            bounds = path.boundingRect() if bounds.isNull() else bounds.united(path.boundingRect())
            advance += QFontMetricsF(run_font).horizontalAdvance(run_text)
            descent = max(descent, QFontMetrics(run_font).descent())
        left = min(0, bounds.left())
        top = min(-metrics.ascent(), bounds.top())
        outline = self.outline
        pad = (9 if self_sent else 4) + math.ceil(outline)
        width = max(advance, bounds.right()) - left + pad * 2
        height = max(descent, bounds.bottom()) - top + pad * 2
        # 字形四周留出边距，避免默认字体的下沿、英文下伸部被裁切。
        scale = self.scale
        image = QImage(math.ceil(width * scale), math.ceil(height * scale), QImage.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(scale)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)
        if outline:
            painter.save()
            painter.translate(pad - left, pad - top)
            for _, _, _, path in paths:
                painter.strokePath(path, QPen(Qt.black, outline * 2, Qt.SolidLine,
                                             Qt.RoundCap, Qt.RoundJoin))
            painter.restore()
        # Draw each glyph run with a font that contains the codepoint.
        painter.setPen(color)
        for x, run_text, run_font, _ in paths:
            painter.setFont(run_font)
            painter.drawText(QPointF(pad - left + x, pad - top), run_text)
        if self_sent:
            self._draw_self_sent_box(painter, image)
        painter.end()
        return image


class _RasterSignals(QObject):
    finished = Signal(object)


class CommentRasterJob(QRunnable):
    def __init__(self, renderer, rows):
        super().__init__()
        self.renderer, self.rows = renderer, rows
        self.signals = _RasterSignals()

    def run(self):
        result = None
        try:
            images = []
            for identifier, key, text, color, runs, self_sent in self.rows:
                if key is None:
                    key = self.renderer.key(text, color, runs, self_sent)
                images.append((identifier, key, self.renderer._render_content(
                    text, color, runs, self_sent)))
            result = images
        finally:
            self.signals.finished.emit(result)
