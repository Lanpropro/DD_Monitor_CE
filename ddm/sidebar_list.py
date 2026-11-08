"""Sidebar list implementation; shared sidebar state stays with its owner."""
import time
from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QRect, QSize, QTimer, Qt
from PySide6.QtWidgets import QFrame, QLabel, QScrollArea, QWidget
from shiboken6 import isValid
from . import theme
from .sidebar_drag import FOLDER_MIME, NAV_MIME
from .widget_support import (
    CAROUSEL_WIDTH, NAV_COMPACT_ITEM_HEIGHT, NAV_ITEM_GAP, NAV_ITEM_HEIGHT,
    NAV_LIST_ITEM_HEIGHT, PORTRAIT_LIST_HEIGHT, PORTRAIT_LIST_WIDTH
)
from .sidebar_folders import SmartFolderCard, FollowFolderButton
from .sidebar_item import NavItem


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
