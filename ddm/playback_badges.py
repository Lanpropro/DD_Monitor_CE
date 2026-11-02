"""Playback status badges; independent of tile, wall, sidebar and player ownership."""
import os
import sys

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QMovie, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel

from . import theme
from .badge_surface import BadgeSurface


BADGE_HEIGHT = 24             # 左上角浮标高度

HOLE_SIZE = 16                # 浮标左侧圆形镂空直径

HOLE_MARGIN = 4

ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")

def _badge_font() -> QFont:
    """画面浮标用的字体。

    量文字宽度和画文字都必须用它，**不能用 `widget.fontMetrics()`**：
    QSS 里的 font-size 是 polish 之后才落到控件上的，构造时量出来的宽度会偏小，
    等真正画的时候字变大，人数就被自己的遮罩截掉了（用户报的「人数被遮挡」）。
    """
    font = QFont(theme.FONT_DEFAULT)
    font.setPixelSize(theme.FONT_CONTROL)
    return font

class StreamBadge(BadgeSurface):
    """画面左上角的浮标：左侧同心圆环，右边是 LIVE 和直播间人数。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.live = True
        self.offline = False
        self.viewers = ""
        self._mask_path = QPainterPath()
        self._rebuild()

    def set_state(self, live: bool, viewers: str = "") -> None:
        changed = ((live != self.live) or ((viewers or "") != self.viewers)
                   or self.offline)
        self.offline = False
        self.live = live
        self.viewers = viewers or ""
        if changed:
            self._rebuild()
            self.update()

    def set_offline(self) -> None:
        """这一路刚下播：浮标显示"已下播"。"""
        self.offline = True
        self.live = False
        self.viewers = ""
        self._rebuild()
        self.update()

    def set_compact(self, compact: bool) -> None:
        """格子窄的时候只留 LIVE，不显示人数。"""
        compact = bool(compact)
        if compact == getattr(self, "_compact", False):
            return
        self._compact = compact
        self._rebuild()
        self.update()

    def full_width(self) -> int:
        """不压缩时（带人数）需要的宽度，用来判断放不放得下。"""
        metrics = QFontMetrics(_badge_font())
        meta = self.viewers if (self.live and self.viewers) else ""
        width = HOLE_MARGIN * 2 + HOLE_SIZE + 6 + metrics.horizontalAdvance("LIVE")
        if meta:
            width += 8 + metrics.horizontalAdvance(meta)
        return width + 10

    def _text(self) -> str:
        if self.offline:
            return "已下播"
        return "LIVE" if self.live else "未开播"

    def _rebuild(self) -> None:
        metrics = QFontMetrics(_badge_font())
        meta = ""
        if self.live and self.viewers and not getattr(self, "_compact", False):
            meta = self.viewers
        width = HOLE_MARGIN * 2 + HOLE_SIZE + 6 + metrics.horizontalAdvance(self._text())
        if meta:
            width += 8 + metrics.horizontalAdvance(meta)
        width += 10
        self.resize(width, BADGE_HEIGHT)

        pill = QPainterPath()
        pill.addRoundedRect(QRectF(0, 0, width, BADGE_HEIGHT),
                            BADGE_HEIGHT / 2, BADGE_HEIGHT / 2)
        # 圆环和圆点在 paintEvent 里用同一个中心画；不再把圆孔做成遮罩，
        # 避免路径转整数 QRegion 后圆孔边缘与抗锯齿圆点错开 1px。
        self._mask_path = pill
        self.refresh_theme()

    def paint_badge(self, painter) -> None:
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillPath(self.badge_path, theme.overlay_color("#15171c", "#F7F9FC"))
        dot = HOLE_MARGIN + HOLE_SIZE / 2
        center = QPointF(dot, BADGE_HEIGHT / 2)
        painter.setPen(QPen(QColor("#7b828c"), 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(center, HOLE_SIZE / 2 - 1, HOLE_SIZE / 2 - 1)
        painter.setBrush(theme.overlay_color("#fb7299", "#B93665") if self.live else QColor("#7b828c"))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(center, 4.5, 4.5)
        font = _badge_font()
        painter.setFont(font)
        metrics = QFontMetrics(font)
        x = float(HOLE_MARGIN * 2 + HOLE_SIZE + 6)
        painter.setPen(theme.overlay_color("#fb7299", "#B93665"))
        painter.drawText(QRectF(x, 0, 120, BADGE_HEIGHT),
                         int(Qt.AlignVCenter | Qt.AlignLeft), self._text())
        if self.live and self.viewers:
            x += metrics.horizontalAdvance(self._text()) + 8
            painter.setPen(theme.overlay_color("#e6e9ef", "#202630"))
            painter.drawText(QRectF(x, 0, 120, BADGE_HEIGHT),
                             int(Qt.AlignVCenter | Qt.AlignLeft), self.viewers)

class TimeBadge(BadgeSurface):
    """画面右下角的直播时长浮标（和 LIVE 浮标同款样式）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.text = ""
        self._mask_path = QPainterPath()
        self._rebuild()

    def set_text(self, text: str) -> None:
        text = text or ""
        if text == self.text:
            return
        self.text = text
        self._rebuild()
        self.update()

    def _rebuild(self) -> None:
        metrics = QFontMetrics(_badge_font())
        width = metrics.horizontalAdvance(self.text or "0:00:00") + 20
        self.resize(width, BADGE_HEIGHT)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, width, BADGE_HEIGHT),
                            BADGE_HEIGHT / 2, BADGE_HEIGHT / 2)
        self._mask_path = path
        self.refresh_theme()

    def paint_badge(self, painter) -> None:
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillPath(self.badge_path, theme.overlay_color("#15171c", "#F7F9FC"))
        painter.setPen(theme.overlay_color("#d7dbe2", "#4A5565"))
        painter.setFont(_badge_font())
        painter.drawText(self.rect(), int(Qt.AlignCenter), self.text)

