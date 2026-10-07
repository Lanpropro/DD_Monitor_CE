"""界面组件：侧栏（可收起 / 批量选择）、顶栏、画面格子、自适应网格、布局选择器。"""
import math
import os
import platform
import sys
import time
from uuid import uuid4

from PySide6.QtCore import (
    QAbstractAnimation, QEasingCurve, QEvent, QMimeData, QPoint, QPointF, QPropertyAnimation, QRect, QRectF, QSize, Qt,
    QTimer, QUrl, Signal, QVariantAnimation,
)
from PySide6.QtGui import (
    QAction, QActionGroup, QColor, QCursor, QDrag, QFont, QFontMetrics, QIcon, QKeySequence,
    QLinearGradient, QMovie, QPainter, QPainterPath, QPen, QPixmap, QPolygonF, QRegion,
    QShortcut, QTextDocument,
)
from PySide6.QtWidgets import (
    QApplication, QBoxLayout, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QFrame, QGridLayout, QHBoxLayout, QLabel,
    QInputDialog, QLineEdit, QMenu, QPushButton, QScrollArea, QSizePolicy, QSlider, QStyle, QTextBrowser,
    QStyleOptionToolButton, QToolButton, QVBoxLayout, QWidget, QWidgetAction,
)

from . import layouts, motion, mouse_hook, theme
from . import version as version_module
from .auto_quality import AUTO_QUALITY, OVERSEAS_PLATFORMS
from .images import AvatarLoader
from . import follow_folders
from .player import TilePlayer
from .video_danmaku import VideoDanmaku
from .video_danmaku_settings import VideoDanmakuSettings

AVATAR_COLORS = ["#4c6ef5", "#12b886", "#f76707", "#ae3ec9", "#1098ad", "#e8590c", "#5f3dc4"]

QUALITY_CHOICES = [("原画", 10000), ("蓝光", 400), ("超清 720P", 250), ("流畅", 80)]
QUALITY_NAMES = {value: name for name, value in QUALITY_CHOICES}

TILE_BAR_HEIGHT = 36          # 底部信息条高度（不覆盖画面）
ROOM_MIME = "application/x-ddm-room"
TILE_MIME = "application/x-ddm-tile"
DANMAKU_MIME = "application/x-ddm-danmaku"
NAV_MIME = "application/x-ddm-nav"          # 关注列表内部排序用
FOLDER_MIME = "application/x-ddm-folder"    # 文件夹之间排序，不改变卡片归属

BADGE_HEIGHT = 24             # 左上角浮标高度
WATCHING_TEXT = "正在获取人数"   # 还没拉到实时在线人数时的占位（不能用"人气"顶上）
NAV_ITEM_HEIGHT = 128         # 展开时：206x116 左右，接近 16:9，悬停预览才看得清
NAV_LIST_ITEM_HEIGHT = 60     # 简洁模式：头像 + 两行文字
NAV_COMPACT_ITEM_HEIGHT = 60  # 收起时保持此前的头像间距和滚动手感
NAV_ITEM_GAP = 2              # 项与项之间的间距
CAROUSEL_WIDTH = 206          # 竖屏顶部横栏里横向卡片的宽度（和侧栏展开时一样宽）
PORTRAIT_LIST_WIDTH = 100     # 竖屏简洁模式：窄竖条，仍横向滚动
PORTRAIT_LIST_HEIGHT = NAV_ITEM_HEIGHT  # 竖屏展开栏恢复原 196px 高度
HOLE_SIZE = 16                # 浮标左侧圆形镂空直径
HOLE_MARGIN = 4
ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
BRAND_ASSETS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(sys.executable))
    if getattr(sys, "frozen", False)
    else os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "assets",
)


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


def _badge_font() -> QFont:
    """画面浮标用的字体。

    量文字宽度和画文字都必须用它，**不能用 `widget.fontMetrics()`**：
    QSS 里的 font-size 是 polish 之后才落到控件上的，构造时量出来的宽度会偏小，
    等真正画的时候字变大，人数就被自己的遮罩截掉了（用户报的「人数被遮挡」）。
    """
    font = QFont(theme.FONT_DEFAULT)
    font.setPixelSize(theme.FONT_CONTROL)
    return font


class StreamBadge(QWidget):
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
        self.setMask(QRegion(self._mask_path.toFillPolygon().toPolygon()))

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillPath(self._mask_path, QColor("#15171c"))
        dot = HOLE_MARGIN + HOLE_SIZE / 2
        center = QPointF(dot, BADGE_HEIGHT / 2)
        painter.setPen(QPen(QColor("#7b828c"), 2))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(center, HOLE_SIZE / 2 - 1, HOLE_SIZE / 2 - 1)
        painter.setBrush(QColor("#fb7299" if self.live else "#7b828c"))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(center, 4.5, 4.5)
        font = _badge_font()
        painter.setFont(font)
        metrics = QFontMetrics(font)
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
        metrics = QFontMetrics(_badge_font())
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
        painter.setFont(_badge_font())
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
            self.CHANNEL_LEFT: "　声道：左",
            self.CHANNEL_RIGHT: "　声道：右",
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


