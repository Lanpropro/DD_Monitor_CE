"""Follow cards, folders and their list layout; sidebar coordination stays separate."""
import os
import time
from PySide6.QtCore import (
    QEasingCurve, QMimeData, QPoint, QPointF, QPropertyAnimation, QRect, QRectF, QSize, QTimer,
    Qt, Signal
)
from PySide6.QtGui import (
    QColor, QCursor, QFont, QFontMetrics, QIcon, QLinearGradient, QPainter, QPainterPath, QPen,
    QPixmap, QRegion
)
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QFrame, QHBoxLayout, QLabel, QMenu, QScrollArea, QSizePolicy,
    QWidget
)

from shiboken6 import isValid

from . import motion, theme
from .avatar_widgets import Avatar
from .corner_geometry import continuous_path
from .player import TilePlayer
from .sidebar_drag import FOLDER_MIME, NAV_MIME, ROOM_MIME
from .ui.labels import ElidedLabel
from .widget_support import (
    BRAND_ASSETS_DIR, CAROUSEL_WIDTH, NAV_COMPACT_ITEM_HEIGHT, NAV_ITEM_GAP, NAV_ITEM_HEIGHT,
    NAV_LIST_ITEM_HEIGHT, PORTRAIT_LIST_HEIGHT, PORTRAIT_LIST_WIDTH, _allow_shrink, _ignore_mouse,
    _repolish
)


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
        self._cover_dirty = False
        self._cover_hold = False         # 布局切换期间挂起封面重裁，见 set_cover_hold()
        self._cover_source: QPixmap | None = None
        self._banner_source: QPixmap | None = None
        self._compact_background = True
        self._face_source: QPixmap | None = None

    # ---- 外观 ----
    def set_overlay_widgets(self, name: QWidget, title: QWidget, badge: QWidget,
                            platform: QWidget) -> None:
        self._overlay_widgets = (name, title, badge, platform)
        for widget in self._overlay_widgets:
            widget.setParent(self.face.parentWidget() if widget is platform else self)
            widget.raise_()
        self.face.raise_()
        platform.raise_()
        self._layout_overlay()

    def _layout_overlay(self) -> None:
        if self._overlay_widgets is None:
            return
        name, title, badge, platform = self._overlay_widgets
        card = self.parentWidget()
        if hasattr(card, '_layout_selection_marker'):
            card._layout_selection_marker()
        compact = self._compact_thumb()
        platform.setVisible(not self.video.isVisible() and
                            platform.property("showPlatform") is not False)
        icon_size = QSize(14, 14) if compact else QSize(24, 22)
        if platform.size() != icon_size:
            platform.setFixedSize(icon_size)
            platform.setPixmap(platform.icon.pixmap(12 if compact else 20, 12 if compact else 20))
        if compact:
            platform.move(self.face.pos() + QPoint(0, max(0, self.face.height() - platform.height())))
            platform.setVisible(platform.property("showPlatform") is not False)
            platform.raise_()
            return
        width, height = self._size
        platform_pos = QPoint(8 if self._card_mode and not self._portrait_strip else
                              max(4, width - platform.width() - 8),
                              height - 24 if self._card_mode and not self._portrait_strip else 4)
        if getattr(card, 'select_mode', False) and (not self._card_mode or self._portrait_strip):
            platform_pos.setX(max(4, platform_pos.x() - 28))
        platform.move(self.mapTo(platform.parentWidget(), platform_pos))
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
        name_right = right + (28 if getattr(card, 'select_mode', False) else 0)
        name_y = 7 if self._card_mode else 3
        second_y = 29 if self._card_mode else 25
        badge_y = (height - 24) if self._card_mode else (second_y + 1)
        name.setGeometry(text_left, name_y,
                         max(0, width - text_left - name_right -
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

    def set_banner(self, pixmap) -> None:
        self._banner_source = None if pixmap is None or pixmap.isNull() else pixmap
        if not self._card_mode:
            self._render_cover()

    def set_compact_background(self, enabled: bool) -> None:
        self._compact_background = bool(enabled)
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
        pixmap = self._face_source
        if pixmap is not None and not pixmap.isNull():
            # 尺寸和图片一次更新，圆形裁切与圆环只绘制一遍。
            self.face.set_pixmap_image(pixmap, size=size, ring=True)
        else:
            # 还没下到头像：用名字首字顶着，别让条目空着
            self.face.set_size(size)
            self.face.setText(self._face_letter())
            self.face.set_color(None)
        self._place_face()
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

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        self._place_face()               # 缩略图被布局挪动时，头像要跟着走
        if self._overlay_widgets is not None:
            platform = self._overlay_widgets[3]
            platform.move(platform.pos() + event.pos() - event.oldPos())

    def refresh_cover(self) -> None:
        """按收起/展开后的最终尺寸重裁封面。"""
        self._render_cover()

    def set_cover_hold(self, hold: bool) -> None:
        """切换布局时暂缓封面重裁，最终尺寸确定后只补可见条目。"""
        hold = bool(hold)
        if hold == self._cover_hold:
            return
        self._cover_hold = hold
        self._cover_dirty = True
        try:
            self.cover.setScaledContents(hold)
        except RuntimeError:                    # 控件已经被回收
            return
        # 解除挂起时**不在这里**重绘：由调用方决定哪些条目值得立刻补
        # （见 Sidebar._finish_collapse）—— 36 条一起补会把收尾那一下又拖垮。
        # 没补到的条目滚进视野时由 paintEvent 补裁，不依赖滚动时出现 resizeEvent。

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

    def paintEvent(self, event) -> None:
        if self._cover_dirty and not self._cover_hold:
            self._render_cover()
        super().paintEvent(event)

    def _render_cover(self) -> None:
        """把封面裁成圆角，并加深色渐变供叠加文字阅读。"""
        if self._cover_hold:
            return                       # 布局切换期间不重裁，见 set_cover_hold()
        if self._compact_thumb():
            return                       # 收起后封面隐藏，展开时再裁切即可
        source = getattr(self, "_cover_source", None)
        if not self._card_mode and self._banner_source is not None:
            source = self._banner_source
        if not self._card_mode and not self._compact_background:
            source = None
        has_background = source is not None and not source.isNull()
        if self._overlay_widgets is not None:
            for label in self._overlay_widgets[:2]:
                if label.property('roomBackdrop') != has_background:
                    label.setProperty('roomBackdrop', has_background)
                    _repolish(label)
        self.cover.setVisible(has_background and not self._compact)
        if source is None or source.isNull():
            return
        if self.visibleRegion().isEmpty():
            self._cover_dirty = True
            return
        self._cover_dirty = False
        width, height = self._size
        from .cover_focus import source_rect
        crop = source_rect(source, width, height,
                           focus=self._card_mode or self._banner_source is None)
        canvas = QPixmap(width, height)
        canvas.fill(Qt.transparent)
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        path = QPainterPath()
        path.addPath(continuous_path(QRectF(0, 0, width, height), self.RADIUS))
        painter.setClipPath(path)
        painter.drawPixmap(QRectF(0, 0, width, height), source, crop)
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
        self.cover.setVisible(not self._compact)
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
        self.cover.setVisible(not compact)
        self._render_face()          # 可见性也归它管（见 _render_face）
        self._render_cover()
        self._layout_overlay()

    # ---- 预览播放 ----
    def _ensure_player(self) -> TilePlayer:
        """复用卡片的静音播放器，禁用音轨。"""
        if self._player is None:
            self._player = TilePlayer(self.video, self, silent=True)
            self._player.freeze_watch = False        # 缩略图不用卡死检测
            self._player.stateChanged.connect(self._on_player_state)
        return self._player

    def prepare_preview(self) -> None:
        """在取流期间准备播放器，封面继续显示。"""
        if self._card_mode and not self._compact_thumb():
            self._ensure_player().bind()

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
        if self._player is None and self.video.isHidden() and self.hint.isHidden():
            return
        if self._player is not None:
            self._player.stop()
        self.video.setVisible(False)
        self.hint.setVisible(False)
        self.video.setGeometry(self.rect())
        self.hint.setGeometry(self.rect())
        self.cover.setVisible(not self._compact_thumb() and
                              (self._card_mode or self._compact_background))
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


class NavSelectionCheck(QCheckBox):
    """卡片右上角的选择位，保留复选框的键盘和无障碍行为。"""

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor('#ffffff'), 1.5) if not self.isChecked() else Qt.NoPen)
        painter.setBrush(theme.qcolor(theme.ACCENT) if self.isChecked() else QColor(12, 15, 20, 170))
        painter.drawEllipse(QRectF(4, 4, 20, 20))

    def hitButton(self, pos):
        return self.rect().contains(pos)


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

        self.check = NavSelectionCheck(self)
        self.check.setObjectName("NavCheck")
        self.check.setFixedSize(28, 28)
        self.check.setAccessibleName("选择直播间")
        self.check.setVisible(False)
        self.check.clicked.connect(lambda: self.checkedChanged.emit())

        self.thumb = NavThumb(self)
        from .images import load_room_banner
        from .room_artwork import supports_banner
        if supports_banner(room):
            self.thumb.set_banner(load_room_banner(str(room.get('room_id', ''))))
        self.check.setParent(self.thumb)
        self._layout.addWidget(self.thumb, 1)

        # 收起关注栏时不再有文字徽标，用头像右下角的小圆点提示正在直播。
        self.live_dot = QWidget(self.thumb.face)
        self.live_dot.setObjectName("NavLiveDot")
        self.live_dot.setAttribute(Qt.WA_StyledBackground, True)
        self.live_dot.setFixedSize(12, 12)
        # Avatar 会用内联样式切换占位色/透明背景；圆点也用内联样式，避免被父级覆盖。
        self.live_dot.setStyleSheet(
            f"background: {theme.PINK}; border: 2px solid palette(alternate-base); border-radius: 6px;")
        self.live_dot.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.live_dot.setVisible(False)

        self.name_label = ElidedLabel(room.get("uname") or room.get("room_id", ""))
        self.name_label.setObjectName("NavName")
        self.name_label.setProperty("cardMode", True)
        self.sub = ElidedLabel(room.get("title") or
                               ("直播中" if room.get("live") else "未开播"))
        self.sub.setObjectName("NavSub")
        self.sub.setProperty("cardMode", True)
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
        for label in (self.name_label, self.sub):
            label.setProperty("cardMode", enabled)
            _repolish(label)
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
        else:
            self.thumb.stop()
        self.thumb._layout_overlay()
        self.setCursor(Qt.PointingHandCursor)

    def _layout_selection_marker(self):
        if not self.select_mode:
            return
        self.check.move(max(0, self.thumb.width() - self.check.width() - 2), 2)
        self.check.raise_()

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
        text = "直播中" if live else "未开播"
        name = "BadgeLive" if live else "BadgeOff"
        changed = self.badge.text() != text or self.badge.objectName() != name
        self.badge.setText(text)
        if not self.room.get("title"):
            changed = changed or self.sub._full_text != text
            self.sub.setText(text)
        if self.badge.objectName() != name:
            self.badge.setObjectName(name)
            theme.refresh_theme_properties(self.badge)
            _repolish(self.badge)
        if changed:
            self._sync_live_dot()
            self.thumb._layout_overlay()

    def set_title(self, title: str) -> None:
        """更新卡片上的直播间名，并同步悬停时的完整提示。"""
        self.room["title"] = title or ""
        text = title or "未开播"
        if self.sub._full_text != text:
            self.sub.setText(text)
            self.thumb._layout_overlay()

    def set_uname(self, uname: str) -> None:
        """补上主播名：启动时占位条目只有「房间 X」，状态刷新后才拿到真名。"""
        self.room["uname"] = uname or ""
        text = self.room["uname"] or str(self.room.get("room_id") or "")
        if self.name_label._full_text != text:
            self.name_label.setText(text)
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
        host = self.drop_host
        if host is None or self._drag_started:
            return
        self._press_pos = None
        mime = QMimeData()
        room_id = str(self.room.get("room_id"))
        mime.setData(ROOM_MIME, room_id.encode("utf-8"))     # 落到画面墙：播放这一路
        mime.setData(NAV_MIME, room_id.encode("utf-8"))      # 落在列表里：排序
        mime.setText(room_id)
        drag_ids = host.dragged_room_ids(room_id)
        self._drag_started = True
        pixmap, hotspot = motion.lifted_drag(
            self._drag_pixmap(len(drag_ids)),
            QPoint(max(0, min(event.pos().x(), self.width() - 1)),
                   max(0, min(event.pos().y(), self.height() - 1))))
        host.drag_session.start(self, mime, pixmap, hotspot, self.mapToGlobal(event.pos()))

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
        path.addPath(continuous_path(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), theme.RADIUS_MD))
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
            painter.drawPath(continuous_path(badge, 12))
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
        self.update()

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
            for folder in self.drop_host.folders:
                if folder["type"] == "smart":
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