class LoadingLabel(QLabel):
    """保留布局和字体信息，由浮层统一绘制到带 Alpha 的画布。"""

    def paintEvent(self, event):
        pass

class LoadingIndicator(BadgeSurface):
    """缓冲动画：沿用 BewlyCat 的 loading.gif + 文案，样式与整体一致。"""

    def __init__(self, parent=None, text: str = "连接中…", icon: bool = True):
        super().__init__(parent)
        self.setObjectName("LoadingIndicator")
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self._mask_path = QPainterPath()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12 if icon else 14, 7, 16 if icon else 14, 7)
        layout.setSpacing(8)
        self._icon = LoadingLabel(self) if icon else None
        self._movie = None
        if self._icon is not None:
            self._movie = QMovie(os.path.join(ASSETS_DIR, "loading.gif"))
            self._icon.setFixedSize(32, 32)
            self._movie.setScaledSize(QSize(32, 32))
            self._icon.setMovie(self._movie)
            self._movie.frameChanged.connect(self.update)
            layout.addWidget(self._icon)
        self._text = LoadingLabel(text)
        self._text.setObjectName("LoadingText")
        layout.addWidget(self._text)
        self.setVisible(False)

    def start(self) -> None:
        if self._movie is not None:
            scale = self.devicePixelRatioF()
            self._movie.setScaledSize(QSize(round(32 * scale), round(32 * scale)))
        if self._movie is not None and self._movie.isValid():
            self._movie.start()
        self.adjustSize()
        self._apply_mask()
        self.setVisible(True)
        self.raise_()

    def stop(self) -> None:
        if self._movie is not None:
            self._movie.stop()
        self.setVisible(False)

    def _apply_mask(self) -> None:
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, self.width(), self.height()),
                            self.height() / 2, self.height() / 2)
        self._mask_path = path
        self.clearMask()

    def refresh_theme(self):
        self.clearMask()
        if getattr(self, '_movie', None) is not None:
            scale = self.devicePixelRatioF()
            self._movie.setScaledSize(QSize(round(32 * scale), round(32 * scale)))
        self.update()

    def _render_badge(self, painter):
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.setOpacity(205 / 255)
        painter.fillPath(self._mask_path, theme.overlay_color('#1b1e24', '#F7F9FC'))
        if self._movie is not None:
            pixmap = self._movie.currentPixmap()
            painter.drawPixmap(self._icon.geometry(), pixmap, pixmap.rect())
        painter.setFont(self._text.font())
        painter.setPen(theme.qcolor(theme.TEXT2))
        painter.drawText(self._text.geometry(), Qt.AlignCenter, self._text.text())

    def paintEvent(self, event):
        if sys.platform == 'win32' and QApplication.platformName() == 'windows':
            self._schedule_layered_paint()
        else:
            painter = QPainter(self)
            self._render_badge(painter)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_mask()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self.testAttribute(Qt.WA_NativeWindow):
            self.setAttribute(Qt.WA_NativeWindow, True)
        self.update()

class TitleBadge(BadgeSurface):
    """浮在画面上的标题条：主播名 + 直播间标题，摆在 LIVE 浮标右侧。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.uname = ""
        self.title = ""
        self._name_text = ""
        self._title_text = ""
        self._max_width = 320
        self._mask_path = QPainterPath()
        self.setVisible(False)

    def set_text(self, uname: str, title: str) -> None:
        uname = uname or ""
        title = title or ""
        if (uname, title) == (self.uname, self.title):
            return
        self.uname, self.title = uname, title
        self._rebuild()

    def set_max_width(self, width: int) -> None:
        if width == self._max_width:
            return
        self._max_width = max(60, int(width))
        self._rebuild()

    def _rebuild(self) -> None:
        metrics = self.fontMetrics()
        limit = self._max_width - 20
        name = self.uname
        if metrics.horizontalAdvance(name) > limit * 0.5:
            name = metrics.elidedText(name, Qt.ElideRight, int(limit * 0.5))
        self._name_text = name
        self._title_text = ""
        if self.title:
            used = metrics.horizontalAdvance(name + " · ")
            room = limit - used
            if room > 24:
                self._title_text = metrics.elidedText(self.title, Qt.ElideRight, int(room))
        text = self._name_text + (" · " + self._title_text if self._title_text else "")
        width = min(self._max_width, metrics.horizontalAdvance(text) + 20)
        self.resize(max(60, width), BADGE_HEIGHT)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, self.width(), BADGE_HEIGHT),
                            BADGE_HEIGHT / 2, BADGE_HEIGHT / 2)
        self._mask_path = path
        self.refresh_theme()
        self.update()

    def paint_badge(self, painter) -> None:
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillPath(self.badge_path, theme.overlay_color("#15171c", "#F7F9FC"))
        metrics = self.fontMetrics()
        x = 10
        painter.setPen(theme.overlay_color("#eef1f5", "#202630"))
        painter.drawText(QRectF(x, 0, self.width(), BADGE_HEIGHT),
                         int(Qt.AlignVCenter | Qt.AlignLeft), self._name_text)
        if self._title_text:
            x += metrics.horizontalAdvance(self._name_text)
            painter.setPen(theme.overlay_color("#98a0ab", "#4A5565"))
            painter.drawText(QRectF(x, 0, self.width() - x, BADGE_HEIGHT),
                             int(Qt.AlignVCenter | Qt.AlignLeft),
                             " · " + self._title_text)