class SidebarToggleButton(QPushButton):
    """收起 / 展开的箭头键。

    横屏（侧栏在左）沿用原来的左右字形「« / »」；竖屏时侧栏变成顶部横栏，
    左右箭头方向不对，改成**自己画的上下箭头**（用户要求）。上下箭头不用
    `⌃`/`⌄` 这类字形 —— 雅黑下不可靠，和 `BarIconButton` 一个路子自己画。
    展开时箭头朝上（点一下收起来），收起时朝下（点一下放下来）。
    """

    def __init__(self, parent=None):
        super().__init__("«", parent)
        self.setObjectName("SidebarToggle")
        self.setCursor(Qt.PointingHandCursor)
        self.portrait = False
        self.collapsed = False

    def set_orientation(self, portrait: bool, collapsed: bool) -> None:
        """竖屏走自绘的上下箭头，横屏回到原来的字形。"""
        self.portrait = bool(portrait)
        self.collapsed = bool(collapsed)
        self.setText("" if self.portrait else ("»" if self.collapsed else "«"))
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)          # 背景 / 悬停底色交给样式表
        if not self.portrait:
            return                         # 横屏：字形已经由 QPushButton 画好
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(theme.qcolor(theme.TEXT1 if self.underMouse() else theme.TEXT3), 1.8)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        center = self.rect().center()
        half = 4.2
        up = not self.collapsed
        tip_y = center.y() - 3.4 if up else center.y() + 3.4
        base_y = center.y() + 3.4 if up else center.y() - 3.4
        painter.drawLine(QPointF(center.x() - half, base_y),
                         QPointF(center.x(), tip_y))
        painter.drawLine(QPointF(center.x() + half, base_y),
                         QPointF(center.x(), tip_y))


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
        self._angle = 0.0
        self._spin = QVariantAnimation(self)
        self._spin.setStartValue(0.0)
        self._spin.setEndValue(360.0)
        self._spin.setDuration(1000)
        self._spin.setLoopCount(-1)
        self._spin.setEasingCurve(QEasingCurve.Linear)
        self._spin.valueChanged.connect(self._spin_frame)

    def _spin_frame(self, angle):
        self._angle = angle
        self.update()

    def set_refreshing(self, busy):
        self.setProperty("refreshing", busy)
        if busy and self._spin.state() == QAbstractAnimation.Running and motion.enabled():
            return
        self._spin.stop()
        self._angle = 0.0
        if busy and self.isVisible() and motion.enabled():
            self._spin.start()
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        self.set_refreshing(bool(self.property("refreshing")))

    def hideEvent(self, event):
        self._spin.stop()
        super().hideEvent(event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        center = QPointF(self.width() / 2, self.height() / 2)
        painter.translate(center)
        painter.rotate(self._angle)
        painter.translate(-center)
        if self.property("refreshing"):
            color = QColor(theme.ACCENT)
        else:
            color = _icon_color(self, hover_dark=self.objectName() not in ("ChipButton", "BarIcon"))
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

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        copy_action = menu.addAction("复制", self.copy)
        copy_action.setShortcut(QKeySequence.Copy)
        copy_action.setEnabled(self.textCursor().hasSelection())
        link = self.anchorAt(event.pos())
        if link:
            menu.addAction("复制链接地址", lambda: QApplication.clipboard().setText(link))
        menu.addSeparator()
        select_action = menu.addAction("全选", self.selectAll)
        select_action.setShortcut(QKeySequence.SelectAll)
        select_action.setEnabled(not self.document().isEmpty())
        try:
            menu.exec(event.globalPos())
        finally:
            menu.deleteLater()

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

    MAX_BLOCKS = 3000         # 默认最多留多少条（设置里可改）
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
        self._scroll_restore_id = 0
        self._scroll_trim_remainder = 0.0
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
        self.body.document().setMaximumBlockCount(self.max_blocks)
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
        self._scroll_revision += 1
        self._scroll_trim_remainder = 0.0
        self._blocks = []
        self._has_content = False
        self._received = 0
        self._status = "未接入"
        self._follow_tail = True
        self._refresh_count()
        self.body.setHtml(
            f'<div style="color:#8a8f98;line-height:160%">{text}</div>')

    def set_status(self, text: str) -> None:
        """连接状态（连接中… / 已连接 / 连接失败…）。"""
        self._status = text
        self._refresh_count()
        if text == "已连接" and not self._has_content:
            self.body.setHtml('<div style="color:#8a8f98;line-height:160%">等待弹幕…</div>')

    def set_count(self, text: str) -> None:
        self._status = text
        self._refresh_count()

    def _refresh_count(self) -> None:
        text = self._status
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
        removed = max(0, len(self._blocks) - self.max_blocks)
        scroll_state = self._scroll_state(removed)
        if removed:
            self._blocks = self._blocks[-self.max_blocks:]
        block = self._block_html(entry)
        if self._has_content:
            self.body.append(block)
        else:
            self.body.setHtml(block)              # 第一条：先把占位文字换掉
            self._has_content = True
        self._restore_scroll_state(scroll_state)

    def _scroll_state(self, removed_blocks: int = 0) -> tuple[bool, int, int]:
        scroll_bar = self.body.verticalScrollBar()
        value = scroll_bar.value()
        if removed_blocks and not self._follow_tail:
            document = self.body.document()
            remaining = document.findBlockByNumber(removed_blocks)
            if remaining.isValid():
                layout = document.documentLayout()
                removed_height = (layout.blockBoundingRect(remaining).top()
                                  - layout.blockBoundingRect(document.firstBlock()).top())
                # 字体行高可能有小数，逐条取整会让阅读位置不断漂移。
                offset = removed_height + self._scroll_trim_remainder
                pixels = round(offset)
                self._scroll_trim_remainder = offset - pixels
                value = max(0, value - pixels)
        return self._follow_tail, value, self._scroll_revision

    def _restore_scroll_state(self, state: tuple[bool, int, int]) -> None:
        """内容更新不能打断用户阅读；仍在末尾时才继续跟随。"""
        follow_tail, value, revision = state
        self._follow_tail = follow_tail
        self._scroll_restore_id += 1
        restore_id = self._scroll_restore_id

        def restore() -> None:
            if revision != self._scroll_revision or restore_id != self._scroll_restore_id:
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
        self._scroll_trim_remainder = 0.0
        self._follow_tail = self._at_scroll_tail()

    def _on_scroll_pressed(self) -> None:
        self._scroll_revision += 1
        self._scroll_trim_remainder = 0.0
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
        scroll_state = self._scroll_state(max(0, len(self._blocks) - self.max_blocks))
        if len(self._blocks) > self.max_blocks:
            self._blocks = self._blocks[-self.max_blocks:]
        self.body.document().setMaximumBlockCount(self.max_blocks)
        self._restore_scroll_state(scroll_state)

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
        """整体重排（表情图下好、或者字体变化时用）。"""
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
        self._index = index
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

    def set_color(self, color: str | None = None) -> None:
        """换底色；传 None 回到按序号取的那个彩色。

        未登录的「登录」按钮用中性底色（用户要求「颜色不要这么突出」），
        有真实头像时底色反正看不见，不用管。
        """
        self._color = color or AVATAR_COLORS[self._index % len(AVATAR_COLORS)]
        if self._source is None:
            self.setStyleSheet(f"background: {self._color}; "
                               f"border-radius: {self._size // 2}px;")

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
    logoutClicked = Signal()

    def __init__(self, parent=None, *, allow_logout=False):
        super().__init__(parent)
        self.setObjectName("AccountRow")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(34)          # 和底部两个按钮同高、同圆角
        self.uname = ""
        self.platform = ""
        self.uid = ""
        self._allow_logout = allow_logout

        layout = QHBoxLayout(self)
        # 头像 26px：上下各留 4px 正好 34px 高，内容才能真的垂直居中
        # （原来留 6px，26 的头像塞不进 22 的空间，整行看着是偏的）
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)
        self.avatar = Avatar("?", 3, 26)
        layout.addWidget(self.avatar)
        self.platform_badge = QLabel(self)
        self.platform_badge.setFixedSize(12, 12)
        self.platform_badge.setStyleSheet("background: transparent; border: none;")
        _ignore_mouse(self.platform_badge)
        self.platform_badge.hide()
        self.account_text = QWidget()
        text_layout = QVBoxLayout(self.account_text)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(0)
        self.name = ElidedLabel("")
        self.name.setObjectName("NavName")
        _ignore_mouse(self.name)
        _allow_shrink(self.name)
        text_layout.addWidget(self.name)
        self.account_id = ElidedLabel("")
        self.account_id.setObjectName("NavSub")
        self.account_id.setStyleSheet("font-size: 10px;")
        self.account_id.setFixedHeight(12)
        _ignore_mouse(self.account_id)
        _allow_shrink(self.account_id)
        text_layout.addWidget(self.account_id)
        self.account_id.hide()
        _allow_shrink(self.account_text)
        _ignore_mouse(self.account_text)
        layout.addWidget(self.account_text, 1)
        layout.addWidget(self.platform_badge)
        self.arrow = QLabel("⋯")
        self.arrow.setObjectName("NavSub")
        _ignore_mouse(self.arrow)
        layout.addWidget(self.arrow)
        self.logout_button = QPushButton("退出", self)
        self.logout_button.setObjectName("AccountLogoutButton")
        self.logout_button.setStyleSheet(f"""padding: 0; min-height: 0; min-width: 0; text-align: center;
            background: {theme.CONTENT}; border: 1px solid {theme.BORDER}; border-radius: 12px;""")
        self.logout_button.setFixedSize(44, 24)
        self.logout_button.clicked.connect(self.logoutClicked)
        layout.addWidget(self.logout_button)
        self.logout_button.hide()
        self._layout = layout
        self._compact_spacer = False

    def set_account(self, uname: str, pixmap=None, *, platform="bilibili", uid="") -> None:
        self.uname = uname or ""
        self.platform = platform if self.uname else ""
        self.uid = str(uid or "") if self.uname else ""
        self.logout_button.setVisible(self._allow_logout and bool(self.uname)
                                      and not getattr(self, "_compact", False))
        self.account_id.setText("ID: " + self.uid if self.uid else "")
        self.account_id.setVisible(bool(self.uid))
        self.name.setStyleSheet("font-size: 11px;" if self.uid else "")
        self.name.setMaximumHeight(14 if self.uid else 16_777_215)
        if pixmap is None:
            self.avatar._source = None
            self.avatar.clear()
        if self.uname:
            self.name.setText(self.uname)
            self.arrow.setVisible(not self._allow_logout and not getattr(self, "_compact", False))
            self.setToolTip(self.uname + (" · ID: " + self.uid if self.uid else ""))
            icon_path = os.path.join(BRAND_ASSETS_DIR, "platforms",
                                     "huya.png" if platform == "huya" else platform + ".ico")
            if not os.path.isfile(icon_path):
                icon_path = os.path.join(BRAND_ASSETS_DIR, "platforms", "generic.svg")
            self.platform_badge.setPixmap(QIcon(icon_path).pixmap(12, 12))
            self.platform_badge.setAccessibleName(platform)
            self.platform_badge.setVisible(not getattr(self, "_compact", False))
            self.avatar.set_color(None)          # 回到彩色（哈希取的）
            if pixmap is not None:
                self.avatar.set_pixmap_image(pixmap)
            else:
                self.avatar.setText(self.uname[0])
            return
        # 未登录：这一格当「登录」按钮（用户要求：没登录也放出来）。
        # 底色用中性色，别像彩色头像那么显眼
        self.name.setText("登录")
        self.avatar.setText("登")
        self.avatar.set_color(theme.CONTENT_HOVER)
        self.arrow.setVisible(False)
        self.platform_badge.hide()
        self.setToolTip("选择平台并登录账号")

    def set_compact(self, compact: bool, *, avatar: int | None = None,
                    margin: int = 6) -> None:
        """侧栏收起后只留头像：尺寸跟列表里的主播头像一样，同样居中。

        avatar / margin：竖屏横栏收起时账号头像要和头排头像同尺寸、同一行
        （那边一行只有 36px），所以允许指名头像大小和上下留白。
        """
        compact = bool(compact)
        size = theme.AVATAR_SIZE if avatar is None else int(avatar)
        state = (compact, size, int(margin))
        if state == getattr(self, "_compact_state", None):
            return
        self._compact_state = state
        self._compact = compact
        self.account_text.setVisible(not compact)
        # 未登录时这一格是「登录」按钮，不该带菜单那个 ⋯
        self.arrow.setVisible(not self._allow_logout and not compact and bool(self.uname))
        self.logout_button.setVisible(self._allow_logout and not compact and bool(self.uname))
        self.avatar.set_size(size if compact else 26)
        self.platform_badge.setVisible(not compact and bool(self.uname))
        self.setFixedHeight(size + margin * 2 if compact else 34)
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
            self._layout.setContentsMargins(0, margin, 0, margin)
        else:
            # 展开态：34 高的行里放 26 的头像，上下各 4 才真的居中
            self._layout.setContentsMargins(8, 4, 8, 4)
        self._layout.setSpacing(0 if compact else 8)
        self.setToolTip(self.uname + (" · ID: " + self.uid if self.uid else "") if self.uname else
                       "选择平台并登录账号")

    def mouseReleaseEvent(self, event) -> None:
        # 未登录时这一格是「登录」按钮，也要能点 —— 以前这里卡了 `and self.uname`，
        # 登录按钮点下去什么也不发生（用户实测）
        if event.button() == Qt.LeftButton:
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
    PORTRAIT_AVATAR_SIZE = 48

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
        self._portrait_strip = False
        self._player: TilePlayer | None = None
        self._overlay_widgets: tuple[QWidget, QWidget, QWidget, QWidget] | None = None

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
        self._cover_hold = False         # 宽度动画期间挂起封面重裁，见 set_cover_hold()
        self._cover_source: QPixmap | None = None
        self._face_source: QPixmap | None = None

    # ---- 外观 ----
    def set_overlay_widgets(self, name: QWidget, title: QWidget, badge: QWidget,
                            platform: QWidget) -> None:
        self._overlay_widgets = (name, title, badge, platform)
        for widget in self._overlay_widgets:
            widget.setParent(self)
            widget.raise_()
        self._layout_overlay()

    def _layout_overlay(self) -> None:
        if self._overlay_widgets is None:
            return
        name, title, badge, platform = self._overlay_widgets
        compact = self._compact_thumb()
        parent = self.face if compact else self
        if platform.parentWidget() is not parent:
            platform.setParent(parent)
            platform.setVisible(not self.video.isVisible() and
                                platform.property("showPlatform") is not False)
        platform.setFixedSize(14 if compact else 24, 14 if compact else 22)
        platform.setPixmap(platform.icon.pixmap(12 if compact else 20, 12 if compact else 20))
        if compact:
            platform.move(0, max(0, self.face.height() - platform.height()))
            platform.setVisible(platform.property("showPlatform") is not False)
            platform.raise_()
            return
        width, height = self._size
        platform.move(8 if self._card_mode and not self._portrait_strip else
                      max(4, width - platform.width() - 8),
                      height - 24 if self._card_mode and not self._portrait_strip else 4)
        if self._portrait_strip:
            name.setGeometry(4, 67, max(0, width - 8), 20)
            name.setAlignment(Qt.AlignCenter)
            title.setGeometry(4, 89, max(0, width - 8), 18)
            title.setAlignment(Qt.AlignCenter)
            badge.hide()
            name.raise_()
            title.raise_()
            platform.raise_()
            return
        name.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        text_left = 48 if self._card_mode else 44
        right = 8
        name_y = 7 if self._card_mode else 3
        second_y = 29 if self._card_mode else 25
        badge_y = (height - 24) if self._card_mode else (second_y + 1)
        name.setGeometry(text_left, name_y,
                         max(0, width - text_left - right -
                             (platform.width() + 6 if not self._card_mode and
                              platform.property("showPlatform") is not False else 0)), 20)
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

    def face_pixmap(self) -> QPixmap | None:
        """已经下载好的主播头像（顶部横栏的头像排要用同一张）。"""
        return self._face_source

    def _avatar_size(self) -> int:
        return (self.COMPACT_SIZE if self._compact_thumb() else
                self.PORTRAIT_AVATAR_SIZE if self._portrait_strip else self.AVATAR_SIZE)

    def _face_letter(self) -> str:
        """还没拿到头像时顶上去的那个字：主播名首字，取不到就是问号。"""
        room = getattr(self.parentWidget(), "room", None) or {}
        name = str(room.get("uname") or "").strip()
        return name[0] if name else "?"

    def _render_face(self) -> None:
        """头像的尺寸、位置、可见性**全在这里算**。

        以前这三件事散在三处：这里末尾写「视频没在播就露脸」、`resizeEvent` 之后的
        `_sync_geometry` 里写「有 pixmap 才露脸」、初始化时写死 `False` ——
        谁最后跑谁说了算，同一条目会随着布局/尺寸变化在「露脸」和「不露」之间跳。
        收起的关注栏**只有头像这一样东西**（封面本来就不显示），一旦走了后一条，
        整个条目就空掉，头像还没下到的那段时间尤其明显。

        另外：拿不到头像时不再直接 return，而是用主播名首字顶着 —— 否则连尺寸和
        位置都不更新，收起后条目的留白也全是错的。
        """
        size = self._avatar_size()
        self.face.set_size(size)
        pixmap = self._face_source
        if pixmap is not None and not pixmap.isNull():
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
        else:
            # 还没下到头像：用名字首字顶着，别让条目空着
            self.face.setText(self._face_letter())
            self.face.set_color(None)
        self._place_face()
        self.face.raise_()
        # 紧凑条目只有头像可认，所以一定要露；卡片模式封面才是主体，头像还没下到
        # 就先别占那一块。视频预览占着整块时两者都让位。
        self.face.setVisible(not self.video.isVisible() and
                             (self._compact_thumb() or pixmap is not None))

    def _face_local_rect(self) -> QRect:
        """展开时头像叠在封面左侧；收起时在 32px 方框中居中。"""
        width, height = self._size
        avatar_size = (self.COMPACT_SIZE if self._compact_thumb() else
                       self.PORTRAIT_AVATAR_SIZE if self._portrait_strip else self.AVATAR_SIZE)
        if self._compact_thumb():
            return QRect((width - avatar_size) // 2,
                         (height - avatar_size) // 2,
                         avatar_size, avatar_size)
        if self._portrait_strip:
            return QRect((width - avatar_size) // 2, 8, avatar_size, avatar_size)
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

    def refresh_cover(self) -> None:
        """强制重裁一次封面（收起/展开动画结束后补账用）。"""
        self._render_cover()

    def set_cover_hold(self, hold: bool) -> None:
        """宽度动画期间挂起封面重裁。

        侧栏收起/展开是改宽度的动画，**每一帧**都会让每个条目收到 resizeEvent，
        而 `_render_cover()` 每次都要做一次平滑缩放 + 圆角裁剪 + 两段渐变填充 ——
        36 个关注就是每帧 36 次，动画自然卡。挂起期间让 QLabel 先拉伸旧图顶着
        （`setScaledContents`），动画结束再补一次精确的。
        """
        hold = bool(hold)
        if hold == self._cover_hold:
            return
        self._cover_hold = hold
        try:
            self.cover.setScaledContents(hold)
        except RuntimeError:                    # 控件已经被回收
            return
        # 解除挂起时**不在这里**重绘：由调用方决定哪些条目值得立刻补
        # （见 Sidebar._finish_collapse）—— 36 条一起补会把收尾那一下又拖垮。
        # 没补到的条目滚进视野时会收到 resizeEvent，那时自然会重裁。

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
        if self._cover_hold:
            return                       # 宽度动画期间不重裁，见 set_cover_hold()
        if self._compact_thumb():
            return                       # 收起后封面隐藏，展开时再裁切即可
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
        """预览画面占据的矩形。

        卡片模式（封面铺满条目）和竖屏条都用整块。紧凑的长条卡片**不放预览**
        （只有 48px 高，画面会被压扁；预览改在卡片旁边弹浮层），所以这里也不用再
        算「右侧 1/3」那块小窗了。
        """
        return self.rect()

    def _set_overlay_visible(self, visible: bool) -> None:
        if self._overlay_widgets is None:
            return
        for widget in self._overlay_widgets:
            widget.setVisible(bool(visible) and (not self._compact or widget is self._overlay_widgets[3])
                              and (not self._portrait_strip or widget is not self._overlay_widgets[2])
                              and (widget is not self._overlay_widgets[3] or
                                   widget.property("showPlatform") is not False))

    def set_portrait_strip(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled == self._portrait_strip:
            return
        if self._player is not None:
            self.stop()
        self._portrait_strip = enabled
        if not self._compact:
            height = (PORTRAIT_LIST_HEIGHT - 12 if enabled else
                      self.HEIGHT if self._card_mode else self.LIST_HEIGHT)
            self.setFixedHeight(height)
        self._render_face()
        self._place_face()
        self._layout_overlay()
        self._set_overlay_visible(True)

    def set_card_mode(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled == self._card_mode:
            return
        if self._player is not None:
            self.stop()
        self._card_mode = enabled
        if not self._compact:
            height = (PORTRAIT_LIST_HEIGHT - 12 if self._portrait_strip else
                      self.HEIGHT if enabled else self.LIST_HEIGHT)
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
        expanded_height = (PORTRAIT_LIST_HEIGHT - 12 if self._portrait_strip else
                           self.HEIGHT if self._card_mode else self.LIST_HEIGHT)
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
        self._render_face()          # 可见性也归它管（见 _render_face）
        self._render_cover()
        self._layout_overlay()

    # ---- 预览播放 ----
    def _ensure_player(self) -> TilePlayer:
        """预览播放器一个卡片只建一次，之后换台只 stop / play（和画面墙的格子一样）。

        以前每次悬停都新建 TilePlayer、鼠标一移开就 release()：libvlc 的
        media_player 建了又拆比 stop / play 重得多，而且建和拆都发生在主线程上，
        卡死风险高得多 —— 用户报的「悬停预览时窗口卡死」就出在这一带。
        """
        if self._player is None:
            # silent=True：预览用**自己的** libvlc 实例（dummy 音频输出），
            # 从根上保证它出不了声 —— 用户那边一直听得到预览的声音
            self._player = TilePlayer(self.video, self, silent=True)
            self._player.freeze_watch = False        # 缩略图不用卡死检测
            self._player.stateChanged.connect(self._on_player_state)
        return self._player

    def play(self, url: str, profile: str = "web", options=None, *, headers=None) -> None:
        """在这个缩略图里放预览（静音、低画质）。

        ``options`` 由预览那边给（见 ddm/preview.py 的 PREVIEW_MEDIA_OPTIONS）。
        """
        if self._compact_thumb():
            return                         # 收起的关注栏固定显示主播头像
        if not self._card_mode:
            # 紧凑（长条）卡片里**不塞预览**：这行只有 LIST_HEIGHT(48) 高，塞进去
            # 只会得到一块压扁的小画面 —— 用户要求把卡片里那个小预览窗删掉。
            # 紧凑布局的预览改成在卡片旁边弹浮层，见 ddm/preview.py 的 _needs_popup()。
            return
        player = self._ensure_player()
        self.video.setGeometry(self._preview_rect())
        self.hint.setGeometry(self._preview_rect())
        self.video.setVisible(True)
        self.video.raise_()
        # 大卡片预览时让画面完全干净；简洁列表的预览只占右侧三分之一，左侧信息保留。
        self._set_overlay_visible(not self._card_mode and not self._portrait_strip)
        self.face.setVisible(not self._card_mode and not self._portrait_strip)
        self.hint.setVisible(False)
        player.set_muted(True)                       # 预览永远静音
        player.set_volume(0)
        player.play(url, profile, headers=headers, options=options)

    def stop(self) -> None:
        """收掉预览，回到封面（播放器留着复用，下回悬停直接 play）。"""
        if self._player is not None:
            self._player.stop()
        self.video.setVisible(False)
        self.hint.setVisible(False)
        self.video.setGeometry(self.rect())
        self.hint.setGeometry(self.rect())
        self.cover.setVisible(self._card_mode and not self._compact_thumb())
        self.face.setVisible(bool(self.face.pixmap()))
        self._set_overlay_visible(True)

    def release_player(self) -> None:
        """真正放掉预览播放器：只在关窗时用，平时留着复用。"""
        if self._player is None:
            return
        self._player.release()
        self._player = None

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
    openBrowserRequested = Signal(str)
    checkedChanged = Signal()
    pinToggled = Signal(dict)
    hovered = Signal(dict)             # 鼠标停在条目上（给悬停预览用）
    unhovered = Signal(dict)

    def __init__(self, room: dict, index: int, parent=None):
        super().__init__(parent)
        self.setObjectName("NavItem")
        self.room = room
        self.setProperty("selected", room.get("selected", False))
        self.setProperty("sortSelected", False)
        self.setProperty("hovered", False)
        self.setProperty("onWall", False)
        self.setProperty("portraitStrip", False)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(NAV_ITEM_HEIGHT)
        self._compact = False
        self._card_mode = True
        self._compact_spacers = False
        self._portrait_strip = False
        self.select_mode = False
        self._drag_started = False
        self.filtered_out = False        # 搜索过滤：不匹配就藏起来
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
        self.sub = ElidedLabel(room.get("title") or
                               ("直播中" if room.get("live") else "未开播"))
        self.sub.setObjectName("NavSub")
        _ignore_mouse(self.name_label)
        _allow_shrink(self.name_label)
        _ignore_mouse(self.sub)
        _allow_shrink(self.sub)
        self.badge = QLabel("直播中" if room.get("live") else "未开播")
        if room.get("platform") in ("huya", "douyu", "douyin", "twitch", "youtube") and not room.get("live_known", True):
            self.badge.setText("待刷新")
        self.badge.setObjectName("BadgeLive" if room.get("live") else "BadgeOff")
        _ignore_mouse(self.badge)
        platform = room.get("platform") or str(room.get("room_id", "")).partition(":")[0]
        labels = {"huya": "虎牙", "douyu": "斗鱼", "douyin": "抖音", "twitch": "Twitch", "youtube": "YouTube"}
        label = "B站" if str(room.get("room_id", "")).isdigit() else labels.get(platform, platform)
        if str(room.get("room_id", "")).isdigit():
            platform = "bilibili"
        icon_path = os.path.join(BRAND_ASSETS_DIR, "platforms",
                                 "huya.png" if platform == "huya" else platform + ".ico")
        if not os.path.isfile(icon_path):
            icon_path = os.path.join(BRAND_ASSETS_DIR, "platforms", "generic.svg")
        self.platform_badge = QLabel()
        self.platform_badge.icon = QIcon(icon_path)
        self.platform_badge.setObjectName("NavPlatformBadge")
        self.platform_badge.setAlignment(Qt.AlignCenter)
        self.platform_badge.setToolTip(label)
        self.platform_badge.setAccessibleName(label)
        self.platform_badge.setStyleSheet(
            "background: transparent; border: none;")
        _ignore_mouse(self.platform_badge)
        self.thumb.set_overlay_widgets(self.name_label, self.sub, self.badge, self.platform_badge)
        self.setToolTip("")

    def set_on_wall(self, on_wall: bool) -> None:
        """标出这一路已经在画面墙中；蓝色与粉色开播状态互不混淆。"""
        on_wall = bool(on_wall)
        if self.property("onWall") is on_wall:
            return
        self.setProperty("onWall", on_wall)
        _repolish(self)

    def set_portrait_strip(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled == self._portrait_strip:
            return
        self._portrait_strip = enabled
        self.setProperty("portraitStrip", enabled)
        _repolish(self)
        self.thumb.set_portrait_strip(enabled)
        self._sync_live_dot()
        if not self._compact:
            self.setFixedHeight(PORTRAIT_LIST_HEIGHT if enabled else
                                (NAV_ITEM_HEIGHT if self._card_mode else NAV_LIST_ITEM_HEIGHT))
        self._layout.setContentsMargins(8, 6, 10, 6)

    def _sync_live_dot(self) -> None:
        size = self.live_dot.width()
        self.live_dot.move(max(0, self.thumb.face.width() - size),
                           max(0, self.thumb.face.height() - size))
        self.live_dot.setVisible((self._compact or self._portrait_strip)
                                 and bool(self.room.get("live")))
        self.live_dot.raise_()

    def set_compact(self, compact: bool) -> None:
        if compact == self._compact:
            return
        self._compact = compact
        expanded_height = (PORTRAIT_LIST_HEIGHT if self._portrait_strip else
                           NAV_ITEM_HEIGHT if self._card_mode else NAV_LIST_ITEM_HEIGHT)
        self.setFixedHeight(NAV_COMPACT_ITEM_HEIGHT if compact else expanded_height)
        for widget in (self.name_label, self.sub, self.badge, self.platform_badge):
            widget.setVisible(not compact and (widget is not self.platform_badge or
                              self.platform_badge.property("showPlatform") is not False))
        self.thumb.set_thumb_size(compact)
        if not compact and self._portrait_strip:
            self.thumb._layout_overlay()
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
        self._layout.setContentsMargins(0 if compact else 8, 6,
                                        0 if compact else 10, 6)
        self._layout.setSpacing(0 if compact else 10)   # 收起时别留间距，头像才真正居中

    def set_card_mode(self, enabled: bool) -> None:
        """展开侧栏时在大封面卡片和头像＋文字列表之间切换。"""
        enabled = bool(enabled)
        if enabled == self._card_mode:
            return
        self._card_mode = enabled
        self.thumb.set_card_mode(enabled)
        if not self._compact:
            self.setFixedHeight(NAV_ITEM_HEIGHT if enabled else
                                (PORTRAIT_LIST_HEIGHT if self._portrait_strip else NAV_LIST_ITEM_HEIGHT))

    def set_filtered_out(self, hidden: bool) -> None:
        """搜索不匹配就藏起来。只动可见性 —— 排序、置顶、多选态都不碰。"""
        hidden = bool(hidden)
        if hidden == self.filtered_out:
            return
        self.filtered_out = hidden
        self.setVisible(not hidden)

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

    def set_sort_selected(self, selected: bool) -> None:
        if self.property("sortSelected") == selected:
            return
        self.setProperty("sortSelected", selected)
        _repolish(self)

    def set_live(self, live: bool) -> None:
        self.room["live"] = live
        self.badge.setText("直播中" if live else "未开播")
        if not self.room.get("title"):
            self.sub.setText("直播中" if live else "未开播")
        self.badge.setObjectName("BadgeLive" if live else "BadgeOff")
        _repolish(self.badge)
        self._sync_live_dot()
        self.thumb._layout_overlay()

    def set_title(self, title: str) -> None:
        """更新卡片上的直播间名，并同步悬停时的完整提示。"""
        self.room["title"] = title or ""
        self.sub.setText(title or "未开播")
        self.thumb._layout_overlay()

    def set_uname(self, uname: str) -> None:
        """补上主播名：启动时占位条目只有「房间 X」，状态刷新后才拿到真名。"""
        self.room["uname"] = uname or ""
        self.name_label.setText(self.room["uname"]
                                or str(self.room.get("room_id") or ""))
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
        # 左上角的置顶角标：顺着卡片圆角（QSS 里 #NavItem 用的 RADIUS_MD）
        # 画一段弧，而不是原来那个直角三角 —— 这样标记是贴着圆角边框走的
        thickness = 3.0
        corner = float(theme.RADIUS_MD)
        radius = corner - thickness / 2
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(QColor(theme.ACCENT), thickness)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawArc(QRectF(corner - radius, corner - radius, radius * 2, radius * 2),
                        90 * 16, 90 * 16)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            return
        if self._drag_started:
            self._drag_started = False
            return
        if self.select_mode:
            self.check.setChecked(not self.check.isChecked())
            self.checkedChanged.emit()
            return
        if self.drop_host is not None:
            self.drop_host.select_sort_item(str(self.room.get("room_id")), event.modifiers())
            if event.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier):
                return
        self.clicked.emit(self.room)

    def mousePressEvent(self, event) -> None:
        self._press_pos = event.pos()
        self._drag_started = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        """拖动 = 在关注列表里上下排序；拖到画面墙上就是在那个格子里播放。"""
        if not (event.buttons() & Qt.LeftButton):
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
        drag_ids = self.drop_host.dragged_room_ids(room_id)
        self._drag_started = True
        pixmap, hotspot = motion.lifted_drag(
            self._drag_pixmap(len(drag_ids)),
            QPoint(min(event.pos().x(), self.width() - 1), event.pos().y()))
        drag.setPixmap(pixmap)
        drag.setHotSpot(hotspot)
        # 抓起来的一瞬间就把自己那一格空出来
        self.drop_host.show_drop_indicator(room_id, self._index_in_host())
        # 拖动期间把滚轮借过来：DnD 里 Qt 收不到滚轮，只能靠低级鼠标钩子
        host = self.drop_host
        if host is not None:
            host.begin_drag_scroll()
        try:
            drag.exec(Qt.CopyAction | Qt.MoveAction)
        finally:
            if host is not None:
                host.end_drag_scroll()
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
        items = self.drop_host.visible_items()
        for index, item in enumerate(items):
            if item is self:
                return index
        return 0

    def _drag_pixmap(self, count: int = 1) -> QPixmap:
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
        if count > 1:
            painter = QPainter(pixmap)
            badge = QRect(max(0, pixmap.width() - 39), 4, 35, 24)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(theme.ACCENT))
            painter.drawRoundedRect(badge, 12, 12)
            painter.setPen(QColor(theme.BG))
            painter.drawText(badge, Qt.AlignCenter, str(count))
            painter.end()
        return pixmap

    def mouseDoubleClickEvent(self, event) -> None:
        if not self.select_mode and not (event.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier)):
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

    def _context_menu(self) -> QMenu:
        """卡片右键菜单。

        内容单独一个方法，好处是自检可以直接看有哪些项、并触发某一项验证接线，
        不用真的把菜单弹出来（弹出来会挡住自检、也没法断言）。
        """
        menu = motion.AnimatedMenu(self)
        if not self.select_mode:
            menu.addAction("取消置顶" if self._pinned else "置顶").triggered.connect(
                lambda _checked=False: self.pinToggled.emit(self.room))
        if self.drop_host is not None:
            room_id = str(self.room.get("room_id"))
            selected = self.drop_host.selected_sort_ids()
            count = len(selected) if room_id in selected else 1
            prefix = f"将选中的 {count} 张" if count > 1 else ""
            menu.addAction(f"{prefix}移到最前").triggered.connect(
                lambda _checked=False: self.drop_host.move_sort_selection(room_id, True))
            menu.addAction(f"{prefix}移到最后").triggered.connect(
                lambda _checked=False: self.drop_host.move_sort_selection(room_id, False))
            folders = menu.addMenu("移入文件夹")
            folders.addAction("移出文件夹").triggered.connect(
                lambda: self.drop_host.move_to_folder(self.drop_host.dragged_room_ids(room_id), ""))
            for folder in self.drop_host.folders:
                if folder["type"] != "normal":
                    continue
                folders.addAction(folder["name"]).triggered.connect(
                    lambda _checked=False, fid=folder["id"]:
                    self.drop_host.move_to_folder(self.drop_host.dragged_room_ids(room_id), fid))
            folders.addSeparator()
            folders.addAction("新建文件夹…").triggered.connect(
                lambda: self.drop_host.prompt_folder(self.drop_host.dragged_room_ids(room_id)))
        if self.select_mode:
            return menu
        menu.addSeparator()
        menu.addAction("加入画面墙").triggered.connect(
            lambda _checked=False: self.addRequested.emit(self.room))
        url = (self.drop_host.browser_url_resolver(self.room)
               if self.drop_host is not None else "")
        if url:
            menu.addAction("用默认浏览器打开直播间").triggered.connect(
                lambda _checked=False: self.openBrowserRequested.emit(url))
        menu.addSeparator()
        menu.addAction("移除关注").triggered.connect(
            lambda _checked=False: self.removeRequested.emit(self.room))
        return menu

    def contextMenuEvent(self, event) -> None:
        room_id = str(self.room.get("room_id"))
        if (not self.select_mode and self.drop_host is not None
                and room_id not in self.drop_host.selected_sort_ids()):
            self.drop_host.clear_sort_selection()
        self._context_menu().exec_context(event)


class SmartFolderDialog(QDialog):
    """编辑状态、平台组合条件和文件夹内部排序。"""

    def __init__(self, sidebar, folder=None):
        super().__init__(sidebar)
        self.setWindowTitle("编辑智能文件夹" if folder else "新建智能文件夹")
        self.setMinimumWidth(360)
        folder = folder or {}
        rule = folder.get("rule") or {}
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name_edit = QLineEdit(folder.get("name", ""))
        self.status_combo = QComboBox()
        for value, label in (("any", "全部状态"), ("live", "开播"), ("offline", "未开播")):
            self.status_combo.addItem(label, value)
        self.status_combo.setCurrentIndex(max(0, self.status_combo.findData(rule.get("status", "any"))))
        self.sort_combo = QComboBox()
        for mode, label in sidebar.SORT_MODES:
            self.sort_combo.addItem(label, mode)
        self.sort_combo.setCurrentIndex(max(0, self.sort_combo.findData(folder.get("sort", "custom"))))
        form.addRow("文件夹名称", self.name_edit)
        sources = rule.get("sources", [follow_folders.UNCLASSIFIED] if folder else [])
        self.source_button = QPushButton()
        self.source_button.setObjectName("IconButton")
        self.source_menu = QMenu(self.source_button)
        source_content = QWidget()
        source_layout = QVBoxLayout(source_content)
        source_layout.setContentsMargins(12, 10, 12, 10)
        self.all_sources = QCheckBox("全部关注")
        self.all_sources.setChecked(not sources)
        source_layout.addWidget(self.all_sources)
        self.source_checks = {}
        options = [(source["id"], source["name"]) for source in sidebar.folders if source["type"] != "smart"]
        options.extend((fid, "原来源文件夹已删除（请重新选择）") for fid in sources
                       if fid not in dict(options))
        for fid, label in options:
            check = QCheckBox(label)
            check.setChecked(fid in sources)
            check.toggled.connect(self._source_changed)
            source_layout.addWidget(check)
            self.source_checks[fid] = check
        self.all_sources.toggled.connect(self._all_sources_changed)
        source_scroll = QScrollArea()
        source_scroll.setFrameShape(QFrame.NoFrame)
        source_scroll.setWidgetResizable(True)
        source_scroll.setMinimumWidth(260)
        source_scroll.setFixedHeight(min(260, source_content.sizeHint().height()))
        source_scroll.setWidget(source_content)
        source_action = QWidgetAction(self.source_menu)
        source_action.setDefaultWidget(source_scroll)
        self.source_menu.addAction(source_action)
        self.source_button.setMenu(self.source_menu)
        self._update_source_label()
        self.display_combo = QComboBox()
        self.display_combo.addItem("匹配时移入显示，不匹配时回到原处", "move")
        self.display_combo.addItem("保留原处，同时在智能文件夹显示", "copy")
        self.display_combo.setCurrentIndex(max(0, self.display_combo.findData(rule.get("display", "move"))))
        form.addRow("来源文件夹（可多选）", self.source_button)
        form.addRow("显示方式", self.display_combo)
        form.addRow("开播状态", self.status_combo)
        form.addRow("卡片排序", self.sort_combo)
        layout.addLayout(form)
        layout.addWidget(QLabel("平台筛选（不勾选表示全部平台）"))
        self.platform_checks = {}
        platforms = dict(follow_folders.PLATFORM_NAMES)
        for room in sidebar.rooms():
            platform = follow_folders.room_platform(room)
            platforms.setdefault(platform, platform)
        for platform in rule.get("platforms", []):
            platforms.setdefault(platform, platform)
        for platform, label in platforms.items():
            check = QCheckBox(label)
            check.setChecked(platform in rule.get("platforms", []))
            layout.addWidget(check)
            self.platform_checks[platform] = check
        hint = QLabel("从来源文件夹筛选同时满足状态与平台条件的主播，保留原归属。\n多条移入规则匹配时，优先显示在最靠前的智能文件夹。")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("保存")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.name_edit.textChanged.connect(lambda text: buttons.button(QDialogButtonBox.Ok).setEnabled(bool(text.strip())))
        buttons.button(QDialogButtonBox.Ok).setEnabled(bool(self.name_edit.text().strip()))
        layout.addWidget(buttons)

    def _source_changed(self, checked):
        if checked:
            self.all_sources.setChecked(False)
        elif not any(check.isChecked() for check in self.source_checks.values()):
            self.all_sources.setChecked(True)
        self._update_source_label()

    def _all_sources_changed(self, checked):
        if checked:
            for check in self.source_checks.values():
                check.setChecked(False)
        elif not any(check.isChecked() for check in self.source_checks.values()):
            self.all_sources.setChecked(True)
        self._update_source_label()

    def _update_source_label(self):
        labels = [check.text() for check in self.source_checks.values() if check.isChecked()]
        self.source_button.setText("全部关注" if not labels else labels[0] if len(labels) == 1
                                   else f"已选择 {len(labels)} 个文件夹")
        self.source_button.setToolTip("、".join(labels) if labels else "从全部关注中筛选")

    def values(self):
        return {"name": self.name_edit.text().strip(), "sort": self.sort_combo.currentData(),
                "rule": {"status": self.status_combo.currentData(),
                         "platforms": [key for key, check in self.platform_checks.items() if check.isChecked()],
                         "sources": [key for key, check in self.source_checks.items() if check.isChecked()],
                         "display": self.display_combo.currentData()}}


class SmartFolderCard(QWidget):
    """同一关注卡片的显示副本；操作使用原卡片，不增加关注或播放实例。"""

    def __init__(self, original, parent):
        super().__init__(parent)
        self.original = original
        self.room = original.room
        self._dragged = False
        self.setCursor(Qt.PointingHandCursor)
        original.installEventFilter(self)
        for child in original.findChildren(QWidget):
            child.installEventFilter(self)
        self._preview_timer = QTimer(self)
        self._preview_timer.setInterval(50)
        self._preview_timer.timeout.connect(self.update)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Paint and not getattr(self.original, "_smart_grabbing", False):
            self.update()
        return False

    def paintEvent(self, event):
        self.original._smart_grabbing = True
        try:
            pixmap = self.original.grab()
        finally:
            self.original._smart_grabbing = False
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), pixmap)

    def enterEvent(self, event):
        self._preview_timer.start()
        self.original.hovered.emit(self.room)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._preview_timer.stop()
        self.original.unhovered.emit(self.room)
        super().leaveEvent(event)

    def hideEvent(self, event):
        if self._preview_timer.isActive():
            self._preview_timer.stop()
            self.original.unhovered.emit(self.room)
        super().hideEvent(event)

    def mousePressEvent(self, event):
        self._press_pos = event.pos()
        self._dragged = False

    def mouseMoveEvent(self, event):
        if not event.buttons() & Qt.LeftButton or self._dragged:
            return
        if (event.pos() - self._press_pos).manhattanLength() < QApplication.startDragDistance():
            return
        self._dragged = True
        drag = QDrag(self)
        mime = QMimeData()
        rid = str(self.room["room_id"])
        mime.setData(ROOM_MIME, rid.encode("utf-8"))
        mime.setText(rid)
        drag.setMimeData(mime)
        pixmap, hotspot = motion.lifted_drag(self.grab(), event.pos())
        drag.setPixmap(pixmap)
        drag.setHotSpot(hotspot)
        drag.exec(Qt.CopyAction)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and not self._dragged:
            if self.original.select_mode:
                self.original.check.setChecked(not self.original.check.isChecked())
                self.original.checkedChanged.emit()
            else:
                self.original.clicked.emit(self.room)
            self.update()

    def contextMenuEvent(self, event):
        self.original._context_menu().exec_context(event)


class FollowFolderButton(QToolButton):
    """关注文件夹标题；点击展开，右键管理，拖入卡片归类。"""

    def __init__(self, sidebar, folder_id):
        super().__init__(sidebar.list_box)
        self.sidebar = sidebar
        self.folder_id = folder_id
        self.setObjectName("IconButton")
        kind = sidebar.get_folder(folder_id)["type"]
        self.setIcon(self.style().standardIcon(QStyle.SP_DirLinkIcon if kind == "smart" else QStyle.SP_DirIcon))
        self.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.setCursor(Qt.PointingHandCursor)
        self.setAcceptDrops(True)
        self.clicked.connect(lambda: sidebar.toggle_folder(folder_id, animate=self._press_pos is not None))
        self._press_pos = None
        self._drag_started = False

    def mousePressEvent(self, event):
        self._press_pos = event.position().toPoint() if event.button() == Qt.LeftButton else None
        self._drag_started = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._press_pos is None or not event.buttons() & Qt.LeftButton:
            super().mouseMoveEvent(event)
            return
        if (event.position().toPoint() - self._press_pos).manhattanLength() < QApplication.startDragDistance():
            super().mouseMoveEvent(event)
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(FOLDER_MIME, self.folder_id.encode("utf-8"))
        drag.setMimeData(mime)
        hotspot = QPoint(self._press_pos)
        self._press_pos = None
        self._drag_started = True
        self.setDown(False)
        self.sidebar.start_folder_drag()
        pixmap, hotspot = motion.lifted_drag(self.grab(), hotspot)
        drag.setPixmap(pixmap)
        drag.setHotSpot(hotspot)
        self.sidebar.begin_drag_scroll()
        try:
            drag.exec(Qt.MoveAction)
        finally:
            self.sidebar.end_drag_scroll()
            self.sidebar.end_folder_drag()
            self.setDown(False)
            drag.deleteLater()

    def mouseReleaseEvent(self, event):
        if self._drag_started:
            self._press_pos = None
            self._drag_started = False
            self.setDown(False)
            return
        super().mouseReleaseEvent(event)
        self._press_pos = None

    def paintEvent(self, event):
        if self.sidebar.side != "top":
            super().paintEvent(event)
            return
        option = QStyleOptionToolButton()
        self.initStyleOption(option)
        option.rect = QRect(0, 0, self.height(), self.width())
        painter = QPainter(self)
        painter.translate(self.width(), 0)
        painter.rotate(90)
        self.style().drawComplexControl(QStyle.CC_ToolButton, option, painter, self)

    def _context_menu(self):
        menu = motion.AnimatedMenu(self)
        folder = self.sidebar.get_folder(self.folder_id)
        self.sidebar.add_folder_sort_menu(menu.addMenu("排序"), folder)
        menu.addSeparator()
        if folder["type"] == "smart":
            menu.addAction("编辑智能文件夹…").triggered.connect(
                lambda: self.sidebar.prompt_smart_folder(self.folder_id))
        elif folder["type"] == "normal":
            menu.addAction("重命名文件夹…").triggered.connect(
                lambda: self.sidebar.prompt_folder(folder_id=self.folder_id))
        index = self.sidebar.folders.index(folder)
        up = menu.addAction("文件夹上移")
        up.setEnabled(index > 0)
        up.triggered.connect(lambda: self.sidebar.move_folder(self.folder_id, -1))
        down = menu.addAction("文件夹下移")
        down.setEnabled(index < len(self.sidebar.folders) - 1)
        down.triggered.connect(lambda: self.sidebar.move_folder(self.folder_id, 1))
        if folder["type"] != "unclassified":
            menu.addAction("删除文件夹（保留关注）").triggered.connect(
                lambda: self.sidebar.delete_folder(self.folder_id))
        return menu

    def contextMenuEvent(self, event):
        self._context_menu().exec_context(event)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(FOLDER_MIME) or (
                event.mimeData().hasFormat(NAV_MIME) and self.sidebar.get_folder(self.folder_id)["type"] != "smart"):
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(FOLDER_MIME):
            event.acceptProposedAction()
            folder_id = bytes(event.mimeData().data(FOLDER_MIME)).decode("utf-8", "ignore")
            self.sidebar.hover_folder_drag(folder_id, self.mapToGlobal(event.position().toPoint()))
        elif event.mimeData().hasFormat(NAV_MIME) and self.sidebar.get_folder(self.folder_id)["type"] != "smart":
            event.acceptProposedAction()

    def dropEvent(self, event):
        if event.mimeData().hasFormat(FOLDER_MIME):
            folder_id = bytes(event.mimeData().data(FOLDER_MIME)).decode("utf-8", "ignore")
            self.sidebar.finish_folder_drag(folder_id, self.mapToGlobal(event.position().toPoint()))
            event.acceptProposedAction()
        elif event.mimeData().hasFormat(NAV_MIME) and self.sidebar.get_folder(self.folder_id)["type"] != "smart":
            room_id = bytes(event.mimeData().data(NAV_MIME)).decode("utf-8", "ignore")
            self.sidebar.move_to_folder(self.sidebar.dragged_room_ids(room_id), self.folder_id)
            event.acceptProposedAction()


