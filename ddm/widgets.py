"""界面组件：侧栏（可收起 / 批量选择）、顶栏、画面格子、自适应网格、布局选择器。"""
import math
import os
import platform
import sys
import time

from PySide6.QtCore import (
    QEasingCurve, QMimeData, QPoint, QPointF, QPropertyAnimation, QRect, QRectF, QSize, Qt,
    QTimer, QUrl, Signal,
)
from PySide6.QtGui import (
    QAction, QActionGroup, QColor, QCursor, QDrag, QFont, QFontMetrics, QIcon, QLinearGradient,
    QMovie, QPainter, QPainterPath, QPen, QPixmap, QPolygonF, QRegion, QTextDocument,
)
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMenu,
    QPushButton, QScrollArea, QSizePolicy, QSlider, QTextBrowser, QToolButton, QVBoxLayout,
    QWidget, QWidgetAction,
)

from . import layouts, theme
from .images import AvatarLoader
from .player import TilePlayer

AVATAR_COLORS = ["#4c6ef5", "#12b886", "#f76707", "#ae3ec9", "#1098ad", "#e8590c", "#5f3dc4"]

QUALITY_CHOICES = [("原画", 10000), ("蓝光", 400), ("超清 720P", 250), ("流畅", 80)]
QUALITY_NAMES = {value: name for name, value in QUALITY_CHOICES}

TILE_BAR_HEIGHT = 36          # 底部信息条高度（不覆盖画面）
ROOM_MIME = "application/x-ddm-room"
TILE_MIME = "application/x-ddm-tile"
DANMAKU_MIME = "application/x-ddm-danmaku"
NAV_MIME = "application/x-ddm-nav"          # 关注列表内部排序用

BADGE_HEIGHT = 24             # 左上角浮标高度
WATCHING_TEXT = "正在获取人数"   # 还没拉到实时在线人数时的占位（不能用"人气"顶上）
NAV_ITEM_HEIGHT = 128         # 展开时：206x116 左右，接近 16:9，悬停预览才看得清
NAV_LIST_ITEM_HEIGHT = 60     # 简洁模式：头像 + 两行文字
NAV_COMPACT_ITEM_HEIGHT = 60  # 收起时保持此前的头像间距和滚动手感
NAV_ITEM_GAP = 2              # 项与项之间的间距
HOLE_SIZE = 16                # 浮标左侧圆形镂空直径
HOLE_MARGIN = 4
ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")


def _brightness(color: str) -> int:
    """这个颜色够不够亮（用来决定徽章上写黑字还是白字）。"""
    text = str(color).lstrip("#")
    if len(text) != 6:
        return 0
    try:
        red, green, blue = (int(text[index:index + 2], 16) for index in (0, 2, 4))
    except ValueError:
        return 0
    return (red * 299 + green * 587 + blue * 114) // 1000


def _is_running(thread) -> bool:
    """QThread 已经被 Qt 回收时也算没在跑。"""
    try:
        return thread.isRunning()
    except RuntimeError:
        return False


def _medal_chip(name: str, level: str, color: str, font_size: int) -> QPixmap:
    """粉丝牌底：圆角小色块 + 名字和等级。

    QTextDocument 的富文本不支持圆角，所以直接把牌子画成图片贴进弹幕行里。
    """
    font = QFont(theme.FONT_DEFAULT)
    font.setPixelSize(max(8, round(font_size * 0.82)))
    font.setBold(True)
    text = f"{name}{level}"
    metrics = QFontMetrics(font)
    padding = max(4, round(font_size * 0.42))
    height = max(12, round(font_size * 1.45))
    width = metrics.horizontalAdvance(text) + padding * 2
    pixmap = QPixmap(width, height)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    radius = max(3.0, height * 0.28)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, width, height), radius, radius)
    painter.fillPath(path, QColor(color))
    painter.setPen(QColor("#14161a" if _brightness(color) > 150 else "#ffffff"))
    painter.setFont(font)
    painter.drawText(QRectF(0, 0, width, height), int(Qt.AlignCenter), text)
    painter.end()
    return pixmap


def circular_pixmap(source: QPixmap, size: int) -> QPixmap:
    """把头像裁成圆形（和 B 站网页一致）。"""
    scaled = source.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    result = QPixmap(size, size)
    result.fill(Qt.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.Antialiasing, True)
    path = QPainterPath()
    path.addEllipse(0, 0, size, size)
    painter.setClipPath(path)
    painter.drawPixmap((size - scaled.width()) // 2, (size - scaled.height()) // 2, scaled)
    painter.end()
    return result


class StreamBadge(QWidget):
    """画面左上角的浮标：左侧圆形镂空，右边是 LIVE 和直播间人数。"""

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
        metrics = self.fontMetrics()
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
        metrics = self.fontMetrics()
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
        hole = QPainterPath()
        hole.addEllipse(QRectF(HOLE_MARGIN, HOLE_MARGIN, HOLE_SIZE, HOLE_SIZE))
        # 遮罩 = （胶囊 − 圆孔）+ 孔中央的实心圆点，否则圆点会被一起裁掉
        dot_center = HOLE_MARGIN + HOLE_SIZE / 2
        dot = QPainterPath()
        dot.addEllipse(QRectF(dot_center - 4.5, BADGE_HEIGHT / 2 - 4.5, 9, 9))
        self._mask_path = pill.subtracted(hole).united(dot)
        self.setMask(QRegion(self._mask_path.toFillPolygon().toPolygon()))

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillPath(self._mask_path, QColor("#15171c"))
        # 镂空里放一个实心圆点（相当于先扣出一个圆弧，再在中间点一个点）
        dot = HOLE_MARGIN + HOLE_SIZE / 2
        painter.setBrush(QColor("#fb7299" if self.live else "#7b828c"))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QRectF(dot - 4.5, BADGE_HEIGHT / 2 - 4.5, 9, 9))
        metrics = self.fontMetrics()
        x = float(HOLE_MARGIN * 2 + HOLE_SIZE + 6)
        painter.setPen(QColor("#fb7299"))
        painter.drawText(QRectF(x, 0, 120, BADGE_HEIGHT),
                         int(Qt.AlignVCenter | Qt.AlignLeft), self._text())
        if self.live and self.viewers:
            x += metrics.horizontalAdvance(self._text()) + 8
            painter.setPen(QColor("#e6e9ef"))
            painter.drawText(QRectF(x, 0, 120, BADGE_HEIGHT),
                             int(Qt.AlignVCenter | Qt.AlignLeft), self.viewers)


class TimeBadge(QWidget):
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
        metrics = self.fontMetrics()
        width = metrics.horizontalAdvance(self.text or "0:00:00") + 20
        self.resize(width, BADGE_HEIGHT)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, width, BADGE_HEIGHT),
                            BADGE_HEIGHT / 2, BADGE_HEIGHT / 2)
        self._mask_path = path
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillPath(self._mask_path, QColor("#15171c"))
        painter.setPen(QColor("#d7dbe2"))
        painter.drawText(self.rect(), int(Qt.AlignCenter), self.text)


class LoadingIndicator(QWidget):
    """缓冲动画：沿用 BewlyCat 的 loading.gif + 文案，样式与整体一致。"""

    def __init__(self, parent=None, text: str = "连接中…", icon: bool = True):
        super().__init__(parent)
        self.setObjectName("LoadingIndicator")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12 if icon else 14, 7, 16 if icon else 14, 7)
        layout.setSpacing(8)
        self._icon = QLabel(self) if icon else None
        self._movie = None
        if self._icon is not None:
            self._movie = QMovie(os.path.join(ASSETS_DIR, "loading.gif"))
            self._icon.setFixedSize(32, 32)
            self._movie.setScaledSize(QSize(32, 32))
            self._icon.setMovie(self._movie)
            layout.addWidget(self._icon)
        self._text = QLabel(text)
        self._text.setObjectName("LoadingText")
        layout.addWidget(self._text)
        self.setVisible(False)

    def start(self) -> None:
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
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_mask()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self.testAttribute(Qt.WA_NativeWindow):
            self.setAttribute(Qt.WA_NativeWindow, True)
        self._apply_layered_alpha()

    def _apply_layered_alpha(self) -> None:
        """整层半透明：Qt 的子窗口没有逐像素透明，Windows 上借分层窗口实现。"""
        if platform.system() != "Windows":
            return
        try:
            import ctypes

            hwnd = int(self.winId())
            user32 = ctypes.windll.user32
            style = user32.GetWindowLongW(hwnd, -20)          # GWL_EXSTYLE
            user32.SetWindowLongW(hwnd, -20, style | 0x00080000)   # WS_EX_LAYERED
            user32.SetLayeredWindowAttributes(hwnd, 0, 205, 0x00000002)  # LWA_ALPHA
        except Exception:  # noqa: BLE001
            pass


class VolumeButton(QPushButton):
    """音量按钮：细线喇叭 + 声道标记，静音时喇叭右边打一个 ×。

    点击切换静音，滚轮调音量；声道（原始 / 仅左 / 仅右）由右键菜单切换，
    这里只用 L / R 标出当前在听哪一路。
    """

    volumeChanged = Signal(int)

    CHANNEL_LEFT = 3
    CHANNEL_RIGHT = 4

    def __init__(self, parent=None, size: int = theme.CONTROL_HEIGHT):
        super().__init__(parent)
        self.setObjectName("BiliVolumeButton")
        self._size = size
        # 喇叭 + 右边的 L / R 两个标记：比纯图标按钮宽一点，字才不会贴边
        self.setFixedSize(size + (8 if size >= 30 else 14), size)
        self.setCursor(Qt.PointingHandCursor)
        self.muted = False
        self.level = 42
        self.audio_channel = 0
        self._update_tooltip()

    def set_state(self, muted: bool, level: int, audio_channel: int = 0) -> None:
        self.muted = bool(muted)
        self.level = max(0, min(100, int(level)))
        self.audio_channel = int(audio_channel)
        self._update_tooltip()
        self.update()

    def _update_tooltip(self) -> None:
        state = "已静音" if self.muted else f"音量 {self.level}"
        channel = {
            self.CHANNEL_LEFT: "　仅左声道",
            self.CHANNEL_RIGHT: "　仅右声道",
        }.get(self.audio_channel, "")
        self.setToolTip(f"{state}{channel}　（点击静音，滚轮调音量，右键调声道）")

    def wheelEvent(self, event) -> None:
        step = 5 if event.angleDelta().y() > 0 else -5
        self.level = max(0, min(100, self.level + step))
        self.muted = self.level == 0
        self._update_tooltip()
        self.update()
        self.volumeChanged.emit(self.level)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)          # 背景由样式表画
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        # B 站播放器风格：细线喇叭；悬停时切成主题蓝。
        color = QColor("#9499a0" if self.muted else "#f1f2f3")
        if self.underMouse():
            color = QColor(theme.ACCENT)
        pen = QPen(color, 1.7)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        center = self.rect().center()
        left = center.x() - 8
        top = center.y() - 6
        path = QPainterPath()
        path.moveTo(left, top + 4)
        path.lineTo(left + 3.5, top + 4)
        path.lineTo(left + 8, top)
        path.lineTo(left + 8, top + 12)
        path.lineTo(left + 3.5, top + 8)
        path.lineTo(left, top + 8)
        path.closeSubpath()
        painter.drawPath(path)
        if self.muted:
            # 静音：喇叭右边一个 ×（不再用斜线划掉整只喇叭）。
            cross = center.y() - 3.5
            right = center.x() + 8.5
            painter.drawLine(right, cross, right + 7, cross + 7)
            painter.drawLine(right + 7, cross, right, cross + 7)
        else:
            self._paint_channel(painter, top, left)

    def _paint_channel(self, painter: QPainter, top: float, left: float) -> None:
        """在喇叭右边标出当前声道：L / R，选中的那一路更亮。"""
        font = QFont(theme.FONT_DEFAULT)
        font.setPixelSize(8)
        font.setBold(True)
        painter.setFont(font)
        for label, x, selected in (
            ("L", left + 10.0, self.audio_channel == self.CHANNEL_LEFT),
            ("R", left + 15.5, self.audio_channel == self.CHANNEL_RIGHT),
        ):
            if selected:
                colour = QColor(theme.ACCENT)
            else:
                colour = QColor("#9499a0" if self.muted else "#6d737d")
                colour.setAlpha(150)
            painter.setPen(colour)
            painter.drawText(QRectF(x, top + 2, 7, 9), int(Qt.AlignCenter), label)



def _icon_color(button: QPushButton, hover_dark: bool = True) -> QColor:
    """图标颜色：平时浅色；悬停时按钮底变成主题色，图标要反过来用深色。"""
    if button.underMouse() or button.property("hovered") is True:
        return QColor("#04161f") if hover_dark else QColor(theme.ACCENT)
    return QColor("#e7ebf0")


class PauseButton(QPushButton):
    """暂停 / 继续：最常见的 ⏸ / ▶ 图形按钮。"""

    def __init__(self, parent=None, size: int = theme.TILE_CONTROL_HEIGHT):
        super().__init__(parent)
        self.setObjectName("TileCtrl")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(size + 8, size)
        self.paused = False
        self._update_tooltip()

    def set_paused(self, paused: bool) -> None:
        self.paused = bool(paused)
        self._update_tooltip()
        self.update()

    def _update_tooltip(self) -> None:
        self.setToolTip("继续播放" if self.paused else "暂停这一路")

    def paintEvent(self, event) -> None:
        super().paintEvent(event)          # 背景交给样式表
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(_icon_color(self))
        center = self.rect().center()
        if self.paused:
            # ▶ 继续
            path = QPainterPath()
            path.moveTo(center.x() - 4, center.y() - 6)
            path.lineTo(center.x() + 6, center.y())
            path.lineTo(center.x() - 4, center.y() + 6)
            path.closeSubpath()
            painter.drawPath(path)
        else:
            # ⏸ 暂停
            painter.drawRoundedRect(
                QRectF(center.x() - 5.2, center.y() - 6, 3.6, 12), 1.3, 1.3)
            painter.drawRoundedRect(
                QRectF(center.x() + 1.6, center.y() - 6, 3.6, 12), 1.3, 1.3)


class RefreshButton(QPushButton):
    """刷新：两个箭头首尾相接的圆环图标。"""

    def __init__(self, parent=None, size: int = theme.TILE_CONTROL_HEIGHT,
                 object_name: str = "TileCtrl"):
        super().__init__(parent)
        self.setObjectName(object_name)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(size + (6 if size < 30 else 8), size)
        self.setToolTip("刷新")

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        center = self.rect().center()
        color = _icon_color(self)
        radius = min(7.0, self.height() / 2 - 5)
        rect = QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2)
        pen = QPen(color, 1.7)
        pen.setCapStyle(Qt.FlatCap)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawArc(rect, 40 * 16, 140 * 16)
        painter.drawArc(rect, 220 * 16, 140 * 16)
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        for angle, direction in ((40, -1), (220, -1)):
            _draw_arrow_head(painter, center, radius, angle, direction)


def _draw_arrow_head(painter: QPainter, center, radius: float, angle: float,
                     direction: int, size: float = 3.4) -> None:
    """在圆环的指定角度处画一个顺着切线的箭头。"""
    radians = math.radians(angle)
    x = center.x() + radius * math.cos(radians)
    y = center.y() - radius * math.sin(radians)
    tangent = math.radians(angle + 90 * direction)
    tip = QPointF(x + size * math.cos(tangent), y - size * math.sin(tangent))
    left = QPointF(x + size * 0.95 * math.cos(tangent + 2.4),
                   y - size * 0.95 * math.sin(tangent + 2.4))
    right = QPointF(x + size * 0.95 * math.cos(tangent - 2.4),
                    y - size * 0.95 * math.sin(tangent - 2.4))
    painter.drawPolygon(QPolygonF([tip, left, right]))


class TitleBadge(QWidget):
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
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillPath(self._mask_path, QColor("#15171c"))
        metrics = self.fontMetrics()
        x = 10
        painter.setPen(QColor("#eef1f5"))
        painter.drawText(QRectF(x, 0, self.width(), BADGE_HEIGHT),
                         int(Qt.AlignVCenter | Qt.AlignLeft), self._name_text)
        if self._title_text:
            x += metrics.horizontalAdvance(self._name_text)
            painter.setPen(QColor("#98a0ab"))
            painter.drawText(QRectF(x, 0, self.width() - x, BADGE_HEIGHT),
                             int(Qt.AlignVCenter | Qt.AlignLeft),
                             " · " + self._title_text)


class DanmakuTextBrowser(QTextBrowser):
    """能告诉面板“用户正在查看旧弹幕”的文本区。"""

    userScrolled = Signal()

    def wheelEvent(self, event) -> None:
        super().wheelEvent(event)
        self.userScrolled.emit()

    def keyPressEvent(self, event) -> None:
        super().keyPressEvent(event)
        self.userScrolled.emit()


