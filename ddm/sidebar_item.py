"""Sidebar item implementation; shared sidebar state stays with its owner."""
import os
from PySide6.QtCore import QMimeData, QPoint, QRect, QRectF, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QRegion
from PySide6.QtWidgets import QApplication, QCheckBox, QFrame, QHBoxLayout, QLabel, QMenu, QWidget
from . import motion, theme
from .corner_geometry import continuous_path
from .sidebar_drag import NAV_MIME, ROOM_MIME
from .ui.labels import ElidedLabel
from .widget_support import (
    BRAND_ASSETS_DIR, NAV_COMPACT_ITEM_HEIGHT, NAV_ITEM_HEIGHT, NAV_LIST_ITEM_HEIGHT,
    PORTRAIT_LIST_HEIGHT, _allow_shrink, _ignore_mouse, _repolish
)
from .live_alert import LiveAlert
from .sidebar_thumbnail import NavThumb


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
