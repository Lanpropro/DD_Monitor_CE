"""Host-owned translated caption overlay above native video and danmaku."""
from dataclasses import dataclass
import sys

from PySide6.QtCore import QEvent, QRect, QRectF, QPointF, QTimer, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QTextLayout, QTextOption
from PySide6.QtWidgets import QApplication

from . import theme
from .badge_surface import BadgeSurface


@dataclass(frozen=True)
class CaptionStyle:
    mode: str = "both"
    lines: int = 2
    opacity: int = 65
    width: int = 80
    height: int = 18
    font_size: int = 24

    @classmethod
    def from_value(cls, value=None):
        if isinstance(value, cls):
            return value
        data = dict(value or {})
        mode = str(data.get("mode") or "both")
        if mode not in ("both", "original", "translation"):
            mode = "both"
        return cls(
            mode=mode,
            lines=_bounded_int(data, "lines", 2, 1, 4),
            opacity=_bounded_int(data, "opacity", 65, 0, 100),
            width=_bounded_int(data, "width", 80, 20, 100),
            height=_bounded_int(data, "height", 18, 8, 45),
            font_size=_bounded_int(data, "font_size", 24, 10, 64),
        )

    def as_dict(self):
        return {
            "mode": self.mode,
            "lines": self.lines,
            "opacity": self.opacity,
            "width": self.width,
            "height": self.height,
            "font_size": self.font_size,
        }


def _bounded_int(data, key, default, low, high):
    try:
        value = int(data.get(key, default))
    except (TypeError, ValueError):
        value = default
    return max(low, min(high, value))


