"""头像绘制与关注头像条；不依赖主窗口、播放器或聚合 widgets 模块。"""
from PySide6.QtCore import QMimeData, QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QWidget

from . import motion, theme
from .sidebar_drag import ROOM_MIME

AVATAR_COLORS = ["#4c6ef5", "#12b886", "#f76707", "#ae3ec9", "#1098ad", "#e8590c", "#5f3dc4"]


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


class Avatar(QLabel):
    """圆形头像占位。"""

    def __init__(self, name: str, index: int, size: int = theme.AVATAR_SIZE, parent=None):
        super().__init__(parent)
        self.setObjectName("NavAvatar")
        self._size = size
        self._index = index
        self._color = AVATAR_COLORS[index % len(AVATAR_COLORS)]
        self._source: QPixmap | None = None
        self._ring = False
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
            self.set_pixmap_image(self._source, ring=self._ring)
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

    def set_pixmap_image(self, pixmap: QPixmap, *, size: int | None = None, ring: bool = False) -> None:
        """换成真实头像（圆形裁切）。"""
        if pixmap is None or pixmap.isNull():
            return
        if size is not None and size != self._size:
            self._size = size
            self.setFixedSize(size, size)
        self._source = pixmap
        self._ring = ring
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
        if ring:
            painter.setClipping(False)
            painter.setBrush(Qt.NoBrush)
            painter.setPen(QPen(QColor(255, 255, 255, 70), 1.4))
            painter.drawEllipse(QRectF(1, 1, self._size - 2, self._size - 2))
        painter.end()
        if self.styleSheet() != "background: transparent;":
            self.setStyleSheet("background: transparent;")
        super().setPixmap(rounded)


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
        self.sidebar = parent
        self.setObjectName("RoomStrip")
        self.setFixedHeight(self.AVATAR + 2)
        self._rooms: list[dict] = []
        self._faces: dict = {}                   # room_id -> 头像图
        self._on_wall_ids: set[str] = set()
        self._avatars: dict[str, QWidget] = {}   # room_id -> 头像控件（换头像图要用）
        self._avatar_signatures = {}
        self._press_pos = None
        self._press_room = None
        self._hovered_room: dict | None = None
        self._drag_started = False
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
            signature = self._avatar_signatures.get(str(room_id))
            if signature is not None:
                self._avatar_signatures[str(room_id)] = (*signature[:-1], pixmap.cacheKey())
        except Exception:                      # noqa: BLE001
            pass

    # ---- 交互 ----
    def mousePressEvent(self, event) -> None:
        self._press_pos = event.position().toPoint()
        self._press_room = self._room_at(self._press_pos) if event.button() == Qt.LeftButton else None
        self._drag_started = False
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
        mime = QMimeData()
        mime.setData(ROOM_MIME, self._press_room.encode("utf-8"))
        mime.setText(self._press_room)
        avatar = self._avatars[self._press_room]
        hotspot = avatar.mapFromGlobal(self.mapToGlobal(event.position().toPoint()))
        pixmap, hotspot = motion.lifted_drag(avatar.grab(), hotspot)
        self._press_room = None
        self._drag_started = True
        self.sidebar.drag_session.start(
            self, mime, pixmap, hotspot, self.mapToGlobal(event.position().toPoint()))

    def mouseReleaseEvent(self, event) -> None:
        if event.button() != Qt.LeftButton:
            return
        if self._drag_started:
            self._drag_started = False
            return
        super().mouseReleaseEvent(event)
        # Avatar 对鼠标透明，按已知头像几何范围命中，不能依赖 childAt。
        room_id = self._room_at(event.position().toPoint())
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
        previous = self._avatars
        signatures = self._avatar_signatures
        while self._layout.count():
            self._layout.takeAt(0)
        self._avatars = {}
        self._avatar_signatures = {}
        for room in self._rooms:
            room_id = str(room.get("room_id") or "")
            uname = str(room.get("uname") or "")
            face = self._faces.get(room_id)
            signature = (uname, bool(room.get("live")), bool(room.get("pinned")),
                         room_id in self._on_wall_ids, face.cacheKey() if face is not None else None)
            if room_id in previous and signatures.get(room_id) == signature:
                avatar = previous.pop(room_id)
                self._layout.addWidget(avatar)
            else:
                avatar = self._add_avatar(
                    uname[0] if uname else "?", bool(room.get("live")),
                    tooltip=uname or room_id, face=face, room_id=room_id,
                    pinned=bool(room.get("pinned")), on_wall=room_id in self._on_wall_ids)
            if room_id:
                self._avatars[room_id] = avatar
                self._avatar_signatures[room_id] = signature
        for widget in previous.values():
            widget.hide()
            widget.setParent(None)
            widget.deleteLater()
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