class RoomListBox(QWidget):
    """关注列表的滚动内容：卡片自己摆位置，拖动时让位、松手后滑动归位。"""

    #: 光标离**视口**边缘多近就开始自动滚（像素）
    SCROLL_EDGE = 30
    #: 刚进边缘带 / 贴死边缘（或已经拖到视口外）时，一拍各滚多少像素
    SCROLL_STEP_MIN = 4
    SCROLL_STEP_MAX = 36
    #: 拖动期间滚轮一格滚多少像素（钩子借来的滚轮，见 ddm/mouse_hook.py）
    WHEEL_PIXELS = 80
    #: 搜索一条都没匹配上时，那句提示占多高（列表里只摆它一个）
    EMPTY_HINT_HEIGHT = 72

    def __init__(self, sidebar, parent=None):
        super().__init__(parent)
        self.sidebar = sidebar
        self.setAcceptDrops(True)
        #: 过滤到一条不剩（或本来就没关注）时顶上来的一句话，
        #: 免得列表区一片空白，让人以为列表坏了
        self.empty_hint = QLabel(self)
        self.empty_hint.setObjectName("FilterHint")
        self.empty_hint.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.empty_hint.setWordWrap(True)
        self.empty_hint.setVisible(False)
        self._animations: dict = {}
        self._scroll_dir = 0
        self._scroll_step = float(self.SCROLL_STEP_MIN)
        self._scroll_timer = QTimer(self)
        self._scroll_timer.setInterval(30)      # 30ms 一拍：贴死边缘约 1200px/s
        self._scroll_timer.timeout.connect(self._scroll_tick)
        self.folder_drop_indicator = QFrame(self)
        self.folder_drop_indicator.setStyleSheet(f"background: {theme.ACCENT};")
        self.folder_drop_indicator.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.folder_drop_indicator.hide()

    # ---- 拖到上下边缘时自动滚动 ----
    @property
    def horizontal(self) -> bool:
        """竖屏顶部横栏里，卡片是横向排的（关注多了就左右滚）。"""
        return getattr(self.sidebar, "side", "left") == "top"

    def _visible_items(self) -> list:
        """摆放和拖动落点都只按露出来的那些算。"""
        return self.sidebar.visible_items()

    def contextMenuEvent(self, event) -> None:
        self.sidebar._folder_create_menu().exec_context(event)
        event.accept()

    def set_scroll_dir(self, direction: int, step: float | None = None) -> None:
        self._scroll_dir = int(direction)
        if step is not None:
            self._scroll_step = float(step)
        if self._scroll_dir and not self._scroll_timer.isActive():
            self._scroll_timer.start()
        elif not self._scroll_dir:
            self._scroll_timer.stop()

    def _scroll_tick(self) -> None:
        area = self.sidebar.scroll
        if area is None or not self._scroll_dir:
            return
        bar = area.horizontalScrollBar() if self.horizontal else area.verticalScrollBar()
        bar.setValue(bar.value() + self._scroll_dir * int(round(self._scroll_step)))

    def _scroll_step_for(self, depth: float) -> float:
        """离边缘越近滚越快：刚进边缘带 4px/拍，贴死边缘 36px/拍。"""
        return self.SCROLL_STEP_MIN + (self.SCROLL_STEP_MAX - self.SCROLL_STEP_MIN) * depth

    def auto_scroll(self, global_pos) -> None:
        """光标贴到视口的上/下（横排时是左/右）边缘就自动滚。

        判据必须用**视口**坐标：本控件是 ``scroll.setWidget()`` 的内容 widget
        （``widgetResizable=True``），``height()`` 是内容总高（40 个关注时 5200px），
        不是能看见的视口高度（517px）。以前拿内容高度当边界，「往下」要等光标到
        内容最底部才成立 —— 视口里根本够不着，等于只有「往上」能用。
        """
        area = self.sidebar.scroll
        if area is None:
            self.set_scroll_dir(0)
            return
        viewport = area.viewport()
        local = viewport.mapFromGlobal(global_pos)
        span = viewport.width() if self.horizontal else viewport.height()
        along = local.x() if self.horizontal else local.y()
        edge = self.SCROLL_EDGE
        if along < edge:
            depth = min(1.0, (edge - along) / edge)           # 拖出视口也继续滚
            self.set_scroll_dir(-1, self._scroll_step_for(depth))
        elif along > span - edge:
            depth = min(1.0, (along - (span - edge)) / edge)
            self.set_scroll_dir(1, self._scroll_step_for(depth))
        else:
            self.set_scroll_dir(0)

    def item_size(self) -> tuple[int, int]:
        """卡片尺寸。竖屏横栏里用固定宽度，横向排一长条。"""
        if self.horizontal:
            return (CAROUSEL_WIDTH, NAV_ITEM_HEIGHT) if self.sidebar.card_mode else (
                PORTRAIT_LIST_WIDTH, PORTRAIT_LIST_HEIGHT)
        if self.sidebar.collapsed:
            height = NAV_COMPACT_ITEM_HEIGHT
        else:
            height = NAV_ITEM_HEIGHT if self.sidebar.card_mode else NAV_LIST_ITEM_HEIGHT
        return self.width(), height

    def slot_height(self) -> int:
        if self.sidebar.collapsed:
            height = NAV_COMPACT_ITEM_HEIGHT
        else:
            height = NAV_ITEM_HEIGHT if self.sidebar.card_mode else NAV_LIST_ITEM_HEIGHT
        return height + NAV_ITEM_GAP

    def content_height(self) -> int:
        if self.horizontal:
            return self.item_size()[1] + NAV_ITEM_GAP
        return self.slot_height() * max(1, len(self.sidebar.items()))

    def content_width(self) -> int:
        if not self.horizontal:
            return super().sizeHint().width()
        return (self.item_size()[0] + NAV_ITEM_GAP) * max(1, len(self.sidebar.items()))

    def sizeHint(self) -> QSize:
        return QSize(self.content_width(), self.content_height())

    def _glide_to(self, item: NavItem, x: int, y: int, animate: bool, duration=150) -> None:
        target = QPoint(x, y)
        previous = self._animations.get(item)
        if previous is not None:
            previous.stop()
        if item.pos() == target:
            return
        if not animate:
            item.move(target)
            return
        animation = QPropertyAnimation(item, b"pos", item)
        animation.setDuration(duration)
        animation.setStartValue(item.pos())
        animation.setEndValue(target)
        animation.setEasingCurve(QEasingCurve.OutCubic)
        self._animations[item] = animation
        animation.start()

    def relayout(self, animate: bool = False, preview_order: list | None = None,
                 dragging_ids: set[str] | None = None, *, duration=150, revealing=()) -> None:
        """按当前顺序摆卡片；拖动时用空位显示整组卡片的落点。

        竖屏顶部横栏里改成横向排（卡片向右排开，多了就左右滚）。
        """
        items = self._visible_items()
        order = preview_order if preview_order is not None else list(items)
        if self.sidebar.folders and preview_order is None:
            order = self.sidebar.folder_entries()
        width, item_height = self.item_size()
        horizontal = self.horizontal
        # 不要在这里改 width：卡片宽度必须和侧栏内容宽度一致，
        # 差几个像素就会让头像和列表对不齐（自检里钉着这一条）
        run = 0
        for entry in order:
            if entry is None:
                # 落点让位：竖屏横排时也要让（用户要求动效和横屏一致），
                # 横排的让位就是往右挪一格
                run += width + NAV_ITEM_GAP if horizontal else self.slot_height()
                continue
            entry.setVisible(True)
            is_folder = isinstance(entry, FollowFolderButton)
            thickness = max(36, entry.minimumSizeHint().height()) if is_folder else item_height
            entry_width = thickness if is_folder and horizontal else width
            entry_height = thickness if is_folder and not horizontal else item_height
            entry.resize(entry_width, entry_height)
            if horizontal:
                if animate and entry in revealing:
                    entry.move(run + 24, 0)
                self._glide_to(entry, run, 0, animate, duration)
                run += entry_width + NAV_ITEM_GAP
            else:
                # 回到左栏时必须把横栏留下的 x 清零，否则卡片会继续沿用
                # 横向卡片条的位置，只剩第一张完整可见。
                if animate and entry in revealing:
                    entry.move(0, run + 24)
                self._glide_to(entry, 0, run, animate, duration)
                run += entry_height + NAV_ITEM_GAP
        if not order:
            # 一条都没有：摆上那句话，并且把它的高度算进 run —— 不然滚动区
            # 高度是 0，提示会被压得看不见
            self.empty_hint.setText(self.sidebar.empty_hint_text())
            self.empty_hint.setFixedSize(max(self.width(), 1), self.EMPTY_HINT_HEIGHT)
            self.empty_hint.move(0, 0)
            self.empty_hint.setVisible(True)
            self.empty_hint.raise_()
            run = self.EMPTY_HINT_HEIGHT
        else:
            self.empty_hint.setVisible(False)
        if dragging_ids:
            for item in items:
                if str(item.room.get("room_id")) in dragging_ids:
                    item.hide()                  # 原卡片藏起来，鼠标上跟着的是它的影子
        if self.horizontal:
            self.setMinimumWidth(max(run, 1))
            self.setMaximumWidth(16_777_215)
            self.setMinimumHeight(0)
            self.setMaximumHeight(16_777_215)
        else:
            # 竖向时必须清掉横排留下的宽度约束，否则左栏会被撑歪
            self.setMinimumWidth(0)
            self.setMaximumWidth(16_777_215)
            self.setMinimumHeight(max(run, 1))
            self.setMaximumHeight(16_777_215)
        self._clamp_vertical_scroll()

    def _clamp_vertical_scroll(self) -> None:
        """竖向时把可滚动范围压在视口高度内：留着横排时的宽度会让 Qt 判成
        「横向内容更宽」，于是弹出横滚条、挤掉高度，列表看起来只剩一张卡片。"""
        if self.horizontal:
            return
        self.setMinimumWidth(0)
        self.setMaximumWidth(16_777_215)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # 文件夹展开只改变内容高度，不重新排版打断正在进行的让位。
        if not self.horizontal and event.size().width() != event.oldSize().width():
            self.relayout(animate=False)

    def index_at(self, y: float) -> int:
        """鼠标落在第几个位置（0 = 最前面，len = 追加到最后）。

        按格子尺寸直接算，拖动中卡片位置在动也不影响判断。竖屏横栏里按 x 算。
        """
        count = len(self._visible_items())
        if self.sidebar.folders:
            # 使用原顺序的槽位；动画中的控件坐标会变化，不能拿它们重新判定落点。
            width, height = self.item_size()
            run, index = 0, 0
            for entry in self.sidebar.folder_entries():
                is_folder = isinstance(entry, FollowFolderButton)
                span = max(36, entry.minimumSizeHint().height()) if is_folder else (
                    width if self.horizontal else height)
                if isinstance(entry, SmartFolderCard):
                    run += span + NAV_ITEM_GAP
                    continue
                if not is_folder:
                    if y < run + span / 2:
                        return index
                    index += 1
                run += span + NAV_ITEM_GAP
            return count
        if self.horizontal:
            width = self.item_size()[0]
            slot = width + NAV_ITEM_GAP
            return max(0, min(int((y + width / 2) // slot), count))
        slot = self.slot_height()
        if self.sidebar.collapsed:
            item_height = NAV_COMPACT_ITEM_HEIGHT
        else:
            item_height = NAV_ITEM_HEIGHT if self.sidebar.card_mode else NAV_LIST_ITEM_HEIGHT
        index = int((y + item_height / 2) // slot)
        return max(0, min(index, count))

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(NAV_MIME) or event.mimeData().hasFormat(FOLDER_MIME):
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasFormat(FOLDER_MIME):
            event.acceptProposedAction()
            folder_id = bytes(event.mimeData().data(FOLDER_MIME)).decode("utf-8", "ignore")
            self.sidebar.hover_folder_drag(folder_id, self.mapToGlobal(event.position().toPoint()))
            return
        if not event.mimeData().hasFormat(NAV_MIME):
            return
        event.acceptProposedAction()
        room_id = bytes(event.mimeData().data(NAV_MIME)).decode("utf-8", "ignore")
        self.sidebar.hover_drag(room_id, self.mapToGlobal(event.position().toPoint()))

    def dragLeaveEvent(self, event) -> None:
        pass                              # 离开某一格不等于拖动结束，交给 drag 结束后统一结算

    def dropEvent(self, event) -> None:
        if event.mimeData().hasFormat(FOLDER_MIME):
            event.acceptProposedAction()
            folder_id = bytes(event.mimeData().data(FOLDER_MIME)).decode("utf-8", "ignore")
            self.sidebar.finish_folder_drag(folder_id, self.mapToGlobal(event.position().toPoint()))
            return
        if not event.mimeData().hasFormat(NAV_MIME):
            return
        event.acceptProposedAction()
        room_id = bytes(event.mimeData().data(NAV_MIME)).decode("utf-8", "ignore")
        self.sidebar.finish_drag(room_id, self.mapToGlobal(event.position().toPoint()))


class CarouselScroll(QScrollArea):
    """竖向滚轮也能用来横向滚动的滚动区（竖屏卡片条用）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.horizontal_only = False

    def wheelEvent(self, event) -> None:
        if not self.horizontal_only:
            super().wheelEvent(event)
            return
        # 竖屏时列表是横着排的：把竖直滚轮换算成横向滚动，
        # 这样鼠标滚轮照样能把后面的主播翻出来
        delta = event.angleDelta().y() or event.angleDelta().x()
        bar = self.horizontalScrollBar()
        bar.setValue(bar.value() - delta)
        event.accept()


class RoomStrip(QFrame):
    """竖屏顶部横栏里的一排头像：只放关注的主播（账号头像在横栏右侧那一块）。

    收起横栏时这是唯一露出来的东西（所以头像尺寸和列表里的一致、对齐成一排）；
    展开时它换成搜索框 + 横向卡片条。
    头像不设上限：关注多了就由外层的滚动区横向滚（见 Sidebar._head_scroll），
    所以这里也不再需要「+N」。
    """

    roomClicked = Signal(str)
    roomHovered = Signal(dict)
    roomUnhovered = Signal(dict)

    AVATAR = 34
    SPACING = 8

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("RoomStrip")
        self.setFixedHeight(self.AVATAR + 2)
        self._rooms: list[dict] = []
        self._faces: dict = {}                   # room_id -> 头像图
        self._on_wall_ids: set[str] = set()
        self._avatars: dict[str, QWidget] = {}   # room_id -> 头像控件（换头像图要用）
        self._press_pos = None
        self._press_room = None
        self._hovered_room: dict | None = None
        self.setMouseTracking(True)
        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(2, 0, 2, 0)
        self._layout.setSpacing(self.SPACING)
        self._layout.addStretch(1)
        self.setCursor(Qt.PointingHandCursor)

    # ---- 数据 ----
    def set_rooms(self, rooms: list, faces: dict | None = None,
                  on_wall_ids: set[str] | None = None) -> None:
        """rooms：关注列表；faces：room_id -> 已经下载好的头像图（可省）。"""
        fields = ("room_id", "uname", "live", "pinned")
        unchanged = (
            [tuple(room.get(key) for key in fields) for room in rooms or []] ==
            [tuple(room.get(key) for key in fields) for room in self._rooms]
            and {rid: pixmap.cacheKey() for rid, pixmap in (faces or {}).items()} ==
            {rid: pixmap.cacheKey() for rid, pixmap in self._faces.items()}
            and set(on_wall_ids or set()) == self._on_wall_ids)
        hovered_id = str((self._hovered_room or {}).get("room_id") or "")
        self._rooms = list(rooms or [])
        self._faces = dict(faces or {})
        self._on_wall_ids = set(on_wall_ids or set())
        if unchanged:
            # 状态轮询只更新标题/封面时保留头像控件，避免触发 leave 中断悬停预览。
            self._hovered_room = next((room for room in self._rooms
                                      if str(room.get("room_id")) == hovered_id), None)
            return
        self._rebuild()

    def set_room_face(self, room_id: str, pixmap) -> None:
        """某个主播的头像下载好了：只换那一张，整排不重建。"""
        if pixmap is None or pixmap.isNull():
            return
        self._faces[str(room_id)] = pixmap
        avatar = self._avatars.get(str(room_id))
        if avatar is None:
            return
        try:
            avatar.set_pixmap_image(pixmap)
        except Exception:                      # noqa: BLE001
            pass

    # ---- 交互 ----
    def mousePressEvent(self, event) -> None:
        self._press_pos = event.position().toPoint()
        self._press_room = None
        if event.button() == Qt.LeftButton:
            widget = self.childAt(event.position().toPoint())
            while widget is not None and widget is not self:
                room_id = widget.property("roomId")
                if room_id:
                    self._press_room = str(room_id)
                    break
                widget = widget.parentWidget()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        """把某个主播头像拖出去 = 拖进画面墙（和从列表里拖一样）。"""
        self._set_hover_room("" if event.buttons() else
                             self._room_at(event.position().toPoint()))
        if not self._press_room or not (event.buttons() & Qt.LeftButton):
            return
        start = getattr(self, "_press_pos", None)
        if start is None or (event.position().toPoint() - start).manhattanLength() \
                < QApplication.startDragDistance():
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(ROOM_MIME, self._press_room.encode("utf-8"))
        mime.setText(self._press_room)
        drag.setMimeData(mime)
        drag.exec(Qt.CopyAction)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            return
        super().mouseReleaseEvent(event)
        hit = self.childAt(event.position().toPoint())
        # 头像上的开播小圆点 / 置顶角标是子控件，childAt 会返回它们，
        # 所以要往上找到真正带 roomId 的那个头像，否则点圆点会被当成点头像。
        widget = hit
        room_id = None
        while widget is not None and widget is not self:
            room_id = widget.property("roomId")
            if room_id:
                break
            widget = widget.parentWidget()
        if room_id:
            self.roomClicked.emit(str(room_id))

    def _set_hover_room(self, room_id: str) -> None:
        room = next((room for room in self._rooms
                     if str(room.get("room_id") or "") == room_id), None)
        if room is self._hovered_room:
            return
        if self._hovered_room is not None:
            self.roomUnhovered.emit(self._hovered_room)
        self._hovered_room = room
        if room is not None:
            self.roomHovered.emit(room)

    def _room_at(self, point: QPoint) -> str:
        return next((room_id for room_id, avatar in self._avatars.items()
                     if avatar.geometry().contains(point)), "")

    def enterEvent(self, event) -> None:
        self._set_hover_room(self._room_at(event.position().toPoint()))
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._set_hover_room("")
        super().leaveEvent(event)

    def _rebuild(self) -> None:
        self._set_hover_room("")
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        self._avatars = {}
        for room in self._rooms:
            room_id = str(room.get("room_id") or "")
            uname = str(room.get("uname") or "")
            avatar = self._add_avatar(
                uname[0] if uname else "?", bool(room.get("live")),
                tooltip=uname or room_id,
                face=self._faces.get(room_id),
                room_id=room_id,
                pinned=bool(room.get("pinned")),
                on_wall=room_id in self._on_wall_ids)
            if room_id:
                self._avatars[room_id] = avatar
        self._layout.addStretch(1)

    def rebuild(self) -> None:
        """关注列表变了（增删/排序/状态）时重建这一排。"""
        self._rebuild()

    def _add_avatar(self, text: str, live: bool, tooltip: str = "",
                    face=None, room_id: str = "", pinned: bool = False,
                    on_wall: bool = False) -> QWidget:
        avatar = Avatar(text, 2, self.AVATAR)
        avatar.setFixedSize(self.AVATAR, self.AVATAR)
        avatar.setProperty("roomId", room_id)
        if face is not None:
            try:
                avatar.set_pixmap_image(face)
            except Exception:                      # noqa: BLE001
                pass
        tip = tooltip
        if pinned:
            tip += "（已置顶）"
        if on_wall:
            tip += "（已在画面墙）"
        avatar.setToolTip(tip)
        self._layout.addWidget(avatar)
        # 右下角开播小圆点：直接用 QSS 画一个圆，省得再加一个控件
        if live:
            dot = QLabel(avatar)
            dot.setFixedSize(12, 12)
            dot.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            dot.setStyleSheet(f"background: {theme.PINK}; border-radius: 6px;"
                              f" border: 2px solid {theme.SIDEBAR};")
            dot.move(self.AVATAR - 12, self.AVATAR - 12)
            dot.show()
        if pinned:
            mark = PinnedArc(avatar)
            mark.setGeometry(0, 0, self.AVATAR, self.AVATAR)
            mark.show()
        if on_wall:
            mark = QLabel(avatar)
            mark.setFixedSize(14, 7)
            mark.setStyleSheet(
                f"background: {theme.ACCENT}; border: 2px solid {theme.SIDEBAR};"
                " border-radius: 3px;")
            mark.move(self.AVATAR - 14, 1)
            mark.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            mark.show()
        avatar.show()
        return avatar


class BarIconButton(QPushButton):
    """竖屏横栏里的小图标按钮：横屏是文字按钮，竖屏自己画图标。

    为什么不用字形：雅黑下 `↑↓` 的墨迹明显偏左（实测图标框中心比按钮中心
    左 5px），`✓` 又偏小；自己画两个箭头 / 一个勾，位置和粗细都可控，
    也和 `RefreshButton` 那个手绘圆环是一个路子。
    """

    KINDS = ("check", "sort")

    def __init__(self, text: str, kind: str, parent=None):
        super().__init__(text, parent)
        assert kind in self.KINDS, kind
        self._plain_text = text
        self._kind = kind
        self._icon_mode = False

    def set_icon_mode(self, on: bool) -> None:
        self._icon_mode = bool(on)
        self.setText("" if self._icon_mode else self._plain_text)
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self._icon_mode:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        color = _icon_color(self)
        center = self.rect().center()
        if self._kind == "check":
            pen = QPen(color, 2.0)
            pen.setCapStyle(Qt.RoundCap)
            pen.setJoinStyle(Qt.RoundJoin)
            painter.setPen(pen)
            path = QPainterPath()
            path.moveTo(center.x() - 5.0, center.y() + 0.4)
            path.lineTo(center.x() - 1.6, center.y() + 4.0)
            path.lineTo(center.x() + 5.2, center.y() - 4.0)
            painter.drawPath(path)
        else:
            # 上箭头 + 下箭头 = 「排序」。两根杆子要拉开、箭头别画太宽，
            # 否则两个箭头的三角会和旁边那根杆子叠在一起（用户报过重叠）。
            pen = QPen(color, 1.8)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            for offset, up in ((-4.0, True), (4.0, False)):
                x = center.x() + offset
                top = center.y() - 5.5
                bottom = center.y() + 5.5
                painter.drawLine(QPointF(x, top), QPointF(x, bottom))
                tip = top if up else bottom
                base = top + 3.4 if up else bottom - 3.4
                painter.drawLine(QPointF(x, tip), QPointF(x - 2.2, base))
                painter.drawLine(QPointF(x, tip), QPointF(x + 2.2, base))


class PinnedArc(QWidget):
    """置顶标记：沿圆形头像左上边缘画一段弧。

    原来是 14x14 的方块按钮（`border-top-left-radius: 7px`），贴在直径 34 的
    圆头像左上角，方角会戳到圆外面；改成贴着圆周的一段圆弧，边缘就贴合了。
    """

    #: 弧的起止角度（Qt 的角度：0° 在 3 点钟方向，逆时针为正）；90°..180° 是左上
    #: 和卡片上那个角标的画法保持一致（都是一段贴着圆角走的弧）
    START_ANGLE = 90
    SPAN_ANGLE = 90
    THICKNESS = 3

    def __init__(self, parent=None):
        super().__init__(parent)
        # 别抢鼠标：点头像仍然要能选中 / 拖出这一路
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(QColor(theme.ACCENT), self.THICKNESS)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        inset = self.THICKNESS / 2 + 0.5
        rect = QRectF(inset, inset, self.width() - inset * 2, self.height() - inset * 2)
        painter.drawArc(rect, self.START_ANGLE * 16, self.SPAN_ANGLE * 16)


class Sidebar(QFrame):
    """左侧房间列表：可收起、可批量选择删除。"""

    SORT_MODES = follow_folders.SORT_MODES

    #: 竖屏横栏里账号条的宽度上限（昵称太长就省略，别把搜索框挤没）
    ACCOUNT_PILL_MAX = 220

    roomSelected = Signal(dict)
    addRoomClicked = Signal()
    importFollowsClicked = Signal()
    addToWallRequested = Signal(dict)
    removeRequested = Signal(dict)
    openBrowserRequested = Signal(str)
    deleteRequested = Signal(list)
    collapsedChanged = Signal(bool)
    logoutRequested = Signal()
    platformLogoutRequested = Signal(str)
    loginRequested = Signal()
    pinChanged = Signal(list)
    sortChanged = Signal(str)
    orderChanged = Signal()
    foldersChanged = Signal()
    refreshRequested = Signal()
    previewHovered = Signal(dict)       # 鼠标停在某个直播间上
    previewUnhovered = Signal(dict)
    layoutChosen = Signal(str)
    settingsRequested = Signal()
    # 注意：菜单项要走**已经接好的**信号 —— addRoomClicked / importFollowsClicked
    # 才是 MainWindow 连了槽的那两个；另起名字会是「发了没人听」的空信号
    # （用户报的「登录按钮点了没反应」就是踩了这个）。

    def __init__(self, rooms: list[dict], parent=None, card_mode: bool = True,
                 auto_compact: bool = True, compact_threshold: int = 18):
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(theme.SIDEBAR_WIDTH)
        self._items: list[NavItem] = []
        self.browser_url_resolver = lambda _room: ""
        self.collapsed = False
        self.preferred_card_mode = bool(card_mode)
        self.auto_compact = bool(auto_compact)
        self.compact_threshold = max(2, int(compact_threshold))
        self.card_mode = self.preferred_card_mode and not (
            self.auto_compact and len(rooms) >= self.compact_threshold)
        self._wall_room_ids: set[str] = set()
        self.select_mode = False
        self._sort_selected_ids: set[str] = set()
        self._sort_anchor: str | None = None
        self.side = "left"                     # left = 横屏的左栏；top = 竖屏的顶部横栏
        self.pinned: list[str] = []
        self.sort_mode = "custom"
        self.import_order: list[str] = []      # 导入/添加的先后顺序，用于「导入顺序」排序
        self.custom_order: list[str] = []      # 拖动排出来的顺序，切换排序方式也不丢
        self.folders: list[dict] = follow_folders.normalize_folders([])
        self._folder_assignments: dict[str, str] = {}
        self._smart_cards: dict[tuple[str, str], SmartFolderCard] = {}
        self._folder_pending: set[str] = set()
        self._entering_room_ids: set[str] = set()
        self._card_entry_timer = QTimer(self)
        self._card_entry_timer.setSingleShot(True)
        self._card_entry_timer.timeout.connect(self._reveal_added_rooms)
        self._folders_folded_by_drag: set[str] = set()
        self._folder_drag_previous: dict[str, bool] = {}
        self._folder_buttons: dict[str, FollowFolderButton] = {}
        self._layout_id = layouts.DEFAULT_LAYOUT

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 14, 12, 12)
        layout.setSpacing(10)
        self._layout = layout

        # 竖屏顶部横栏里的头像排；横屏时一直是隐藏的。
        # 外面套一个滚动区：关注多了头像排放不下，就横向滚（不显示滚动条，
        # 免得占掉头像那一行的高度；滚轮/触控板横向滚，和卡片条同一套机制）。
        self._head_strip = RoomStrip(self)
        self._head_strip.roomClicked.connect(self._on_strip_room)
        self._head_strip.roomHovered.connect(self.previewHovered.emit)
        self._head_strip.roomUnhovered.connect(self.previewUnhovered.emit)
        self._head_scroll = CarouselScroll(self)
        self._head_scroll.setWidgetResizable(True)
        self._head_scroll.setFrameShape(QFrame.NoFrame)
        self._head_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._head_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._head_scroll.horizontal_only = True
        self._head_scroll.setFixedHeight(self._head_strip.height())
        self._head_scroll.setWidget(self._head_strip)
        self._head_scroll.setVisible(False)
        layout.addWidget(self._head_scroll)

        # 标题行（做成一个容器，竖屏收起时整行收掉）
        self._header_row = QWidget(self)
        header = QHBoxLayout(self._header_row)
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(9)
        self.logo_label = QLabel()
        self.logo_label.setObjectName("AppLogo")
        self.logo_label.setToolTip(version_module.DISPLAY_NAME)
        self._brand_logo = QPixmap(os.path.join(BRAND_ASSETS_DIR, "logo.png"))
        self.title_box = QVBoxLayout()
        self.title_box.setSpacing(0)
        title = QLabel(version_module.DISPLAY_NAME)
        title.setObjectName("AppTitle")
        subtitle = QLabel("多窗口直播监控")
        subtitle.setObjectName("AppSubtitle")
        #: 竖屏横栏第一行只留标题当 logo（副标题藏起来，横栏高度很紧）
        self.title_label = title
        self.subtitle_label = subtitle
        self.title_box.addWidget(title)
        self.title_box.addWidget(subtitle)
        self._set_brand_header(compact=False)
        self.batch_button = BarIconButton("多选", "check")
        self.batch_button.setObjectName("ChipButton")
        self.batch_button.setCursor(Qt.PointingHandCursor)
        self.batch_button.setToolTip("多选卡片后可一起拖动、移到最前或最后，也可批量删除")
        self.batch_button.setCheckable(True)
        self.batch_button.setFixedHeight(22)
        self.batch_button.clicked.connect(lambda: self.set_select_mode(not self.select_mode))
        self.toggle_button = SidebarToggleButton(self)
        self.toggle_button.setToolTip("收起 / 展开房间列表")
        self.toggle_button.clicked.connect(self.toggle_collapsed)
        header.addWidget(self.logo_label, 0, Qt.AlignVCenter)
        header.addLayout(self.title_box, 1)
        header.addWidget(self.batch_button, 0, Qt.AlignTop)
        header.addWidget(self.toggle_button, 0, Qt.AlignTop)
        layout.addWidget(self._header_row)

        self.search = QLineEdit()
        self.search.setObjectName("Search")
        self.search.setPlaceholderText("搜索主播 / 房间号")
        self.search.setClearButtonEnabled(True)
        #: 当前搜索词（已去空白、转小写）；空串 = 不过滤
        self.filter_text = ""
        self.search.textChanged.connect(self.apply_filter)      # 边打字边过滤
        # 回车不再额外「执行搜索」（本来就实时），把焦点交给列表，接着就能直接
        # 点选 / 拖动；Esc 等价于点清空按钮（清空按钮自己会走 textChanged）
        self.search.returnPressed.connect(self._focus_room_list)
        escape = QShortcut(QKeySequence(Qt.Key_Escape), self.search)
        escape.setContext(Qt.WidgetShortcut)
        escape.activated.connect(self.search.clear)
        self.find_shortcut = QShortcut(QKeySequence.Find, self)
        self.find_shortcut.setContext(Qt.WindowShortcut)
        self.find_shortcut.activated.connect(self.focus_search)
        layout.addWidget(self.search)

        self.status_row = QWidget(self)
        status_box = QHBoxLayout(self.status_row)
        status_box.setContentsMargins(0, 0, 0, 0)
        status_box.setSpacing(6)
        self.count_label = QLabel(f"关注中 · {len(rooms)}")
        self.count_label.setObjectName("SectionLabel")
        self.sort_button = BarIconButton("排序", "sort")
        self.sort_button.setObjectName("ChipButton")
        self.sort_button.setCursor(Qt.PointingHandCursor)
        self.sort_button.setToolTip("分别设置各文件夹的排序；Ctrl / Shift 点击卡片可直接多选")
        self.sort_button.setMenu(self._build_sort_menu())
        self.refresh_button = RefreshButton(size=22, object_name="ChipButton")
        self.refresh_button.clicked.connect(self.refreshRequested.emit)
        status_box.addWidget(self.count_label, 1)
        status_box.addWidget(self.sort_button, 0, Qt.AlignRight)
        status_box.addWidget(self.refresh_button, 0, Qt.AlignRight)
        layout.addWidget(self.status_row)

        scroll = CarouselScroll()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll = scroll
        holder = RoomListBox(self)
        self.list_box = holder
        self._wheel_hook: mouse_hook.WheelHook | None = None
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
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setObjectName("IconButton")
        self.cancel_button.setCursor(Qt.PointingHandCursor)
        self.cancel_button.clicked.connect(lambda: self.set_select_mode(False))
        batch_layout.addWidget(self.batch_label, 1)
        batch_layout.addWidget(self.delete_button)
        batch_layout.addWidget(self.cancel_button)
        self.batch_bar.setVisible(False)
        layout.addWidget(self.batch_bar)

        # 已登录账号（在底部操作之上）
        self.account_row = AccountRow(allow_logout=True)
        self.account_row.logoutClicked.connect(self.logoutRequested)
        self.account_row.clicked.connect(self._open_account_menu)
        # 未登录时它就是「登录」按钮，所以一开始就要露出来
        self.account_row.set_account("")
        self.account_row.setVisible(self._account_row_should_show())
        layout.addWidget(self.account_row)

        # 布局 + 设置：原来挂在右侧顶栏，现在跟着列表放左下角
        self.tool_row = QWidget(self)
        tool_box = QHBoxLayout(self.tool_row)
        tool_box.setContentsMargins(0, 0, 0, 0)
        tool_box.setSpacing(6)
        self.layout_button = QPushButton()
        self.layout_button.setFocusPolicy(Qt.TabFocus)
        self.layout_button.setObjectName("IconButton")
        self.layout_button.setCursor(Qt.PointingHandCursor)
        self.layout_button.setToolTip("选择布局方式")
        self.layout_button.clicked.connect(self.open_layout_picker)
        self.settings_button = QPushButton("设置")
        self.settings_button.setFocusPolicy(Qt.TabFocus)
        self.settings_button.setObjectName("IconButton")
        self.settings_button.setCursor(Qt.PointingHandCursor)
        self.settings_button.setToolTip("打开设置")
        self.settings_button.clicked.connect(self.settingsRequested.emit)
        tool_box.addWidget(self.layout_button, 1)
        tool_box.addWidget(self.settings_button, 0)
        layout.addWidget(self.tool_row)
        self.set_layout_name(layouts.DEFAULT_LAYOUT)

        self.normal_bar = QWidget()
        normal_layout = QHBoxLayout(self.normal_bar)
        normal_layout.setContentsMargins(0, 0, 0, 0)
        normal_layout.setSpacing(6)
        self.import_button = QPushButton("导入关注")
        self.import_button.setFocusPolicy(Qt.TabFocus)
        self.import_button.setObjectName("IconButton")
        self.import_button.setCursor(Qt.PointingHandCursor)
        self.import_button.setToolTip("从 B 站或支持关注导入的平台账号导入列表（需要先登录）")
        self.import_button.clicked.connect(self.importFollowsClicked.emit)
        self.add_button = QPushButton("+  添加直播间")
        self.add_button.setFocusPolicy(Qt.TabFocus)
        self.add_button.setObjectName("PrimaryButton")
        self.add_button.setCursor(Qt.PointingHandCursor)
        self.add_button.clicked.connect(self.addRoomClicked.emit)
        normal_layout.addWidget(self.import_button)
        normal_layout.addWidget(self.add_button, 1)
        layout.addWidget(self.normal_bar)

        # 竖屏横栏那一行（见 _adopt_bar_row）：左边搜索框/头像排，右边一块
        # 「账号头像 / 布局预设 / 设置」，中间夹着「多选 / 排序 / 刷新」三个小图标。
        # 横屏要拆回竖排，所以先把左栏的原始顺序记下来，_release_bar_row 按它还原。
        self._column_order = [self._head_scroll, self._header_row, self.search,
                              self.status_row, self.scroll, self.batch_bar,
                              self.account_row, self.tool_row, self.normal_bar]
        # 竖屏会把这两个按钮改成撑满 + 竖排，回横屏时要还原原来的策略
        self._tool_button_policies = {
            self.layout_button: self.layout_button.sizePolicy(),
            self.settings_button: self.settings_button.sizePolicy(),
        }
        self._account_policy = self.account_row.sizePolicy()
        self._bar_row: QWidget | None = None
        self._bar_row_box: QHBoxLayout | None = None
        self._bar_in_use = False
        self.refresh_filter()
        self._sync_count()

    # ---- 账号 ----
    def set_layout_name(self, layout_id: str) -> None:
        """按钮只写「布局预设」，当前用的是哪套放在悬停提示里。"""
        self._layout_id = layout_id
        layout = layouts.BY_ID.get(layout_id) or layouts.BY_ID[layouts.DEFAULT_LAYOUT]
        self.layout_button.setText("布局预设")
        self.layout_button.setToolTip(f"当前布局：{layout['name']}　（点击切换）")

    def open_layout_picker(self) -> None:
        # 只列当前方向能用的布局：横屏不列竖屏预设（套上去画面会变形）
        picker = LayoutPicker(self._layout_id, self, portrait=self.side == "top")
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
            # 连主屏都问不到时，至少把它压进屏幕左上角能看见的范围，
            # 别让 x 也跟着锚点跑到屏幕外去
            x = max(6, min(x, max(6, 1200 - picker.width() - 6)))
            y = max(6, y)
        picker.move(x, y)
        picker.show()
        self._picker = picker

    def _on_layout_chosen(self, layout_id: str) -> None:
        self.set_layout_name(layout_id)
        self.layoutChosen.emit(layout_id)

    def set_account(self, uname: str, pixmap=None, *, platform="bilibili", uid="") -> None:
        self.account_row.set_account(uname, pixmap, platform=platform, uid=uid)
        self._sync_account_row_shape()
        self.account_row.setVisible(self._account_row_should_show())
        self._sync_account_row_width()
        self.refresh_strip()

    def clear_account(self) -> None:
        # 退出登录后**不隐藏**：这一格要当「登录」按钮继续露着（用户要求）
        self.account_row.set_account("")
        self.account_row.setVisible(self._account_row_should_show())
        self._sync_account_row_shape()
        self._sync_account_row_width()

    def set_room_face(self, room_id: str, pixmap) -> None:
        """某个主播的头像下载好了：头排那一张也换掉（横屏走列表，竖屏走头排）。"""
        strip = getattr(self, "_head_strip", None)
        if strip is not None:
            strip.set_room_face(room_id, pixmap)

    def account_menu(self) -> QMenu:
        """账号菜单：退出登录；放不进横栏的入口也在这里。

        竖屏横栏只有一行：导入关注 / 添加直播间收进这个菜单；「布局预设 / 设置」
        是并排摆在横栏上的按钮，只有收起时（按钮藏起来）才需要放进菜单。
        单独一个方法是为了能测——exec 一弹就是模态，自检里没法取菜单内容。
        """
        menu = QMenu(self)
        menu.setObjectName("AccountPopup")
        menu.setStyleSheet(f"""
            QMenu#AccountPopup {{ background: transparent; border: none; padding: 0; }}
            QMenu#AccountPopup::item {{ background: {theme.CONTENT}; border: 1px solid {theme.BORDER};
                           border-radius: 17px; padding: 8px 12px; margin: 3px 0; }}
            QMenu#AccountPopup::item:selected {{ background: {theme.CONTENT_HOVER}; }}
            QMenu#AccountPopup::separator {{ height: 6px; margin: 0; background: transparent; }}
        """)
        menu.setWindowFlags(menu.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        menu.setAttribute(Qt.WA_TranslucentBackground)
        popup_width = self.account_row.width() if not self.collapsed else 240
        menu.setFixedWidth(popup_width)
        account_actions = []
        if not self.account_row.uname:
            # 未登录时这一格就是「登录」按钮（用户要求：没登录也要放出来）
            menu.addAction("登录…")
            menu.addSeparator()
        else:
            action = QWidgetAction(menu)
            action.setText("登录其他平台…" if getattr(self, "can_login_other", True)
                           else "所有平台均已登录")
            button = QPushButton(action.text(), menu)
            button.setCursor(Qt.PointingHandCursor)
            button.setObjectName("AccountPopupButton")
            button.setFixedSize(popup_width, self.account_row.height() if not self.collapsed else 34)
            button.setStyleSheet(f"""QPushButton {{ padding: 0; min-height: 32px; text-align: center;
                background: {theme.CONTENT}; border: 1px solid {theme.BORDER};
                border-radius: {theme.CONTROL_HEIGHT // 2}px; }}
                QPushButton:hover {{ background: {theme.CONTENT_HOVER}; border-color: {theme.ACCENT}; }}
                QPushButton:pressed {{ background: {theme.ACCENT_SOFT}; }}""")
            def activate(_checked=False):
                menu.close()
                self.loginRequested.emit()
            button.clicked.connect(activate)
            action.setDefaultWidget(button)
            menu.addAction(action)
            menu.addSeparator()
            for kind, account in reversed(getattr(self, "logged_accounts", [])):
                if kind == self.account_row.platform:
                    continue
                action = QWidgetAction(menu)
                item = QWidget(menu)
                item.setObjectName("AccountPopupItem")
                item.setStyleSheet("#AccountPopupItem { background: transparent; }")
                layout = QHBoxLayout(item)
                layout.setContentsMargins(0, 3, 0, 3)
                row = AccountRow(item, allow_logout=True)
                item.setFixedSize(popup_width, self.account_row.height() + 6 if not self.collapsed else 40)
                row.setFixedHeight(self.account_row.height() if not self.collapsed else 34)
                row.set_account(account.get("uname") or str(account.get("uid") or "已登录"),
                                account.get("_pixmap"), platform=kind, uid=account.get("uid"))
                row.arrow.hide()
                layout.addWidget(row, 1)
                button = row.logout_button
                button.setProperty("platform", kind)
                def logout(_checked=False, k=kind):
                    menu.close()
                    self.platformLogoutRequested.emit(k)
                row.logoutClicked.connect(logout)
                action.setDefaultWidget(item)
                menu.addAction(action)
                account_actions.append(action)
        if self.side == "top":
            menu.addSeparator()
            menu.addAction("导入关注…")
            menu.addAction("+ 添加直播间…")
            if self.collapsed:
                menu.addSeparator()
                menu.addAction("布局预设…")
                menu.addAction("设置…")
        elif self.collapsed:
            # 横屏收起后「布局预设 / 设置」那行按钮跟着藏起来了，只剩这个头像；
            # 点头像就把它们以菜单形式放出来，不用先展开侧栏。
            menu.addSeparator()
            menu.addAction("布局预设…")
            menu.addAction("设置…")
        for action in account_actions:
            menu.removeAction(action)
            menu.addAction(action)
        return menu

    def _open_account_menu(self) -> None:
        if not self.account_row.uname and not self.collapsed:
            self.loginRequested.emit()
            return
        menu = self.account_menu()
        texts = [action.text() for action in menu.actions() if action.text()]
        size = menu.sizeHint()
        if self.side == "top":
            # 竖屏：贴着头排右侧那个账号头像弹（展开/收起都在）
            anchor = QRect(self.account_row.mapToGlobal(
                self.account_row.rect().topLeft()), self.account_row.size())
            position = QPoint(anchor.left(), anchor.bottom() + 6)
        elif self.collapsed:
            # 横屏收起：只剩头像，菜单贴着头像右侧展开
            anchor = self.account_row.mapToGlobal(self.account_row.rect().topRight())
            position = QPoint(anchor.x() + 6, anchor.y() - size.height() - 6)
        else:
            # 账号栏在最底部，菜单往上弹、右对齐整行
            anchor = self.account_row.mapToGlobal(self.account_row.rect().topRight())
            position = QPoint(anchor.x() - size.width(), anchor.y() - size.height() - 6)
        chosen = menu.exec(position)
        if chosen is None:
            return
        label = chosen.text()
        if label in ("退出登录", "登录…", "登录其他平台…", "所有平台均已登录"):
            if label != "退出登录":
                self.loginRequested.emit()
            else:
                self.logoutRequested.emit()
        elif label == "布局预设…":
            self.open_layout_picker()
        elif label == "设置…":
            self.settingsRequested.emit()
        elif label == "导入关注…":
            self.importFollowsClicked.emit()
        elif label == "+ 添加直播间…":
            self.addRoomClicked.emit()

    # ---- 竖屏横栏 ----
    def _on_strip_room(self, room_id: str) -> None:
        """点横栏里的头像 = 点列表里那一条（行为和横屏一致）。"""
        item = next((entry for entry in self._items
                     if str(entry.room.get("room_id")) == str(room_id)), None)
        if item is not None:
            self.roomSelected.emit(item.room)

    # ---- 搜索过滤 ----
    def apply_filter(self, text: str) -> None:
        """搜索框一有动静就过滤；批量删除的勾选状态不受影响。"""
        wanted = (text or "").strip().lower()
        if wanted == self.filter_text:
            return
        self.clear_sort_selection()
        self.filter_text = wanted
        self.refresh_filter()

    def refresh_filter(self) -> None:
        """按当前搜索词重算谁该露出来（状态刷新、增删、换排序之后都要走一遍）。"""
        self._apply_filter_marks()
        self.list_box.relayout(animate=False)
        self.refresh_strip()

    def _apply_filter_marks(self) -> None:
        """只更新「谁被过滤掉了」，不动位置 —— 由调用方决定什么时候重排。"""
        words = self.filter_text.split()
        self._folder_assignments = follow_folders.assign_folders(
            self.rooms(), self.folders, self._folder_pending)
        for item in self._items:
            folder = self.get_folder(self.folder_for(str(item.room.get("room_id"))))
            folded = folder and folder["collapsed"] and (
                not words or folder["id"] in self._folders_folded_by_drag)
            item.set_filtered_out(bool(folded) or not self.matches(item, words))
            if folded:
                self._sort_selected_ids.discard(str(item.room.get("room_id")))
                item.set_sort_selected(False)
                item.check.setChecked(False)

    def matches(self, item: NavItem, words: list[str], folder_id=None) -> bool:
        """主播名 / 房间号 / 直播间标题，大小写不敏感；写了多个词就要全中。"""
        if not words:
            return True
        room = item.room
        haystack = " ".join(str(room.get(key) or "")
                            for key in ("uname", "room_id", "title")).lower()
        folder_id = folder_id or self.folder_for(str(room.get("room_id")))
        haystack += " " + next((folder["name"].lower() for folder in self.folders
                                if folder["id"] == folder_id), "")
        return all(word in haystack for word in words)

    def visible_items(self) -> list:
        """当前露在外面的条目（过滤掉的不算）。"""
        items = [item for item in self._items if not item.filtered_out]
        return [item for folder in self.folders for item in items
                if self.folder_for(str(item.room.get("room_id"))) == folder["id"]]

    def empty_hint_text(self) -> str:
        """列表一条都露不出来时说的话（列表区就摆它一个）。"""
        if self.filter_text:
            return f"没有匹配「{self.filter_text}」的直播间"
        return "还没有关注任何直播间"

    # ---- 关注文件夹 ----
    def _folder_create_menu(self) -> QMenu:
        menu = motion.AnimatedMenu(self)
        menu.addAction("新建文件夹…").triggered.connect(lambda: self.prompt_folder())
        menu.addAction("新建智能文件夹…").triggered.connect(lambda: self.prompt_smart_folder())
        return menu

    def contextMenuEvent(self, event) -> None:
        child = self.childAt(event.pos())
        if child is None or child in (self._head_strip, self._head_scroll.viewport(), self.scroll.viewport()):
            self._folder_create_menu().exec_context(event)
            event.accept()
        else:
            super().contextMenuEvent(event)

    def folder_state(self) -> list[dict]:
        return follow_folders.folder_state(self.folders)

    def get_folder(self, folder_id: str):
        return next((folder for folder in self.folders if folder["id"] == folder_id), None)

    def folder_for(self, room_id: str) -> str:
        return self._folder_assignments.get(room_id) or next(
            (folder["id"] for folder in self.folders if room_id in folder["rooms"]), "")

    def set_folders(self, folders: list) -> None:
        self.folders = follow_folders.normalize_folders(folders, self.sort_mode)
        self._refresh_folders(notify=False)

    def create_folder(self, name: str, *, rule=None, sort="custom") -> str:
        name = name.strip()
        if not name or any(folder["name"] == name for folder in self.folders):
            return ""
        folder_id = uuid4().hex
        folder = {"id": folder_id, "name": name, "type": "smart" if rule is not None else "normal",
                  "collapsed": False, "rooms": [], "sort": sort}
        if rule is not None:
            folder["rule"] = rule
        index = self.folders.index(self.get_folder(follow_folders.UNCLASSIFIED))
        self.folders.insert(index, follow_folders.normalize_folders([folder])[0])
        self._refresh_folders()
        return folder_id

    def prompt_folder(self, room_ids=None, *, folder_id="") -> None:
        folder = next((item for item in self.folders if item["id"] == folder_id), None)
        name, accepted = QInputDialog.getText(
            self, "重命名文件夹" if folder else "新建文件夹", "文件夹名称：",
            text=folder["name"] if folder else "")
        if not accepted or not name.strip():
            return
        name = name.strip()
        if any(item["name"] == name and item["id"] != folder_id for item in self.folders):
            return
        if folder:
            folder["name"] = name
            self._refresh_folders()
        else:
            folder_id = self.create_folder(name)
            if room_ids:
                self.move_to_folder(room_ids, folder_id)

    def delete_folder(self, folder_id: str) -> None:
        if folder_id == follow_folders.UNCLASSIFIED:
            return
        self.folders = [folder for folder in self.folders if folder["id"] != folder_id]
        self._refresh_folders()

    def toggle_folder(self, folder_id: str, *, animate=False) -> None:
        for folder in self.folders:
            if folder["id"] == folder_id:
                self._folders_folded_by_drag.discard(folder_id)
                folder["collapsed"] = not folder["collapsed"]
                self._refresh_folders(animate=animate and motion.enabled())
                return

    def move_to_folder(self, room_ids: list[str], folder_id: str) -> None:
        target = self.get_folder(folder_id or follow_folders.UNCLASSIFIED)
        if target is None or target["type"] == "smart":
            return
        known = {str(item.room.get("room_id")) for item in self._items}
        moving = list(dict.fromkeys(key for key in room_ids if key in known))
        for folder in self.folders:
            folder["rooms"] = [key for key in folder["rooms"] if key not in moving]
        if target["type"] == "normal":
            target["rooms"].extend(moving)
            self._folder_pending.difference_update(moving)
        else:
            self._folder_pending.update(moving)
        self._refresh_folders()

    def move_folder(self, folder_id: str, direction: int) -> None:
        folder = self.get_folder(folder_id)
        if folder is None:
            return
        index = self.folders.index(folder)
        target = index + direction
        if 0 <= target < len(self.folders):
            self.folders[index], self.folders[target] = self.folders[target], self.folders[index]
            self._refresh_folders()

    def start_folder_drag(self) -> None:
        """拖动标题时临时收起全部文件夹，结束后恢复原来的展开状态。"""
        self._folder_drag_previous = {folder["id"]: folder["collapsed"] for folder in self.folders}
        self._folders_folded_by_drag.update(folder["id"] for folder in self.folders)
        for folder in self.folders:
            folder["collapsed"] = True
        self._refresh_folders(notify=False)

    def end_folder_drag(self) -> None:
        self.list_box.set_scroll_dir(0)
        self.list_box.folder_drop_indicator.hide()
        for folder in self.folders:
            if folder["id"] in self._folder_drag_previous:
                folder["collapsed"] = self._folder_drag_previous[folder["id"]]
        self._folder_drag_previous.clear()
        self._folders_folded_by_drag.clear()
        self._refresh_folders()

    def _folder_drop_target(self, folder_id: str, global_pos):
        box = self.list_box
        local = box.mapFromGlobal(global_pos)
        if self.get_folder(folder_id) is None or not box.rect().contains(local):
            return None
        remaining = [folder for folder in self.folders if folder["id"] != folder_id]
        headers = [(index, self._folder_buttons[folder["id"]]) for index, folder in enumerate(remaining)
                   if not self._folder_buttons[folder["id"]].isHidden()]
        along = local.x() if box.horizontal else local.y()
        for index, header in headers:
            start = header.x() if box.horizontal else header.y()
            length = header.width() if box.horizontal else header.height()
            if along < start + length / 2:
                return index, max(0, start - NAV_ITEM_GAP)
        if headers:
            index, header = headers[-1]
            end = header.geometry().right() if box.horizontal else header.geometry().bottom()
            return index + 1, end + 1
        return None

    def hover_folder_drag(self, folder_id: str, global_pos) -> None:
        self.list_box.auto_scroll(global_pos)
        target = self._folder_drop_target(folder_id, global_pos)
        indicator = self.list_box.folder_drop_indicator
        if target is None:
            indicator.hide()
            return
        _, along = target
        if self.list_box.horizontal:
            indicator.setGeometry(along, 0, 2, self.list_box.item_size()[1])
        else:
            indicator.setGeometry(0, along, self.list_box.width(), 2)
        indicator.show()
        indicator.raise_()

    def finish_folder_drag(self, folder_id: str, global_pos) -> None:
        self.list_box.set_scroll_dir(0)
        self.list_box.folder_drop_indicator.hide()
        target = self._folder_drop_target(folder_id, global_pos)
        if target is None:
            return
        index, _ = target
        folder = self.get_folder(folder_id)
        if self.folders.index(folder) != index:
            self.folders.remove(folder)
            self.folders.insert(index, folder)
            self._refresh_folders(notify=not bool(self._folder_drag_previous))

    def prompt_smart_folder(self, folder_id="") -> None:
        folder = self.get_folder(folder_id)
        dialog = SmartFolderDialog(self, folder)
        if dialog.exec() != QDialog.Accepted:
            return
        data = dialog.values()
        if any(item["name"] == data["name"] and item["id"] != folder_id for item in self.folders):
            return
        if folder:
            folder.update(data)
            self._refresh_folders()
        else:
            self.create_folder(**data)

    def _refresh_folders(self, notify: bool = True, *, animate=False) -> None:
        revealing = {item for item in self._items if item.filtered_out} if animate else ()
        ids = {folder["id"] for folder in self.folders}
        self._folders_folded_by_drag.intersection_update(ids)
        for folder_id in list(self._folder_buttons):
            if folder_id not in ids:
                button = self._folder_buttons.pop(folder_id)
                button.hide()
                button.deleteLater()
        self.clear_sort_selection()
        self.resort(animate=animate, duration=280 if animate else 150, revealing=revealing)
        for item in self._items:
            if item.filtered_out:
                item.check.setChecked(False)
        self._update_batch_label()
        self._sync_count()
        self._sync_sort_selection()
        if notify:
            self.foldersChanged.emit()

    def folder_entries(self, preview_items: list | None = None,
                       dragging_ids: set[str] | None = None) -> list:
        """分组显示，不改变关注、置顶或自定义顺序的保存方式。"""
        entries = []
        visible = self.visible_items() if preview_items is None else [
            item for item in preview_items if not item.filtered_out]
        active_copies = set()
        for folder in self.folders:
            button = self._folder_buttons.get(folder["id"])
            if button is None:
                button = FollowFolderButton(self, folder["id"])
                self._folder_buttons[folder["id"]] = button
            members = [item for item in visible
                       if self.folder_for(str(item.room.get("room_id"))) == folder["id"]]
            count = sum(fid == folder["id"] for fid in self._folder_assignments.values())
            copies = folder["type"] == "smart" and folder["rule"].get("display") == "copy"
            if copies:
                matched = follow_folders.smart_members(self.rooms(), self.folders, folder, self._folder_pending)
                count = len(matched)
                members = [item for item in self._items if str(item.room["room_id"]) in matched
                           and self.matches(item, self.filter_text.split(), folder["id"])]
                order = self.import_order if folder["sort"] == "imported" else self.custom_order
                positions = {rid: i for i, rid in enumerate(order)}
                def copy_key(item):
                    index = positions.get(str(item.room["room_id"]), len(positions))
                    value = (str(item.room.get("uname") or "").casefold() if folder["sort"] == "name"
                             else bool(item.room.get("live")) != (folder["sort"] == "live")
                             if folder["sort"] in ("live", "offline") else index)
                    return (not item.is_pinned, value, index)
                members.sort(key=copy_key)
                folded = folder["collapsed"] and (not self.filter_text or folder["id"] in self._folders_folded_by_drag)
                displayed = []
                if not folded:
                    for item in members:
                        key = (folder["id"], str(item.room["room_id"]))
                        active_copies.add(key)
                        if key not in self._smart_cards:
                            self._smart_cards[key] = SmartFolderCard(item, self.list_box)
                        displayed.append(self._smart_cards[key])
                members = displayed
            arrow = "▸" if folder["collapsed"] and (
                not self.filter_text or folder["id"] in self._folders_folded_by_drag) else "▾"
            title = f"{arrow} {folder['name']} · {count}"
            button.setToolTip(title + ("\n智能文件夹：拖动标题排序；右键编辑规则和排序" if folder["type"] == "smart"
                                      else "\n点击展开/收起；拖动标题排序；拖入卡片归类；右键管理"))
            width, height = self.list_box.item_size()
            label_width = height if self.side == "top" else width
            button.setToolButtonStyle(Qt.ToolButtonIconOnly if self.collapsed and self.side == "left"
                                      else Qt.ToolButtonTextBesideIcon)
            button.setText(button.fontMetrics().elidedText(title, Qt.ElideRight, max(12, label_width - 44)))
            search_match = bool(members) if copies else any(
                self.folder_for(str(item.room.get("room_id"))) == folder["id"]
                and self.matches(item, self.filter_text.split()) for item in self._items)
            button.setVisible((folder["type"] != "unclassified" or count > 0)
                              and (not self.filter_text or search_match))
            if not button.isHidden():
                entries.append(button)
                entries.extend(None if dragging_ids and str(item.room.get("room_id")) in dragging_ids
                               else item for item in members)
        originals = set(self._items)
        for key, card in list(self._smart_cards.items()):
            if key not in active_copies:
                card.hide()
            if card.original not in originals or not self.get_folder(key[0]):
                self._smart_cards.pop(key)
                card.deleteLater()
        return entries

    def _focus_room_list(self) -> None:
        """回车：把焦点从搜索框让给列表，接着就能直接点选 / 拖动。"""
        self.scroll.setFocus()

    def refresh_strip(self) -> None:
        """把当前关注列表（连已经下载好的头像）同步到顶部横栏。"""
        strip = getattr(self, "_head_strip", None)
        if strip is None:
            return
        rooms = []
        faces = {}
        for item in self.visible_items():          # 过滤时头像排也跟着缩
            room = dict(item.room)
            rooms.append(room)
            pixmap = item.thumb.face_pixmap()
            if pixmap is not None:
                faces[str(room.get("room_id") or "")] = pixmap
        strip.set_rooms(rooms, faces, self._wall_room_ids)

    def focus_search(self) -> None:
        """Ctrl+F：展开关注栏并把输入焦点交给搜索框。"""
        if self.collapsed:
            self.set_collapsed(False, animate=False)
        self.search.setFocus(Qt.ShortcutFocusReason)
        self.search.selectAll()

    def set_wall_rooms(self, room_ids) -> None:
        """同步画面墙占用状态，供卡片和竖屏头像条显示蓝色标记。"""
        ids = {str(room_id) for room_id in room_ids if str(room_id)}
        if ids == self._wall_room_ids:
            return
        self._wall_room_ids = ids
        self._refresh_wall_marks()
        self.refresh_strip()

    def _refresh_wall_marks(self) -> None:
        """按当前的画面墙占用，重设每张卡片的蓝框。

        列表一变（加 / 删 / 重建）就调一次。`_append_item()` 建卡片时读的是**当时**的
        `_wall_room_ids`，而 `set_wall_rooms()` 有个「没变就直接返回」的短路 ——
        两条路径一交叉，卡片就可能留着一个过期的蓝框（用户报的「刚加进关注栏就被
        标成已在画面墙」）。所以列表动过之后统一重设一遍，状态只有一个来源。
        """
        for item in self._items:
            item.set_on_wall(str(item.room.get("room_id") or "") in self._wall_room_ids)

    # ---- 收起 / 展开 ----
    def set_side(self, side: str) -> None:
        """摆放方式：left = 横屏的左栏（默认）；top = 竖屏的顶部横栏。

        竖屏下侧栏变成一条顶部横栏：宽度撑满、搜索框变宽、列表只留一行头像
        （收起时只剩头像，展开时多一行按钮），逻辑和横屏的收起/展开一致。
        """
        side = "top" if side == "top" else "left"
        # 无论走哪个分支，先把约束解掉：
        # - 滚动区的高度上限（竖屏那条「只占一条」的限制留着，切回左栏就只剩一条）
        # - 侧栏的竖直策略（竖屏时被压成一条，切回左栏必须重新撑满）
        self.scroll.setMinimumHeight(0)
        self.scroll.setMaximumHeight(16_777_215)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.setMinimumHeight(0)
        self.setMaximumHeight(16_777_215)
        self.list_box._clamp_vertical_scroll()
        if side == self.side:
            # 已经是这个摆放方式：不重复设置宽度，但仍要同步一次可见性 ——
            # 调用方（换排布 / 刚设过收起状态）可能正等着头像排露出来
            if side == "top":
                self._sync_top_mode()
            else:
                # 竖向时务必把滚动区的高度上限解掉：竖屏那条 130px 的限制留着，
                # 左栏就只剩一条（用户看到的就是这个）
                self._apply_scroll_axis()
            return
        self.side = side
        self.set_card_mode(self._effective_card_mode())
        horizontal = side == "top"
        for item in self._items:
            item.set_portrait_strip(horizontal and not self.card_mode)
        if not horizontal:
            # 切回左栏：横栏那一行先拆掉（控件按原顺序挂回竖排），头像排收掉
            # （它只服务于顶部横栏），展开键还回标题行，并把「顶部横栏收起时
            # 藏起来的控件」逐个恢复 —— 只显示标题行容器是不够的，
            # 搜索/列表/按钮行会一直是隐藏状态，左栏就只剩一小条。
            self._release_bar_row()
            self._head_scroll.setVisible(False)      # 头像排只服务于顶部横栏
            header = getattr(self, "_header_row", None)
            if header is not None:
                header.setVisible(True)
            for index in range(self.title_box.count()):
                holder = self.title_box.itemAt(index).widget()
                if holder is not None:
                    holder.setVisible(True)
            self._set_brand_header(compact=False)
            self.batch_button.setVisible(True)
            for widget, visible in ((self.search, True), (self.status_row, True),
                                    (self.scroll, True),
                                    (self.normal_bar, not self.select_mode),
                                    (self.batch_bar, self.select_mode),
                                    (self.tool_row, True)):
                widget.setVisible(visible)
            self.settings_button.setVisible(True)    # 竖屏时它收进「⋯」里了
            # 竖屏时被摘进横栏那一行的控件要各回各家：多选回标题行、
            # 排序/刷新回状态行，图标样式也换回文字按钮
            self._restore_side_children()
            self.account_row.setVisible(self._account_row_should_show())
            self._restore_toggle_to_header()
            # 竖屏那套滚动轴状态必须在这里还原：横排时 horizontal_only=True、
            # 竖条常关、横条 AsNeeded，不回滚的话回横屏后竖向滚动条一直藏着，
            # 滚轮还会被 CarouselScroll 当成横滚吞掉 —— 左栏整列就滚不动了。
            self._apply_scroll_axis()
        self.setFixedWidth(theme.SIDEBAR_WIDTH)      # 先恢复宽度约束，下面再改
        if horizontal:
            self._layout.setContentsMargins(10, 8, 10, 8)
            self._layout.setSpacing(6)
            self.setMinimumWidth(0)
            self.setMaximumWidth(16_777_215)
        else:
            self._layout.setContentsMargins(12 if not self.collapsed else 8, 14,
                                            12 if not self.collapsed else 8, 12)
            self._layout.setSpacing(10)
            self.setFixedWidth(
                theme.SIDEBAR_RAIL_WIDTH if self.collapsed else theme.SIDEBAR_WIDTH)
        self._sync_top_mode()
        self.list_box.relayout(animate=False)

    def _restore_toggle_to_header(self) -> None:
        """把「收起/展开」按钮放回标题行（竖屏时它是摘出来放在横栏右上角的）。"""
        toggle = getattr(self, "toggle_button", None)
        header = getattr(self, "_header_row", None)
        if toggle is None or header is None:
            return
        self._detach_from_rows(toggle)
        toggle.setObjectName("SidebarToggle")      # 换回标题行那套样式
        toggle.setFixedSize(24, 24)
        toggle.setParent(header)
        header.layout().addWidget(toggle, 0, Qt.AlignTop)
        toggle.setVisible(True)
        _repolish(toggle)

    # ---- 横栏那一行 ----
    def _detach_from_rows(self, widget: QWidget) -> None:
        """把控件从「竖排布局」和横栏那两个容器里都摘出来。"""
        for holder in (self._layout, self._bar_row_box, self._bar_row2_box,
                       self._bar_right_box):
            if holder is not None:
                holder.removeWidget(widget)

    def _ensure_bar_row(self) -> None:
        """建出横栏的两行容器（只建一次）。

        第一行：logo + 搜索框（收起时换成头像排）+ 多选/排序/刷新小图标 + 展开键。
        第二行：横向卡片条 + 右侧单独一块（账号 / 布局预设 / 设置 竖排）。
        右侧那一块只占第二行，不侵占第一行的地方（用户要求）；高度就是卡片条
        那一行的高度，三个按钮 + 两条分割线把它正好分完。
        """
        if self._bar_row is not None:
            return
        self._bar_row = QWidget(self)
        box = QHBoxLayout(self._bar_row)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(6)
        self._bar_row_box = box
        self._bar_row2 = QWidget(self)
        box2 = QHBoxLayout(self._bar_row2)
        box2.setContentsMargins(0, 0, 0, 0)
        box2.setSpacing(6)
        self._bar_row2_box = box2
        self._bar_right = QWidget(self._bar_row2)
        right = QVBoxLayout(self._bar_right)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(0)
        self._bar_right_box = right
        #: 三个按钮之间的分割线（用户要求「适当给予分割」）
        self._bar_divider_label = QFrame(self._bar_right)
        self._bar_divider_tool = QFrame(self._bar_right)
        for divider in (self._bar_divider_label, self._bar_divider_tool):
            divider.setObjectName("BarDivider")
            divider.setFixedHeight(1)
            divider.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        #: 分割线两侧的空白：高度由 _sync_bar_gaps() 按缩略图高度算出来
        self._bar_gaps = tuple(QWidget(self._bar_right) for _ in range(4))
        for gap in self._bar_gaps:
            gap.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        # 末尾留一条 stretch：三个按钮的总高只到缩略图下沿，剩下的高度（滚动条
        # 那条）不参与分配，这一块本身仍然撑满卡片条那一行
        right.addStretch(1)

    def _bar_widgets(self) -> list:
        """竖屏时会被横栏借走的控件（横屏要按原样挂回去）。"""
        return [self.search, self._head_scroll, self.batch_button, self.sort_button,
                self.refresh_button, self.account_row, self.tool_row,
                self.batch_bar, self.toggle_button]

    def _place_account(self, in_right_block: bool) -> None:
        """账号头像的位置：展开时在整块里排第一，收起时回到第一行最右端。"""
        wanted = self._bar_right if in_right_block else self._bar_row
        if self.account_row.parentWidget() is wanted:
            return
        self._detach_from_rows(self.account_row)
        self.account_row.setParent(wanted)
        if in_right_block:
            self._bar_right_box.insertWidget(0, self.account_row, 1)
            self._apply_bar_block_stretches()
        else:
            self._bar_row_box.insertWidget(self._bar_row_box.count() - 1,
                                           self.account_row)

    def _sync_bar_gaps(self) -> None:
        """算两条空白的高度。

        目标是让**最下面的按钮下沿和直播间缩略图的下沿齐平**，所以减的是缩略图
        高度（`NAV_ITEM_HEIGHT`），不是整条卡片行 —— 卡片行还含那 8px 滚动条。
        三个按钮各用横屏那套高度，两条线各 1px，剩下的**均分**给两条空白。
        """
        target = NAV_ITEM_HEIGHT
        buttons = (theme.CONTROL_HEIGHT + self.layout_button.sizeHint().height()
                   + self.settings_button.sizeHint().height())
        slack = max(0, target - buttons - 2)       # 四条空白加起来的高度
        # 每条空白 = 线上那段 + 1px 线 + 线下那段，所以先把那 1px 加回来再对半分
        per_gap, extra = divmod(slack + 2, 2)
        blank, blank_extra = divmod(max(0, per_gap - 1), 2)
        for index, gap in enumerate(self._bar_gaps):
            # 每条空白里「线上 / 线下」两段：先按对半分，余数给上面那段
            height = blank + (blank_extra if index % 2 == 0 else 0)
            if index >= 2:
                height += extra                    # 除不尽的那 1px 给第二条空白
            gap.setFixedHeight(height)

    def _sync_bar_density(self) -> None:
        """竖屏两种卡片密度共用账号、布局、设置的竖排位置。"""
        self._bar_right_box.setDirection(QBoxLayout.TopToBottom)
        self._bar_right_box.setSpacing(0)
        tool_box = self.tool_row.layout()
        tool_box.setDirection(QBoxLayout.TopToBottom)
        tool_box.setSpacing(0)
        for widget in (*self._bar_gaps, self._bar_divider_label, self._bar_divider_tool):
            widget.setVisible(True)
        self.layout_button.setText("布局预设")
        for button in (self.layout_button, self.settings_button):
            button.setMaximumWidth(16_777_215)
        self.tool_row.setMinimumWidth(0)
        self.tool_row.setMaximumWidth(16_777_215)
        self._sync_bar_gaps()

    def _apply_bar_block_stretches(self) -> None:
        """账号和工具行自己不占 stretch（高度全由按钮 + 空白算出来）。

        每次挪动账号都要重设：`insertWidget` / `removeWidget` 会让布局里其它项
        的下标平移。
        """
        for index in range(self._bar_right_box.count()):
            widget = self._bar_right_box.itemAt(index).widget()
            if widget is self.account_row or widget is self.tool_row:
                self._bar_right_box.setStretch(index, 0)

    def _bar_icons(self) -> tuple:
        """横栏里当小图标用的三个按钮（横屏时它们各有各的文字位置）。"""
        return (self.batch_button, self.sort_button, self.refresh_button)

    def _sync_bar_icons(self) -> None:
        """竖屏那一行把「多选 / 排序 / 刷新」压成小图标；横屏还原成文字按钮。

        横屏的多选在标题行、排序/刷新在状态行，都是带文字的；横栏一行里
        放不下三块文字，所以只留图标（悬停提示照旧说明用途）。
        """
        top = self.side == "top"
        if top:
            # 图标是自己画的（BarIconButton）：字形在雅黑下会偏左 / 偏小。
            # 按钮换成 #BarIcon 那套方形样式，ChipButton 的 10px 内边距会挤掉图标
            for button in self._bar_icons():
                button.setObjectName("BarIcon")
                button.setFixedSize(30, 30)
                if isinstance(button, BarIconButton):
                    button.set_icon_mode(True)
        else:
            for button in self._bar_icons():
                button.setObjectName("ChipButton")
                button.setMinimumSize(0, 0)
                button.setMaximumSize(16_777_215, 16_777_215)
                if isinstance(button, BarIconButton):
                    button.set_icon_mode(False)
            self.batch_button.setFixedHeight(22)     # 标题行里那套矮样式
            self.refresh_button.setFixedSize(28, 22)  # RefreshButton 的原始尺寸
        for button in self._bar_icons():
            _repolish(button)

    def _restore_side_children(self) -> None:
        """回左栏：多选回标题行、排序/刷新回状态行（顺序和 __init__ 里一致）。"""
        self._detach_from_rows(self.batch_button)
        self.batch_button.setParent(self._header_row)
        self._header_row.layout().addWidget(self.batch_button, 0, Qt.AlignTop)

        box = self.status_row.layout()
        for widget in (self.count_label, self.sort_button, self.refresh_button):
            box.removeWidget(widget)
        box.addWidget(self.count_label, 1)
        box.addWidget(self.sort_button, 0, Qt.AlignRight)
        box.addWidget(self.refresh_button, 0, Qt.AlignRight)
        self.sort_button.setParent(self.status_row)
        self.refresh_button.setParent(self.status_row)
        self._sync_bar_icons()

    def _adopt_bar_row(self) -> None:
        """竖屏：把横栏排成两行。

        第一行：logo（圆点 + 「DD监控室CE」）+ 搜索框（收起时换成头排）
        + 多选/排序/刷新三个小图标 + 展开键。
        第二行：横向卡片条 + 右侧单独一块，那块里「账号 / 布局预设 / 设置」竖排、
        中间两条 1px 分割线 —— 三个按钮 + 两条线正好把卡片条那一行的高度分完，
        不占第一行的地方（用户要求：加起来和左侧展开关注栏同高，别占用别处）。
        """
        self._ensure_bar_row()
        if not self._bar_in_use:
            index = self._layout.indexOf(self._header_row)
            for widget in (self._header_row, self.search, self._head_scroll,
                           self.batch_bar, self.batch_button, self.sort_button,
                           self.refresh_button, self.toggle_button):
                self._detach_from_rows(widget)
                widget.setParent(self._bar_row)
            # 左边是 logo，然后是搜索框（收起时换成头像排）、多选条、图标、展开键。
            # 多选条和搜索框轮流坐第一行：**不额外占一行**，横栏高度不变，
            # 画面墙就不会因为点「多选」抖一下（用户报的）。
            self._bar_row_box.addWidget(self._header_row)
            self._bar_row_box.addWidget(self.search, 1)
            self._bar_row_box.addWidget(self._head_scroll, 1)
            self._bar_row_box.addWidget(self.batch_bar, 1)
            for widget in self._bar_icons() + (self.toggle_button,):
                self._bar_row_box.addWidget(widget)
            # 第一行的高度固定成标准控件那一档（多选条里的删除/取消就是原来那两个
            # 按钮，压矮了圆角就和样式表对不上）。固定住之后，搜索框和多选条谁在
            # 这一行里都一样高 —— 点「多选」不会让横栏变高、画布不抖。
            self._bar_row.setFixedHeight(self.batch_bar.sizeHint().height())

            self._detach_from_rows(self.scroll)
            self._detach_from_rows(self.tool_row)
            self.scroll.setParent(self._bar_row2)
            self._bar_row2_box.addWidget(self.scroll, 1)
            self._bar_row2_box.addWidget(self._bar_right)
            # 右边那一块：账号 / 空白 / 分割线 / 空白 / 工具行。
            # 三个按钮都用横屏那套自然高度，两条空白（含中间的 1px 线）一样高，
            # 最上面、最下面的按钮正好贴着卡片条那一行的上下沿。
            self._place_account(True)
            self._bar_right_box.insertWidget(1, self._bar_gaps[0])
            self._bar_right_box.insertWidget(2, self._bar_divider_label)
            self._bar_right_box.insertWidget(3, self._bar_gaps[1])
            self._bar_right_box.insertWidget(4, self.tool_row)
            self._apply_bar_block_stretches()
            tool_box = self.tool_row.layout()
            tool_box.setDirection(QBoxLayout.TopToBottom)
            tool_box.setSpacing(0)
            tool_box.insertWidget(1, self._bar_gaps[2])
            tool_box.insertWidget(2, self._bar_divider_tool)
            tool_box.insertWidget(3, self._bar_gaps[3])
            # 两个按钮自己不吃 stretch（横屏时布局预设是 stretch 1）
            tool_box.setStretch(0, 0)
            tool_box.setStretch(4, 0)
            self._sync_bar_gaps()
            # 三个按钮左右长度一样（都撑满这一块）；高度用横屏那套自然高度
            for button in (self.layout_button, self.settings_button):
                button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

            self._layout.insertWidget(index + 1 if index >= 0 else 1, self._bar_row)
            self._layout.insertWidget(index + 2 if index >= 0 else 2, self._bar_row2)
            self._bar_in_use = True
            self._sync_bar_icons()
        self._bar_row.setVisible(True)

    def _release_bar_row(self) -> None:
        """回左栏：把这两行拆掉，控件按 __init__ 里的原始顺序挂回竖排布局。"""
        if not self._bar_in_use:
            return
        for row in (self._bar_row, self._bar_row2):
            self._layout.removeWidget(row)
            row.setVisible(False)
        for widget in self._bar_widgets() + [self.scroll, self._header_row]:
            self._detach_from_rows(widget)
        for widget in self._column_order:
            self._detach_from_rows(widget)
            self._layout.addWidget(widget)
        # 布局预设 / 设置回到横排一行，把竖排时插进去的空白和分割线拿出来
        tool_box = self.tool_row.layout()
        tool_box.removeWidget(self._bar_divider_tool)
        for gap in self._bar_gaps[2:]:
            tool_box.removeWidget(gap)
        tool_box.setDirection(QBoxLayout.LeftToRight)
        tool_box.setStretch(0, 1)
        tool_box.setSpacing(6)
        for gap in self._bar_gaps[:2]:
            self._bar_right_box.removeWidget(gap)
        for button, policy in self._tool_button_policies.items():
            button.setSizePolicy(policy)
            button.setMaximumWidth(16_777_215)   # 竖屏时按自身宽度限过
        self.layout_button.setText("布局预设")
        self.tool_row.setMinimumWidth(0)
        self.tool_row.setMaximumWidth(16_777_215)
        # 多选条回左栏：高度限制解掉，按钮恢复样式表那套高度
        self._bar_row.setMinimumHeight(0)
        self._bar_row.setMaximumHeight(16_777_215)
        self.batch_bar.setMinimumHeight(0)
        self.batch_bar.setMaximumHeight(16_777_215)
        for button in (self.delete_button, self.cancel_button):
            button.setMinimumHeight(0)
            button.setMaximumHeight(16_777_215)
        self.account_row.setSizePolicy(self._account_policy)
        self._bar_in_use = False
        self._sync_account_row_shape()          # 账号条恢复原来的固定高度
        self._sync_account_row_width()          # 左栏的账号条恢复撑满

    def _account_row_should_show(self) -> bool:
        """账号按钮什么时候露出来。

        用户 2026-09-18：**没登录也要露**（显示「登录」，点了弹扫码登录）；
        登录后横屏在侧栏底部、竖屏在横栏右侧那一块 / 收起态头像排旁边。
        """
        return True

    def _sync_account_row_shape(self) -> None:
        """账号条的形状跟着「横屏/竖屏 + 收起/展开」走。

        竖屏收起时横栏只有 36px 高，账号头像要按头排头像的尺寸（34）挤进去；
        竖屏展开时它在右侧那一块里，高度就用横屏那套（34），多出来的高度留给
        两条空白；其它情况沿用原来的样子。
        """
        if self.side == "top" and not self.collapsed:
            self.account_row.set_compact(False)
            # 高度用横屏那套（34），宽度跟着这一块走（三个按钮左右一样长）
            self.account_row.setFixedHeight(theme.CONTROL_HEIGHT)
            self.account_row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        elif self.side == "top":
            self.account_row.set_compact(True, avatar=RoomStrip.AVATAR, margin=1)
        else:
            self.account_row.set_compact(self.collapsed)

    def _sync_account_row_width(self) -> None:
        """横栏里的账号条宽度。

        展开时放得下昵称（否则会被挤成「A…」）；收起时它就是一个和头排头像
        一样大的小圆点 —— 不这么算的话它会一直沿用昵称的宽度，变成一条长胶囊。
        横屏时它本来就撑满侧栏，不需要这个限制。
        """
        row = self.account_row
        if self.side != "top":
            row.setMinimumWidth(0)
            row.setMaximumWidth(16_777_215)
            return
        row.setMaximumWidth(16_777_215)
        if self.collapsed:
            row.setMinimumWidth(row.avatar.width() + 2)
            return
        box = row._layout
        margins = box.contentsMargins()
        # +8：留一点余量，正好卡着算出来的宽度会让昵称尾字差几个像素被省略
        need = (margins.left() + margins.right() + box.spacing() * 2
                + row.avatar.width() + max(row.name.sizeHint().width(), row.account_id.sizeHint().width())
                + row.arrow.sizeHint().width() + 8)
        row.setMinimumWidth(min(self.ACCOUNT_PILL_MAX, need))

    def _sync_top_mode(self) -> None:
        """按 side + collapsed 决定顶部横栏露哪些控件。

        横栏是**一行**：左边搜索框（收起时换成头像排），中间「多选 / 排序 / 刷新」
        三个小图标，右边一块是账号头像 + 布局预设 + 设置 + 展开/收起键；
        下面只剩横向卡片条。头像排在收起时露出来（它就是关注列表）。
        """
        self._sync_toggle_arrow()          # 竖屏要上下箭头，横屏左右
        if self.side != "top":
            return
        self._adopt_bar_row()
        self._sync_bar_density()
        self._sync_account_row_shape()
        self._sync_account_row_width()
        header = getattr(self, "_header_row", None)
        toggle = getattr(self, "toggle_button", None)
        # 展开时收起头排（用户要求展开后不显示头像排，那点高度留给卡片）；
        # 收起时它顶掉搜索框的位置，一行摆满关注头像
        self._head_scroll.setVisible(self.collapsed)
        # 账号头像：展开时在卡片条右边那一块里，收起时回到第一行最右端
        self._place_account(not self.collapsed)
        self._bar_right.setVisible(not self.collapsed)
        self._bar_row2.setVisible(not self.collapsed)
        if toggle is not None:
            # 摘到横栏这一行的右端常驻；换成紧凑样式，
            # 否则标题行那套 24px 最小尺寸 + padding 会把横栏撑高一截
            toggle.setObjectName("BarToggle")
            toggle.setFixedSize(22, 22)
            if toggle.parentWidget() is not self._bar_row:
                toggle.setParent(self._bar_row)
                self._bar_row_box.addWidget(toggle)
            toggle.setVisible(True)
            _repolish(toggle)
        if self.collapsed:
            if header is not None:
                header.setVisible(False)
            # 收起时这一行只剩：头像排 + 账号头像 + 展开键
            for widget in (self.search, self.status_row, self.scroll, self.normal_bar,
                           self.batch_bar, self.tool_row) + self._bar_icons():
                widget.setVisible(False)
            self.account_row.setVisible(self._account_row_should_show())
        else:
            # 标题行留在第一行最前面当 logo（用户要求左侧给 logo 留位置）：
            # 只露「DD监控室CE」，副标题藏起来；搜索框因此短了一截
            if header is not None:
                header.setVisible(True)
            self._show_logo_title()
            # 第一行：平时是搜索框 + 三个图标；进多选态就让多选条顶掉它们，
            # 这一行的高度不变 —— 点「多选」时画面墙不会跟着抖（用户报的）
            select = self.select_mode
            self.search.setVisible(not select)
            self.batch_bar.setVisible(select)
            for button in self._bar_icons():
                button.setVisible(not select)
            self.batch_button.setVisible(True)
            # 排序/刷新已经在搜索那一行当图标了，「关注中 · N」那一行不再出来
            self.status_row.setVisible(False)
            self.scroll.setVisible(True)
            # 导入关注 / 添加直播间收进账号菜单，别再占一行
            self.normal_bar.setVisible(False)
            self.account_row.setVisible(self._account_row_should_show())
            self.tool_row.setVisible(True)           # 布局预设 + 设置并排
            self.settings_button.setVisible(True)
            self._apply_scroll_axis()

    def _show_logo_title(self) -> None:
        """竖屏横栏只挂紧凑 Logo，不改变原有第一行高度。"""
        self._set_brand_header(compact=True)

    def _set_brand_header(self, compact: bool) -> None:
        """横屏显示 Logo + 名称；紧凑横栏只显示 Logo。"""
        size = 30 if compact else 28
        self.logo_label.setFixedSize(size, size)
        if not self._brand_logo.isNull():
            self.logo_label.setPixmap(self._brand_logo.scaled(
                size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.logo_label.setVisible(True)
        self.title_label.setVisible(not compact)
        self.subtitle_label.setVisible(False)
        if not compact:
            self.subtitle_label.setVisible(True)

    def _apply_scroll_axis(self) -> None:
        """竖屏横栏里关注列表是横向卡片条：左右滚，只占一条高度。"""
        top = self.side == "top"
        if top:
            # 一条卡片 + 间距 + 横向滚动条自己的高度：滚动条是占位的，
            # 不留这 8px 卡片底边会被它切掉（「直播中」角标会缺一角）
            rows = self.list_box.item_size()[1] + NAV_ITEM_GAP + theme.SCROLLBAR_SIZE
            self.scroll.setMinimumHeight(rows)
            self.scroll.setMaximumHeight(rows)
            self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            self.scroll.horizontal_only = True
        else:
            self.scroll.setMinimumHeight(0)
            self.scroll.setMaximumHeight(16_777_215)
            # 横滚条必须显式关掉：留着 AsNeeded 时，卡片宽度正好等于视口宽度，
            # Qt 会把滚动条弹出来，挤掉高度后就只剩一张卡片可见了
            self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.scroll.setVerticalScrollBarPolicy(
                Qt.ScrollBarAlwaysOff if self.collapsed else Qt.ScrollBarAsNeeded)
            self.scroll.horizontal_only = False
        self.list_box.relayout(animate=False)

    def toggle_collapsed(self) -> None:
        self.set_collapsed(not self.collapsed)

    def _sync_toggle_arrow(self) -> None:
        """收起键的箭头方向：横屏左右、竖屏上下（用户要求）。"""
        toggle = getattr(self, "toggle_button", None)
        if toggle is None:
            return
        if hasattr(toggle, "set_orientation"):
            toggle.set_orientation(self.side == "top", self.collapsed)

    def set_collapsed(self, collapsed: bool, animate: bool = True) -> None:
        if collapsed == self.collapsed:
            return
        self.collapsed = collapsed
        if self.side == "top":
            # 竖屏：宽度始终撑满，收起/展开只影响露出哪些控件
            self._layout.setContentsMargins(10, 8, 10, 8)
            self._sync_top_mode()
            if not collapsed:
                for item in self._items:
                    item.set_compact(False)
                self.list_box.relayout(animate=False)
            self.collapsedChanged.emit(collapsed)
            return
        target = theme.SIDEBAR_RAIL_WIDTH if collapsed else theme.SIDEBAR_WIDTH
        for widget in (self.search, self.status_row, self.normal_bar, self.batch_bar,
                       self.logo_label, self.batch_button, self.tool_row):
            widget.setVisible(not collapsed and (widget is not self.batch_bar or self.select_mode))
        self._sync_account_row_shape()
        self.account_row.setVisible(self._account_row_should_show())
        # 窄条里列表一出现滚动条就会把内容挤窄，上下两排头像就对不齐了；
        # 收起时干脆不显示滚动条，滚轮照样能滚
        self.scroll.setVerticalScrollBarPolicy(
            Qt.ScrollBarAlwaysOff if collapsed else Qt.ScrollBarAsNeeded)
        for index in range(self.title_box.count()):
            widget = self.title_box.itemAt(index).widget()
            if widget:
                widget.setVisible(not collapsed)
        self._layout.setContentsMargins(8 if collapsed else 12, 14, 8 if collapsed else 12, 12)
        self._sync_toggle_arrow()
        for item in self._items:
            item.set_compact(collapsed)
        self.list_box.relayout(animate=False)

        if not animate:
            self.setFixedWidth(target)
            self.collapsedChanged.emit(collapsed)
            return

        # 动画期间挂起封面重裁：改宽度会让**每一帧**都给每个条目发 resizeEvent，
        # 而重裁一次就是平滑缩放 + 圆角裁剪 + 两段渐变，36 个关注足以把动画拖垮
        # （见 NavThumb.set_cover_hold）。先挂起，收尾只补当前可见的那几条。
        for item in self._items:
            try:
                item.thumb.set_cover_hold(True)
            except RuntimeError:                # 条目已经被回收
                continue
        group = []
        for prop in (b"minimumWidth", b"maximumWidth"):
            animation = QPropertyAnimation(self, prop)
            animation.setDuration(160)
            animation.setStartValue(self.width())
            animation.setEndValue(target)
            animation.setEasingCurve(QEasingCurve.OutCubic)
            group.append(animation)
        group[-1].finished.connect(lambda: self._finish_collapse(target))
        for animation in group:
            animation.start()
        self._animations = group          # 保持引用，避免被回收
        self.collapsedChanged.emit(collapsed)

    def _finish_collapse(self, target: int) -> None:
        """宽度动画收尾：补上动画期间省下的封面重裁。

        只补**当前可见**的条目（滚动区里通常只有 5~8 条）—— 36 条一起补就会把
        收尾这一下又拖住。看不见的那些等滚进视野时收到 resizeEvent 自己会重裁，
        不会留下没更新的封面。
        """
        self.setFixedWidth(target)
        for item in self._items:
            try:
                item.thumb.set_cover_hold(False)
                if item.isVisible():
                    item.thumb.refresh_cover()
            except RuntimeError:                # 条目已经被回收
                continue

    def set_card_mode(self, enabled: bool) -> None:
        """切换关注列表样式；侧栏收起时只记录选择，展开后再呈现。"""
        enabled = bool(enabled)
        if enabled == self.card_mode:
            return
        self.card_mode = enabled
        for item in self._items:
            item.thumb.stop()
            item.set_card_mode(enabled)
            item.set_portrait_strip(self.side == "top" and not enabled)
        self.list_box.relayout(animate=False)
        if self.side == "top" and self._bar_in_use:
            self._sync_top_mode()

    def set_compact_policy(self, card_mode: bool, auto_compact: bool,
                           compact_threshold: int) -> None:
        """保存用户偏好，并按当前关注数量决定实际使用哪种列表。"""
        self.preferred_card_mode = bool(card_mode)
        self.auto_compact = bool(auto_compact)
        self.compact_threshold = max(2, int(compact_threshold))
        self.set_card_mode(self._effective_card_mode())

    def _effective_card_mode(self) -> bool:
        """横竖屏共用关注数量阈值，竖屏改为紧凑横向列表。"""
        return self.preferred_card_mode and not (
            self.auto_compact and len(self._items) >= self.compact_threshold)

    # ---- 批量选择 ----
    def set_select_mode(self, enabled: bool) -> None:
        self.select_mode = enabled
        if enabled:
            self.clear_sort_selection()
        self.batch_button.setChecked(enabled)
        if enabled and self.filter_text:
            # 进多选就把搜索清掉：藏起来的条目也还在「已选」里，批量删太危险
            self.search.clear()
        # 竖屏时 batch_bar 被借到横栏第一行里（见 _adopt_bar_row），
        # 露不露由 _sync_top_mode 统一决定，这里只管横屏那一列。
        if self.side != "top":
            self.batch_bar.setVisible(enabled and not self.collapsed)
            self.normal_bar.setVisible(not enabled and not self.collapsed)
        else:
            self._sync_top_mode()
        for item in self._items:
            item.set_select_mode(enabled and not self.collapsed)
        self._update_batch_label()

    def _update_batch_label(self) -> None:
        count = sum(1 for item in self._items if item.is_checked())
        self.batch_label.setText(f"已选 {count} 个")
        self._sync_sort_selection()

    def _emit_delete(self) -> None:
        chosen = [item.room for item in self._items if item.is_checked()]
        if chosen:
            self.deleteRequested.emit(chosen)
        self.set_select_mode(False)

    def selected_sort_ids(self) -> list[str]:
        if self.select_mode:
            return [str(item.room.get("room_id")) for item in self._items
                    if item.is_checked() and not item.filtered_out]
        return [str(item.room.get("room_id")) for item in self._items
                if str(item.room.get("room_id")) in self._sort_selected_ids]

    def _sync_sort_selection(self) -> None:
        selected = set(self.selected_sort_ids())
        for item in self._items:
            item.set_sort_selected(str(item.room.get("room_id")) in selected)

    def clear_sort_selection(self) -> None:
        if self._sort_selected_ids:
            self._sort_selected_ids.clear()
            self._sync_sort_selection()
        self._sort_anchor = None

    def select_sort_item(self, room_id: str, modifiers) -> None:
        """Ctrl 增减选择，Shift 选一段；普通点击回到单卡片操作。"""
        room_id = str(room_id)
        if modifiers & Qt.ShiftModifier:
            visible = [str(item.room.get("room_id")) for item in self.visible_items()]
            if self._sort_anchor in visible and room_id in visible:
                start, end = sorted((visible.index(self._sort_anchor), visible.index(room_id)))
                chosen = set(visible[start:end + 1])
            else:
                chosen = {room_id}
            self._sort_selected_ids = (self._sort_selected_ids | chosen
                                       if modifiers & Qt.ControlModifier else chosen)
        elif modifiers & Qt.ControlModifier:
            if room_id in self._sort_selected_ids:
                self._sort_selected_ids.remove(room_id)
            else:
                self._sort_selected_ids.add(room_id)
            self._sort_anchor = room_id
        else:
            self._sort_selected_ids.clear()
            self._sort_anchor = room_id
        self._sync_sort_selection()

    def dragged_room_ids(self, room_id: str) -> list[str]:
        """从选中卡片拖动时带上整组；拖动未选中的卡片则只移动它。"""
        room_id = str(room_id)
        if room_id in self.selected_sort_ids():
            return self.selected_sort_ids()
        if not self.select_mode:
            self.clear_sort_selection()
        return [room_id]

    def move_sort_selection(self, room_id: str, to_front: bool) -> bool:
        return self.reorder_items(self.dragged_room_ids(room_id),
                                  0 if to_front else len(self._items))

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
        item.openBrowserRequested.connect(self.openBrowserRequested.emit)
        item.checkedChanged.connect(self._update_batch_label)
        item.pinToggled.connect(self.toggle_pin)
        item.hovered.connect(self.previewHovered.emit)
        item.unhovered.connect(self.previewUnhovered.emit)
        item.set_card_mode(self.card_mode)
        item.set_portrait_strip(self.side == "top" and not self.card_mode)
        item.set_on_wall(room_id in self._wall_room_ids)
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
        self._folder_pending.add(room_id)
        self._append_item(room)
        self.set_compact_policy(self.preferred_card_mode, self.auto_compact,
                                self.compact_threshold)
        # 新控件初始坐标是 (0, 0)，必须立即排版，否则会压在第一项上，
        # 直到用户拖动列表才恢复。
        self.resort(animate=False)
        self._sync_count()
        self._refresh_wall_marks()      # 新卡片的蓝框按当前墙面重设一次
        self.refresh_strip()
        if self.isVisible() and motion.enabled():
            self._entering_room_ids.add(room_id)
            self._card_entry_timer.start(0)
        return True

    def _reveal_added_rooms(self) -> None:
        """等批量添加与目标文件夹归类结束，只让新卡片从最终落点滑入。"""
        entering = {item for item in self._items
                    if str(item.room.get("room_id")) in self._entering_room_ids}
        self._entering_room_ids.clear()
        if entering and self.isVisible() and motion.enabled():
            self.list_box.relayout(animate=True, duration=220, revealing=entering)

    def remove_room(self, room: dict) -> None:
        item = next((entry for entry in self._items
                     if str(entry.room.get("room_id")) == str(room.get("room_id"))), None)
        if item is None:
            return
        item.hide()
        item.drop_live_alert()
        item.thumb.stop()               # 缩略图里可能正在放预览
        item.thumb.release_player()
        item.setParent(None)
        item.deleteLater()
        self._items.remove(item)
        room_id = str(room.get("room_id"))
        self._folder_pending.discard(room_id)
        for folder in self.folders:
            if room_id in folder["rooms"]:
                folder["rooms"].remove(room_id)
        self._sort_selected_ids.discard(room_id)
        if self._sort_anchor == room_id:
            self._sort_anchor = None
        if room_id in self.import_order:
            self.import_order.remove(room_id)
        if room_id in self.custom_order:
            self.custom_order.remove(room_id)
        self.set_compact_policy(self.preferred_card_mode, self.auto_compact,
                                self.compact_threshold)
        self.refresh_filter()
        self._sync_count()
        self._refresh_wall_marks()      # 删完也重设一次，蓝框状态别留旧账
        self.refresh_strip()

    def rooms(self) -> list[dict]:
        return [item.room for item in self._items]

    def items(self) -> list[NavItem]:
        return list(self._items)

    def drop_index_at(self, global_pos) -> int:
        """全局坐标 -> 列表里的落点下标（给 NavItem 转发拖动用）。"""
        local = self.list_box.mapFromGlobal(global_pos)
        return self.list_box.index_at(local.x() if self.list_box.horizontal
                                      else local.y())

    # ---- 拖动期间把滚轮借过来 ----
    def begin_drag_scroll(self) -> None:
        """装上低级鼠标钩子，让拖动时滚轮还能滚列表。

        Windows 上拖动走 OLE 的 DoDragDrop，那期间 Qt 收不到滚轮（API 级限制，
        见 ddm/mouse_hook.py）；钩子只在拖动这一下存在，松手 / 取消立刻卸掉。
        装不上就静默降级 —— 拖动本身和「贴边自动滚」都照常。
        """
        if self._wheel_hook is not None:
            return
        hook = mouse_hook.WheelHook(self._scroll_from_wheel)
        hook.start()
        self._wheel_hook = hook

    def end_drag_scroll(self) -> None:
        hook, self._wheel_hook = self._wheel_hook, None
        if hook is not None:
            hook.stop()

    def _scroll_from_wheel(self, delta: int) -> None:
        """钩子回调（主线程）：一格滚轮滚 WHEEL_PIXELS 像素。"""
        area = self.scroll
        if area is None or not delta:
            return
        box = self.list_box
        bar = area.horizontalScrollBar() if box.horizontal else area.verticalScrollBar()
        steps = delta / mouse_hook.WHEEL_DELTA            # 高精度滚轮可能是小数格
        bar.setValue(bar.value() - int(round(steps * box.WHEEL_PIXELS)))

    def hover_drag(self, room_id: str, global_pos) -> None:
        """拖动过程中：贴近边缘自动滚，并在落点让出一格。"""
        # 自动滚吃**全局坐标**（它内部按视口算边界）；落点下标要的是**内容坐标**
        # —— 以前把两者混成同一个变量，往下滚就永远触发不了。
        self.list_box.auto_scroll(global_pos)
        local = self.list_box.mapFromGlobal(global_pos)
        along = local.x() if self.list_box.horizontal else local.y()
        self.show_drop_indicator(room_id, self.list_box.index_at(along))

    def finish_drag(self, room_id: str, global_pos) -> None:
        """松手时结算：鼠标还在列表里就按落点排序，否则只把卡片放回去。"""
        self.list_box.set_scroll_dir(0)
        local = self.list_box.mapFromGlobal(global_pos)
        inside = (0 <= local.x() <= self.list_box.width()
                  and 0 <= local.y() <= self.list_box.height())
        if inside:
            for folder_id, button in self._folder_buttons.items():
                if not button.isHidden() and button.geometry().contains(local):
                    self.move_to_folder(self.dragged_room_ids(room_id), folder_id)
                    return
            along = local.x() if self.list_box.horizontal else local.y()
            self.reorder_items(self.dragged_room_ids(room_id),
                               self._full_drop_index(self.list_box.index_at(along)))
        self.list_box.relayout(animate=True)

    # ---- 拖动排序 ----
    def _full_drop_index(self, visible_index: int) -> int:
        """搜索过滤时把屏幕上的落点换算为完整列表下标。"""
        visible = self.visible_items()
        if not visible:
            return len(self._items)
        if visible_index >= len(visible):
            return self._items.index(visible[-1]) + 1
        return self._items.index(visible[max(0, visible_index)])

    def _reordered_items(self, room_ids: list[str], drop_index: int) -> list[NavItem]:
        """将选中项作为一组移动；置顶和普通项分别留在自己的区域。"""
        moving = set(room_ids)
        result = []
        groups = [[item for item in self._items if item.is_pinned == pinned
                   and self.folder_for(str(item.room.get("room_id"))) == folder["id"]]
                  for folder in self.folders for pinned in (True, False)]
        for group in groups:
            start = self._items.index(group[0]) if group else 0
            target = max(0, min(drop_index - start, len(group)))
            before = sum(str(item.room.get("room_id")) not in moving
                         for item in group[:target])
            remaining = [item for item in group
                         if str(item.room.get("room_id")) not in moving]
            selected = [item for item in group
                        if str(item.room.get("room_id")) in moving]
            result.extend(remaining[:before] + selected + remaining[before:])
        return result

    def show_drop_indicator(self, room_id: str | None, drop_index: int) -> None:
        """拖动中：选中卡片藏起来，其余卡片让出整组空位。"""
        if not room_id:
            self.list_box.relayout(animate=True)
            return
        moving = set(self.dragged_room_ids(room_id))
        items = self._reordered_items(list(moving), self._full_drop_index(drop_index))
        preview = self.folder_entries(items, moving) if self.folders else [
            None if str(item.room.get("room_id")) in moving else item
            for item in items if not item.filtered_out]
        self.list_box.relayout(animate=True, preview_order=preview, dragging_ids=moving)

    def end_drag(self) -> None:
        """拖动结束（放下或者取消）：所有卡片恢复显示并归位。"""
        self.list_box.set_scroll_dir(0)
        self.list_box.relayout(animate=True)

    def reorder_item(self, room_id: str, drop_index: int) -> bool:
        return self.reorder_items([str(room_id)], drop_index)

    def reorder_items(self, room_ids: list[str], drop_index: int) -> bool:
        """按当前顺序整体移动卡片，并立即保存自定义顺序。"""
        known = {str(item.room.get("room_id")) for item in self._items}
        if not known.intersection(room_ids):
            return False
        items = self._reordered_items(room_ids, drop_index)
        if [str(entry.room.get("room_id")) for entry in items] == \
                [str(entry.room.get("room_id")) for entry in self._items]:
            return False
        pinned_before = list(self.pinned)
        self._items = items
        self.pinned = [str(entry.room.get("room_id")) for entry in items if entry.is_pinned]
        changed_folders = {self.folder_for(rid) for rid in room_ids}
        for folder in self.folders:
            if folder["id"] in changed_folders:
                self._remember_folder_order(folder["id"])
                folder["sort"] = "custom"
        self.sort_mode = self.get_folder(follow_folders.UNCLASSIFIED)["sort"]
        self._sync_sort_menu()
        self.list_box.relayout(animate=True)
        self.refresh_strip()
        if self.pinned != pinned_before:
            self.pinChanged.emit(list(self.pinned))
        self.orderChanged.emit()
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
        self._populate_sort_menu(menu)
        menu.aboutToShow.connect(lambda: self._populate_sort_menu(menu))
        return menu

    def _populate_sort_menu(self, menu) -> None:
        menu.clear()
        for folder in self.folders:
            self.add_folder_sort_menu(menu.addMenu(folder["name"]), folder)
        menu.addSeparator()
        menu.addAction("新建文件夹…").triggered.connect(lambda: self.prompt_folder())
        menu.addAction("新建智能文件夹…").triggered.connect(lambda: self.prompt_smart_folder())

    def add_folder_sort_menu(self, menu, folder) -> None:
        group = QActionGroup(menu)
        group.setExclusive(True)
        for mode, label in self.SORT_MODES:
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(mode == folder["sort"])
            action.triggered.connect(lambda _checked=False, value=mode, fid=folder["id"]:
                                     self.set_folder_sort(fid, value))
            group.addAction(action)
        menu.addSeparator()
        menu.addAction("固定当前显示顺序").triggered.connect(
            lambda: self.freeze_current_order(folder["id"]))

    def freeze_current_order(self, folder_id=follow_folders.UNCLASSIFIED) -> None:
        """把当前看到的顺序保存为自定义顺序。"""
        self._remember_folder_order(folder_id)
        self.set_folder_sort(folder_id, "custom")

    def _remember_folder_order(self, folder_id: str) -> None:
        current = [str(item.room.get("room_id")) for item in self._items
                   if self.folder_for(str(item.room.get("room_id"))) == folder_id]
        ordered = iter(current)
        self.custom_order = [next(ordered) if rid in current else rid for rid in self.custom_order]

    def _sync_sort_menu(self) -> None:
        menu = self.sort_button.menu() if hasattr(self, "sort_button") else None
        if menu is not None:
            self._populate_sort_menu(menu)

    def set_folder_sort(self, folder_id: str, mode: str, notify=True) -> None:
        folder = self.get_folder(folder_id)
        if folder is None:
            return
        folder["sort"] = mode if mode in dict(self.SORT_MODES) else "custom"
        self.resort(animate=False)
        if notify:
            self.foldersChanged.emit()

    def set_sort_mode(self, mode: str, notify: bool = True) -> None:
        """切排序方式：自定义 / 开播优先 / 导入顺序。"""
        if mode not in dict(self.SORT_MODES):
            mode = "custom"
        self.sort_mode = mode
        self.set_folder_sort(follow_folders.UNCLASSIFIED, mode, notify=False)
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

    def resort(self, animate: bool = False, *, duration=150, revealing=()) -> None:
        """每个文件夹独立排序，置顶只作用于所在文件夹。"""
        self.sort_mode = self.get_folder(follow_folders.UNCLASSIFIED)["sort"]
        self._folder_assignments = follow_folders.assign_folders(
            self.rooms(), self.folders, self._folder_pending)
        pinned_ids = list(self.pinned)
        ordered = []
        for folder in self.folders:
            members = [item for item in self._items
                       if self.folder_for(str(item.room.get("room_id"))) == folder["id"]]
            pinned = [item for rid in pinned_ids for item in members if str(item.room.get("room_id")) == rid]
            rest = [item for item in members if str(item.room.get("room_id")) not in pinned_ids]
            order = self.import_order if folder["sort"] == "imported" else self.custom_order
            position = {rid: index for index, rid in enumerate(order)}
            def key(item):
                index = position.get(str(item.room.get("room_id")), len(position))
                if folder["sort"] in ("live", "offline"):
                    return (bool(item.room.get("live")) != (folder["sort"] == "live"), index)
                if folder["sort"] == "name":
                    return (str(item.room.get("uname") or "").casefold(), index)
                return index
            rest.sort(key=key)
            ordered.extend(pinned + rest)
        self._items = ordered
        # 先按搜索词重算谁该藏起来，再摆位置 —— 顺序反了会留下「藏起来的还占位」
        self._apply_filter_marks()
        self.list_box.relayout(animate=animate, duration=duration, revealing=revealing)
        self._sync_sort_menu()
        self._sync_count()             # 过滤时这里写成「露出来几路 / 一共几路」
        # 顺手把顶部横栏那一排头像也刷新：竖屏下它就是关注列表
        self.refresh_strip()

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
        platforms = {str(item.room.get("room_id", "")).split(":", 1)[0]
                     if ":" in str(item.room.get("room_id", "")) else "bilibili"
                     for item in self._items}
        for item in self._items:
            item.platform_badge.setProperty("showPlatform", len(platforms) > 1)
            item.platform_badge.setVisible(len(platforms) > 1 and not item.thumb.video.isVisible())
            item.thumb._layout_overlay()
        shown = len(self.visible_items())
        if self.filter_text:
            # 搜索时把「露出来几路 / 一共几路」都写上，免得以为关注丢了
            self.count_label.setText(f"关注中 · {shown} / {len(self._items)}")
        else:
            self.count_label.setText(f"关注中 · {len(self._items)}")

    def set_refreshing(self, busy: bool) -> None:
        self.refresh_button.setEnabled(True)
        self.refresh_button.set_refreshing(busy)
        self.refresh_button.setToolTip(
            "正在刷新关注列表…再次点击可排队刷新" if busy else "立刻刷新关注列表：直播状态、标题、在线人数、头像")


class Tile(QFrame):
    """一个播放格子：画面 + 底部信息条 + 独立控制。"""

    clicked = Signal(dict)
    qualityChanged = Signal(dict, int)
    muteToggled = Signal(dict, bool)
    reloadRequested = Signal(dict)
    fullscreenRequested = Signal(object)
    closeRequested = Signal(dict)
    roomDropped = Signal(str)
    tileDropped = Signal(str)          # 拖过来的来源房间号
    danmakuDropped = Signal()          # 弹幕格被拖到本格上
    volumeChanged = Signal(dict, int)
    audioChannelChanged = Signal(dict, int)
    pauseToggled = Signal(dict)
    recordingRequested = Signal()
    videoDanmakuChanged = Signal(bool)
    videoDanmakuSettingsChanged = Signal(dict)
    videoDanmakuAdvancedRequested = Signal()
    pluginMenuRequested = Signal()     # 右键菜单要弹了，请外部先把插件菜单项填好

    def __init__(self, room: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("Tile")
        #: 插件往本格右键菜单加的项目：[(显示文字, 回调), …]，由外层填
        self.plugin_actions: list = []
        #: 当前这一路的取流结果，插件（录像等）从这里拿
        self.stream_url = ""
        self.stream_profile = ""
        self.stream_headers: dict = {}
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
        self.quality = int(room.get("quality", AUTO_QUALITY
            if str(room.get("room_id", "")).partition(":")[0] in OVERSEAS_PLATFORMS else 250))
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
        self.video_danmaku = VideoDanmaku(self)

        # 信息条（在画面下方，不遮挡画面）：左侧暂停和音量，右侧录制和全屏
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
                                    WATCHING_TEXT if room.get("live") and
                                    str(room.get("room_id", "")).isdigit() else "")
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
        self.fullscreen_button = QPushButton("⛶")
        self.fullscreen_button.setObjectName("TileCtrl")
        self.fullscreen_button.setFixedSize(28, 26)
        self.fullscreen_button.setToolTip("全屏查看这一路（F）")
        self.fullscreen_button.clicked.connect(lambda: self.fullscreenRequested.emit(self))
        self.recording_button = QPushButton("● 录制")
        self.recording_button.setObjectName("TileCtrl")
        self.recording_button.setFixedSize(64, 26)
        self.recording_button.setToolTip("开始录制这一路（右键可保存即时回放）")
        self.recording_button.clicked.connect(self.recordingRequested)
        self.danmaku_button = QPushButton("弹幕")
        self.danmaku_button.setObjectName("TileCtrl")
        self.danmaku_button.setCheckable(True)
        self.danmaku_button.setFixedSize(44, 26)
        self.danmaku_button.setToolTip("启用这一路的画面弹幕；右侧齿轮可调整观看设置")
        self.danmaku_button.toggled.connect(self._toggle_video_danmaku)
        self.danmaku_button.setChecked(bool(room.get("video_danmaku_enabled", False)))
        self.danmaku_settings_button = QPushButton("⚙")
        self.danmaku_settings_button.setObjectName("TileCtrl")
        self.danmaku_settings_button.setFixedSize(26, 26)
        self.danmaku_settings_button.setToolTip("弹幕观看设置：大小、速度、不透明度、显示区域")
        self.danmaku_settings_menu = VideoDanmakuSettings(self)
        self.danmaku_settings_menu.settingsChanged.connect(self._change_video_danmaku_settings)
        self.danmaku_settings_menu.advancedRequested.connect(self.videoDanmakuAdvancedRequested)
        self.danmaku_settings_button.clicked.connect(
            lambda: self.danmaku_settings_menu.open_at(self.danmaku_settings_button, self.video_danmaku.settings))
        # 「● REC」右边显示已录制时长（app 层每秒刷一次；没在录就藏起来）
        self.recording_time = QLabel("")
        self.recording_time.setObjectName("TileTitle")
        self.recording_time.setToolTip("这一路已经录了多久")
        self.recording_time.setVisible(False)
        _ignore_mouse(self.recording_time)
        # 信息条中间：常驻状态（连接中 / 缓冲中 / 断流重连 / 已下播…）
        # 画面被 VLC 原生窗口盖住时，这里也一定看得见
        self.status_label = ElidedLabel("")
        self.status_label.setObjectName("TileStatus")
        _ignore_mouse(self.status_label)
        _allow_shrink(self.status_label)
        self.status_label.setMinimumWidth(0)

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
        bottom_layout.addWidget(self.status_label, 1)
        bottom_layout.addWidget(self.danmaku_button, 0, Qt.AlignVCenter)
        bottom_layout.addWidget(self.danmaku_settings_button, 0, Qt.AlignVCenter)
        bottom_layout.addWidget(self.recording_button, 0, Qt.AlignVCenter)
        bottom_layout.addWidget(self.recording_time, 0, Qt.AlignVCenter)
        bottom_layout.addWidget(self.fullscreen_button, 0, Qt.AlignVCenter)

        # 悬停时才出现的单窗口控制：与浮标同款样式，浮在画面右上角
        self.controls = QWidget(self)
        self.controls.setObjectName("TileControls")
        self.controls.setAttribute(Qt.WA_StyledBackground, False)
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
            button.setParent(self.controls)
        self.controls.setVisible(False)
        #: 悬停才露的浮层（LIVE 浮标 + 标题）：和控制条同一套显隐（用户要求：
        #: 「live 和人数改成和右上角悬浮按钮一样，自动消失、鼠标移上出现」）
        self._overlay_visible = False
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
        #: 悬停浮层相关的控件都建好了，之后 set_controls_visible 才能重摆布局
        self._overlay_ready = True
        self.set_recording_state("")
        if not room.get("room_id"):
            self.set_room(None)          # 空格子：显示"拖入直播间"

    # ---- 播放状态 ----
    def set_room(self, room: dict | None, cover: QPixmap | None = None) -> None:
        """换这一个格子播放的房间；音量和静音属于格子，不跟着房间移动。"""
        self.room = room or {}
        self.video_danmaku.clear()
        self.quality_options = []          # 换平台/直播间后不能沿用上一个房间的档位
        self.actual_quality = 0
        self.stream_url = ""
        self.stream_headers = {}
        self.set_recording_state("")
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
        self._sync_stream_badge()
        self._cover_source = cover if cover is not None else self.room.get("cover")
        self.title_badge.set_text(self.room.get("uname", ""), self.room.get("title", ""))
        self.title_badge.setVisible(bool(self.room.get("uname")) and self._overlay_visible)
        self._refresh_badge()
        self.quality = int(self.room.get("quality", AUTO_QUALITY
            if str(self.room.get("room_id", "")).partition(":")[0] in OVERSEAS_PLATFORMS else 250))
        # 声道和音量 / 静音一样属于**格子**，不跟着房间走：换台不该把用户调好的
        # 「只播左 / 只播右」丢掉。房间自带的那份只在第一次上墙时用（_prepare_room）。
        self.room["audio_channel"] = self.audio_channel
        self.quality_button.setText(self._quality_text())
        self.volume_slider.blockSignals(True)
        self.volume_slider.setValue(self.volume)
        self.volume_slider.blockSignals(False)
        self.volume_label.setText(str(self.volume))
        self.volume_button.set_state(self.muted, self.volume, self.audio_channel)
        self.set_status("" if self.room.get("live") else "未开播")
        self.stop_elapsed_timer()
        self._layout_cover()

    def _toggle_video_danmaku(self, enabled: bool) -> None:
        self.video_danmaku.set_enabled(enabled)
        if getattr(self, "_overlay_ready", False):
            self.raise_overlays()
        self.videoDanmakuChanged.emit(enabled)

    def _change_video_danmaku_settings(self, values: dict) -> None:
        self.video_danmaku.apply_settings({**self.video_danmaku.settings, **values})
        self.videoDanmakuSettingsChanged.emit(values)

    def _layout_bottom_controls(self) -> None:
        width = self.width()
        compact = width < 420
        layout = self.bottom.layout()
        margin, spacing = (6, 4) if compact else (10, 8)
        if width < 260:
            margin, spacing = 4, 2
        layout.setContentsMargins(margin, 4, margin, 4)
        layout.setSpacing(spacing)
        self.pause_button.setFixedWidth(26 if width < 260 else 34)
        self.danmaku_button.setFixedWidth(26 if compact else 44)
        self.danmaku_button.setText("弹" if compact else "弹幕")
        self.volume_label.setVisible(width >= 280 and
                                     (not self.recording_time.text() or width >= 480))
        self.recording_time.setVisible(bool(self.recording_time.text()) and width >= 360
                                       and getattr(self, "_recording_available", True))
        self.volume_slider.setVisible(width >= 220)
        controls = [self.pause_button, self.volume_button, self.volume_label,
                    self.danmaku_button, self.danmaku_settings_button, self.recording_button, self.recording_time,
                    self.fullscreen_button]
        visible = [widget for widget in controls if not widget.isHidden()]
        fixed = sum(widget.sizeHint().width() if widget is self.recording_time else widget.width()
                    for widget in visible)
        remaining = width - fixed - margin * 2 - spacing * (len(visible) + 1) - 8
        self.volume_slider.setFixedWidth(max(18, min(86, remaining)))
        layout.activate()

    def set_recording_state(self, state: str) -> None:
        self._recording_state = state
        self._update_recording_button()
        self.recording_button.setProperty("recording", state == "record")
        _repolish(self.recording_button)
        self.recording_button.setToolTip(
            "停止录制这一路" if state == "record" else
            "即时回放缓存中；点击开始完整录制" if state == "cache" else
            "开始录制这一路（右键可保存即时回放）")

    def set_recording_elapsed(self, text: str) -> None:
        """更新「● REC」旁边的已录制时长；空串就把标签收起来。"""
        if not hasattr(self, "recording_time"):
            return
        self.recording_time.setText(text)
        self._layout_bottom_controls()

    def set_recording_available(self, available: bool) -> None:
        """录制功能总开关：关掉时把底栏的「● 录制」按钮收起来。"""
        self._recording_available = bool(available)
        self._update_recording_button()

    def _update_recording_button(self) -> None:
        if not hasattr(self, "recording_button"):
            return
        # 录制功能总开关关掉时，整个「● 录制」按钮收起来（见 set_recording_available）。
        # 放在这里而不是 set_recording_available 里：录制状态每次变都会走这个方法，
        # 各处刷新不会把按钮又露出来。
        available = getattr(self, "_recording_available", True)
        self.recording_button.setVisible(available)
        if not available:
            self._layout_bottom_controls()
            return
        narrow = self.width() < 320
        labels = ({"record": "●", "cache": "◉", "": "●"} if narrow else
                  {"record": "● REC", "cache": "◉ 缓存", "": "● 录制"})
        self.recording_button.setFixedWidth(26 if narrow else 64)
        self.recording_button.setText(labels.get(getattr(self, "_recording_state", ""), "●"))
        self._layout_bottom_controls()

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
        """把浮层重新抬到**原生视频窗口**之上。

        画面是原生子窗口（HWND），默认压在所有 Qt 子控件上面；浮层只有也是原生
        窗口、并且被 raise 过，才既画得出来也点得到。所以每次摆完位都要再抬一次
        —— 用户报过「竖屏 1+4 里最下面两个格子的 ✕ 点不动」，就是浮层被视频盖住。
        """
        self.video_danmaku.raise_()
        for widget in (self.controls, self.stream_badge, self.title_badge,
                       self.time_badge, self.spinner, self.pause_overlay):
            widget.raise_()

    def set_video_active(self, active: bool) -> None:
        self._player_active = active
        self.video_danmaku.set_active(active)
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
        self.video_danmaku.set_paused(self.paused)
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
            self.stop_elapsed_timer()          # 右下角的时长浮标也立刻收掉
        self._refresh_badge()

    def set_uname_title(self, uname: str, title: str) -> None:
        """补上主播名/标题：启动占位后由状态刷新补齐（悬停浮标显示用）。"""
        self.room["uname"] = uname or ""
        self.room["title"] = title or ""
        self.title_badge.set_text(self.room["uname"], self.room["title"])
        self.title_badge.setVisible(bool(self.room["uname"]) and self._overlay_visible)

    def set_watched(self, watched_text: str) -> None:
        """实时在线人数（高能榜 onlineNum，和 B 站页面一致）。"""
        if watched_text:
            self.room["online"] = watched_text
        self._refresh_badge()

    def _refresh_badge(self) -> None:
        supports_count = str(self.room.get("room_id", "")).isdigit()
        watched = (self.room.get("online") or "") if supports_count else ""
        popularity = (self.room.get("viewers") or "") if supports_count else ""
        live = bool(self.room.get("live"))
        # 优先显示实时在线人数；还没拉到就别拿人气值顶上（那个数看着很像异常）
        self.stream_badge.set_state(live, watched or (WATCHING_TEXT if live and supports_count else ""))
        # 悬停才露（和控制条同步）；不然一屏好几格的 LIVE 一直挂着太吵。
        # 宽度够不够同时放下它和控制条，交给 _sync_stream_badge() 一起算
        self._sync_stream_badge()
        self._layout_areas()          # 浮标宽度会变（人数位数不同），标题要跟着重新让位
        if not supports_count:
            self.stream_badge.setToolTip("直播中" if live else "未开播")
        elif watched and popularity:
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
        if self.quality == AUTO_QUALITY:
            return "自动" + (" · " + self._quality_name(self.actual_quality, short=True)
                           if self.actual_quality else "")
        return self._quality_name(self.actual_quality or self.quality, short=True)

    def _quality_name(self, qn: int, *, short: bool = False) -> str:
        if qn == AUTO_QUALITY:
            return "自动" if short else "自动（根据网络选择流畅的最高画质）"
        for item in self.quality_options:
            if int(item.get("qn") or 0) == int(qn):
                return str((item.get("label") if short else None) or item.get("desc") or qn)
        if ":" in str(self.room.get("room_id") or ""):
            return "最高可用" if int(qn) == 10000 else "获取画质…"
        return QUALITY_NAMES.get(int(qn), f"{qn}P")

    def _quality_choices(self) -> list[tuple[str, int]]:
        """优先用接口给的档位：直播间只提供哪些，菜单里就只留哪些。"""
        if self.quality_options:
            return [(self._quality_name(int(item["qn"])), int(item["qn"]))
                    for item in self.quality_options]
        if ":" in str(self.room.get("room_id") or ""):
            return []                     # 接口返回前不展示 B 站的固定画质菜单
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
        if ":" in str(self.room.get("room_id") or ""):
            self.quality_button.setToolTip(("自动画质，当前：" if self.quality == AUTO_QUALITY else "")
                                          + self._quality_name(self.actual_quality))
        elif self.actual_quality and self.actual_quality < self.quality:
            self.quality_button.setToolTip(
                f"请求 {self._quality_name(self.quality)}，"
                f"实际 {self._quality_name(self.actual_quality)}"
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
        if getattr(self, "quality_locked", False) and value != 10000:
            return
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

    def set_fullscreen_controls_hidden(self, hidden: bool) -> None:
        self._fullscreen_controls_hidden = hidden
        self.bottom.setVisible(not hidden)
        self.set_controls_visible(not hidden)
        self._layout_areas()

    def set_controls_visible(self, visible: bool) -> None:
        visible = visible and not getattr(self, "_fullscreen_controls_hidden", False)
        visible = bool(visible)
        self.controls.setVisible(visible)
        # LIVE 浮标和标题跟着一起显隐（用户要求：别一直挂在画面上）
        self._overlay_visible = visible
        self._sync_stream_badge()
        # 右下角的直播时长和它们一样：鼠标在格子上才露出来
        self.time_badge.setVisible(self._elapsed_visible())
        if visible and getattr(self, "_overlay_ready", False):
            # 露出来之前按当前宽度重摆一遍（标题要重新让位）。
            # 构造过程中（spinner 等还没建好）不能走这里，否则会碰空控件。
            self._layout_areas()
        if visible:
            self.raise_overlays()          # 视频是原生窗口，浮层要重新抬上来
            self._round_video()            # 控制条那块从视频遮罩里挖掉
            self._controls_hide_timer.stop()
            # 显示之前先按文本把按钮宽度摆好：否则会沿用上一次的尺寸，
            # 画质文字换了之后整条控制条看起来就是错位的。
            self._layout_controls()
            self._sync_control_hover()
            self._control_hover_timer.start()
        else:
            self._control_hover_timer.stop()
            self._set_control_hover(None)
            self.title_badge.setVisible(False)   # 收起时标题一起收
            self._round_video()                  # 收起来就把视频遮罩补回圆角

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
        self._update_recording_button()
        video_height = max(60, height if getattr(self, "_fullscreen_controls_hidden", False)
                           else height - TILE_BAR_HEIGHT)
        # 留 1px 给圆角边框；视频是原生窗口，用窗口遮罩做圆角
        self.video.setGeometry(1, 1, max(1, width - 2), max(1, video_height - 1))
        self._round_video()
        video_right = self.video.width() + 1
        self.stream_badge.move(10, 8)
        self.stream_badge.raise_()
        self._layout_controls()
        # 第一行要同时站得下「LIVE 浮标」和「控制条」，控制条永远钉在右上角。
        # 以前是让控制条折到第二行去给浮标腾地方，结果它跑出了右上角、还压在
        # 画面中间的封面文字上（用户报的「竖屏格子右上角按钮错位」）。现在反过来
        # 让浮标让位：先收起人数（浮标变短），实在不够再整个收起来。
        # 浮标的宽度和显隐只由 _sync_stream_badge() 决定 —— 别在这里再写一套
        # 「if overlay: setVisible(...)」，那样 overlay 收起来时它就不受控了
        # （放不下的浮标会一直露着，压住右上角控制条）。
        self._sync_stream_badge()
        # 标题浮标紧跟在 LIVE 右边，剩下的宽度让给控制条那一行
        controls_left = (video_right - 10
                         if self.controls.y() > 20 else self.controls.x())
        title_left = self.stream_badge.x() + self.stream_badge.width() + 6
        room = max(0, controls_left - title_left - 8)
        show_title = bool(self.room.get("uname")) and room >= 110 and self._overlay_visible
        self.title_badge.setVisible(show_title)
        if show_title:
            self.title_badge.set_max_width(room)
            self.title_badge.move(title_left, 8)
            self.title_badge.raise_()
        self.time_badge.move(max(10, video_right - self.time_badge.width() - 10),
                             max(8, video_height - self.time_badge.height() - 10))
        # 摆位和显隐放在一起：重排（改窗口大小、切布局）之后状态不会走丢
        self.time_badge.setVisible(self._elapsed_visible())
        self.time_badge.raise_()
        self.spinner.move(max(0, (self.video.width() - self.spinner.width()) // 2),
                          max(8, (video_height - self.spinner.height()) // 2))
        self.spinner.raise_()
        self.pause_overlay.move(
            max(0, (self.video.width() - self.pause_overlay.width()) // 2),
            max(8, (video_height - self.pause_overlay.height()) // 2))
        self.pause_overlay.raise_()
        self.bottom.setGeometry(0, video_height, width, height - video_height)
        self.video_danmaku.setGeometry(self.video.geometry())
        self._layout_bottom_controls()
        self._layout_cover()
        # 摆完位重新抬一次浮层，并且按控制条当前位置重做视频遮罩：
        # 视频是原生窗口，压在浮层上就点不到按钮（用户报的竖屏 1+4 关不掉）
        self.raise_overlays()
        self._round_video()

    def _sync_stream_badge(self) -> bool:
        """收窄 / 显隐 LIVE 浮标，让它和右上角的控制条在同一行站得下。

        返回「浮标露出来了没有」。

        第一行右边是控制条（画质 / 重连 / 关闭）—— 它是操作入口，必须钉在右上角，
        跑掉了就点不准。所以空间不够时让浮标让位：先收起人数（`set_compact`），
        再不够就整个收起来。

        注意别再用「格子够不够宽放下浮标自己」来判定：浮标放得下、加上控制条就
        不一定放得下，那正是控制条被挤到第二行的原因。

        **可见性只在这里决定**：以前好几处各设各的（`set_room` / `_refresh_badge` /
        `set_controls_visible`），漏一处就会出现「放不下却还露着」；`_layout_areas`
        那句还带了个 `if self._overlay_visible`，overlay 收起来时干脆不设，浮标就
        一直保持默认的可见。
        """
        room = self.width() - 10 - self.controls.width() - 12 - 10
        self.stream_badge.set_compact(self.stream_badge.full_width() > room)
        visible = (self._overlay_visible and bool(self.room.get("room_id"))
                   and self.stream_badge.width() <= room)
        self.stream_badge.setVisible(visible)
        return visible

    def _round_video(self) -> None:
        """视频窗口的圆角遮罩。

        **不要**在这里挖掉控制条那一块：挖了就露出格子底色，按钮周围会出现
        一条长方形黑底（用户报过好几次的老问题，`_update_controls_mask()` 那套
        「只留按钮轮廓」的机制才是治它的）。让控制条能点到靠的是
        `raise_overlays()` 把浮层重新抬到原生视频窗口之上。
        """
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

        按文本量宽后直接摆放三个按钮，让原生窗口遮罩和按钮始终使用同一组坐标。
        原生视频窗口上的 Qt 布局可能在显示或缩放后延迟更新子按钮的位置。
        """
        # 高度统一由代码给：样式表不再写 min-height，交给布局量出来会矮一截
        self.quality_button.setFixedHeight(theme.TILE_CONTROL_HEIGHT)
        self.quality_button.setFixedWidth(self._quality_button_width())
        self.close_button.setFixedSize(theme.TILE_CONTROL_HEIGHT, theme.TILE_CONTROL_HEIGHT)
        x = 0
        for button in (self.quality_button, self.reload_button, self.close_button):
            button.move(x, 0)
            x += button.width() + 6
        width = x - 6
        self.controls.resize(width, theme.TILE_CONTROL_HEIGHT)
        video_right = self.video.width() + 1
        self.controls.move(max(10, video_right - width - 10), 8)
        self._update_controls_mask()

    def event(self, event) -> bool:
        result = super().event(event)
        if (event.type() == QEvent.DevicePixelRatioChange
                and getattr(self, "_overlay_ready", False)):
            # 等原生子窗口都切换到新屏幕比例后再重做遮罩。
            QTimer.singleShot(0, self._refresh_overlay_masks)
        return result

    def _refresh_overlay_masks(self) -> None:
        """所有原生浮层都要重新换算遮罩，文字不变时 Qt 不会自动更新它。"""
        for widget in (self.video, self.controls, self.stream_badge,
                       self.title_badge, self.time_badge):
            mask = widget.mask()
            widget.clearMask()
            if not mask.isEmpty():
                widget.setMask(mask)
        self._layout_areas()

    def _update_controls_mask(self) -> None:
        """裁掉原生控制窗口的矩形底，只留下三个圆角按钮的轮廓。"""
        scale = self.controls.devicePixelRatioF()
        if getattr(self, "_controls_mask_scale", None) != scale:
            # 跨屏后逻辑轮廓相同，Qt 会跳过 setMask，留下按旧 DPI 换算的原生区域。
            self.controls.clearMask()
        self._controls_mask_scale = scale
        region = QRegion()
        for button in (self.quality_button, self.reload_button, self.close_button):
            rect = QRectF(button.geometry())
            path = QPainterPath()
            radius = min(rect.height() / 2, theme.TILE_CONTROL_HEIGHT / 2)
            # 原生底色只能按整数区域裁切；扩张轮廓会露出圆角外的黑色底层。
            path.addRoundedRect(rect, radius, radius)
            region = region.united(QRegion(path.toFillPolygon().toPolygon()))
        if (sys.platform == "win32" and QApplication.platformName() == "windows"
                and self.controls.testAttribute(Qt.WA_NativeWindow)):
            # Let Qt paint the complete antialiased edge; clip the native backing
            # at physical-pixel resolution instead of scaling a logical region.
            paint_region = QRegion()
            for button in (self.quality_button, self.reload_button, self.close_button):
                paint_region = paint_region.united(QRegion(button.geometry()))
            self.controls.setMask(paint_region)
            if self._apply_native_controls_mask(scale):
                return
        self.controls.setMask(region)

    def _apply_native_controls_mask(self, scale: float) -> bool:
        import ctypes
        from ctypes import wintypes

        gdi32, user32 = ctypes.windll.gdi32, ctypes.windll.user32
        gdi32.CreateRectRgn.argtypes = (ctypes.c_int,) * 4
        gdi32.CreateRectRgn.restype = wintypes.HANDLE
        gdi32.CreateRoundRectRgn.argtypes = (ctypes.c_int,) * 6
        gdi32.CreateRoundRectRgn.restype = wintypes.HANDLE
        gdi32.CombineRgn.argtypes = (wintypes.HANDLE,) * 3 + (ctypes.c_int,)
        gdi32.DeleteObject.argtypes = (wintypes.HANDLE,)
        user32.SetWindowRgn.argtypes = (wintypes.HWND, wintypes.HANDLE, wintypes.BOOL)
        region = gdi32.CreateRectRgn(0, 0, 0, 0)
        if not region:
            return False
        try:
            for button in (self.quality_button, self.reload_button, self.close_button):
                rect = button.geometry()
                diameter = round(rect.height() * scale)
                part = gdi32.CreateRoundRectRgn(
                    round(rect.x() * scale), round(rect.y() * scale),
                    round((rect.x() + rect.width()) * scale),
                    round((rect.y() + rect.height()) * scale), diameter, diameter)
                if not part:
                    return False
                try:
                    if not gdi32.CombineRgn(region, region, part, 2):  # RGN_OR
                        return False
                finally:
                    gdi32.DeleteObject(part)
            if user32.SetWindowRgn(int(self.controls.winId()), region, True):
                region = None          # Windows owns the successfully assigned region.
                return True
            return False
        finally:
            if region:
                gdi32.DeleteObject(region)

    def showEvent(self, event) -> None:
        # 需要在窗口真正显示之后再设为原生窗口，否则 Qt 会抱怨不是顶层窗口
        super().showEvent(event)
        for widget in (self.stream_badge, self.title_badge,
                       self.time_badge, self.controls,
                       self.spinner, self.pause_overlay):
            if not widget.testAttribute(Qt.WA_NativeWindow):
                widget.setAttribute(Qt.WA_NativeWindow, True)
            widget.raise_()
        self._update_controls_mask()

    # ---- 直播时长 ----
    def _elapsed_visible(self) -> bool:
        """直播时长浮标该不该露出来。

        用户要求：它和 LIVE 浮标、标题、控制条一样**自动隐藏** —— 鼠标在格子上
        才露，移开就跟着一起收（以前是只要在播就一直挂在右下角）。
        """
        return bool(self._overlay_visible
                    and getattr(self, "_elapsed_timer", None) is not None
                    and self._elapsed_timer.isActive()
                    and self.room.get("live")
                    and self.room.get("live_start_ts"))

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
        self.time_badge.setVisible(self._elapsed_visible())

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
        # 插件要先把自己那一组菜单项登记进来（本体不认识它们）
        self.pluginMenuRequested.emit()
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
        menu.addAction("全屏查看", lambda: self.fullscreenRequested.emit(self))
        if self.plugin_actions:
            # 插件加的一项占一行；组与组之间用分隔线断开，免得和本体的项混在一起
            menu.addSeparator()
            for label, callback in self.plugin_actions:
                menu.addAction(label, callback)
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

    def sync_audio_ui(self) -> None:
        """按自己的 volume / muted / audio_channel 重画音量条（不发信号）。

        「秒切」把音量 / 静音 / 声道在对调的两个格子之间换了位，但只改了
        ``self.volume`` 这几个值、没重画控件 —— 用户看到的就是「音量条跟着画面
        跑过去，跟实际听到的声音对不上」。
        """
        if self.volume_slider.value() != self.volume:
            self.volume_slider.blockSignals(True)
            self.volume_slider.setValue(self.volume)
            self.volume_slider.blockSignals(False)
        self.volume_label.setText(str(self.volume))
        self.volume_button.set_state(self.muted, self.volume, self.audio_channel)
        self._layout_controls()

    def set_audio_channel(self, value: int) -> None:
        if self.muted:
            self.set_muted(False)
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
    tileCreated = Signal(object)
    roomDropped = Signal(object, str)      # 目标格子, 房间号
    tileSwapped = Signal(str, object)      # 来源房间号, 目标格子

    def __init__(self, rooms: list[dict], layout_id: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("WallGrid")
        # 老配置里可能存着已经删掉的布局，回落到自动布局
        self.layout_id = layout_id if layout_id in layouts.BY_ID else layouts.DEFAULT_LAYOUT
        self.tiles: list[Tile] = []
        self.fullscreen_tile: Tile | None = None
        #: 退出全屏时「布局先算好、格子分批露面」用的状态（见 reveal_tiles_staggered）
        self._defer_show = False
        self._pending_reveal: list[Tile] = []
        self._stagger_first: Tile | None = None
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

    def set_layout(self, layout_id: str, *, relayout: bool = True) -> None:
        if layout_id == self.layout_id:
            return
        self.layout_id = layout_id
        self._danmaku_cell = layouts.danmaku_cell(layout_id)
        self._columns = -1
        self._last_height = 0
        if relayout:
            self.relayout(force=True)

    def set_fullscreen_tile(self, tile: Tile | None, *, stagger: bool = False,
                            first: Tile | None = None) -> None:
        """临时只显示一个格子，保持原布局和格子顺序。

        ``stagger=True``（退出全屏时用）只把布局算好，**不立刻显示**其余格子，
        它们交给 :meth:`reveal_tiles_staggered` 分批露面；``first`` 指定的那个
        格子仍然马上显示（用户刚从那格退出来，视线在它身上）。

        为什么要拆：一次把 9 个格子的 VLC 原生窗口全重配，4K 上实测约 190 ms，
        期间主线程完全僵住 —— 盖在上面的过渡图也就跟着"冻"在原地，看起来就是
        卡住再突然一跳。拆成几帧之后，帧与帧之间事件循环能跑，过渡图才淡得动。
        """
        self._relayout_timer.stop()
        self._defer_show = bool(stagger)
        self._pending_reveal = []
        self._stagger_first = first
        self.fullscreen_tile = tile
        margin = 0 if tile else 16
        self.grid.setContentsMargins(margin, margin, margin, margin)
        self.relayout(force=True)

    def reveal_tiles_staggered(self, chunk: int = 2) -> None:
        """把「布局算好了但还没露面」的格子分批显示，每批一帧。

        每批只放两格：4K 下单格 VLC 原生窗口重配约 23 ms（实测 9 格一起做是
        190 ms 上下），一批两格就是约 46 ms —— 差不多三帧，是可感知的上限；
        再大就又开始"僵住"。

        批次之间用 `singleShot(0)` 让出事件循环：一来下一批要等这一批的窗口
        重配落地，二来让遮盖图的淡出动画有机会推进（连着做完主线程一样是僵的，
        那就白拆了）。代价是"分批期间格子还没全部可见"，所以调用方如果要立刻
        读可见性，得先让事件循环跑完。
        """
        if not self._pending_reveal:
            self._defer_show = False
            return
        batch, rest = self._pending_reveal[:chunk], self._pending_reveal[chunk:]
        self._pending_reveal = rest
        for tile in batch:
            tile.setVisible(True)
        if rest:
            QTimer.singleShot(0, lambda: self.reveal_tiles_staggered(chunk))
        else:
            self._defer_show = False

    def remove_room(self, room: dict) -> None:
        room_id = str(room.get("room_id") or "")
        tile = next((item for item in self.tiles
                     if room_id and str(item.room.get("room_id") or "") == room_id), None)
        if tile is None:
            return
        tile.set_room(None)

    def add_room(self, room: dict) -> Tile:
        tile = self._make_tile(room)
        self.relayout(force=True)
        return tile

    def _make_tile(self, room: dict) -> Tile:
        # 竖屏布局是手动 setGeometry，不经过 QGridLayout 的 addWidget；
        # 先挂到画面墙，新增空格才不会在 setVisible() 时变成顶层悬浮窗。
        tile = Tile(room, self)
        tile.clicked.connect(self.tileClicked.emit)
        tile.roomDropped.connect(lambda rid, t=tile: self.roomDropped.emit(t, rid))
        tile.tileDropped.connect(lambda rid, t=tile: self.tileSwapped.emit(rid, t))
        tile.danmakuDropped.connect(lambda t=tile: self.move_danmaku_to_tile(t))
        self.tiles.append(tile)
        self.tileCreated.emit(tile)
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
        if force:
            self._relayout_timer.stop()
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

        if self.fullscreen_tile is not None:
            self.danmaku.setVisible(False)
            for tile in self.tiles:
                if tile is self.fullscreen_tile:
                    self.grid.addWidget(tile, 0, 0)
                    tile.setVisible(True)
                else:
                    tile.setVisible(False)
            self.grid.setColumnStretch(0, 1)
            self.grid.setRowStretch(0, 1)
            return

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
        if layouts.is_portrait_layout(self.layout_id):
            self._relayout_portrait(rows, columns, cells)
            return
        order = self._cell_order()
        for index, tile in enumerate(self.tiles):
            if index < len(order):
                row, column, rowspan, colspan = cells[order[index]]
                self.grid.addWidget(tile, row, column, rowspan, colspan)
                if self._defer_show and tile is not self._stagger_first:
                    self._pending_reveal.append(tile)      # 交给 reveal_tiles_staggered
                else:
                    tile.setVisible(True)
            else:
                # 布局严格按格子数走，放不下的由主窗口停止播放。
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

    # ---- 竖屏摆放 ----
    def _relayout_portrait(self, rows: int, columns: int, cells: list) -> None:
        """竖屏：主画面按 16:9 固定高度，其余格子用自动网格填满剩下的空间。

        为什么不用等分网格：竖屏里主画面要 16:9（占整宽时高度 = 宽 × 9/16），
        小画面也要接近 16:9；等分网格只能满足一个 —— 主画面占整宽 1 行时，
        小格子会被拉成 0.8 左右的竖条，画面缩成中间一条。这里改成手动摆。
        """
        margin = self.grid.contentsMargins()
        spacing = self.grid.spacing()
        # 竖屏是自己算坐标摆的，先把格子从网格布局里摘出来，否则布局会覆盖几何。
        # removeWidget 只是解除管理，不改变父子关系，可以安全地再 addWidget 回去。
        for tile in self.tiles:
            self.grid.removeWidget(tile)
        self.grid.removeWidget(self.danmaku)
        for index in range(24):
            self.grid.setColumnStretch(index, 0)
            self.grid.setRowStretch(index, 0)

        left = margin.left()
        top = margin.top()
        width = max(1, self.width() - margin.left() - margin.right())
        height = max(1, self.height() - margin.top() - margin.bottom())

        # 弹幕：最底下整宽一条，先把它和主画面的高度扣掉
        danmaku_height = 0
        if self.has_danmaku:
            danmaku_height = max(140, int(height * 0.22))
            self.danmaku.setGeometry(
                QRect(left, top + height - danmaku_height, width, danmaku_height))
            self.danmaku.setVisible(True)
            self.danmaku.raise_()
            danmaku_height += spacing
        else:
            self.danmaku.setVisible(False)

        main = self.tiles[0] if self.tiles else None
        rest = self.tiles[1:]
        available = height - danmaku_height

        if main is None:
            self._columns = columns
            return

        # 主画面：整宽 + 16:9。**不给它加上限** —— 它是主角，先满足它；
        # 小画面去适应剩下的高度（挤不下就矮一点，也比主画面变形好）。
        main_height = max(80, int(width * 9 / 16))
        main.setGeometry(QRect(left, top, width, main_height))
        main.setVisible(True)

        grid_top = top + main_height + spacing
        grid_height = max(1, top + available - grid_top)
        for index, tile in enumerate(rest):
            if index < self._portrait_capacity() - 1:
                tile.setVisible(True)
            else:
                tile.setVisible(False)
        visible = [tile for tile in rest if tile.isVisible()]
        # 小画面的列数**跟缩略图画的是同一个数**。交给 best_columns 自己挑的话，
        # 竖屏这块又高又窄的区域在它眼里「1 列画面更大」，就会摆成上下，和缩略图
        # （左右）对不上 —— 用户报的就是这个。
        self._place_auto(visible, QRect(left, grid_top, width, grid_height), spacing,
                         columns=layouts.PORTRAIT_SMALL_COLUMNS)
        self._columns = columns

    def _portrait_capacity(self) -> int:
        return max(1, len(self._cell_order()))

    def _place_auto(self, tiles: list, area: QRect, spacing: int,
                    columns: int | None = None) -> None:
        """在一个矩形里按网格摆这些格子。

        ``columns`` 给了就照用（竖屏小画面要跟缩略图一致）；没给才让
        ``best_columns`` 挑一个「画面尽量大」的列数。
        """
        if not tiles:
            return
        if columns is None:
            columns = best_columns(len(tiles), max(area.width(), 1), max(area.height(), 1))
        columns = max(1, min(int(columns), len(tiles)))
        lines = math.ceil(len(tiles) / columns)
        cell_width = (area.width() - spacing * (columns - 1)) / columns
        cell_height = (area.height() - spacing * (lines - 1)) / lines
        for index, tile in enumerate(tiles):
            line, column = divmod(index, columns)
            tile.setGeometry(QRect(
                int(area.left() + column * (cell_width + spacing)),
                int(area.top() + line * (cell_height + spacing)),
                int(cell_width), int(cell_height)))


    def visible_tiles(self) -> list[Tile]:
        return [tile for tile in self.tiles if tile.isVisible()]

    def hidden_count(self) -> int:
        return sum(1 for tile in self.tiles if not tile.isVisible())

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        # 自动布局和竖屏布局都是按当前尺寸算坐标的，尺寸变了必须重排；
        # 固定行列的布局由 Qt 自己按 stretch 摆，不用管。
        if self.fullscreen_tile is None and (self.layout_id == "auto" or
                                             layouts.is_portrait_layout(self.layout_id)):
            self._relayout_timer.start()


class LayoutPicker(QFrame):
    """布局选择弹层：顶上按钮切组，下面是缩略图卡片。

    只列**当前方向能用**的布局：横屏不给竖屏预设、竖屏不给横屏预设 —— 两套摆放
    规则不一样，套错方向画面会被压变形（用户报的）。组里带 ``section`` 的布局
    表示换一段，上面插一行小标题（用户要求把平分布局和大带小布局分开）。
    """

    chosen = Signal(str)

    #: 一行摆几张卡片
    COLUMNS = 4
    #: 卡片图标尺寸（所有卡片统一，否则格子会错开）
    _icon_size = QSize(52, 34)
    #: 卡片最小宽度（名字都很短时也别挤成一条）
    _min_card_width = 108

    def __init__(self, current: str, parent=None, portrait: bool = False):
        super().__init__(parent, Qt.Popup)
        self.setObjectName("LayoutPicker")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._cards: dict[str, list[QToolButton]] = {}
        self._sections: dict[str, list[QLabel]] = {}

        # 两组都列出来（横屏也能点竖屏预设）：选中另一个方向的预设时，本体
        # 会把**窗口**也改成那个方向（见 MainWindow._on_layout_changed /
        # _reshape_window），所以不会再出现「竖屏排布塞在横屏窗口里被压扁」。
        # 用户要的「切成竖屏后 alt+tab 的窗口预览也是竖的」就是靠这条路。
        groups = [(name, group) for name, group in layouts.GROUPS if group]
        if not groups:                       # 兜底：一张都没有就照旧全列
            groups = list(layouts.GROUPS)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)

        self._tabs: dict[str, QPushButton] = {}
        if len(groups) > 1:                  # 只剩一组时不用摆标签栏
            tabs = QHBoxLayout()
            tabs.setSpacing(6)
            for name, _group in groups:
                button = QPushButton(name)
                button.setObjectName("PickerTab")
                button.setFocusPolicy(Qt.TabFocus)
                button.setCheckable(True)
                button.setCursor(Qt.PointingHandCursor)
                button.clicked.connect(
                    lambda _checked=False, key=name: self.set_group(key))
                tabs.addWidget(button)
                self._tabs[name] = button
            tabs.addStretch(1)
            outer.addLayout(tabs)

        self._grid = QGridLayout()
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(6)
        outer.addLayout(self._grid)
        outer.addStretch(1)          # 各组行数不同，多出来的高度留在下面

        active = groups[0][0]
        for name, group in groups:
            cards: list[QToolButton] = []
            sections: list[QLabel] = []
            row, column, current_section = 0, 0, None
            for layout in group:
                section = layout.get("section")
                if section and section != current_section:
                    if column:              # 上一段没排满也换行
                        row, column = row + 1, 0
                    heading = QLabel(section)
                    heading.setObjectName("SectionLabel")
                    self._grid.addWidget(heading, row, 0, 1, self.COLUMNS)
                    sections.append(heading)
                    current_section = section
                    row += 1
                button = QToolButton(self)
                button.setObjectName("LayoutCard")
                button.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
                button.setIcon(QIcon(layouts.thumbnail(layout["spec"],
                                                       danmaku=layout.get("danmaku"))))
                button.setIconSize(self._icon_size)
                button.setText(layout["name"])
                button.setCheckable(True)
                button.setChecked(layout["id"] == current)
                button.setProperty("layoutId", layout["id"])
                button.setToolTip(layout.get("hint") or layout["name"])
                button.setCursor(Qt.PointingHandCursor)
                button.clicked.connect(
                    lambda _checked=False, lid=layout["id"]: self._choose(lid))
                self._grid.addWidget(button, row, column)
                cards.append(button)
                column += 1
                if column >= self.COLUMNS:
                    row, column = row + 1, 0
            self._cards[name] = cards
            self._sections[name] = sections
            if any(item["id"] == current for item in group):
                active = name
        self._even_cards()
        self.set_group(active)
        self._lock_size()

    def _even_cards(self) -> None:
        """把所有卡片做成一样大 —— 名字长短不一，不统一就会出现「大小不一样、
        上下没对齐」（用户报的）。宽度按最长的名字算，高度按图标 + 一行文字算。"""
        cards = [card for group in self._cards.values() for card in group]
        if not cards:
            return
        metrics = QFontMetrics(self.font())
        label = max(metrics.horizontalAdvance(card.text()) for card in cards)
        height = (self._icon_size.height() + metrics.height() + 14)
        self._card_size = QSize(max(self._min_card_width, label + 18), height)
        for card in cards:
            card.setFixedSize(self._card_size)
            card.setIconSize(self._icon_size)

    def set_group(self, name: str) -> None:
        """切到某一组布局（普通 / 弹幕 / 竖屏）。"""
        if name not in self._cards:
            return
        for key, button in self._tabs.items():
            button.setChecked(key == name)
            _repolish(button)
        for key, cards in self._cards.items():
            for card in cards:
                card.setVisible(key == name)
        for key, headings in self._sections.items():
            for heading in headings:
                heading.setVisible(key == name)
        self._group = name
        self.adjustSize()
        # 宽度固定（右边对齐布局按钮），高度跟着这一组卡片走
        self.resize(getattr(self, "_width", self.width()), self.sizeHint().height())

    def group(self) -> str:
        return getattr(self, "_group", next(iter(self._cards)))

    def card_ids(self) -> list:
        """当前这一栏里列出来的布局 id（自检用来确认没把别方向的预设列出来）。"""
        return [card.property("layoutId") for card in self._cards.get(self.group(), [])]

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