class DanmakuPanel(QFrame):
    """弹幕格：占画面墙里的一整格，风格和别的格子统一。

    内容是主画面那一路的弹幕（app.py 里的 sync_danmaku 负责连谁）。
    整格可以像别的窗口一样拖动，换到别的格子上。
    """

    MAX_BLOCKS = 300          # 默认最多留多少条（设置里可改）
    MIN_BLOCKS = 20
    EMOTICON_HEIGHT = 22      # 表情在弹幕里的显示高度
    BASE_FONT_SIZE = 13       # 默认弹幕字号
    MIN_FONT_SIZE = 8
    MAX_FONT_SIZE = 32
    KIND_COLORS = {           # 不同消息的配色：弹幕蓝、礼物粉、上舰紫、SC 橙
        "danmaku": theme.ACCENT,
        "gift": theme.PINK,
        "guard": "#c084fc",
        "super_chat": theme.WARNING,
    }

    roomDropped = Signal(str)          # 有直播间被拖到弹幕格上
    fontSizeChanged = Signal(int)      # 面板上的字号滑块被拖动

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DanmakuPanel")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAcceptDrops(True)
        self.setCursor(Qt.OpenHandCursor)
        self._status = "未接入"
        self._received = 0
        self._blocks: list[dict] = []            # 每条消息的原始信息，表情下好之后整体重排
        self._images: dict = {}                  # 表情图 / 粉丝牌底图：url -> 图片
        self._loading_emoticons: set[str] = set()
        self._emoticon_loaders: list = []
        self._has_content = False
        self._base_size = self.BASE_FONT_SIZE
        self._font_family = theme.FONT_DEFAULT
        self.max_blocks = self.MAX_BLOCKS
        self._follow_tail = True
        self._scroll_dragging = False
        self._scroll_revision = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QWidget(self)
        header.setObjectName("DanmakuHeader")
        header.setAttribute(Qt.WA_StyledBackground, True)
        header.setFixedHeight(32)
        header_box = QHBoxLayout(header)
        header_box.setContentsMargins(10, 0, 10, 0)
        header_box.setSpacing(6)
        dot = QLabel("●")
        dot.setObjectName("DanmakuDot")
        title = QLabel("弹幕")
        title.setObjectName("DanmakuTitle")
        self.count = QLabel("未接入")
        self.count.setObjectName("DanmakuCount")
        self.count.setProperty("state", "idle")
        self.count.setFixedHeight(20)
        header_box.addWidget(dot)
        header_box.addWidget(title)
        header_box.addStretch(1)
        header_box.addWidget(self.count, 0, Qt.AlignVCenter)
        layout.addWidget(header)

        self.body = DanmakuTextBrowser(self)
        self.body.setObjectName("DanmakuBody")
        self.body.setFrameShape(QFrame.NoFrame)
        self.body.setOpenExternalLinks(False)
        self.body.document().setDocumentMargin(8)
        self.body.userScrolled.connect(self._on_user_scroll)
        scroll_bar = self.body.verticalScrollBar()
        scroll_bar.sliderPressed.connect(self._on_scroll_pressed)
        scroll_bar.sliderReleased.connect(self._on_scroll_released)
        scroll_bar.valueChanged.connect(self._on_scroll_value_changed)
        layout.addWidget(self.body, 1)

        # 底部条：字号滑块（跟格子的音量条一个做法，拖了立刻生效）
        self.bar = QWidget(self)
        self.bar.setObjectName("DanmakuBar")
        self.bar.setAttribute(Qt.WA_StyledBackground, True)
        self.bar.setFixedHeight(32)
        bar_box = QHBoxLayout(self.bar)
        bar_box.setContentsMargins(10, 0, 10, 0)
        bar_box.setSpacing(8)
        bar_box.addStretch(1)
        size_label = QLabel("字号")
        size_label.setObjectName("DanmakuBarLabel")
        bar_box.addWidget(size_label)
        self.font_slider = QSlider(Qt.Horizontal)
        self.font_slider.setRange(self.MIN_FONT_SIZE, self.MAX_FONT_SIZE)
        self.font_slider.setFixedWidth(96)
        self.font_slider.setValue(self._base_size)
        self.font_slider.setToolTip("拖一下就能改弹幕字号，直接生效")
        self.font_slider.valueChanged.connect(self._on_font_slider)
        bar_box.addWidget(self.font_slider)
        self.font_value = QLabel(str(self._base_size))
        self.font_value.setObjectName("DanmakuBarValue")
        self.font_value.setFixedWidth(22)
        bar_box.addWidget(self.font_value)
        layout.addWidget(self.bar)
        self.set_placeholder("把直播间放到主画面，这里就会显示它的弹幕")

    # ---- 拖动 ----
    def mousePressEvent(self, event) -> None:
        self._press_pos = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if not (event.buttons() & Qt.LeftButton):
            return
        start = getattr(self, "_press_pos", None)
        if start is None or (event.pos() - start).manhattanLength() < QApplication.startDragDistance():
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(DANMAKU_MIME, b"1")
        mime.setText("弹幕")
        drag.setMimeData(mime)
        drag.exec(Qt.MoveAction)

    def dragEnterEvent(self, event) -> None:
        if (event.mimeData().hasFormat(ROOM_MIME) or event.mimeData().hasFormat(TILE_MIME)
                or event.mimeData().hasFormat(DANMAKU_MIME)):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        if event.mimeData().hasFormat(DANMAKU_MIME):
            return
        source = ""
        if event.mimeData().hasFormat(ROOM_MIME):
            source = bytes(event.mimeData().data(ROOM_MIME)).decode("utf-8", "ignore")
        elif event.mimeData().hasFormat(TILE_MIME):
            source = bytes(event.mimeData().data(TILE_MIME)).decode("utf-8", "ignore")
        if source:
            event.acceptProposedAction()
            self.roomDropped.emit(source)

    # ---- 内容 ----
    def set_placeholder(self, text: str) -> None:
        self._blocks = []
        self._has_content = False
        self._received = 0
        self._status = "未接入"
        self._follow_tail = True
        self._refresh_count()
        self.body.setHtml(
            f'<div style="color:#8a8f98;line-height:160%">{text}</div>')

    def set_status(self, text: str) -> None:
        """连接状态（连接中… / 已连接 / 连接失败…），后面自动跟收到多少条。"""
        self._status = text
        self._refresh_count()

    def set_count(self, text: str) -> None:
        self._status = text
        self._refresh_count()

    def _refresh_count(self) -> None:
        text = self._status
        if self._received:
            text = f"{text} · {self._received}"
        if self._status.startswith("已连接"):
            state = "connected"
        elif any(word in self._status for word in ("连接中", "重连中", "准备重连", "切换服务器")):
            state = "connecting"
        elif self._status == "未接入":
            state = "idle"
        else:
            state = "error"
        if self.count.property("state") != state:
            self.count.setProperty("state", state)
            _repolish(self.count)
        self.count.setText(text)

    def add_message(self, uname: str, text: str, color: str = "#00a1d6") -> None:
        """直接给文本的简写（预览、自检用）。"""
        self.add_event({"kind": "danmaku", "uname": uname, "text": text, "color": color})

    def add_event(self, event: dict) -> None:
        """一条消息：带粉丝牌、表情（表情图下好之后会补上）。"""
        entry = {
            "uname": event.get("uname") or "",
            "text": event.get("text") or "",
            "color": event.get("color") or self.KIND_COLORS.get(
                event.get("kind") or "danmaku", theme.ACCENT),
            "medal": event.get("medal") or {},
            "emoticon": event.get("emoticon") or "",
        }
        self._received += 1
        self._refresh_count()
        if entry["emoticon"]:
            self._ensure_emoticon(entry["emoticon"])
        self._blocks.append(entry)
        if len(self._blocks) > self.max_blocks:
            self._blocks = self._blocks[-self.max_blocks:]
            self._render_all()
            return
        scroll_state = self._scroll_state()
        block = self._block_html(entry)
        if self._has_content:
            self.body.append(block)
        else:
            self.body.setHtml(block)              # 第一条：先把占位文字换掉
            self._has_content = True
        self._restore_scroll_state(scroll_state)

    def _scroll_state(self) -> tuple[bool, int, int]:
        scroll_bar = self.body.verticalScrollBar()
        return self._follow_tail, scroll_bar.value(), self._scroll_revision

    def _restore_scroll_state(self, state: tuple[bool, int, int]) -> None:
        """内容更新不能打断用户阅读；仍在末尾时才继续跟随。"""
        follow_tail, value, revision = state
        self._follow_tail = follow_tail

        def restore() -> None:
            if revision != self._scroll_revision:
                return
            scroll_bar = self.body.verticalScrollBar()
            if self._follow_tail:
                scroll_bar.setValue(scroll_bar.maximum())
            else:
                scroll_bar.setValue(min(value, scroll_bar.maximum()))

        restore()
        # QTextDocument 可能到下一轮事件循环才完成重新排版，再校正一次。
        QTimer.singleShot(0, restore)

    def _scroll_to_bottom(self) -> None:
        if not self._follow_tail:
            return
        scroll_bar = self.body.verticalScrollBar()
        scroll_bar.setValue(scroll_bar.maximum())

    def _at_scroll_tail(self) -> bool:
        scroll_bar = self.body.verticalScrollBar()
        return scroll_bar.value() >= scroll_bar.maximum() - 1

    def _on_user_scroll(self) -> None:
        """用户滚轮/键盘查看旧内容时暂停自动跟随；回到底部后恢复。"""
        self._scroll_revision += 1
        self._follow_tail = self._at_scroll_tail()

    def _on_scroll_pressed(self) -> None:
        self._scroll_revision += 1
        self._scroll_dragging = True

    def _on_scroll_released(self) -> None:
        self._scroll_dragging = False
        self._follow_tail = self._at_scroll_tail()

    def _on_scroll_value_changed(self, _value: int) -> None:
        if self._scroll_dragging:
            self._follow_tail = self._at_scroll_tail()

    # ---- 渲染 ----
    def apply_style(self, font_family: str = "", font_size: int = BASE_FONT_SIZE) -> None:
        """设置里的字体和字号（字号也能在底部滑块上实时拖）。"""
        self._font_family = font_family or theme.FONT_DEFAULT
        self._base_size = max(self.MIN_FONT_SIZE,
                              min(self.MAX_FONT_SIZE, int(font_size or self.BASE_FONT_SIZE)))
        font = QFont(self._font_family)
        font.setPixelSize(self._base_size)
        self.body.setFont(font)          # 具体字号在 HTML 里，这里给个底
        self.font_slider.blockSignals(True)
        self.font_slider.setValue(self._base_size)
        self.font_slider.blockSignals(False)
        self.font_value.setText(str(self._base_size))
        if self._blocks:
            self._render_all()

    def _font_size(self) -> int:
        return self._base_size

    def set_max_blocks(self, count: int) -> None:
        """最多留多少条弹幕：超了就从最早的那条开始丢。"""
        try:
            value = int(count)
        except (TypeError, ValueError):
            value = self.MAX_BLOCKS
        self.max_blocks = max(self.MIN_BLOCKS, value)
        if len(self._blocks) > self.max_blocks:
            self._blocks = self._blocks[-self.max_blocks:]
            self._render_all()

    def _on_font_slider(self, value: int) -> None:
        """面板上拖字号：立刻重排，并通知外面存进配置。"""
        self._base_size = int(value)
        self.font_value.setText(str(self._base_size))
        if self._blocks:
            self._render_all()
        self.fontSizeChanged.emit(self._base_size)

    def _block_html(self, entry: dict) -> str:
        size = self._font_size()
        name = (f'<span style="color:{entry["color"]}">{_escape(entry["uname"])}</span>')
        return (f'<div style="font-size:{size}px;line-height:150%;margin:0 0 4px 0">'
                f'{self._medal_html(entry["medal"])}{name}'
                f'<span style="color:#e6e9ee">：{self._body_html(entry)}</span></div>')

    def _body_html(self, entry: dict) -> str:
        url = entry["emoticon"]
        image = self._images.get(url) if url else None
        if image is not None and not image.isNull():
            height = max(self.EMOTICON_HEIGHT // 2,
                         round(self._font_size() * 1.7))     # 表情跟着字号一起放大
            width = max(1, round(image.width() * height / max(1, image.height())))
            return (f'<img src="{url}" width="{width}" height="{height}">'
                    f'<span style="color:#8a8f98">&#160;{_escape(entry["text"])}</span>')
        return _escape(entry["text"])

    def _medal_html(self, medal: dict) -> str:
        """粉丝牌：有颜色就画成圆角小色块（图片），没有就退化成[名字等级]。"""
        name = str(medal.get("name") or "")
        if not name:
            return ""
        level = str(medal.get("level") or "")
        color = str(medal.get("color") or "")
        if not color:
            return f'<span style="color:#c792ea">[{_escape(name)}{_escape(level)}]</span>&#160;'
        size = self._font_size()
        key = f"medal:{name}|{level}|{color}|{size}"
        if key not in self._images:
            self._images[key] = _medal_chip(name, level, color, size)
        chip = self._images[key]
        self._register_image(key, chip)          # 不注册的话新到的弹幕会画成白块
        return (f'<img src="{key}" width="{chip.width()}" height="{chip.height()}">&#160;')

    def _register_image(self, key: str, image) -> None:
        """把图片挂到文本文档上，这样富文本里的 <img> 才画得出来。"""
        self.body.document().addResource(QTextDocument.ImageResource, QUrl(key), image)

    def _render_all(self) -> None:
        """整体重排（表情图下好、或者消息太多要丢弃旧的时候用）。"""
        scroll_state = self._scroll_state()
        html = "".join(self._block_html(entry) for entry in self._blocks)
        self.body.setHtml(html or "")
        for url, image in self._images.items():       # 图片按 url 注册成文档资源
            self._register_image(url, image)
        self._has_content = bool(self._blocks)
        self._restore_scroll_state(scroll_state)

    # ---- 表情 ----
    def _ensure_emoticon(self, url: str) -> None:
        if url in self._images or url in self._loading_emoticons:
            return
        self._loading_emoticons.add(url)
        loader = AvatarLoader({url: url}, self, subdir="emoticons")
        loader.loaded.connect(self._on_emoticon_loaded)
        loader.finished.connect(loader.deleteLater)
        self._emoticon_loaders = [item for item in self._emoticon_loaders
                                  if _is_running(item)]
        self._emoticon_loaders.append(loader)
        loader.start()

    def _on_emoticon_loaded(self, url: str, pixmap) -> None:
        self._loading_emoticons.discard(url)
        image = pixmap.toImage()
        if image.isNull():
            return
        self._images[url] = image
        self._render_all()          # 之前显示成文字的那些，现在换成图

    def clear(self) -> None:
        self.set_placeholder("等待主画面的直播间…")

    def set_sample(self, messages: list[tuple[str, str, str]]) -> None:
        """预览用：塞几条示例弹幕，看看排版效果。"""
        for uname, text, color in messages:
            self.add_message(uname, text, color)


