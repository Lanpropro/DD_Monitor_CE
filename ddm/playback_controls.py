"""Playback buttons and popup; playback state and native surfaces stay with the host."""
import math

from PySide6.QtCore import QAbstractAnimation, QEasingCurve, QPointF, QRectF, Qt, Signal, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QFrame, QPushButton, QStyle, QStyleOption, QStyleOptionButton

from . import motion, theme
from .config import DEFAULT_VOLUME


class TileButton(QPushButton):
    def focusInEvent(self, event):
        self._keyboard_focus = event.reason() in (Qt.TabFocusReason, Qt.BacktabFocusReason)
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event):
        self._keyboard_focus = False
        super().focusOutEvent(event)
        self.update()

    def mousePressEvent(self, event):
        self._keyboard_focus = False
        super().mousePressEvent(event)
        self.update()

    def paintEvent(self, event):
        if not self.property('tileButton'):
            return super().paintEvent(event)
        option = QStyleOptionButton()
        self.initStyleOption(option)
        painter = QPainter(self)
        self._paint_button(painter, option)

    def _paint_button(self, painter, option):
        focused = self.hasFocus() and getattr(self, '_keyboard_focus', False)
        option.state &= ~QStyle.State_HasFocus
        frame = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        radius = min(9.0, frame.height() / 2)
        painter.save()
        if focused:
            clip = QPainterPath()
            clip.addRoundedRect(frame.adjusted(1, 1, -1, -1), max(0, radius - 1), max(0, radius - 1))
            painter.setClipPath(clip)
        self.style().drawPrimitive(QStyle.PE_Widget, option, painter, self)
        painter.restore()
        self.style().drawControl(QStyle.CE_PushButtonLabel, option, painter, self)
        if focused:
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setPen(QPen(QColor('#ffffff'), 1.2))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(frame, radius, radius)


class VolumeButton(TileButton):
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
        self.level = DEFAULT_VOLUME
        self.audio_channel = 0
        self.compact_popup = False
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
        action = "点击取消静音" if self.muted else "点击静音"
        if self.compact_popup:
            action += "，悬停展开音量"
        self.setToolTip(f"{state}{channel}　（{action}，滚轮调音量，右键调声道）")

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
        color = (theme.qcolor(theme.TEXT3 if self.muted else theme.TEXT1)
                 if theme.is_light() and not self.property('fullscreen')
                 else QColor("#9499a0" if self.muted else "#f1f2f3"))
        if self.underMouse():
            color = QColor(theme.ACCENT)
        pen = QPen(color, 1.7)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        center = QRectF(self.rect()).center()
        # Center the speaker and its right-hand indicator as a single icon.
        left = center.x() - 11
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
            cross = QPointF(left + 17, center.y())
            painter.drawLine(cross + QPointF(-3.5, -3.5), cross + QPointF(3.5, 3.5))
            painter.drawLine(cross + QPointF(-3.5, 3.5), cross + QPointF(3.5, -3.5))
        else:
            self._paint_channel(painter, top, left)

    def _paint_channel(self, painter: QPainter, top: float, left: float) -> None:
        """在喇叭右边标出当前声道：L / R，选中的那一路更亮。"""
        font = QFont(theme.FONT_DEFAULT)
        font.setPixelSize(8)
        font.setBold(True)
        for label, x, selected in (
            ("L", left + 14.75, self.audio_channel in (0, self.CHANNEL_LEFT)),
            ("R", left + 20.25, self.audio_channel in (0, self.CHANNEL_RIGHT)),
        ):
            if selected:
                colour = QColor(theme.ACCENT)
            else:
                colour = QColor("#9499a0" if self.muted else "#6d737d")
                colour.setAlpha(150)
            # Center the visible glyph outline, avoiding font baseline/hinting
            # offsets that put these tiny capitals above or below the speaker.
            glyph = QPainterPath()
            glyph.addText(QPointF(), font, label)
            bounds = glyph.boundingRect()
            glyph.translate(x - bounds.center().x(), top + 6 - bounds.center().y())
            painter.fillPath(glyph, colour)



class VolumePopup(QFrame):
    def paintEvent(self, event) -> None:
        # Paint the styled background explicitly for this translucent tool window.
        option = QStyleOption()
        option.initFrom(self)
        painter = QPainter(self)
        self.style().drawPrimitive(QStyle.PE_Widget, option, painter, self)


class RecordingButton(TileButton):
    def paintEvent(self, event):
        if not self.property('replayOnly'):
            return super().paintEvent(event)
        option = QStyleOptionButton()
        self.initStyleOption(option)
        option.text = ''
        option.icon = QIcon()
        painter = QPainter(self)
        if self.property('tileButton'):
            self._paint_button(painter, option)
        else:
            self.style().drawControl(QStyle.CE_PushButton, option, painter, self)
        painter.setPen(QColor(theme.ACCENT))
        painter.setFont(self.font())
        painter.drawText(self.rect(), Qt.AlignCenter, self.text())


def _icon_color(button: QPushButton, hover_dark: bool = True) -> QColor:
    """图标颜色：平时浅色；悬停时按钮底变成主题色，图标要反过来用深色。"""
    if button.property('fullscreen'):
        return QColor('#ffffff')
    if button.underMouse() or button.property("hovered") is True:
        return QColor("#04161f") if hover_dark else QColor(theme.ACCENT)
    if theme.is_light() and (button.objectName() in ("ChipButton", "BarIcon")
                            or button.objectName() == "TileCtrl"):
        return theme.qcolor(theme.TEXT2)
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


class PauseButton(TileButton):
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
        center = QRectF(self.rect()).center()
        if self.paused:
            # ▶ 继续
            path = QPainterPath()
            path.moveTo(center.x() - 10 / 3, center.y() - 6)
            path.lineTo(center.x() + 20 / 3, center.y())
            path.lineTo(center.x() - 10 / 3, center.y() + 6)
            path.closeSubpath()
            painter.drawPath(path)
        else:
            # ⏸ 暂停
            painter.drawRoundedRect(
                QRectF(center.x() - 5.2, center.y() - 6, 3.6, 12), 1.3, 1.3)
            painter.drawRoundedRect(
                QRectF(center.x() + 1.6, center.y() - 6, 3.6, 12), 1.3, 1.3)


class RefreshButton(TileButton):
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


class DanmakuToggleButton(TileButton):
    """画面弹幕开关：开启时在右下角画一个勾（和 B 站播放器一样），不靠整块底色区分。"""

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if not self.isChecked():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        pen = QPen(QColor(theme.ACCENT), 1.8)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        x = self.width() - 10.5
        y = self.height() - 8.0
        path = QPainterPath()
        path.moveTo(x, y)
        path.lineTo(x + 2.6, y + 2.6)
        path.lineTo(x + 6.0, y - 3.6)
        painter.drawPath(path)


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