class VideoCaption(BadgeSurface):
    """Fixed caption surface; it never enters the scrolling danmaku list."""

    GAP = 12

    def __init__(self, owner):
        super().__init__(owner)
        self._owner = owner
        self._original = ""
        self._translated = ""
        self._style = CaptionStyle()
        self._visible_requested = True
        self._followed = set()
        self._follow_timer = QTimer(self)
        self._follow_timer.setSingleShot(True)
        self._follow_timer.timeout.connect(self.sync_geometry)
        self.setObjectName("VideoCaption")
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        if self.qt_composited:
            self.setWindowFlags(
                Qt.Tool | Qt.FramelessWindowHint
                | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus
            )
        self.hide()

    @property
    def qt_composited(self):
        return sys.platform == "win32" and QApplication.platformName() == "windows"

    def set_caption(self, original, translated="", *, style=None, visible=True):
        self._original = str(original or "")
        self._translated = str(translated or "")
        self._style = CaptionStyle.from_value(style)
        self._visible_requested = bool(visible)
        self._follow_owner()
        self.sync_geometry()
        self._sync_visibility()
        if self.isVisible():
            self.update()

    def clear_caption(self):
        self._original = ""
        self._translated = ""
        self.hide()

    def set_caption_visible(self, visible):
        self._visible_requested = bool(visible)
        self._sync_visibility()

    def _texts(self):
        original = self._original.strip()
        translated = self._translated.strip()
        if self._style.mode == "original":
            return [("original", original)] if original else []
        if self._style.mode == "translation":
            return [("translation", translated)] if translated else []
        texts = []
        if original:
            texts.append(("original", original))
        if translated:
            texts.append(("translation", translated))
        return texts

    def _line_budgets(self, keys):
        if not keys:
            return {}
        if len(keys) == 1:
            return {keys[0]: self._style.lines}
        if self._style.lines < 2:
            key = "translation" if "translation" in keys else keys[0]
            return {key: self._style.lines}
        original_lines = (self._style.lines + 1) // 2
        translation_lines = self._style.lines // 2
        return {"original": original_lines, "translation": translation_lines}

    def _font(self, height, line_budget):
        content_height = max(1, height - 2 * self._padding())
        size = min(self._style.font_size,
                   int(content_height / max(1, line_budget) / 1.35))
        size = max(8, min(64, size))
        font = QFont(theme.danmaku_font_family())
        font.setPixelSize(size)
        font.setWeight(QFont.Normal)
        return font

    def _padding(self):
        return max(6, round(self.width() * 0.018))

    def _layout(self, text, font, width, budget):
        layout = QTextLayout(text, font)
        option = QTextOption()
        option.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
        layout.setTextOption(option)
        layout.beginLayout()
        lines = []
        y = 0.0
        while len(lines) < budget:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(max(1.0, width))
            line.setPosition(QPointF(0, y))
            lines.append(line)
            y += line.height()
        layout.endLayout()
        return layout, lines

    def _render_badge(self, painter):
        if not self._texts():
            return
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        box = self.rect().adjusted(1, 1, -1, -1)
        if box.width() < 8 or box.height() < 8:
            painter.restore()
            return
        padding = self._padding()
        content_width = max(1, box.width() - 2 * padding)
        texts = self._texts()
        budgets = self._line_budgets([key for key, _text in texts])
        font = self._font(box.height(), self._style.lines)
        layouts = []
        for key, text in texts:
            if budgets.get(key, 0) <= 0:
                continue
            layer, lines = self._layout(text, font, content_width, budgets[key])
            layouts.append((key, layer, lines))

        total_height = sum(
            sum(line.height() for line in lines) + (4 if index else 0)
            for index, (_key, _layer, lines) in enumerate(layouts)
        )
        rows = []
        y = box.top() + max(padding, (box.height() - total_height) / 2)
        for index, (key, layout, lines) in enumerate(layouts):
            if index:
                y += 4
            for line in lines:
                text_width = max(0.0, min(content_width, line.naturalTextWidth()))
                x = box.left() + max(padding, (box.width() - text_width) / 2)
                rows.append((key, line, x, y, text_width))
                y += line.height()

        pad_x = max(4, round(font.pixelSize() * 0.22))
        pad_y = max(2, round(font.pixelSize() * 0.10))
        radius = max(4, min(10, round(font.pixelSize() * 0.35)))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(0, 0, 0, round(255 * self._style.opacity / 100)))
        for _key, line, x, y, text_width in rows:
            if text_width <= 0:
                continue
            painter.drawRoundedRect(
                QRectF(x - pad_x, y - pad_y,
                       text_width + 2 * pad_x, line.height() + 2 * pad_y),
                radius, radius,
            )

        painter.setFont(font)
        for key, line, x, y, _text_width in rows:
            painter.setPen(QColor("#E8F0FA" if key == "original" else "#FFFFFF"))
            line.draw(painter, QPointF(x, y))
        painter.restore()

    def _layered_render_key(self):
        return (self._original, self._translated, self._style.as_dict(),
                self.width(), self.height(), self.devicePixelRatioF())

    def _follow_owner(self):
        owner = self._owner
        if owner is None:
            return
        window = owner.window()
        widgets = {owner, window}
        for widget in self._followed - widgets:
            widget.removeEventFilter(self)
        for widget in widgets - self._followed:
            widget.installEventFilter(self)
        self._followed = widgets
        if self.qt_composited:
            parent_handle = window.windowHandle()
            handle = self.windowHandle()
            if parent_handle is not None and handle is not None:
                handle.setTransientParent(parent_handle)

    def eventFilter(self, watched, event):
        if watched in self._followed and event.type() in (
                QEvent.Move, QEvent.Resize, QEvent.Show, QEvent.Hide,
                QEvent.WindowStateChange, QEvent.WindowActivate, QEvent.WindowDeactivate):
            self._follow_timer.start(0)
        return super().eventFilter(watched, event)

    def showEvent(self, event):
        if sys.platform == "win32" and QApplication.platformName() == "windows":
            self.setAttribute(Qt.WA_NativeWindow, True)
        self._follow_owner()
        super().showEvent(event)
        self._follow_timer.start(0)

    def _safe_rect(self):
        owner = self._owner
        if owner is None:
            return None
        video = owner.video
        top = video.y() + self.GAP
        bottom = video.y() + video.height()
        if owner.property("fullscreen"):
            try:
                bottom = min(bottom, owner.bottom.tile_y())
            except (AttributeError, RuntimeError):
                pass
        bottom -= self.GAP
        if bottom - top <= 0:
            return None
        return QRect(video.x(), top, video.width(), bottom - top)

    def sync_geometry(self):
        self._follow_timer.stop()
        owner = self._owner
        if owner is None:
            self.hide()
            return
        if owner.property("pictureInPicture") or not owner.isVisible():
            self.hide()
            return
        area = self._safe_rect()
        if area is None:
            self.hide()
            return
        box_width = max(1, round(area.width() * self._style.width / 100))
        box_height = max(1, round(area.height() * self._style.height / 100))
        box_width = min(box_width, area.width())
        box_height = min(box_height, area.height())
        local = QRect(
            area.x() + max(0, (area.width() - box_width) // 2),
            area.y() + max(0, area.height() - box_height),
            box_width,
            box_height,
        )
        if self.qt_composited:
            self.setGeometry(QRect(owner.mapToGlobal(local.topLeft()), local.size()))
        else:
            self.setGeometry(local)
        self._sync_visibility()

    def _sync_visibility(self):
        owner = self._owner
        visible = bool(
            self._visible_requested
            and self._texts()
            and owner is not None
            and owner.isVisible()
            and owner.window().isVisible()
            and not owner.window().isMinimized()
            and not owner.property("pictureInPicture")
        )
        if visible:
            self._follow_owner()
            self.show()
            self.raise_()
        else:
            self.hide()