def _escape(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _ignore_mouse(widget: QWidget) -> QWidget:
    widget.setAttribute(Qt.WA_TransparentForMouseEvents, True)
    return widget


def _allow_shrink(label: QLabel) -> QLabel:
    """允许标签被压缩到比文本更窄，从而触发省略号。"""
    label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
    label.setMinimumWidth(24)
    return label


def rounded_pixmap(source: QPixmap, size, radius: int) -> QPixmap:
    """圆角铺满的封面图（用于未开播时的占位）。"""
    scaled = source.scaled(size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    result = QPixmap(size)
    result.fill(Qt.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.Antialiasing, True)
    path = QPainterPath()
    path.addRoundedRect(0, 0, size.width(), size.height(), radius, radius)
    painter.setClipPath(path)
    painter.drawPixmap((size.width() - scaled.width()) // 2,
                       (size.height() - scaled.height()) // 2, scaled)
    painter.end()
    return result


def _repolish(widget: QWidget) -> None:
    widget.style().unpolish(widget)
    widget.style().polish(widget)


class ElidedLabel(QLabel):
    """超出宽度自动省略的标签。"""

    def __init__(self, text: str = "", parent=None):
        super().__init__(parent)
        self._full_text = text
        super().setText(text)

    def setText(self, text: str) -> None:
        self._full_text = text or ""
        super().setText(self._full_text)
        self._apply_elide()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_elide()

    def sizeHint(self) -> QSize:
        """用完整文本计算期望宽度，否则省略后的文本会让标签越缩越窄。"""
        metrics = self.fontMetrics()
        return QSize(metrics.horizontalAdvance(self._full_text) + 2, metrics.height())

    def minimumSizeHint(self) -> QSize:
        return QSize(0, self.fontMetrics().height())

    def _apply_elide(self) -> None:
        if not self._full_text:
            return
        elided = self.fontMetrics().elidedText(self._full_text, Qt.ElideRight, max(0, self.width()))
        if elided != super().text():
            super().setText(elided)


class Avatar(QLabel):
    """圆形头像占位。"""

    def __init__(self, name: str, index: int, size: int = theme.AVATAR_SIZE, parent=None):
        super().__init__(parent)
        self.setObjectName("NavAvatar")
        self._size = size
        self._color = AVATAR_COLORS[index % len(AVATAR_COLORS)]
        self._source: QPixmap | None = None
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignCenter)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setStyleSheet(f"background: {self._color}; border-radius: {size // 2}px;")
        self.setText((name or "?")[0])

    def set_size(self, size: int) -> None:
        """换尺寸：侧栏收起时账号头像要跟列表里的头像一样大，得重新裁一次。"""
        if size == self._size:
            return
        self._size = size
        self.setFixedSize(size, size)
        if self._source is not None:
            self.set_pixmap_image(self._source)
        else:
            self.setStyleSheet(f"background: {self._color}; border-radius: {size // 2}px;")

    def set_pixmap_image(self, pixmap: QPixmap) -> None:
        """换成真实头像（圆形裁切）。"""
        if pixmap is None or pixmap.isNull():
            return
        self._source = pixmap
        scaled = pixmap.scaled(self._size, self._size, Qt.KeepAspectRatioByExpanding,
                               Qt.SmoothTransformation)
        rounded = QPixmap(self._size, self._size)
        rounded.fill(Qt.transparent)
        painter = QPainter(rounded)
        painter.setRenderHint(QPainter.Antialiasing, True)
        path = QPainterPath()
        path.addEllipse(0, 0, self._size, self._size)
        painter.setClipPath(path)
        painter.drawPixmap((self._size - scaled.width()) // 2,
                           (self._size - scaled.height()) // 2, scaled)
        painter.end()
        self.setStyleSheet("background: transparent;")
        self.setText("")
        super().setPixmap(rounded)


class AccountRow(QFrame):
    """侧栏底部的已登录账号：头像 + 昵称，点击弹出菜单。"""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("AccountRow")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(34)          # 和底部两个按钮同高、同圆角
        self.uname = ""

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(8)
        self.avatar = Avatar("?", 3, 26)
        layout.addWidget(self.avatar)
        self.name = ElidedLabel("")
        self.name.setObjectName("NavName")
        _ignore_mouse(self.name)
        _allow_shrink(self.name)
        layout.addWidget(self.name, 1)
        self.arrow = QLabel("⋯")
        self.arrow.setObjectName("NavSub")
        _ignore_mouse(self.arrow)
        layout.addWidget(self.arrow)
        self._layout = layout
        self._compact_spacer = False

    def set_account(self, uname: str, pixmap=None) -> None:
        self.uname = uname or ""
        self.name.setText(self.uname or "")
        if pixmap is not None:
            self.avatar.set_pixmap_image(pixmap)
        elif self.uname:
            self.avatar.setText(self.uname[0])

    def set_compact(self, compact: bool) -> None:
        """侧栏收起后只留头像：尺寸跟列表里的主播头像一样，同样居中。"""
        compact = bool(compact)
        if compact == getattr(self, "_compact", False):
            return
        self._compact = compact
        self.name.setVisible(not compact)
        self.arrow.setVisible(not compact)
        self.avatar.set_size(theme.AVATAR_SIZE if compact else 26)
        self.setFixedHeight(theme.AVATAR_SIZE + 12 if compact else 34)
        if compact and not self._compact_spacer:
            self._layout.insertStretch(0, 1)
            self._layout.addStretch(1)
            self._compact_spacer = True
        elif not compact and self._compact_spacer:
            item = self._layout.takeAt(self._layout.count() - 1)
            del item
            item = self._layout.takeAt(0)
            del item
            self._compact_spacer = False
        if compact:
            self._layout.setContentsMargins(0, 6, 0, 6)
        else:
            self._layout.setContentsMargins(8, 6, 8, 6)
        self._layout.setSpacing(0 if compact else 8)
        self.setToolTip(self.uname if compact else "")

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.uname:
            self.clicked.emit()


class LiveAlert(QWidget):
    """开播提醒：粉色水滴落到「未开播」徽标上，把它砸成粉色的「直播中」，
    涟漪随即收成一颗对话气泡，「开播了」从徽标上方弹出来、停 2 秒再淡出。

    气泡要盖住上面那一行，所以这一层是画在列表容器上的（挂在条目上会被裁掉）。
    整块透明、不参与鼠标事件。
    """

    DROP_MS = 460             # 水滴下落
    POP_MS = 340              # 砸中：涟漪扩散 + 气泡弹出来
    HOLD_MS = 2000            # 气泡停留
    FADE_MS = 320             # 气泡淡出
    TOTAL_MS = DROP_MS + POP_MS + HOLD_MS + FADE_MS
    DROP_RADIUS = 4.8         # 水滴圆底的半径（整颗水滴落下时约 20px 高）
    FALL_FROM = 42            # 水滴从徽标上方多高处开始落
    BUBBLE_GAP = 7            # 气泡底边离徽标顶边的距离
    BUBBLE_LIFT = 12          # 气泡弹出时整体再往上抬多少
    BUBBLE_HEIGHT = 26
    HINT = "开播了"
    PINK = QColor(251, 114, 153)        # 跟「直播中」徽标同色
    PINK_LIGHT = QColor(255, 168, 194)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self._elapsed = 0
        self._anchor = QPointF(0, 0)
        self._badge = QRectF()
        self._family = theme.FONT_DEFAULT
        self._on_impact = None
        self._impact_done = False
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self.hide()

    def play(self, badge_rect, on_impact=None, font_family: str = "") -> None:
        """badge_rect 是徽标在本控件（也就是条目）里的位置。"""
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
        self._badge = QRectF(badge_rect)
        self._anchor = QPointF(self._badge.center().x(), self._badge.top())
        self._family = font_family or theme.FONT_DEFAULT
        self._on_impact = on_impact
        self._impact_done = False
        self._elapsed = 0
        self.show()
        self.raise_()
        self._timer.start()

    def _tick(self) -> None:
        self._elapsed += self._timer.interval()
        if not self._impact_done and self._elapsed >= self.DROP_MS:
            self._impact_done = True
            if self._on_impact is not None:
                self._on_impact()             # 砸中：把「未开播」换成「直播中」
        if self._elapsed >= self.TOTAL_MS:
            self._timer.stop()
            self.hide()
            return
        self.update()

    def stop(self) -> None:
        """立刻收掉（条目被移除、或者动画被打断时用）。"""
        self._timer.stop()
        self.hide()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        if self._elapsed < self.DROP_MS:
            self._paint_drop(painter, self._elapsed / self.DROP_MS)
            painter.end()
            return
        since = self._elapsed - self.DROP_MS
        pop = min(1.0, since / self.POP_MS)
        if since < self.POP_MS:
            self._paint_ripple(painter, pop)      # 涟漪先扩散，气泡从涟漪里长出来
        hold_end = self.POP_MS + self.HOLD_MS
        alpha = 1.0 if since <= hold_end else max(0.0, 1.0 - (since - hold_end) / self.FADE_MS)
        self._paint_bubble(painter, self._pop_scale(pop), alpha)
        painter.end()

    @staticmethod
    def _pop_scale(t: float) -> float:
        """弹出：从小长到略大，再回落到正常大小。"""
        if t >= 1.0:
            return 1.0
        if t < 0.62:
            return 0.34 + (1.09 - 0.34) * (t / 0.62)
        return 1.09 - 0.09 * ((t - 0.62) / 0.38)

    def _paint_drop(self, painter: QPainter, t: float) -> None:
        """水滴阶段：粉色水滴从徽标上方落下，越接近越快，并被拉长成雨滴。"""
        fall = t * t                          # 自由落体：后面越来越快
        centre = self._anchor
        start_y = centre.y() - self.FALL_FROM
        y = start_y + (centre.y() - start_y) * fall
        radius = self.DROP_RADIUS * (0.7 + 0.4 * fall)
        stretch = 1.0 + 0.85 * fall

        body = QPainterPath()
        body.addEllipse(QRectF(centre.x() - radius, y - radius * 0.9,
                               radius * 2, radius * 1.8))
        tip = QPainterPath()
        tip.moveTo(centre.x(), y - radius * 2.2 * stretch)
        tip.lineTo(centre.x() - radius * 0.68, y - radius * 0.4)
        tip.lineTo(centre.x() + radius * 0.68, y - radius * 0.4)
        tip.closeSubpath()

        colour = QColor(self.PINK)
        colour.setAlpha(240)
        painter.setPen(QPen(QColor(255, 255, 255, 235), 1.4))   # 白边：深色底上更好认
        painter.setBrush(colour)
        painter.drawPath(body.united(tip))
        painter.setBrush(QColor(255, 255, 255, 150))          # 高光
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QRectF(centre.x() - radius * 0.5, y - radius * 0.7,
                                   radius * 0.4, radius * 0.55))

    def _paint_ripple(self, painter: QPainter, t: float) -> None:
        """砸中阶段：徽标炸开一圈光环，三圈波纹扩散，整行泛一层淡淡的粉。"""
        centre = self._anchor
        painter.setPen(Qt.NoPen)
        flash = max(0.0, 1.0 - t * 3.2)
        if flash > 0:
            colour = QColor(self.PINK_LIGHT)
            colour.setAlpha(int(120 * flash))
            painter.setBrush(colour)
            size = 7.0 * (1 + (1 - flash))
            painter.drawEllipse(QRectF(centre.x() - size / 2, centre.y() - size / 2,
                                       size, size))
        # 徽标本身的光环：像被水滴砸亮了一下
        if t < 0.6:
            grow = 3.0 + 5.0 * t
            colour = QColor(self.PINK)
            colour.setAlpha(int(200 * (1 - t / 0.6)))
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(colour, 1.6))
            painter.drawRoundedRect(self._badge.adjusted(-grow, -grow, grow, grow), 8.0, 8.0)
        for index in range(3):
            phase = t - index * 0.22
            if phase <= 0 or phase >= 1:
                continue
            radius = 6 + phase * 52
            colour = QColor(self.PINK)
            colour.setAlpha(int(165 * (1 - phase)))
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(colour, max(1.0, 2.6 * (1 - phase))))
            painter.drawEllipse(QRectF(centre.x() - radius,
                                       centre.y() - radius * 0.82,
                                       radius * 2, radius * 1.64))
        tint = int(44 * max(0.0, 1 - t))
        if tint:
            colour = QColor(self.PINK)
            colour.setAlpha(tint)
            painter.fillRect(self.rect(), colour)

    def _paint_bubble(self, painter: QPainter, scale: float, alpha: float) -> None:
        """对话气泡：底边对着徽标，向上弹出；里面写「开播了」。"""
        if alpha <= 0:
            return
        font = self._bubble_font()
        body = self.bubble_rect(scale)
        bottom = body.bottom()

        painter.save()
        painter.setOpacity(alpha)
        painter.translate(self._anchor.x(), bottom)
        painter.scale(scale, scale)
        painter.translate(-self._anchor.x(), -bottom)

        path = QPainterPath()
        path.addRoundedRect(body, 9.0, 9.0)
        tail_x = max(body.left() + 12, min(self._anchor.x(), body.right() - 12))
        tail = QPainterPath()
        tail.moveTo(tail_x - 6, body.bottom() - 1)
        tail.lineTo(tail_x + 6, body.bottom() - 1)
        tail.lineTo(tail_x, body.bottom() + 7)
        tail.closeSubpath()
        painter.setPen(QPen(QColor(255, 255, 255, 240), 1.8))   # 白边：压住前面那一行时也分得清
        painter.setBrush(self.PINK)
        painter.drawPath(path.united(tail))

        painter.setPen(QColor(255, 255, 255, 250))
        painter.setFont(font)
        painter.drawText(body, int(Qt.AlignCenter), self.HINT)
        painter.restore()

    def _bubble_font(self) -> QFont:
        font = QFont(self._family)
        font.setPixelSize(12)
        font.setBold(True)
        return font

    def bubble_rect(self, scale: float = 1.0) -> QRectF:
        """气泡的位置：底边对着徽标，往上弹；上面没空间就往下压，别被裁掉。

        气泡是故意可以盖住上面那一行的（所以这一层画在列表容器上）。
        """
        metrics = QFontMetrics(self._bubble_font())
        width = metrics.horizontalAdvance(self.HINT) + 22
        # 卡片变高后也保持原来的“气泡弹到上一张卡片”效果。
        lift = max(self.BUBBLE_LIFT, NAV_ITEM_HEIGHT - 50)
        bottom = self._anchor.y() - self.BUBBLE_GAP - lift * scale
        left = self._anchor.x() - width / 2
        left = max(6.0, min(left, max(6.0, self.width() - width - 6)))
        top = bottom - self.BUBBLE_HEIGHT
        if top < 2:                       # 第一行上面没空间：往下压一点
            bottom = 2 + self.BUBBLE_HEIGHT
            top = 2
        return QRectF(left, top, width, self.BUBBLE_HEIGHT)