from .sidebar_folders import SmartFolderDialog, SmartFolderCard, FollowFolderButton


class RoomListBox(QWidget):
    """关注列表的滚动内容：卡片自己摆位置，拖动时让位、松手后滑动归位。"""

    #: 光标离**视口**边缘多近就开始自动滚（像素）
    SCROLL_EDGE = 30
    #: 刚进边缘带 / 贴死边缘（或已经拖到视口外）时，一拍各滚多少像素
    SCROLL_STEP_MIN = 4
    SCROLL_STEP_MAX = 36
    #: 拖动期间滚轮一格滚多少像素。
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
        self._animation_started: dict = {}
        self._animation_clock = QTimer(self)
        self._animation_clock.setInterval(16)
        self._animation_clock.setTimerType(Qt.PreciseTimer)
        self._animation_clock.timeout.connect(self._advance_row_animations)
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
            if (animate and previous.state() != QPropertyAnimation.Stopped
                    and previous.endValue() == target):
                return  # 同一落点的拖动事件不能重启动画，否则卡片始终追不上目标。
            previous.stop()
            self._animation_started.pop(previous, None)
            self._animations.pop(item)
            previous.deleteLater()
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
        # The shared Qt/Quick animation clock stopped at time zero in captured
        # folder transitions. Keep Qt's interpolation, advance it on a GUI timer.
        animation.pause()
        self._animation_started[animation] = time.monotonic()
        if not self._animation_clock.isActive():
            self._animation_clock.start()

    def _advance_row_animations(self, *, finish=False) -> None:
        now = time.monotonic()
        for animation, started in list(self._animation_started.items()):
            if not isValid(animation):
                self._animation_started.pop(animation, None)
                continue
            duration = animation.duration()
            elapsed = duration if finish else min(duration, round((now - started) * 1000))
            animation.setCurrentTime(elapsed)
            if elapsed >= duration:
                animation.stop()
                self._animation_started.pop(animation, None)
        if not self._animation_started:
            self._animation_clock.stop()

    def hideEvent(self, event) -> None:
        self._advance_row_animations(finish=True)
        super().hideEvent(event)

    def relayout(self, animate: bool = False, preview_order: list | None = None,
                 dragging_ids: set[str] | None = None, *, duration=150, revealing=(),
                 viewport_only=False) -> None:
        """按当前顺序摆卡片；拖动时用空位显示整组卡片的落点。

        竖屏顶部横栏里改成横向排（卡片向右排开，多了就左右滚）。
        """
        if self.sidebar._collapse_animating:
            return
        items = self._visible_items()
        order = preview_order if preview_order is not None else list(items)
        if self.sidebar.folders and preview_order is None:
            order = self.sidebar.folder_entries()
        width, item_height = self.item_size()
        horizontal = self.horizontal
        if viewport_only:
            viewport = self.sidebar.scroll.viewport()
            visible_rect = QRect(self.mapFrom(viewport, QPoint()), viewport.size())
            displayed = set(order)
            for item, animation in list(self._animations.items()):
                if item not in displayed:
                    self._animations.pop(item)
                    self._animation_started.pop(animation, None)
                    try:
                        animation.stop()
                        animation.deleteLater()
                    except RuntimeError:  # A removed smart copy already deleted its animation.
                        pass
        # 不要在这里改 width：卡片宽度必须和侧栏内容宽度一致，
        # 差几个像素就会让头像和列表对不齐（自检里钉着这一条）
        run = 0
        for entry in order:
            if entry is None:
                # 落点让位：竖屏横排时也要让（用户要求动效和横屏一致），
                # 横排的让位就是往右挪一格
                run += width + NAV_ITEM_GAP if horizontal else self.slot_height()
                continue
            is_folder = isinstance(entry, FollowFolderButton)
            thickness = max(36, entry.minimumSizeHint().height()) if is_folder else item_height
            entry_width = thickness if is_folder and horizontal else width
            entry_height = thickness if is_folder and not horizontal else item_height
            entering = entry in revealing or (viewport_only and getattr(entry, 'original', None) in revealing)
            move_animated = animate
            if viewport_only:
                target = QRect(run if horizontal else 0, 0 if horizontal else run,
                               entry_width, entry_height)
                move_animated = animate and (target.intersects(visible_rect)
                    or (not entering and not entry.isHidden() and entry.geometry().intersects(visible_rect)))
            entry.setVisible(True)
            entry.resize(entry_width, entry_height)
            if horizontal:
                if move_animated and entering:
                    entry.move(run + 24, 0)
                self._glide_to(entry, run, 0, move_animated, duration)
                run += entry_width + NAV_ITEM_GAP
            else:
                # 回到左栏时必须把横栏留下的 x 清零，否则卡片会继续沿用
                # 横向卡片条的位置，只剩第一张完整可见。
                if move_animated and entering:
                    entry.move(0, run + 24)
                self._glide_to(entry, 0, run, move_animated, duration)
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
        if (not self.sidebar._collapse_animating and not self.horizontal
                and event.size().width() != event.oldSize().width()):
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
