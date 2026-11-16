"""Live alert implementation; shared sidebar state stays with its owner."""
from PySide6.QtCore import QPointF, QRectF, QTimer, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget
from . import theme
from .corner_geometry import continuous_path
from .widget_support import NAV_ITEM_HEIGHT


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
            painter.drawPath(continuous_path(self._badge.adjusted(-grow, -grow, grow, grow), 8.0))
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
        path.addPath(continuous_path(body, 9.0))
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