class NavThumb(QFrame):
    """关注列表的封面卡片。

    展开时封面铺满条目，头像、主播名、标题和状态叠在上面；收起时只留头像。
    鼠标停够时间后直接在卡片里播放静音预览，移开就回到封面。
    """

    WIDTH, HEIGHT = 176, 116        # 展开后约 206x116，完整保持 16:9 预览比例
    LIST_HEIGHT = 48                # 简洁列表中，预览仍在这一行里播放
    COMPACT_SIZE = 32               # 收起成窄条时缩成正方
    RADIUS = 6
    AVATAR_SIZE = 28                # 展开卡片上的圆形主播头像

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("NavThumb")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setMinimumSize(0, self.HEIGHT)
        self.setMaximumSize(16777215, self.HEIGHT)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._size = (self.WIDTH, self.HEIGHT)
        self._compact = False
        self._card_mode = True
        self._player: TilePlayer | None = None
        self._overlay_widgets: tuple[QWidget, QWidget, QWidget] | None = None

        self.cover = QLabel(self)
        self.cover.setObjectName("NavThumbCover")
        self.cover.setAlignment(Qt.AlignCenter)
        self.cover.setText("")
        self.cover.setGeometry(0, 0, self.WIDTH, self.HEIGHT)
        _ignore_mouse(self.cover)

        self.video = QFrame(self)
        self.video.setObjectName("NavThumbVideo")
        self.video.setAttribute(Qt.WA_StyledBackground, True)
        self.video.setGeometry(0, 0, self.WIDTH, self.HEIGHT)
        self.video.setVisible(False)

        self.hint = QLabel(self)
        self.hint.setObjectName("NavThumbHint")
        self.hint.setAlignment(Qt.AlignCenter)
        self.hint.setGeometry(0, 0, self.WIDTH, self.HEIGHT)
        self.hint.setVisible(False)
        _ignore_mouse(self.hint)

        # 头像挂在整行上，收起时仍能和底部账号头像保持同一条中线。
        self.face = Avatar("", 0, self.AVATAR_SIZE,
                           parent=parent if parent is not None else self)
        self.face.setObjectName("NavThumbFace")
        self._place_face()
        self.face.setVisible(False)
        self._cover_source: QPixmap | None = None
        self._face_source: QPixmap | None = None

    # ---- 外观 ----
    def set_overlay_widgets(self, name: QWidget, title: QWidget, badge: QWidget) -> None:
        self._overlay_widgets = (name, title, badge)
        for widget in self._overlay_widgets:
            widget.setParent(self)
            widget.raise_()
        self._layout_overlay()

    def _layout_overlay(self) -> None:
        if self._overlay_widgets is None or self._compact_thumb():
            return
        name, title, badge = self._overlay_widgets
        width, height = self._size
        text_left = 48 if self._card_mode else 44
        right = 8
        name_y = 7 if self._card_mode else 3
        second_y = 29 if self._card_mode else 25
        badge_y = (height - 24) if self._card_mode else (second_y + 1)
        name.setGeometry(text_left, name_y,
                         max(0, width - text_left - right), 20)
        badge.adjustSize()
        badge_width = badge.width()
        badge.move(max(text_left, width - badge_width - right), badge_y)
        title_width = (width - text_left - right if self._card_mode
                       else max(0, badge.x() - text_left - 6))
        title.setGeometry(text_left, second_y, max(0, title_width), 18)
        for widget in self._overlay_widgets:
            widget.raise_()

    def set_cover(self, pixmap) -> None:
        if pixmap is None or pixmap.isNull():
            return
        self.cover.setText("")
        self._cover_source = pixmap
        self._render_cover()

    def set_face(self, pixmap) -> None:
        if pixmap is None or pixmap.isNull():
            return
        self._face_source = pixmap
        self._render_face()

    def _render_face(self) -> None:
        """展开时画小头像，收起时改为完整的 32px 主播头像。"""
        pixmap = self._face_source
        if pixmap is None or pixmap.isNull():
            return
        size = self.COMPACT_SIZE if self._compact_thumb() else self.AVATAR_SIZE
        self.face.set_size(size)
        # 圆环直接画进头像图里：QLabel 的边框会缩小内容区，圆形会被裁成圆角方
        disc = circular_pixmap(pixmap, size)
        painter = QPainter(disc)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, 70), 1.4))
        inset = 1.0
        painter.drawEllipse(QRectF(inset, inset,
                                   size - inset * 2,
                                   size - inset * 2))
        painter.end()
        self.face.set_pixmap_image(disc)
        self._place_face()
        self.face.raise_()
        self.face.setVisible(not self.video.isVisible())

    def _face_local_rect(self) -> QRect:
        """展开时头像叠在封面左侧；收起时在 32px 方框中居中。"""
        width, height = self._size
        avatar_size = self.COMPACT_SIZE if self._compact_thumb() else self.AVATAR_SIZE
        if self._compact_thumb():
            return QRect((width - avatar_size) // 2,
                         (height - avatar_size) // 2,
                         avatar_size, avatar_size)
        return QRect(10 if self._card_mode else 4,
                     10,
                     avatar_size, avatar_size)

    def _place_face(self) -> None:
        """把头像摆到它该在的位置（挂在自己身上就按相对坐标，挂在行上就加上偏移）。"""
        rect = self._face_local_rect()
        if self.face.parentWidget() is self:
            self.face.move(rect.topLeft())
        else:
            self.face.move(self.pos() + rect.topLeft())
        self.face.raise_()

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        self._place_face()               # 缩略图被布局挪动时，头像要跟着走

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        size = (self.width(), self.height())
        if size != self._size:
            was_compact = self._compact_thumb()
            self._size = size
            self.cover.setGeometry(self.rect())
            self.video.setGeometry(self.rect())
            self.hint.setGeometry(self.rect())
            self._render_cover()
            if was_compact != self._compact_thumb():
                self._render_face()
        self._place_face()
        self._layout_overlay()

    def _render_cover(self) -> None:
        """把封面裁成圆角，并加深色渐变供叠加文字阅读。"""
        source = getattr(self, "_cover_source", None)
        if source is None or source.isNull():
            return
        width, height = self._size
        scaled = source.scaled(width, height, Qt.KeepAspectRatioByExpanding,
                               Qt.SmoothTransformation)
        canvas = QPixmap(width, height)
        canvas.fill(Qt.transparent)
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.Antialiasing, True)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, width, height), self.RADIUS, self.RADIUS)
        painter.setClipPath(path)
        painter.drawPixmap((width - scaled.width()) // 2,
                           (height - scaled.height()) // 2, scaled)
        if not self._compact_thumb():
            shade = QLinearGradient(0, 0, width, 0)
            shade.setColorAt(0.0, QColor(7, 9, 13, 205))
            shade.setColorAt(0.62, QColor(7, 9, 13, 130))
            shade.setColorAt(1.0, QColor(7, 9, 13, 92))
            painter.fillRect(QRectF(0, 0, width, height), shade)
            header = QLinearGradient(0, 0, 0, height * 0.68)
            header.setColorAt(0.0, QColor(7, 9, 13, 190))
            header.setColorAt(1.0, QColor(7, 9, 13, 0))
            painter.fillRect(QRectF(0, 0, width, height), header)
        painter.end()
        self.cover.setPixmap(canvas)

    def set_hint(self, text: str) -> None:
        """封面上的小提示（连接中…/取流失败），播放起来就藏掉。"""
        self.hint.setText(text or "")
        if text and not self.video.isVisible() and not self._compact_thumb():
            self.hint.setGeometry(self._preview_rect())
        else:
            self.hint.setGeometry(self.rect())
        self.hint.setVisible(bool(text) and not self.video.isVisible())

    def _compact_thumb(self) -> bool:
        return self._compact

    def _preview_rect(self) -> QRect:
        if self._card_mode:
            return self.rect()
        left = max(1, int(self.width() * 2 / 3))
        return QRect(left, 0, max(1, self.width() - left), self.height())

    def _set_overlay_visible(self, visible: bool) -> None:
        if self._overlay_widgets is None:
            return
        for widget in self._overlay_widgets:
            widget.setVisible(bool(visible) and not self._compact)

    def set_card_mode(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled == self._card_mode:
            return
        if self._player is not None:
            self.stop()
        self._card_mode = enabled
        if not self._compact:
            height = self.HEIGHT if enabled else self.LIST_HEIGHT
            self.setMinimumSize(0, height)
            self.setMaximumSize(16777215, height)
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.cover.setVisible(enabled and not self._compact)
        self._render_face()
        self._render_cover()
        self._place_face()
        self._layout_overlay()

    def set_thumb_size(self, compact: bool) -> None:
        width = self.COMPACT_SIZE if compact else self.WIDTH
        expanded_height = self.HEIGHT if self._card_mode else self.LIST_HEIGHT
        height = self.COMPACT_SIZE if compact else expanded_height
        if compact == self._compact_thumb():
            return
        if compact and self._player is not None:
            self.stop()
        self._compact = compact
        if compact:
            self.setFixedSize(width, height)
        else:
            self.setMinimumSize(0, height)
            self.setMaximumSize(16777215, height)
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._size = (self.width(), self.height())
        self.cover.setGeometry(self.rect())
        preview_rect = self._preview_rect() if self.video.isVisible() else self.rect()
        self.video.setGeometry(preview_rect)
        self.hint.setGeometry(preview_rect if self.hint.isVisible() else self.rect())
        self.cover.setVisible(self._card_mode and not compact)
        self._render_face()
        self._render_cover()
        self._layout_overlay()
        self.face.setVisible(bool(self.face.pixmap()))

    # ---- 预览播放 ----
    def play(self, url: str, profile: str = "web") -> None:
        """在这个缩略图里放预览（静音、低画质）。"""
        if self._compact_thumb():
            return                         # 收起的关注栏固定显示主播头像
        if self._player is None:
            self._player = TilePlayer(self.video, self)
            self._player.freeze_watch = False        # 缩略图不用卡死检测
            self._player.stateChanged.connect(self._on_player_state)
        self.video.setGeometry(self._preview_rect())
        self.hint.setGeometry(self._preview_rect())
        self.video.setVisible(True)
        self.video.raise_()
        # 大卡片预览时让画面完全干净；简洁列表的预览只占右侧三分之一，左侧信息保留。
        self._set_overlay_visible(not self._card_mode)
        self.face.setVisible(not self._card_mode)
        self.hint.setVisible(False)
        self._player.set_muted(True)                 # 预览永远静音
        self._player.set_volume(0)
        self._player.play(url, profile)

    def stop(self) -> None:
        """收掉预览，回到封面。"""
        if self._player is not None:
            self._player.release()
            self._player = None
        self.video.setVisible(False)
        self.hint.setVisible(False)
        self.video.setGeometry(self.rect())
        self.hint.setGeometry(self.rect())
        self.cover.setVisible(self._card_mode and not self._compact_thumb())
        self.face.setVisible(bool(self.face.pixmap()))
        self._set_overlay_visible(True)

    def _on_player_state(self, state: str) -> None:
        if state == "playing":
            self.hint.setVisible(False)
        elif state == "buffering":
            self.set_hint("缓冲中…")
        elif state == "error":
            self.video.setVisible(False)
            self._set_overlay_visible(True)
            self.face.setVisible(bool(self.face.pixmap()))
            self.set_hint("播放失败")


class NavItem(QFrame):
    """侧栏里的一个直播间条目。"""

    clicked = Signal(dict)
    addRequested = Signal(dict)
    removeRequested = Signal(dict)
    checkedChanged = Signal()
    pinToggled = Signal(dict)
    hovered = Signal(dict)             # 鼠标停在条目上（给悬停预览用）
    unhovered = Signal(dict)

    def __init__(self, room: dict, index: int, parent=None):
        super().__init__(parent)
        self.setObjectName("NavItem")
        self.room = room
        self.setProperty("selected", room.get("selected", False))
        self.setProperty("hovered", False)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(NAV_ITEM_HEIGHT)
        self._compact = False
        self._card_mode = True
        self._compact_spacers = False
        self.select_mode = False
        self._pinned = bool(room.get("pinned"))
        self.drop_host = None            # 侧栏：拖动排序时由它来排
        self._alert: LiveAlert | None = None
        self._hover_leave_timer = QTimer(self)
        self._hover_leave_timer.setSingleShot(True)
        self._hover_leave_timer.setInterval(60)
        self._hover_leave_timer.timeout.connect(self._clear_hover_if_outside)
        self.setAcceptDrops(True)

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(8, 6, 10, 6)
        self._layout.setSpacing(10)

        self.check = QCheckBox(self)
        self.check.setObjectName("NavCheck")
        self.check.setVisible(False)
        self.check.clicked.connect(lambda: self.checkedChanged.emit())
        self._layout.addWidget(self.check)

        self.thumb = NavThumb(self)
        self._layout.addWidget(self.thumb, 1)

        # 收起关注栏时不再有文字徽标，用头像右下角的小圆点提示正在直播。
        self.live_dot = QWidget(self.thumb.face)
        self.live_dot.setObjectName("NavLiveDot")
        self.live_dot.setAttribute(Qt.WA_StyledBackground, True)
        self.live_dot.setFixedSize(12, 12)
        # Avatar 会用内联样式切换占位色/透明背景；圆点也用内联样式，避免被父级覆盖。
        self.live_dot.setStyleSheet(
            f"background: {theme.PINK}; border: 2px solid {theme.SIDEBAR}; border-radius: 6px;")
        self.live_dot.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.live_dot.setVisible(False)

        self.name_label = ElidedLabel(room.get("uname") or room.get("room_id", ""))
        self.name_label.setObjectName("NavName")
        self.sub = ElidedLabel(room.get("title") or "未开播")
        self.sub.setObjectName("NavSub")
        _ignore_mouse(self.name_label)
        _allow_shrink(self.name_label)
        _ignore_mouse(self.sub)
        _allow_shrink(self.sub)
        self.badge = QLabel("直播中" if room.get("live") else "未开播")
        self.badge.setObjectName("BadgeLive" if room.get("live") else "BadgeOff")
        _ignore_mouse(self.badge)
        self.thumb.set_overlay_widgets(self.name_label, self.sub, self.badge)
        self.setToolTip("")

    def _sync_live_dot(self) -> None:
        size = self.live_dot.width()
        self.live_dot.move(max(0, self.thumb.face.width() - size),
                           max(0, self.thumb.face.height() - size))
        self.live_dot.setVisible(self._compact and bool(self.room.get("live")))
        self.live_dot.raise_()

    def set_compact(self, compact: bool) -> None:
        if compact == self._compact:
            return
        self._compact = compact
        expanded_height = NAV_ITEM_HEIGHT if self._card_mode else NAV_LIST_ITEM_HEIGHT
        self.setFixedHeight(NAV_COMPACT_ITEM_HEIGHT if compact else expanded_height)
        for widget in (self.name_label, self.sub, self.badge):
            widget.setVisible(not compact)
        self.thumb.set_thumb_size(compact)
        self._sync_live_dot()
        # 收起成窄条时把头像单独夹在中间，否则会被挤到右边、右侧还被裁掉
        if compact and not self._compact_spacers:
            self._layout.insertStretch(0, 1)
            self._layout.addStretch(1)
            self._compact_spacers = True
        elif not compact and self._compact_spacers:
            item = self._layout.takeAt(self._layout.count() - 1)
            del item
            item = self._layout.takeAt(0)
            del item
            self._compact_spacers = False
        self._layout.setContentsMargins(0 if compact else 8, 6, 0 if compact else 10, 6)
        self._layout.setSpacing(0 if compact else 10)   # 收起时别留间距，头像才真正居中

    def set_card_mode(self, enabled: bool) -> None:
        """展开侧栏时在大封面卡片和头像＋文字列表之间切换。"""
        enabled = bool(enabled)
        if enabled == self._card_mode:
            return
        self._card_mode = enabled
        self.thumb.set_card_mode(enabled)
        if not self._compact:
            self.setFixedHeight(NAV_ITEM_HEIGHT if enabled else NAV_LIST_ITEM_HEIGHT)

    def set_select_mode(self, enabled: bool) -> None:
        self.select_mode = enabled
        self.check.setVisible(enabled)
        if not enabled:
            self.check.setChecked(False)
        self.setCursor(Qt.PointingHandCursor)

    def is_checked(self) -> bool:
        return self.check.isChecked()

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        _repolish(self)

    def set_live(self, live: bool) -> None:
        self.room["live"] = live
        self.badge.setText("直播中" if live else "未开播")
        self.badge.setObjectName("BadgeLive" if live else "BadgeOff")
        _repolish(self.badge)
        self._sync_live_dot()
        self.thumb._layout_overlay()

    def set_title(self, title: str) -> None:
        """更新卡片上的直播间名，并同步悬停时的完整提示。"""
        self.room["title"] = title or ""
        self.sub.setText(title or "未开播")
        self.thumb._layout_overlay()

    def set_pinned(self, pinned: bool) -> None:
        self._pinned = bool(pinned)
        self.room["pinned"] = self._pinned
        self.update()

    @property
    def is_pinned(self) -> bool:
        return self._pinned

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self._pinned:
            return
        # 左上角一个蓝色小三角标
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(theme.ACCENT))
        path = QPainterPath()
        path.moveTo(2, 2)
        path.lineTo(14, 2)
        path.lineTo(2, 14)
        path.closeSubpath()
        painter.drawPath(path)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            return
        if self.select_mode:
            self.check.setChecked(not self.check.isChecked())
            self.checkedChanged.emit()
            return
        self.clicked.emit(self.room)

    def mousePressEvent(self, event) -> None:
        self._press_pos = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        """拖动 = 在关注列表里上下排序；拖到画面墙上就是在那个格子里播放。"""
        if self.select_mode or not (event.buttons() & Qt.LeftButton):
            return
        start = getattr(self, "_press_pos", None)
        if start is None:
            return
        if (event.pos() - start).manhattanLength() < QApplication.startDragDistance():
            return
        drag = QDrag(self)
        mime = QMimeData()
        room_id = str(self.room.get("room_id"))
        mime.setData(ROOM_MIME, room_id.encode("utf-8"))     # 落到画面墙：播放这一路
        mime.setData(NAV_MIME, room_id.encode("utf-8"))      # 落在列表里：排序
        mime.setText(room_id)
        drag.setMimeData(mime)
        drag.setPixmap(self._drag_pixmap())
        drag.setHotSpot(QPoint(min(event.pos().x(), self.width() - 1), event.pos().y()))
        # 抓起来的一瞬间就把自己那一格空出来
        self.drop_host.show_drop_indicator(room_id, self._index_in_host())
        drag.exec(Qt.CopyAction | Qt.MoveAction)
        if self.drop_host is None:
            return
        if QApplication.mouseButtons() & Qt.LeftButton:
            self.drop_host.end_drag()        # 按了 Esc 取消：恢复原样
        else:
            # 松手：不管落点事件有没有被别的控件吃掉，都按鼠标位置结算一次
            self.drop_host.finish_drag(room_id, QCursor.pos())

    def _index_in_host(self) -> int:
        if self.drop_host is None:
            return 0
        items = self.drop_host.items()
        for index, item in enumerate(items):
            if item is self:
                return index
        return 0

    def _drag_pixmap(self) -> QPixmap:
        """把这张卡片抽出来当拖动时跟着鼠标的"影子"（补一层卡片底色，看着是被抓起来）。"""
        pixmap = QPixmap(self.size())
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing, True)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1),
                            theme.RADIUS_MD, theme.RADIUS_MD)
        painter.fillPath(path, QColor(theme.ELEVATED))
        painter.setPen(QPen(QColor(theme.ACCENT), 1))
        painter.drawPath(path)
        painter.end()
        self.render(pixmap, QPoint(), QRegion(), QWidget.DrawChildren)
        return pixmap

    def mouseDoubleClickEvent(self, event) -> None:
        if not self.select_mode:
            self.addRequested.emit(self.room)

    # ---- 悬停（给预览用）----
    def _set_hovered(self, hovered: bool) -> None:
        hovered = bool(hovered)
        if self.property("hovered") is hovered:
            return
        self.setProperty("hovered", hovered)
        _repolish(self)

    def _clear_hover_if_outside(self) -> None:
        if self.rect().contains(self.mapFromGlobal(QCursor.pos())):
            return
        self._set_hovered(False)
        if self.room.get("room_id"):
            self.unhovered.emit(self.room)

    def play_live_alert(self) -> None:
        """刚从「未开播」变成「直播中」：先落一滴粉色水滴，砸中徽标再把它切成「直播中」。"""
        self.room["live"] = True          # 状态先记下（排序要用），徽标等砸中再换
        host = self.parentWidget()
        if host is None or not self.badge.isVisible():     # 收起侧栏时徽标是隐藏的
            self.set_live(True)
            return
        if self._alert is None or self._alert.parentWidget() is not host:
            self._alert = LiveAlert(host)      # 画在列表容器上，气泡才能盖住上面一行
        badge_origin = self.badge.mapTo(host, QPoint(0, 0))
        self._alert.play(QRect(badge_origin, self.badge.size()),
                         on_impact=self._on_live_impact)

    def drop_live_alert(self) -> None:
        """条目被移除时把动效一起收掉。"""
        if self._alert is not None:
            self._alert.stop()
            self._alert.deleteLater()
            self._alert = None

    def _on_live_impact(self) -> None:
        """水滴砸中的那一刻：徽标变成粉色的「直播中」+ 直播中该有的提示。"""
        self.set_live(True)

    def play_live_alert_demo(self) -> None:
        """手动演示开播提醒（右键菜单里那个「播放开播提醒（测试）」）。

        不看开播状态，先把徽标压回「未开播」再播一遍完整动效，
        所以随时都能检查水滴 + 气泡长什么样；下一个轮询周期会把真实状态刷回来。
        """
        self.set_live(False)
        self.play_live_alert()

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self._hover_leave_timer.stop()
        self._set_hovered(True)
        if self.room.get("room_id"):
            self.hovered.emit(self.room)

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        # 头像、封面都是子控件，从上往下跨过它们时 Qt 可能短暂发出 leave。
        # 延迟后按全局坐标确认，避免收起模式的悬停底色一闪即灭。
        self._hover_leave_timer.start()

    # ---- 拖动排序（列表内部）----
    def _nav_room_id(self, event) -> str:
        return bytes(event.mimeData().data(NAV_MIME)).decode("utf-8", "ignore")

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(NAV_MIME):
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        if not event.mimeData().hasFormat(NAV_MIME) or self.drop_host is None:
            return
        event.acceptProposedAction()
        self.drop_host.hover_drag(self._nav_room_id(event),
                                  self.mapToGlobal(event.position().toPoint()))

    def dragLeaveEvent(self, event) -> None:
        pass                              # 离开某一格不等于拖动结束

    def dropEvent(self, event) -> None:
        if not event.mimeData().hasFormat(NAV_MIME) or self.drop_host is None:
            return
        event.acceptProposedAction()
        self.drop_host.finish_drag(self._nav_room_id(event),
                                   self.mapToGlobal(event.position().toPoint()))

    def contextMenuEvent(self, event) -> None:
        if self.select_mode:
            return
        menu = QMenu(self)
        pin_action = menu.addAction("取消置顶" if self._pinned else "置顶")
        menu.addSeparator()
        demo_action = menu.addAction("播放开播提醒（测试）")
        add_action = menu.addAction("加入画面墙")
        menu.addSeparator()
        remove_action = menu.addAction("移除关注")
        action = menu.exec(event.globalPos())
        if action == pin_action:
            self.pinToggled.emit(self.room)
        elif action == demo_action:
            self.play_live_alert_demo()
        elif action == add_action:
            self.addRequested.emit(self.room)
        elif action == remove_action:
            self.removeRequested.emit(self.room)


class RoomListBox(QWidget):
    """关注列表的滚动内容：卡片自己摆位置，拖动时让位、松手后滑动归位。"""

    def __init__(self, sidebar, parent=None):
        super().__init__(parent)
        self.sidebar = sidebar
        self.setAcceptDrops(True)
        self._animations: dict = {}
        self._scroll_dir = 0
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setInterval(40)
        self._scroll_timer.timeout.connect(self._scroll_tick)

    # ---- 拖到上下边缘时自动滚动 ----
    def set_scroll_dir(self, direction: int) -> None:
        self._scroll_dir = int(direction)
        if self._scroll_dir and not self._scroll_timer.isActive():
            self._scroll_timer.start()
        elif not self._scroll_dir:
            self._scroll_timer.stop()

    def _scroll_tick(self) -> None:
        area = self.sidebar.scroll
        if area is None or not self._scroll_dir:
            return
        bar = area.verticalScrollBar()
        bar.setValue(bar.value() + self._scroll_dir * 12)

    def auto_scroll(self, y: float) -> None:
        """光标贴近上下边缘就自动滚，方便把卡片拖到看不见的位置。"""
        if y < 28:
            self.set_scroll_dir(-1)
        elif y > self.height() - 28:
            self.set_scroll_dir(1)
        else:
            self.set_scroll_dir(0)

    def slot_height(self) -> int:
        if self.sidebar.collapsed:
            height = NAV_COMPACT_ITEM_HEIGHT
        else:
            height = NAV_ITEM_HEIGHT if self.sidebar.card_mode else NAV_LIST_ITEM_HEIGHT
        return height + NAV_ITEM_GAP

    def content_height(self) -> int:
        return self.slot_height() * max(1, len(self.sidebar.items()))

    def sizeHint(self) -> QSize:
        return QSize(super().sizeHint().width(), self.content_height())

    def _glide(self, item: NavItem, y: int, animate: bool) -> None:
        target = QPoint(item.x(), y)
        if item.pos() == target:
            return
        previous = self._animations.get(item)
        if previous is not None:
            previous.stop()
        if not animate:
            item.move(target)
            return
        animation = QPropertyAnimation(item, b"pos", item)
        animation.setDuration(150)
        animation.setStartValue(item.pos())
        animation.setEndValue(target)
        animation.setEasingCurve(QEasingCurve.OutCubic)
        self._animations[item] = animation
        animation.start()

    def relayout(self, animate: bool = False, gap_index: int | None = None,
                 dragging: str | None = None) -> None:
        """按当前顺序摆卡片；gap_index 处留一个空位给正在拖的那一张。"""
        items = self.sidebar.items()
        if dragging is not None:
            items = [item for item in items
                     if str(item.room.get("room_id")) != str(dragging)]
            order: list = list(items)
            index = 0 if gap_index is None else max(0, min(gap_index, len(items)))
            order.insert(index, None)
        else:
            order = list(items)
        y = 0
        if self.sidebar.collapsed:
            item_height = NAV_COMPACT_ITEM_HEIGHT
        else:
            item_height = NAV_ITEM_HEIGHT if self.sidebar.card_mode else NAV_LIST_ITEM_HEIGHT
        for entry in order:
            if entry is None:
                y += self.slot_height()          # 空出来的位置
                continue
            entry.setVisible(True)
            entry.resize(self.width(), item_height)
            self._glide(entry, y, animate)
            y += self.slot_height()
        if dragging is not None:
            held = next((item for item in self.sidebar.items()
                         if str(item.room.get("room_id")) == str(dragging)), None)
            if held is not None:
                held.hide()                      # 原卡片藏起来，鼠标上跟着的是它的影子
        self.setMinimumHeight(max(y, 1))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.relayout(animate=False)

    def index_at(self, y: float) -> int:
        """鼠标落在第几个位置（0 = 最上面，len = 追加到最后）。

        按格子高度直接算，拖动中卡片位置在动也不影响判断。
        """
        slot = self.slot_height()
        if self.sidebar.collapsed:
            item_height = NAV_COMPACT_ITEM_HEIGHT
        else:
            item_height = NAV_ITEM_HEIGHT if self.sidebar.card_mode else NAV_LIST_ITEM_HEIGHT
        index = int((y + item_height / 2) // slot)
        return max(0, min(index, len(self.sidebar.items())))

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(NAV_MIME):
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        if not event.mimeData().hasFormat(NAV_MIME):
            return
        event.acceptProposedAction()
        room_id = bytes(event.mimeData().data(NAV_MIME)).decode("utf-8", "ignore")
        self.sidebar.hover_drag(room_id, self.mapToGlobal(event.position().toPoint()))

    def dragLeaveEvent(self, event) -> None:
        pass                              # 离开某一格不等于拖动结束，交给 drag 结束后统一结算

    def dropEvent(self, event) -> None:
        if not event.mimeData().hasFormat(NAV_MIME):
            return
        event.acceptProposedAction()
        room_id = bytes(event.mimeData().data(NAV_MIME)).decode("utf-8", "ignore")
        self.sidebar.finish_drag(room_id, self.mapToGlobal(event.position().toPoint()))


class Sidebar(QFrame):
    """左侧房间列表：可收起、可批量选择删除。"""

    SORT_MODES = [("custom", "自定义顺序（拖动调整）"),
                  ("live", "开播优先"),
                  ("imported", "导入顺序")]

    roomSelected = Signal(dict)
    addRoomClicked = Signal()
    importFollowsClicked = Signal()
    addToWallRequested = Signal(dict)
    removeRequested = Signal(dict)
    deleteRequested = Signal(list)
    collapsedChanged = Signal(bool)
    logoutRequested = Signal()
    pinChanged = Signal(list)
    sortChanged = Signal(str)
    refreshRequested = Signal()
    previewHovered = Signal(dict)       # 鼠标停在某个直播间上
    previewUnhovered = Signal(dict)
    layoutChosen = Signal(str)
    settingsRequested = Signal()

    def __init__(self, rooms: list[dict], parent=None, card_mode: bool = True):
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(theme.SIDEBAR_WIDTH)
        self._items: list[NavItem] = []
        self.collapsed = False
        self.card_mode = bool(card_mode)
        self.select_mode = False
        self.pinned: list[str] = []
        self.sort_mode = "custom"
        self.import_order: list[str] = []      # 导入/添加的先后顺序，用于「导入顺序」排序
        self.custom_order: list[str] = []      # 拖动排出来的顺序，切换排序方式也不丢
        self._layout_id = "auto"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 14, 12, 12)
        layout.setSpacing(10)
        self._layout = layout

        # 标题行
        header = QHBoxLayout()
        header.setSpacing(9)
        self.dot = QLabel()
        self.dot.setFixedSize(10, 10)
        self.dot.setStyleSheet(f"background: {theme.ACCENT}; border-radius: 5px;")
        self.title_box = QVBoxLayout()
        self.title_box.setSpacing(0)
        title = QLabel("DD 监控室")
        title.setObjectName("AppTitle")
        subtitle = QLabel("多窗口直播监控")
        subtitle.setObjectName("AppSubtitle")
        self.title_box.addWidget(title)
        self.title_box.addWidget(subtitle)
        self.batch_button = QPushButton("多选")
        self.batch_button.setObjectName("ChipButton")
        self.batch_button.setCursor(Qt.PointingHandCursor)
        self.batch_button.setToolTip("批量选择直播间")
        self.batch_button.setCheckable(True)
        self.batch_button.setFixedHeight(22)
        self.batch_button.clicked.connect(lambda: self.set_select_mode(not self.select_mode))
        self.toggle_button = QPushButton("«")
        self.toggle_button.setObjectName("SidebarToggle")
        self.toggle_button.setCursor(Qt.PointingHandCursor)
        self.toggle_button.setToolTip("收起 / 展开房间列表")
        self.toggle_button.clicked.connect(self.toggle_collapsed)
        header.addWidget(self.dot, 0, Qt.AlignVCenter)
        header.addLayout(self.title_box, 1)
        header.addWidget(self.batch_button, 0, Qt.AlignTop)
        header.addWidget(self.toggle_button, 0, Qt.AlignTop)
        layout.addLayout(header)

        self.search = QLineEdit()
        self.search.setObjectName("Search")
        self.search.setPlaceholderText("搜索主播 / 房间号")
        self.search.setClearButtonEnabled(True)
        layout.addWidget(self.search)

        self.status_row = QWidget(self)
        status_box = QHBoxLayout(self.status_row)
        status_box.setContentsMargins(0, 0, 0, 0)
        status_box.setSpacing(6)
        self.count_label = QLabel(f"关注中 · {len(rooms)}")
        self.count_label.setObjectName("SectionLabel")
        self.sort_button = QPushButton("排序")
        self.sort_button.setObjectName("ChipButton")
        self.sort_button.setCursor(Qt.PointingHandCursor)
        self.sort_button.setToolTip("关注列表的排序方式")
        self.sort_button.setMenu(self._build_sort_menu())
        self.refresh_button = RefreshButton(size=22, object_name="ChipButton")
        self.refresh_button.clicked.connect(self.refreshRequested.emit)
        status_box.addWidget(self.count_label, 1)
        status_box.addWidget(self.sort_button, 0, Qt.AlignRight)
        status_box.addWidget(self.refresh_button, 0, Qt.AlignRight)
        layout.addWidget(self.status_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll = scroll
        holder = RoomListBox(self)
        self.list_box = holder
        for room in rooms:
            self._append_item(room)
        holder.relayout(animate=False)
        scroll.setWidget(holder)
        layout.addWidget(scroll, 1)

        # 底部：批量操作条 / 正常操作
        self.batch_bar = QWidget()
        batch_layout = QHBoxLayout(self.batch_bar)
        batch_layout.setContentsMargins(0, 0, 0, 0)
        batch_layout.setSpacing(6)
        self.batch_label = QLabel("已选 0 个")
        self.batch_label.setObjectName("NavSub")
        self.delete_button = QPushButton("删除")
        self.delete_button.setObjectName("DangerButton")
        self.delete_button.setCursor(Qt.PointingHandCursor)
        self.delete_button.clicked.connect(self._emit_delete)
        cancel_button = QPushButton("取消")
        cancel_button.setObjectName("IconButton")
        cancel_button.setCursor(Qt.PointingHandCursor)
        cancel_button.clicked.connect(lambda: self.set_select_mode(False))
        batch_layout.addWidget(self.batch_label, 1)
        batch_layout.addWidget(self.delete_button)
        batch_layout.addWidget(cancel_button)
        self.batch_bar.setVisible(False)
        layout.addWidget(self.batch_bar)

        # 已登录账号（在底部操作之上）
        self.account_row = AccountRow()
        self.account_row.clicked.connect(self._open_account_menu)
        self.account_row.setVisible(False)
        layout.addWidget(self.account_row)

        # 布局 + 设置：原来挂在右侧顶栏，现在跟着列表放左下角
        self.tool_row = QWidget(self)
        tool_box = QHBoxLayout(self.tool_row)
        tool_box.setContentsMargins(0, 0, 0, 0)
        tool_box.setSpacing(6)
        self.layout_button = QPushButton()
        self.layout_button.setObjectName("IconButton")
        self.layout_button.setCursor(Qt.PointingHandCursor)
        self.layout_button.setToolTip("选择布局方式")
        self.layout_button.clicked.connect(self.open_layout_picker)
        self.settings_button = QPushButton("设置")
        self.settings_button.setObjectName("IconButton")
        self.settings_button.setCursor(Qt.PointingHandCursor)
        self.settings_button.setToolTip("打开设置")
        self.settings_button.clicked.connect(self.settingsRequested.emit)
        tool_box.addWidget(self.layout_button, 1)
        tool_box.addWidget(self.settings_button, 0)
        layout.addWidget(self.tool_row)
        self.set_layout_name("auto")

        self.normal_bar = QWidget()
        normal_layout = QHBoxLayout(self.normal_bar)
        normal_layout.setContentsMargins(0, 0, 0, 0)
        normal_layout.setSpacing(6)
        self.import_button = QPushButton("导入关注")
        self.import_button.setObjectName("IconButton")
        self.import_button.setCursor(Qt.PointingHandCursor)
        self.import_button.setToolTip("从 B 站账号导入关注列表（需要先登录）")
        self.import_button.clicked.connect(self.importFollowsClicked.emit)
        self.add_button = QPushButton("+  添加直播间")
        self.add_button.setObjectName("PrimaryButton")
        self.add_button.setCursor(Qt.PointingHandCursor)
        self.add_button.clicked.connect(self.addRoomClicked.emit)
        normal_layout.addWidget(self.import_button)
        normal_layout.addWidget(self.add_button, 1)
        layout.addWidget(self.normal_bar)

    # ---- 账号 ----
    def set_layout_name(self, layout_id: str) -> None:
        """按钮只写「布局预设」，当前用的是哪套放在悬停提示里。"""
        self._layout_id = layout_id
        layout = layouts.BY_ID.get(layout_id, layouts.BY_ID["auto"])
        self.layout_button.setText("布局预设")
        self.layout_button.setToolTip(f"当前布局：{layout['name']}　（点击切换）")

    def open_layout_picker(self) -> None:
        picker = LayoutPicker(self._layout_id, self)
        picker.chosen.connect(self._on_layout_chosen)
        # 收起时「布局预设」按钮是藏起来的，改从头像那个位置弹出来
        source = self.account_row if self.collapsed else self.layout_button
        anchor = source.mapToGlobal(source.rect().topLeft())
        picker.adjustSize()
        screen = (QApplication.screenAt(anchor)
                  or QApplication.screenAt(QCursor.pos())
                  or QApplication.primaryScreen())
        # screenAt 偶尔全落空（窗口还在屏幕外、或显示器刚改过配置），
        # 这时千万别把窗口摆到屏幕外去：退回主屏可用区域，至少还能看见。
        available = screen.availableGeometry() if screen is not None else QRect()
        if not available.isValid():
            primary = QApplication.primaryScreen()
            if primary is not None:
                available = primary.availableGeometry()
        x = anchor.x()
        if self.collapsed:
            x = anchor.x() + source.width() + 6
        y = anchor.y() - picker.height() - 6
        if available.isValid():
            x = max(available.left() + 6,
                    min(x, available.right() - picker.width() - 6))
            if y < available.top() + 6:
                y = anchor.y() + source.height() + 6
            min_y = available.top() + 6
            max_y = available.bottom() - picker.height() - 6
            if max_y < min_y:
                y = min_y
            else:
                y = max(min_y, min(y, max_y))
        else:
            y = max(6, y)
        picker.move(x, y)
        picker.show()
        self._picker = picker

    def _on_layout_chosen(self, layout_id: str) -> None:
        self.set_layout_name(layout_id)
        self.layoutChosen.emit(layout_id)

    def set_account(self, uname: str, pixmap=None) -> None:
        self.account_row.set_account(uname, pixmap)
        self.account_row.set_compact(self.collapsed)
        self.account_row.setVisible(bool(uname))

    def clear_account(self) -> None:
        self.account_row.set_account("")
        self.account_row.setVisible(False)

    def account_menu(self) -> QMenu:
        """账号菜单：退出登录；侧栏收起时把藏起来的「布局预设 / 设置」也放进来。

        单独一个方法是为了能测——exec 一弹就是模态，自检里没法取菜单内容。
        """
        menu = QMenu(self)
        menu.addAction("退出登录")
        if self.collapsed:
            # 收起后「布局预设 / 设置」那行按钮跟着藏起来了，只剩这个头像；
            # 点头像就把它们以菜单形式放出来，不用先展开侧栏。
            menu.addSeparator()
            menu.addAction("布局预设…")
            menu.addAction("设置…")
        return menu

    def _open_account_menu(self) -> None:
        menu = self.account_menu()
        texts = [action.text() for action in menu.actions() if action.text()]
        size = menu.sizeHint()
        anchor = self.account_row.mapToGlobal(self.account_row.rect().topRight())
        if self.collapsed:
            # 收起时只有头像，菜单贴着头像右侧展开
            position = QPoint(anchor.x() + 6, anchor.y() - size.height() - 6)
        else:
            # 账号栏在最底部，菜单往上弹、右对齐整行
            position = QPoint(anchor.x() - size.width(), anchor.y() - size.height() - 6)
        chosen = menu.exec(position)
        if chosen is None:
            return
        label = chosen.text()
        if label == texts[0]:
            self.logoutRequested.emit()
        elif label == "布局预设…":
            self.open_layout_picker()
        elif label == "设置…":
            self.settingsRequested.emit()

    # ---- 收起 / 展开 ----
    def toggle_collapsed(self) -> None:
        self.set_collapsed(not self.collapsed)

    def set_collapsed(self, collapsed: bool, animate: bool = True) -> None:
        if collapsed == self.collapsed:
            return
        self.collapsed = collapsed
        target = theme.SIDEBAR_RAIL_WIDTH if collapsed else theme.SIDEBAR_WIDTH
        for widget in (self.search, self.status_row, self.normal_bar, self.batch_bar,
                       self.dot, self.batch_button, self.tool_row):
            widget.setVisible(not collapsed and (widget is not self.batch_bar or self.select_mode))
        self.account_row.set_compact(collapsed)
        self.account_row.setVisible(bool(self.account_row.uname))
        # 窄条里列表一出现滚动条就会把内容挤窄，上下两排头像就对不齐了；
        # 收起时干脆不显示滚动条，滚轮照样能滚
        self.scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarAlwaysOff if collapsed else Qt.ScrollBarAsNeeded)
        for index in range(self.title_box.count()):
            widget = self.title_box.itemAt(index).widget()
            if widget:
                widget.setVisible(not collapsed)
        self._layout.setContentsMargins(8 if collapsed else 12, 14, 8 if collapsed else 12, 12)
        self.toggle_button.setText("»" if collapsed else "«")
        for item in self._items:
            item.set_compact(collapsed)
        self.list_box.relayout(animate=False)

        if not animate:
            self.setFixedWidth(target)
            self.collapsedChanged.emit(collapsed)
            return

        group = []
        for prop in (b"minimumWidth", b"maximumWidth"):
            animation = QPropertyAnimation(self, prop)
            animation.setDuration(160)
            animation.setStartValue(self.width())
            animation.setEndValue(target)
            animation.setEasingCurve(QEasingCurve.OutCubic)
            group.append(animation)
        group[-1].finished.connect(lambda: self.setFixedWidth(target))
        for animation in group:
            animation.start()
        self._animations = group          # 保持引用，避免被回收
        self.collapsedChanged.emit(collapsed)

    def set_card_mode(self, enabled: bool) -> None:
        """切换关注列表样式；侧栏收起时只记录选择，展开后再呈现。"""
        enabled = bool(enabled)
        if enabled == self.card_mode:
            return
        self.card_mode = enabled
        for item in self._items:
            item.thumb.stop()
            item.set_card_mode(enabled)
        self.list_box.relayout(animate=False)

    # ---- 批量选择 ----
    def set_select_mode(self, enabled: bool) -> None:
        self.select_mode = enabled
        self.batch_button.setChecked(enabled)
        self.batch_bar.setVisible(enabled and not self.collapsed)
        self.normal_bar.setVisible(not enabled and not self.collapsed)
        for item in self._items:
            item.set_select_mode(enabled and not self.collapsed)
        self._update_batch_label()

    def _update_batch_label(self) -> None:
        count = sum(1 for item in self._items if item.is_checked())
        self.batch_label.setText(f"已选 {count} 个")

    def _emit_delete(self) -> None:
        chosen = [item.room for item in self._items if item.is_checked()]
        if chosen:
            self.deleteRequested.emit(chosen)
        self.set_select_mode(False)

    # ---- 列表维护 ----
    def select_room(self, room: dict) -> None:
        room_id = str(room.get("room_id") or "")
        for item in self._items:
            item.set_selected(bool(room_id) and str(item.room.get("room_id") or "") == room_id)

    def _append_item(self, room: dict) -> NavItem:
        item = NavItem(room, len(self._items), parent=self.list_box)
        room_id = str(room.get("room_id"))
        if room_id and room_id not in self.import_order:
            self.import_order.append(room_id)     # 「导入顺序」排序用
        if room_id and room_id not in self.custom_order:
            self.custom_order.append(room_id)     # 新加的房间先排在自定义顺序最后
        item.drop_host = self                 # 列表内部拖动排序
        item.clicked.connect(self.roomSelected.emit)
        item.addRequested.connect(self.addToWallRequested.emit)
        item.removeRequested.connect(self.removeRequested.emit)
        item.checkedChanged.connect(self._update_batch_label)
        item.pinToggled.connect(self.toggle_pin)
        item.hovered.connect(self.previewHovered.emit)
        item.unhovered.connect(self.previewUnhovered.emit)
        item.set_card_mode(self.card_mode)
        item.set_select_mode(self.select_mode)
        self._items.append(item)
        item_height = NAV_ITEM_HEIGHT if self.card_mode else NAV_LIST_ITEM_HEIGHT
        item.resize(self.list_box.width(), item_height)
        item.show()
        return item

    def add_room(self, room: dict) -> bool:
        room_id = str(room.get("room_id"))
        if any(str(item.room.get("room_id")) == room_id for item in self._items):
            return False
        self._append_item(room)
        # 新控件初始坐标是 (0, 0)，必须立即排版，否则会压在第一项上，
        # 直到用户拖动列表才恢复。
        self.resort(animate=False)
        self._sync_count()
        return True

    def remove_room(self, room: dict) -> None:
        item = next((entry for entry in self._items
                     if str(entry.room.get("room_id")) == str(room.get("room_id"))), None)
        if item is None:
            return
        item.hide()
        item.drop_live_alert()
        item.thumb.stop()               # 缩略图里可能正在放预览
        item.setParent(None)
        item.deleteLater()
        self._items.remove(item)
        room_id = str(room.get("room_id"))
        if room_id in self.import_order:
            self.import_order.remove(room_id)
        if room_id in self.custom_order:
            self.custom_order.remove(room_id)
        self.list_box.relayout(animate=False)
        self._sync_count()

    def rooms(self) -> list[dict]:
        return [item.room for item in self._items]

    def items(self) -> list[NavItem]:
        return list(self._items)

    def drop_index_at(self, global_pos) -> int:
        """全局坐标 -> 列表里的落点下标（给 NavItem 转发拖动用）。"""
        return self.list_box.index_at(self.list_box.mapFromGlobal(global_pos).y())

    def hover_drag(self, room_id: str, global_pos) -> None:
        """拖动过程中：贴近边缘自动滚，并在落点让出一格。"""
        local = self.list_box.mapFromGlobal(global_pos)
        self.list_box.auto_scroll(local.y())
        self.show_drop_indicator(room_id, self.list_box.index_at(local.y()))

    def finish_drag(self, room_id: str, global_pos) -> None:
        """松手时结算：鼠标还在列表里就按落点排序，否则只把卡片放回去。"""
        self.list_box.set_scroll_dir(0)
        local = self.list_box.mapFromGlobal(global_pos)
        inside = (0 <= local.x() <= self.list_box.width()
                  and 0 <= local.y() <= self.list_box.height())
        if inside:
            self.reorder_item(str(room_id), self.list_box.index_at(local.y()))
        self.list_box.relayout(animate=True)

    # ---- 拖动排序 ----
    def _clamped_index(self, room_id: str, drop_index: int) -> int | None:
        """把落点收进合法范围：置顶优先；开播优先时不能跨状态组。"""
        items = list(self._items)
        source = next((index for index, item in enumerate(items)
                       if str(item.room.get("room_id")) == str(room_id)), None)
        if source is None:
            return None
        pinned_count = sum(1 for item in items if item.is_pinned)
        if drop_index > source:                  # 先摘出来，后面的下标都要往前挪一格
            drop_index -= 1
        if items[source].is_pinned:
            return max(0, min(drop_index, pinned_count - 1))
        if self.sort_mode == "live":
            source_live = bool(items[source].room.get("live"))
            group = [index for index, item in enumerate(items)
                     if not item.is_pinned and bool(item.room.get("live")) == source_live]
            if group:
                return max(min(group), min(drop_index, max(group)))
        return max(pinned_count, min(drop_index, len(items) - 1))

    def show_drop_indicator(self, room_id: str | None, drop_index: int) -> None:
        """拖动中：被拖的卡片藏起来，其余卡片滑动让出落点那一格。"""
        if not room_id:
            self.list_box.relayout(animate=True)
            return
        index = self._clamped_index(str(room_id), drop_index)
        if index is None:
            return
        self.list_box.relayout(animate=True, gap_index=index, dragging=str(room_id))

    def end_drag(self) -> None:
        """拖动结束（放下或者取消）：所有卡片恢复显示并归位。"""
        self.list_box.set_scroll_dir(0)
        self.list_box.relayout(animate=True)

    def reorder_item(self, room_id: str, drop_index: int) -> bool:
        """把某个直播间挪到新位置；跨过置顶区的落点会被收回来。"""
        items = list(self._items)
        source = next((index for index, item in enumerate(items)
                       if str(item.room.get("room_id")) == str(room_id)), None)
        target = self._clamped_index(str(room_id), drop_index)
        if source is None or target is None:
            return False
        pinned_before = [str(entry.room.get("room_id")) for entry in items
                         if entry.is_pinned]
        item = items.pop(source)
        items.insert(target, item)
        if [str(entry.room.get("room_id")) for entry in items] == \
                [str(entry.room.get("room_id")) for entry in self._items]:
            return False
        self._items = items
        self.pinned = [str(entry.room.get("room_id")) for entry in items if entry.is_pinned]
        self.custom_order = [str(entry.room.get("room_id")) for entry in items]
        if self.sort_mode not in ("custom", "live"):
            # 手动拖过就按用户排的来，否则下次「开播优先」会把刚拖的顺序冲掉
            self.set_sort_mode("custom")
        self.list_box.relayout(animate=True)
        if self.pinned != pinned_before:
            self.pinChanged.emit(list(self.pinned))
        return True

    # ---- 置顶 ----
    def apply_pins(self, pinned: list) -> None:
        """置顶的先显示在前面（顺序按置顶列表）。"""
        self.pinned = [str(item) for item in pinned]
        for item in self._items:
            item.set_pinned(str(item.room.get("room_id")) in self.pinned)
        self.resort(animate=False)

    # ---- 排序 ----
    def _build_sort_menu(self) -> QMenu:
        menu = QMenu(self)
        group = QActionGroup(menu)
        group.setExclusive(True)
        self._sort_actions: dict[str, QAction] = {}
        for mode, label in self.SORT_MODES:
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(mode == self.sort_mode)
            action.triggered.connect(lambda _checked=False, value=mode: self.set_sort_mode(value))
            group.addAction(action)
            self._sort_actions[mode] = action
        return menu

    def _sync_sort_menu(self) -> None:
        for mode, action in getattr(self, "_sort_actions", {}).items():
            action.setChecked(mode == self.sort_mode)

    def set_sort_mode(self, mode: str, notify: bool = True) -> None:
        """切排序方式：自定义 / 开播优先 / 导入顺序。"""
        if mode not in dict(self.SORT_MODES):
            mode = "custom"
        self.sort_mode = mode
        self.resort(animate=False)
        if notify:
            self.sortChanged.emit(mode)

    def set_import_order(self, order: list | None) -> None:
        """导入顺序（配置里存的）；没存过就按当前列表顺序算。"""
        known = [str(item) for item in (order or [])]
        for item in self._items:
            room_id = str(item.room.get("room_id"))
            if room_id not in known:
                known.append(room_id)
        self.import_order = known
        self.resort(animate=False)

    def set_custom_order(self, order: list | None) -> None:
        """自定义顺序（配置里存的）；没存过的房间按当前列表顺序补在后面。"""
        known = list(dict.fromkeys(str(entry) for entry in (order or [])))
        for item in self._items:
            room_id = str(item.room.get("room_id"))
            if room_id not in known:
                known.append(room_id)
        present = {str(item.room.get("room_id")) for item in self._items}
        self.custom_order = [room_id for room_id in known if room_id in present]
        self.resort(animate=False)

    def resort(self, animate: bool = False) -> None:
        """重排：置顶永远在最前，其余按当前排序方式（同组内保持原有先后）。"""
        pinned_ids = list(self.pinned)
        pinned = [item for room_id in pinned_ids for item in self._items
                  if str(item.room.get("room_id")) == room_id]
        rest = [item for item in self._items
                if str(item.room.get("room_id")) not in pinned_ids]
        if self.sort_mode == "custom":
            position = {room_id: index for index, room_id in enumerate(self.custom_order)}
            rest.sort(key=lambda item: position.get(str(item.room.get("room_id")), len(position)))
        elif self.sort_mode == "live":
            # 每次状态更新都重新分组；同一组内沿用用户拖出的自定义顺序。
            position = {room_id: index for index, room_id in enumerate(self.custom_order)}
            rest.sort(key=lambda item: (
                0 if item.room.get("live") else 1,
                position.get(str(item.room.get("room_id")), len(position)),
            ))
        elif self.sort_mode == "imported":
            position = {room_id: index for index, room_id in enumerate(self.import_order)}
            rest.sort(key=lambda item: position.get(str(item.room.get("room_id")), len(position)))
        self._items = pinned + rest
        self.list_box.relayout(animate=animate)
        self._sync_sort_menu()

    def play_live_alerts(self, items: list) -> None:
        """重排之后再播开播动效。

        调用方要先把 room["live"] 置位、再 resort()，卡片才会先挪到「开播优先」
        该在的位置；动效放到下一个事件循环里播，那时卡片已经就位，水滴和气泡
        才会落在卡片身上，而不是留在它挪走之前的那一行。
        """
        pending = [item for item in items if item is not None]
        if not pending:
            return
        QTimer.singleShot(0, lambda: self._play_live_alerts_now(pending))

    @staticmethod
    def _play_live_alerts_now(items: list) -> None:
        for item in items:
            if item.parentWidget() is None:      # 已经不在列表里了
                continue
            item.play_live_alert()
            print(f"[开播提醒] {item.room.get('uname')}", file=sys.stderr, flush=True)

    def toggle_pin(self, room: dict) -> None:
        room_id = str(room.get("room_id"))
        if room_id in self.pinned:
            self.pinned.remove(room_id)
        else:
            self.pinned.append(room_id)
        self.apply_pins(self.pinned)
        self.pinChanged.emit(list(self.pinned))

    def _sync_count(self) -> None:
        self.count_label.setText(f"关注中 · {len(self._items)}")

    def set_refreshing(self, busy: bool) -> None:
        self.refresh_button.setEnabled(not busy)
        self.refresh_button.setToolTip(
            "正在刷新关注列表…" if busy else "立刻刷新关注列表：直播状态、标题、在线人数、头像")


class Tile(QFrame):
    """一个播放格子：画面 + 底部信息条 + 独立控制。"""

    clicked = Signal(dict)
    qualityChanged = Signal(dict, int)
    muteToggled = Signal(dict, bool)
    reloadRequested = Signal(dict)
    fullscreenRequested = Signal(dict)
    closeRequested = Signal(dict)
    roomDropped = Signal(str)
    tileDropped = Signal(str)          # 拖过来的来源房间号
    danmakuDropped = Signal()          # 弹幕格被拖到本格上
    volumeChanged = Signal(dict, int)
    audioChannelChanged = Signal(dict, int)
    pauseToggled = Signal(dict)

    def __init__(self, room: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("Tile")
        self.room = room
        self._cover_source = room.get("cover")
        self._status_text = ""
        self.setMinimumSize(200, 150)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setCursor(Qt.PointingHandCursor)
        self.setProperty("focused", False)
        self.setProperty("empty", False)
        self.setProperty("dropActive", False)
        self.setAcceptDrops(True)
        self.muted = bool(room.get("muted", True))       # 默认静音
        self.quality = int(room.get("quality", 250))
        self.volume = int(room.get("volume", 42))
        self.audio_channel = int(room.get("audio_channel", 0))
        self._buffering = False
        self.actual_quality = 0
        self.quality_options: list[dict] = []

        # 画面区域：高度扣掉底部信息条，保证画面完整可见
        self.video = QFrame(self)
        self.video.setObjectName("TileVideo")
        self.video.setAttribute(Qt.WA_StyledBackground, True)
        self.cover = QLabel(self.video)
        self.cover.setAlignment(Qt.AlignCenter)
        self.cover.setObjectName("TilePlaceholder")
        self.cover.setAttribute(Qt.WA_TransparentForMouseEvents, True)

        # 信息条（在画面下方，不遮挡画面）：左下角暂停 + 右侧音量
        self.bottom = QWidget(self)
        self.bottom.setObjectName("TileBottom")
        self.bottom.setAttribute(Qt.WA_StyledBackground, True)
        bottom_layout = QHBoxLayout(self.bottom)
        bottom_layout.setContentsMargins(10, 4, 10, 4)
        bottom_layout.setSpacing(8)

        # 左上角浮标：圆形镂空 + LIVE + 直播间人数
        self.stream_badge = StreamBadge(self)
        # 这里只放占位：room["viewers"] 是"人气值"，拿它当在线人数会显示成莫名其妙的好几万
        self.stream_badge.set_state(bool(room.get("live")),
                                    WATCHING_TEXT if room.get("live") else "")
        # 左上角第二块浮标：主播名 + 直播间标题（跟在 LIVE 右边）
        self.title_badge = TitleBadge(self)
        self.title_badge.set_text(room.get("uname", ""), room.get("title", ""))
        # 右下角浮标：直播时长
        self.time_badge = TimeBadge(self)
        self.time_badge.setVisible(False)
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._refresh_elapsed)

        # 左下角：暂停 / 继续（图形按钮，常驻不用悬停）
        self.pause_button = PauseButton(self)
        self.pause_button.clicked.connect(lambda: self.pauseToggled.emit(self.room))
        bottom_layout.addWidget(self.pause_button, 0, Qt.AlignVCenter)
        # 信息条中间：常驻状态（连接中 / 缓冲中 / 断流重连 / 已下播…）
        # 画面被 VLC 原生窗口盖住时，这里也一定看得见
        self.status_label = ElidedLabel("")
        self.status_label.setObjectName("TileStatus")
        _ignore_mouse(self.status_label)
        _allow_shrink(self.status_label)
        bottom_layout.addWidget(self.status_label, 1)

        # 音量条直接放在信息条里，不用翻右键菜单
        # 音量图标按钮 + 滑条 + 数值，都在信息条里
        self.volume_button = VolumeButton(size=26)
        self.volume_button.set_state(self.muted, self.volume, self.audio_channel)
        self.volume_button.clicked.connect(self._toggle_mute)
        self.volume_button.volumeChanged.connect(self.set_volume)
        bottom_layout.addWidget(self.volume_button)
        self.volume_slider = QSlider(Qt.Horizontal)
        self.volume_slider.setFixedWidth(86)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(self.volume)
        self.volume_slider.setToolTip("这个格子的音量（更换主播后保持不变）")
        self.volume_slider.valueChanged.connect(self.set_volume)
        bottom_layout.addWidget(self.volume_slider)
        self.volume_label = QLabel(str(self.volume))
        self.volume_label.setObjectName("TileTitle")
        self.volume_label.setFixedWidth(24)
        _ignore_mouse(self.volume_label)
        bottom_layout.addWidget(self.volume_label)

        # 悬停时才出现的单窗口控制：与浮标同款样式，浮在画面右上角
        self.controls = QWidget(self)
        self.controls.setObjectName("TileControls")
        self.controls.setAttribute(Qt.WA_StyledBackground, False)
        control_layout = QHBoxLayout(self.controls)
        control_layout.setContentsMargins(0, 0, 0, 0)
        control_layout.setSpacing(6)          # 按钮之间留缝，不会连成一条底
        self.quality_button = self._make_control(self._quality_text(), "选择这一路的画质")
        self.quality_button.clicked.connect(self._open_quality_menu)
        self.reload_button = RefreshButton(object_name="TileCtrl")
        self.reload_button.setToolTip("重新连接这一路")
        self.reload_button.clicked.connect(lambda: self.reloadRequested.emit(self.room))
        self.close_button = self._make_control("×", "关闭这一路")
        # 固定成方钮：宽度不再依赖样式表，免得被 min-width 撑成画质按钮那么宽
        self.close_button.setFixedSize(theme.TILE_CONTROL_HEIGHT, theme.TILE_CONTROL_HEIGHT)
        self.close_button.clicked.connect(lambda: self.closeRequested.emit(self.room))
        for button in (self.quality_button, self.reload_button, self.close_button):
            control_layout.addWidget(button)
        self.controls.setVisible(False)
        self._control_hover_timer = QTimer(self)
        self._control_hover_timer.setInterval(35)
        self._control_hover_timer.timeout.connect(self._sync_control_hover)
        self._controls_hide_timer = QTimer(self)
        self._controls_hide_timer.setSingleShot(True)
        self._controls_hide_timer.setInterval(90)
        self._controls_hide_timer.timeout.connect(self._hide_controls_if_outside)
        self.paused = False
        self._player_active = False
        self.spinner = LoadingIndicator(self)
        self.pause_overlay = LoadingIndicator(self, text="已暂停", icon=False)
        self.pause_overlay.setObjectName("PauseOverlay")
        if not room.get("room_id"):
            self.set_room(None)          # 空格子：显示"拖入直播间"

    # ---- 播放状态 ----
    def set_room(self, room: dict | None, cover: QPixmap | None = None) -> None:
        """换这一个格子播放的房间；音量和静音属于格子，不跟着房间移动。"""
        self.room = room or {}
        empty = not self.room.get("room_id")
        self.setProperty("empty", empty)
        _repolish(self)
        self.set_controls_visible(False)
        self.set_paused(False)
        self.set_video_active(False)
        self.set_buffering(False)

        if empty:
            self._cover_source = None
            self.title_badge.set_text("", "")
            self.title_badge.setVisible(False)
            self.stream_badge.setVisible(False)
            self.set_status("拖入直播间")
            return

        self.room["volume"] = self.volume
        self.room["muted"] = self.muted
        self.stream_badge.setVisible(True)
        self._cover_source = cover if cover is not None else self.room.get("cover")
        self.title_badge.set_text(self.room.get("uname", ""), self.room.get("title", ""))
        self.title_badge.setVisible(bool(self.room.get("uname")))
        self._refresh_badge()
        self.quality = int(self.room.get("quality", 250))
        self.actual_quality = 0
        self.audio_channel = int(self.room.get("audio_channel", 0))
        self.quality_button.setText(self._quality_text())
        self.volume_slider.blockSignals(True)
        self.volume_slider.setValue(self.volume)
        self.volume_slider.blockSignals(False)
        self.volume_label.setText(str(self.volume))
        self.volume_button.set_state(self.muted, self.volume, self.audio_channel)
        self.set_status("" if self.room.get("live") else "未开播")
        self.stop_elapsed_timer()
        self._layout_cover()

    # ---- 接收拖拽 ----
    def dragEnterEvent(self, event) -> None:
        if (event.mimeData().hasFormat(ROOM_MIME) or event.mimeData().hasFormat(TILE_MIME)
                or event.mimeData().hasFormat(DANMAKU_MIME)):
            event.acceptProposedAction()
            self.setProperty("dropActive", True)
            _repolish(self)

    def dragLeaveEvent(self, event) -> None:
        self.setProperty("dropActive", False)
        _repolish(self)

    def dropEvent(self, event) -> None:
        self.setProperty("dropActive", False)
        _repolish(self)
        if event.mimeData().hasFormat(ROOM_MIME):
            room_id = bytes(event.mimeData().data(ROOM_MIME)).decode("utf-8", "ignore")
            event.acceptProposedAction()
            self.roomDropped.emit(room_id)
        elif event.mimeData().hasFormat(DANMAKU_MIME):
            event.acceptProposedAction()
            self.danmakuDropped.emit()
        elif event.mimeData().hasFormat(TILE_MIME):
            source = bytes(event.mimeData().data(TILE_MIME)).decode("utf-8", "ignore")
            event.acceptProposedAction()
            self.tileDropped.emit(source)

    def mousePressEvent(self, event) -> None:
        self._press_pos = event.pos()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        """拖动画面本身可以和其他格子交换位置。"""
        room_id = str(self.room.get("room_id") or "")
        if not room_id or not (event.buttons() & Qt.LeftButton):
            return
        start = getattr(self, "_press_pos", None)
        if start is None or (event.pos() - start).manhattanLength() < QApplication.startDragDistance():
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(TILE_MIME, room_id.encode("utf-8"))
        mime.setText(room_id)
        drag.setMimeData(mime)
        drag.exec(Qt.MoveAction)

    def raise_overlays(self) -> None:
        """信息条已经在画面之外，不需要再抢层级。"""

    def set_video_active(self, active: bool) -> None:
        self._player_active = active
        self.cover.setVisible(not active)
        if active:
            self.spinner.stop()
            self._connecting = False
        else:
            self.pause_overlay.stop()
        self.raise_overlays()

    def set_status(self, text: str) -> None:
        self._status_text = text
        self._connecting = text.startswith("连接中")
        self._sync_status_label()
        if not self._player_active:
            if self._connecting:
                self.spinner.start()
            else:
                self.spinner.stop()
            self._layout_cover()              # 让封面文字随状态刷新（连接时不显示文字）

    def set_offline(self) -> None:
        """下播：画面清成黑的，格子继续留给这个直播间。"""
        self.room["live"] = False
        self._cover_source = None
        self._player_active = False
        self.cover.setVisible(True)
        self.set_paused(False)
        self.stop_elapsed_timer()
        self._refresh_badge()
        self.stream_badge.set_offline()
        self.set_status("已下播")
        self.video.repaint()                  # 立刻把上一帧擦掉

    def set_buffering(self, active: bool) -> None:
        """卡顿/缓冲中：显示缓冲动画（和连接时同一套样式）。"""
        self._connecting = active
        self._buffering = bool(active)
        self._sync_status_label()
        if active:
            self.spinner.start()
        else:
            self.spinner.stop()
        if not self._player_active:
            self._layout_cover()

    def _sync_status_label(self) -> None:
        """信息条里的状态文字：缓冲优先，其次才是当前状态。"""
        text = "缓冲中…" if getattr(self, "_buffering", False) else self._status_text
        self.status_label.setText(text or "")

    def set_paused(self, paused: bool) -> None:
        self.paused = bool(paused)
        self.pause_button.set_paused(self.paused)
        if self.paused and self._player_active:
            self.pause_overlay.start()
            self.pause_overlay.raise_()
        else:
            self.pause_overlay.stop()
        self._layout_controls()

    def set_live(self, live: bool, viewers: str = "") -> None:
        self.room["live"] = live
        if viewers:
            self.room["viewers"] = viewers
        if not live:
            self.room.pop("online", None)      # 下播后旧的在线人数不能再留着显
        self._refresh_badge()

    def set_watched(self, watched_text: str) -> None:
        """实时在线人数（高能榜 onlineNum，和 B 站页面一致）。"""
        if watched_text:
            self.room["online"] = watched_text
        self._refresh_badge()

    def _refresh_badge(self) -> None:
        watched = self.room.get("online") or ""
        popularity = self.room.get("viewers") or ""
        live = bool(self.room.get("live"))
        # 优先显示实时在线人数；还没拉到就别拿人气值顶上（那个数看着很像异常）
        self.stream_badge.set_state(live, watched or (WATCHING_TEXT if live else ""))
        self.stream_badge.setVisible(bool(self.room.get("room_id")))
        self._layout_areas()          # 浮标宽度会变（人数位数不同），标题要跟着重新让位
        if watched and popularity:
            self.stream_badge.setToolTip(f"{watched} 人在线 · 人气 {popularity}")
        elif watched:
            self.stream_badge.setToolTip(f"{watched} 人在线")
        elif live and popularity:
            self.stream_badge.setToolTip(f"正在获取在线人数…（当前人气 {popularity}）")
        elif live:
            self.stream_badge.setToolTip("正在获取在线人数…")
        elif popularity:
            self.stream_badge.setToolTip(f"人气 {popularity}")

    # ---- 控制 ----
    def _make_control(self, text: str, tip: str) -> QPushButton:
        button = QPushButton(text)
        button.setObjectName("TileCtrl")
        button.setToolTip(tip)
        button.setCursor(Qt.PointingHandCursor)
        return button

    def _quality_text(self) -> str:
        if self.actual_quality:
            return self._quality_name(self.actual_quality)
        return self._quality_name(self.quality)

    def _quality_name(self, qn: int) -> str:
        for item in self.quality_options:
            if int(item.get("qn") or 0) == int(qn):
                return str(item.get("desc") or qn)
        return QUALITY_NAMES.get(int(qn), f"{qn}P")

    def _quality_choices(self) -> list[tuple[str, int]]:
        """优先用接口给的档位：直播间只提供哪些，菜单里就只留哪些。"""
        if self.quality_options:
            return [(self._quality_name(int(item["qn"])), int(item["qn"]))
                    for item in self.quality_options]
        return list(QUALITY_CHOICES)

    def set_quality_options(self, options: list) -> None:
        if not options:
            return
        self.quality_options = [dict(item) for item in options]
        self.quality_button.setText(self._quality_text())
        self._layout_controls()

    def set_actual_quality(self, quality: int) -> None:
        """接口实际给的画质（未登录时通常只有 720P）。"""
        self.actual_quality = int(quality or 0)
        self.quality_button.setText(self._quality_text())
        self._layout_controls()
        if self.actual_quality and self.actual_quality < self.quality:
            self.quality_button.setToolTip(
                f"请求 {QUALITY_NAMES.get(self.quality, self.quality)}，"
                f"实际 {QUALITY_NAMES.get(self.actual_quality, self.actual_quality)}"
                f"（该直播间/当前账号最高只提供这一档）")
        else:
            self.quality_button.setToolTip("选择这一路的画质")

    def _open_quality_menu(self) -> None:
        menu = QMenu(self)
        for name, value in self._quality_choices():
            action = QAction(name, menu)
            action.setCheckable(True)
            action.setChecked(value == self.quality)
            action.triggered.connect(lambda _checked=False, v=value: self.set_quality(v))
            menu.addAction(action)
        menu.exec(self.quality_button.mapToGlobal(self.quality_button.rect().bottomLeft()))

    def set_quality(self, value: int) -> None:
        self.quality = value
        self.actual_quality = 0
        self.quality_button.setText(self._quality_text())
        self.quality_button.setToolTip("选择这一路的画质")
        self._layout_controls()
        self.qualityChanged.emit(self.room, value)

    def _toggle_mute(self) -> None:
        self.set_muted(not self.muted)

    def set_muted(self, muted: bool) -> None:
        self.muted = bool(muted)
        self.room["muted"] = self.muted
        self.volume_button.set_state(muted, self.volume, self.audio_channel)
        self._layout_controls()
        self.muteToggled.emit(self.room, muted)

    def set_controls_visible(self, visible: bool) -> None:
        visible = bool(visible)
        self.controls.setVisible(visible)
        if visible:
            self._controls_hide_timer.stop()
            # 显示之前先按文本把按钮宽度摆好：否则会沿用上一次的尺寸，
            # 画质文字换了之后整条控制条看起来就是错位的。
            self._layout_controls()
            self._sync_control_hover()
            self._control_hover_timer.start()
        else:
            self._control_hover_timer.stop()
            self._set_control_hover(None)

    def _set_control_hover(self, hovered: QPushButton | None) -> None:
        """同步一份不依赖原生窗口 enter/leave 的悬停状态。"""
        for button in (self.quality_button, self.reload_button, self.close_button):
            active = button is hovered
            if button.property("hovered") is active:
                continue
            button.setProperty("hovered", active)
            _repolish(button)
            button.update()

    def _sync_control_hover(self, global_pos: QPoint | None = None) -> None:
        global_pos = global_pos or QCursor.pos()
        hovered = None
        for button in (self.quality_button, self.reload_button, self.close_button):
            local = button.mapFromGlobal(global_pos)
            if button.rect().contains(local):
                hovered = button
                break
        self._set_control_hover(hovered)

    def _hide_controls_if_outside(self) -> None:
        local = self.mapFromGlobal(QCursor.pos())
        if self.rect().contains(local):
            return
        self.set_controls_visible(False)

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        self.set_controls_visible(True)

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        # VLC 画面和控制条都是原生子窗口，横向划过时会产生短暂 leave；
        # 稍后按全局坐标复核，避免按钮还在鼠标下却被提前隐藏。
        self._controls_hide_timer.start()

    # ---- 画面 ----
    def set_cover(self, pixmap: QPixmap | None) -> None:
        self._cover_source = pixmap
        self._layout_cover()

    def _layout_cover(self) -> None:
        self.cover.setGeometry(self.video.rect())
        source = getattr(self, "_cover_source", None)
        if source and not source.isNull():
            self.cover.setPixmap(rounded_pixmap(source, self.video.size(), 8))
        else:
            self.cover.setPixmap(QPixmap())
            if self._player_active or getattr(self, "_connecting", False):
                self.cover.setText("")        # 播放中 / 连接中都不显示文字，避免和动画重叠
            else:
                fallback = self.room.get("uname", "") if self.room.get("live") else "未开播"
                self.cover.setText(self._status_text or fallback)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._layout_areas()

    def _layout_areas(self) -> None:
        """统一摆放：视频区、浮标、控制条、信息条。"""
        width, height = self.width(), self.height()
        video_height = max(60, height - TILE_BAR_HEIGHT)
        # 留 1px 给圆角边框；视频是原生窗口，用窗口遮罩做圆角
        self.video.setGeometry(1, 1, max(1, width - 2), max(1, video_height - 1))
        self._round_video()
        video_right = self.video.width() + 1
        self.stream_badge.move(10, 8)
        self.stream_badge.raise_()
        self._layout_controls()
        # 挤不下时先收起 LIVE 里的人数是；还是挤不下就把控制条折到第二行
        self.stream_badge.set_compact(
            self.controls.x() < self.stream_badge.full_width() + 26)
        if self.controls.x() < self.stream_badge.width() + 22:
            self.controls.move(self.controls.x(), 8 + BADGE_HEIGHT + 6)
        # 标题浮标紧跟在 LIVE 右边，剩下的宽度让给控制条那一行
        controls_left = (video_right - 10
                         if self.controls.y() > 20 else self.controls.x())
        title_left = self.stream_badge.x() + self.stream_badge.width() + 6
        room = max(0, controls_left - title_left - 8)
        show_title = bool(self.room.get("uname")) and room >= 110
        self.title_badge.setVisible(show_title)
        if show_title:
            self.title_badge.set_max_width(room)
            self.title_badge.move(title_left, 8)
            self.title_badge.raise_()
        self.time_badge.move(max(10, video_right - self.time_badge.width() - 10),
                             max(8, video_height - self.time_badge.height() - 10))
        self.time_badge.raise_()
        self.spinner.move(max(0, (self.video.width() - self.spinner.width()) // 2),
                          max(8, (video_height - self.spinner.height()) // 2))
        self.spinner.raise_()
        self.pause_overlay.move(
            max(0, (self.video.width() - self.pause_overlay.width()) // 2),
            max(8, (video_height - self.pause_overlay.height()) // 2))
        self.pause_overlay.raise_()
        self.bottom.setGeometry(0, video_height, width, height - video_height)
        self._layout_cover()

    def _round_video(self) -> None:
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, max(1, self.video.width()), max(1, self.video.height())),
                            9, 9)
        self.video.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def _quality_button_width(self) -> int:
        """按画质文字算按钮宽度。

        用样式表里那号字来量，不能拿 button.fontMetrics()：QSS 的 font-size 不会
        改到控件的 QFont，量出来是默认字号的宽度，几个画质档位会算出同一个数，
        按钮就宽得离谱、文字也没居中。
        """
        font = QFont(theme.FONT_DEFAULT)
        font.setPixelSize(theme.FONT_CAPTION)
        font.setBold(True)                     # #TileCtrl 是 font-weight: 600
        advance = QFontMetrics(font).horizontalAdvance(self.quality_button.text())
        return max(theme.TILE_CONTROL_HEIGHT, advance + 16)

    def _layout_controls(self) -> None:
        """控制条浮在画面右上角，只显示按钮本身。

        每个按钮的宽度都按文本算好并固定下来，然后才让布局排位置。样式表给
        按钮带了 offset（min-width / padding），若交给布局分配，短文本的「×」
        会被撑成和画质按钮一样宽，整条控制条看起来就是错位的。
        """
        # 高度统一由代码给：样式表不再写 min-height，交给布局量出来会矮一截
        self.quality_button.setFixedHeight(theme.TILE_CONTROL_HEIGHT)
        self.quality_button.setFixedWidth(self._quality_button_width())
        self.close_button.setFixedSize(theme.TILE_CONTROL_HEIGHT, theme.TILE_CONTROL_HEIGHT)
        layout = self.controls.layout()
        layout.invalidate()
        size = layout.sizeHint()
        self.controls.resize(size)
        layout.setGeometry(self.controls.rect())
        layout.activate()
        # 原生窗口遮罩必须使用布局完成后的按钮坐标，否则缩放或画质文字改变时会错位。
        video_right = self.video.width() + 1
        self.controls.move(max(10, video_right - size.width() - 10), 8)
        self._update_controls_mask()

    def _update_controls_mask(self) -> None:
        """裁掉原生控制窗口的矩形底，只留下三个圆角按钮的轮廓。"""
        region = QRegion()
        for button in (self.quality_button, self.reload_button, self.close_button):
            rect = QRectF(button.geometry())
            path = QPainterPath()
            radius = min(rect.height() / 2, theme.TILE_CONTROL_HEIGHT / 2)
            path.addRoundedRect(rect, radius, radius)
            region = region.united(QRegion(path.toFillPolygon().toPolygon()))
        self.controls.setMask(region)

    def showEvent(self, event) -> None:
        # 需要在窗口真正显示之后再设为原生窗口，否则 Qt 会抱怨不是顶层窗口
        super().showEvent(event)
        for widget in (self.stream_badge, self.title_badge, self.time_badge, self.controls,
                       self.spinner, self.pause_overlay):
            if not widget.testAttribute(Qt.WA_NativeWindow):
                widget.setAttribute(Qt.WA_NativeWindow, True)
            widget.raise_()

    # ---- 直播时长 ----
    def _refresh_elapsed(self) -> None:
        start = int(self.room.get("live_start_ts") or 0)
        if not start or not self.room.get("live"):
            self.time_badge.setVisible(False)
            self._elapsed_timer.stop()
            return
        seconds = max(0, int(time.time()) - start)
        hours, rest = divmod(seconds, 3600)
        minutes, secs = divmod(rest, 60)
        text = f"{hours}:{minutes:02d}:{secs:02d}"
        self.time_badge.set_text(text)
        self.time_badge.setVisible(True)

    def start_elapsed_timer(self) -> None:
        if self.room.get("live_start_ts"):
            self._refresh_elapsed()
            self._elapsed_timer.start()

    def stop_elapsed_timer(self) -> None:
        self._elapsed_timer.stop()
        self.time_badge.setVisible(False)

    # ---- 右键菜单 ----
    def contextMenuEvent(self, event) -> None:
        if not self.room.get("room_id"):
            return
        self.build_menu().exec(event.globalPos())

    def build_menu(self) -> QMenu:
        """右键菜单：音量滑条 + 画质 + 声道 + 常规操作。"""
        menu = QMenu(self)

        # 音量（菜单里嵌滑条）
        holder = QWidget()
        holder_layout = QVBoxLayout(holder)
        holder_layout.setContentsMargins(10, 6, 10, 4)
        holder_layout.setSpacing(4)
        volume_label = QLabel(f"音量 {self.volume}")
        volume_label.setObjectName("AppSubtitle")
        holder_layout.addWidget(volume_label)
        slider = QSlider(Qt.Horizontal, holder)
        slider.setRange(0, 100)
        slider.setValue(self.volume)
        slider.setFixedWidth(170)
        slider.valueChanged.connect(lambda value: (
            volume_label.setText(f"音量 {value}"), self.set_volume(value)))
        holder_layout.addWidget(slider)
        wrapper = QWidgetAction(menu)
        wrapper.setDefaultWidget(holder)
        menu.addAction(wrapper)
        menu.addSeparator()

        quality_menu = menu.addMenu("画质")
        for name, value in self._quality_choices():
            action = quality_menu.addAction(name)
            action.setCheckable(True)
            action.setChecked(value == self.quality)
            action.triggered.connect(lambda _checked=False, v=value: self.set_quality(v))

        # 声道：0 默认、3 只左、4 只右、2 反向立体声、5 杜比。
        # 只有「只左 / 只右」能把两路画面分到两只耳朵，其余是原程序的音效档。
        audio_menu = menu.addMenu("声道")
        for name, value in (("默认（跟随片源）", 0), ("只播左声道", 3),
                            ("只播右声道", 4), ("反向立体声", 2), ("杜比音效", 5)):
            action = audio_menu.addAction(name)
            action.setCheckable(True)
            action.setChecked(value == self.audio_channel)
            action.triggered.connect(lambda _checked=False, v=value: self.set_audio_channel(v))
        menu.addSeparator()
        menu.addAction("取消静音" if self.muted else "静音", self._toggle_mute)
        menu.addAction("刷新重连", lambda: self.reloadRequested.emit(self.room))
        menu.addAction("放到主画面", lambda: self.fullscreenRequested.emit(self.room))
        menu.addSeparator()
        menu.addAction("关闭这一路", lambda: self.closeRequested.emit(self.room))
        return menu

    def set_volume(self, value: int) -> None:
        value = max(0, min(100, int(value)))
        self.volume = value
        self.room["volume"] = value
        self.volume_label.setText(str(value))
        if self.volume_slider.value() != value:
            self.volume_slider.blockSignals(True)
            self.volume_slider.setValue(value)
            self.volume_slider.blockSignals(False)
        self.volumeChanged.emit(self.room, value)

    def set_audio_channel(self, value: int) -> None:
        self.audio_channel = int(value)
        self.room["audio_channel"] = int(value)
        self.volume_button.set_state(self.muted, self.volume, self.audio_channel)
        self.audioChannelChanged.emit(self.room, int(value))

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.clicked.emit(self.room)

    def set_focused(self, focused: bool) -> None:
        self.setProperty("focused", focused)
        _repolish(self)


def best_columns(count: int, width: int, height: int, gap: int = 8, aspect: float = 16 / 9) -> int:
    """在给定区域内挑一个让画面尽量大的列数。"""
    if count <= 1:
        return 1
    best_score = -1.0
    best = 1
    for columns in range(1, count + 1):
        rows = math.ceil(count / columns)
        tile_width = (width - gap * (columns - 1)) / columns
        tile_height = (height - gap * (rows - 1)) / rows
        if tile_width <= 0 or tile_height <= 0:
            continue
        score = min(tile_width, (tile_height - TILE_BAR_HEIGHT) * aspect)
        if score > best_score:
            best_score = score
            best = columns
    return best


class WallGrid(QWidget):
    """画面墙：自动网格或指定布局方案。"""

    tileClicked = Signal(dict)
    roomDropped = Signal(object, str)      # 目标格子, 房间号
    tileSwapped = Signal(str, object)      # 来源房间号, 目标格子

    def __init__(self, rooms: list[dict], layout_id: str = "auto", parent=None):
        super().__init__(parent)
        self.setObjectName("WallGrid")
        # 老配置里可能存着已经删掉的布局，回落到自动布局
        self.layout_id = layout_id if layout_id in layouts.BY_ID else "auto"
        self.tiles: list[Tile] = []
        self._columns = 0
        self._last_height = 0
        self._last_count = 0
        self._relayout_timer = QTimer(self)
        self._relayout_timer.setSingleShot(True)
        self._relayout_timer.setInterval(120)
        self._relayout_timer.timeout.connect(self.relayout)

        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(16, 16, 16, 16)   # 上下留白一致，隐藏顶栏时不会顶到最上面
        self.grid.setSpacing(8)

        # 弹幕格：占一整格，只在带弹幕的布局里出现（可以拖到别的格子上）
        self.danmaku = DanmakuPanel(self)
        self.danmaku.setVisible(False)
        self.danmaku.roomDropped.connect(self._on_danmaku_room_dropped)
        self._danmaku_cell = layouts.danmaku_cell(layout_id)

        for room in rooms:
            self._make_tile(room)
        self.relayout(force=True)

    def set_layout(self, layout_id: str) -> None:
        if layout_id == self.layout_id:
            return
        self.layout_id = layout_id
        self._danmaku_cell = layouts.danmaku_cell(layout_id)
        self._columns = -1
        self._last_height = 0
        self.relayout(force=True)

    def focus_room(self, room: dict) -> None:
        """把某一路挪到主画面（切到带主画面的布局）。"""
        room_id = str(room.get("room_id") or "")
        tile = next((item for item in self.tiles
                     if room_id and str(item.room.get("room_id") or "") == room_id), None)
        if tile is not None:
            self.tiles.remove(tile)
            self.tiles.insert(0, tile)
        sidebar_count = max(2, min(6, len(self.tiles) - 1))
        self.layout_id = f"main{sidebar_count}"
        self._columns = -1
        self.relayout(force=True)

    def remove_room(self, room: dict) -> None:
        room_id = str(room.get("room_id") or "")
        tile = next((item for item in self.tiles
                     if room_id and str(item.room.get("room_id") or "") == room_id), None)
        if tile is None:
            return
        self._drop_tile(tile)
        self.relayout(force=True)

    def add_room(self, room: dict) -> Tile:
        tile = self._make_tile(room)
        self.relayout(force=True)
        return tile

    def _make_tile(self, room: dict) -> Tile:
        tile = Tile(room)
        tile.clicked.connect(self.tileClicked.emit)
        tile.roomDropped.connect(lambda rid, t=tile: self.roomDropped.emit(t, rid))
        tile.tileDropped.connect(lambda rid, t=tile: self.tileSwapped.emit(rid, t))
        tile.danmakuDropped.connect(lambda t=tile: self.move_danmaku_to_tile(t))
        self.tiles.append(tile)
        return tile

    def _drop_tile(self, tile: Tile) -> None:
        self.grid.removeWidget(tile)
        tile.hide()                     # 先隐藏，否则 setParent(None) 会让它变成独立窗口
        tile.setParent(None)
        tile.deleteLater()
        if tile in self.tiles:
            self.tiles.remove(tile)

    def _capacity(self) -> int:
        """当前布局能放几路；自动布局返回 0（格子数跟着房间数走）。"""
        if self.layout_id == "auto":
            return 0
        return len(self._cell_order())

    def _cells(self) -> list:
        layout = layouts.BY_ID.get(self.layout_id)
        if not layout or not layout.get("spec"):
            return []
        return layout["spec"][2]

    def _cell_order(self) -> list[int]:
        """画面格子依次用哪些 cell（跳过弹幕占的那一格）。"""
        cells = self._cells()
        return [index for index in range(len(cells)) if index != self._danmaku_cell]

    def main_index(self) -> int | None:
        """当前布局里"主画面"是第几路画面（弹幕格不算）；等分布局返回 None。"""
        cells = self._cells()
        order = self._cell_order()
        if not cells or not order:
            return None
        areas = [cells[index][2] * cells[index][3] for index in order]
        if len(set(areas)) <= 1:
            return None
        return areas.index(max(areas))

    @property
    def has_danmaku(self) -> bool:
        return self._danmaku_cell is not None and bool(self._cells())

    def cell_of(self, tile: Tile):
        """这一路画面用的是哪个 cell（排查布局问题时用）。"""
        order = self._cell_order()
        try:
            index = self.tiles.index(tile)
        except ValueError:
            return None
        cells = self._cells()
        if not cells or index >= len(order):
            return None
        return cells[order[index]]

    def danmaku_geometry_cell(self):
        """弹幕格当前用的 cell。"""
        cells = self._cells()
        if self._danmaku_cell is None or not cells:
            return None
        return cells[self._danmaku_cell]

    def move_danmaku_to_tile(self, tile: Tile) -> None:
        """把弹幕格拖到某一路上：两边换位置（弹幕挪过去，那一格挪到弹幕原来的位置）。"""
        cells = self._cells()
        if self._danmaku_cell is None or not cells:
            return
        try:
            target = self.tiles.index(tile)
        except ValueError:
            return
        order = self._cell_order()
        if target >= len(order):
            return
        old_cell, new_cell = self._danmaku_cell, order[target]
        moved = self.tiles.pop(target)
        new_order = [index for index in range(len(cells)) if index != new_cell]
        insert_at = new_order.index(old_cell) if old_cell in new_order else len(self.tiles)
        self.tiles.insert(min(insert_at, len(self.tiles)), moved)
        self._danmaku_cell = new_cell
        self.relayout(force=True)
        print(f"弹幕格已挪到第 {target + 1} 个画面位置", file=sys.stderr, flush=True)

    def _on_danmaku_room_dropped(self, room_id: str) -> None:
        """把一路直播拖到弹幕格上：等于把弹幕换到那一格去。"""
        tile = next((item for item in self.tiles
                     if str(item.room.get("room_id") or "") == str(room_id)), None)
        if tile is not None:
            self.move_danmaku_to_tile(tile)

    def ensure_slots(self) -> None:
        """按布局把格子补齐：缺的位置显示成"拖入直播间"的空格。"""
        capacity = self._capacity()
        if capacity <= 0:
            return
        used = sum(1 for tile in self.tiles if tile.room.get("room_id"))
        target = max(capacity, used)
        while len(self.tiles) < target:
            self._make_tile({})
        while len(self.tiles) > target:
            empty = next((tile for tile in reversed(self.tiles)
                          if not tile.room.get("room_id")), None)
            if empty is None:
                break
            self._drop_tile(empty)

    def _clear(self) -> None:
        for index in range(24):
            self.grid.setColumnStretch(index, 0)
            self.grid.setRowStretch(index, 0)
        for tile in self.tiles:
            self.grid.removeWidget(tile)
        self.grid.removeWidget(self.danmaku)

    def _auto_columns(self) -> int:
        height = max(self.height(), 1)
        count = len(self.tiles)
        if self._columns > 0 and height == self._last_height and count == self._last_count:
            return self._columns          # 只有宽度变化（收起侧栏）时保持原布局
        self._last_height = height
        self._last_count = count
        return best_columns(count, max(self.width(), 1), height)

    def relayout(self, force: bool = False) -> None:
        self.ensure_slots()          # 按布局补空位
        if not self.tiles:
            return
        layout = layouts.BY_ID.get(self.layout_id)     # 老配置可能存着已经删掉的布局
        spec = None if layout is None else layout.get("spec")
        if not force and spec is None:
            # 自动模式：列数没变就不用重排
            if self._auto_columns() == self._columns:
                return
        self._clear()

        if spec is None:
            self.danmaku.setVisible(False)
            columns = self._auto_columns()
            self._columns = columns
            for index, tile in enumerate(self.tiles):
                self.grid.addWidget(tile, index // columns, index % columns)
                tile.setVisible(True)
            for column in range(columns):
                self.grid.setColumnStretch(column, 1)
            for row in range(math.ceil(len(self.tiles) / columns)):
                self.grid.setRowStretch(row, 1)
            return

        rows, columns, cells = spec
        order = self._cell_order()
        for index, tile in enumerate(self.tiles):
            if index < len(order):
                row, column, rowspan, colspan = cells[order[index]]
                self.grid.addWidget(tile, row, column, rowspan, colspan)
                tile.setVisible(True)
            else:
                # 布局严格按格子数走：放不下的先隐藏，换成更大的布局再显示
                tile.setVisible(False)
        if self.has_danmaku:
            row, column, rowspan, colspan = cells[self._danmaku_cell]
            self.grid.addWidget(self.danmaku, row, column, rowspan, colspan)
            self.danmaku.setVisible(True)
            self.danmaku.raise_()
        else:
            self.danmaku.setVisible(False)
        for column in range(columns):
            self.grid.setColumnStretch(column, 1)
        for row in range(rows):
            self.grid.setRowStretch(row, 1)
        self._columns = columns

    def visible_tiles(self) -> list[Tile]:
        return [tile for tile in self.tiles if tile.isVisible()]

    def hidden_count(self) -> int:
        return sum(1 for tile in self.tiles if not tile.isVisible())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.layout_id == "auto":
            self._relayout_timer.start()


class LayoutPicker(QFrame):
    """布局选择弹层：顶上两个按钮切「普通布局 / 弹幕布局」，下面还是缩略图卡片。"""

    chosen = Signal(str)

    def __init__(self, current: str, parent=None):
        super().__init__(parent, Qt.Popup)
        self.setObjectName("LayoutPicker")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._cards: dict[str, list[QToolButton]] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)

        tabs = QHBoxLayout()
        tabs.setSpacing(6)
        self._tabs: dict[str, QPushButton] = {}
        for name, _group in layouts.GROUPS:
            button = QPushButton(name)
            button.setObjectName("PickerTab")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, key=name: self.set_group(key))
            tabs.addWidget(button)
            self._tabs[name] = button
        tabs.addStretch(1)
        outer.addLayout(tabs)

        self._grid = QGridLayout()
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(6)
        outer.addLayout(self._grid)
        outer.addStretch(1)          # 两组行数不同，多出来的高度留在下面

        active = layouts.GROUPS[0][0]
        for name, group in layouts.GROUPS:
            cards: list[QToolButton] = []
            for index, layout in enumerate(group):
                button = QToolButton(self)
                button.setObjectName("LayoutCard")
                button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
                button.setIcon(QIcon(layouts.thumbnail(layout["spec"],
                                                       danmaku=layout.get("danmaku"))))
                button.setIconSize(QSize(52, 34))
                button.setText(layout["name"])
                button.setCheckable(True)
                button.setChecked(layout["id"] == current)
                button.setToolTip(layout.get("hint") or layout["name"])
                button.setCursor(Qt.PointingHandCursor)
                button.clicked.connect(
                    lambda _checked=False, lid=layout["id"]: self._choose(lid))
                self._grid.addWidget(button, index // 4, index % 4)
                cards.append(button)
            self._cards[name] = cards
            if any(item["id"] == current for item in group):
                active = name
        self.set_group(active)
        self._lock_size()

    def set_group(self, name: str) -> None:
        """切到某一组布局（普通 / 弹幕）。"""
        if name not in self._cards:
            return
        for key, button in self._tabs.items():
            button.setChecked(key == name)
            _repolish(button)
        for key, cards in self._cards.items():
            for card in cards:
                card.setVisible(key == name)
        self._group = name
        self.adjustSize()
        # 宽度固定（右边对齐布局按钮），高度跟着这一组卡片走
        self.resize(getattr(self, "_width", self.width()), self.sizeHint().height())

    def group(self) -> str:
        return getattr(self, "_group", layouts.GROUPS[0][0])

    def _lock_size(self) -> None:
        """两组卡片行数不一样，尺寸锁成最大值，切换时不会向屏幕外增长。"""
        active = self.group()
        sizes = []
        for name in self._cards:
            self.set_group(name)
            sizes.append(self.sizeHint())
        self._width = max(size.width() for size in sizes)
        self._height = max(size.height() for size in sizes)
        self.setFixedSize(self._width, self._height)
        self.set_group(active)          # 量完尺寸要切回当前布局所在的那一栏

    def _choose(self, layout_id: str) -> None:
        self.chosen.emit(layout_id)
        self.close()

