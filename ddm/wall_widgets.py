"""Video-wall composition, pane geometry and resize presentation."""
import math
import os
import sys

from PySide6.QtCore import QRect, QRectF, QSize, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPainterPathStroker, QRegion
from PySide6.QtWidgets import QApplication, QGridLayout, QStyle, QStyleOption, QWidget

from . import layouts, resize_layout, theme
from .badge_surface import BadgeSurface
from .corner_geometry import continuous_path
from .danmaku_widgets import DanmakuPanel
from .tile_widgets import Tile
from .widget_support import TILE_BAR_HEIGHT, _repolish


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


class WallPaneBorder(BadgeSurface):
    """A masked native border keeps resize hits above VLC without covering its centre."""

    BAND = 3
    CORNER = 18
    RADIUS = 10

    def __init__(self, pane, wall):
        super().__init__(pane)
        self.wall = wall
        self.targets = {}
        self.hover_edges = {}
        self.highlights = []
        self._outline_path = QPainterPath()
        self._mask_path = QPainterPath()
        self.setAttribute(Qt.WA_NativeWindow, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.ClickFocus)
        self.setToolTip("拖动边框调整大小；拖动角落等比例缩放；双击恢复相邻区域比例")
        self.hide()

    def sync(self, targets):
        self.targets = targets
        if not self.underMouse():
            self.hover_edges = {}
        self.setGeometry(self.parentWidget().rect())
        region = QRegion()
        for edge in targets:
            region |= QRegion(self._edge_rect(edge))
        outer, inner = QPainterPath(), QPainterPath()
        outer.addPath(continuous_path(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), self.RADIUS - .5))
        inner.addPath(continuous_path(QRectF(self.rect()).adjusted(
            self.BAND + .5, self.BAND + .5, -self.BAND - .5, -self.BAND - .5), self.RADIUS - self.BAND - .5))
        self._outline_path = outer.subtracted(inner)
        # 原生遮罩只负责命中；向外留出抗锯齿像素，由逐像素透明绘制轮廓。
        stroker = QPainterPathStroker()
        stroker.setWidth(2)
        outline = QRegion(self._outline_path.united(stroker.createStroke(
            self._outline_path)).toFillPolygon().toPolygon())
        region &= outline
        if region.isEmpty():
            self.hide()
            return
        self.setMask(region)
        self.show()
        self.raise_()

    def _edge_rect(self, edge):
        width, height = self.width(), self.height()
        return {"left": QRect(0, 0, self.RADIUS, height),
                "right": QRect(width - self.RADIUS, 0, self.RADIUS, height),
                "top": QRect(0, 0, width, self.RADIUS),
                "bottom": QRect(0, height - self.RADIUS, width, self.RADIUS)}[edge]

    def edges_at(self, point):
        horizontal = "left" if point.x() < self.CORNER else (
            "right" if point.x() >= self.width() - self.CORNER else None)
        vertical = "top" if point.y() < self.CORNER else (
            "bottom" if point.y() >= self.height() - self.CORNER else None)
        return {edge: self.targets[edge] for edge in (horizontal, vertical) if edge in self.targets}

    def set_highlights(self, rectangles):
        if self.highlights != rectangles:
            self.highlights = rectangles
            self.update()

    def mouseMoveEvent(self, event):
        if self.wall._border_drag is not None and self.wall._border_drag["border"] is self:
            self.wall._move_border_drag(event.globalPosition().toPoint())
        else:
            self.hover_edges = self.edges_at(event.position().toPoint())
            self.wall._set_hover_border(self, self.hover_edges)
            horizontal = next((edge for edge in self.hover_edges if edge in ("left", "right")), None)
            vertical = next((edge for edge in self.hover_edges if edge in ("top", "bottom")), None)
            if horizontal and vertical:
                cursor = Qt.SizeFDiagCursor if (horizontal == "left") == (vertical == "top") else Qt.SizeBDiagCursor
            else:
                cursor = Qt.SizeHorCursor if horizontal else Qt.SizeVerCursor
            self.setCursor(cursor)
        event.accept()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            edges = self.edges_at(event.position().toPoint())
            self.wall._begin_border_drag(self, edges, event.globalPosition().toPoint())
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.wall._finish_border_drag(self, event.globalPosition().toPoint())
            event.accept()
        else:
            super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.wall._reset_border(self, self.edges_at(event.position().toPoint()))
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)

    def leaveEvent(self, event):
        self.hover_edges = {}
        self.wall._set_hover_border()
        self.update()
        super().leaveEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.wall._cancel_border_drag()
            event.accept()
        else:
            super().keyPressEvent(event)

    def paintEvent(self, event):
        if sys.platform == 'win32' and QApplication.platformName() == 'windows':
            self._schedule_layered_paint()
        else:
            painter = QPainter(self)
            self._render_badge(painter)

    def refresh_theme(self):
        self.update()

    def _layered_render_key(self):
        return tuple(rect.getRect() for rect in self.highlights)

    def _render_badge(self, painter):
        painter.setRenderHint(QPainter.Antialiasing)
        # Windows 透明像素会穿透鼠标；极低 alpha 保留未高亮边缘的拖动命中。
        painter.fillPath(self._outline_path, QColor(56, 189, 248, 1))
        selected = QRegion()
        for rect in self.highlights:
            selected |= QRegion(rect)
        painter.setClipRegion(selected)
        painter.fillPath(self._outline_path, QColor('#38bdf8'))


class WallResizePreview(QWidget):
    """Masked native guides stay above VLC while the video windows remain still."""

    LINE = 2
    DASH = 6
    GAP = 5
    COLOR = QColor("#b7c1c4")

    def __init__(self, wall):
        super().__init__(wall)
        self.rectangles = {}
        self.guides = {}
        self._outline = QRegion()
        self.setAttribute(Qt.WA_NativeWindow, True)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.hide()

    def show_guides(self, rectangles, dividers, originals):
        self.rectangles = {cell: QRect(rect) for cell, rect in rectangles.items()}
        self.guides = {}
        self.setGeometry(self.parentWidget().rect())
        outline = QRegion()
        for key, rect in dividers.items():
            previous = originals.get(key)
            vertical = rect.width() < rect.height()
            if previous is None or (rect.left() if vertical else rect.top()) == (
                    previous.left() if vertical else previous.top()):
                continue
            self.guides[key] = QRect(rect)
            length = rect.height() if vertical else rect.width()
            for offset in range(0, length, self.DASH + self.GAP):
                dash = min(self.DASH, length - offset)
                x = rect.center().x() - self.LINE // 2 if vertical else rect.left() + offset
                y = rect.top() + offset if vertical else rect.center().y() - self.LINE // 2
                outline |= QRegion(QRect(x, y,
                                         self.LINE if vertical else dash,
                                         dash if vertical else self.LINE))
        previous_outline, self._outline = self._outline, outline
        if outline.isEmpty():
            self.hide()
        else:
            self.setMask(outline)
            self.show()
            self.raise_()
            self.update()
        self.parentWidget()._repaint_preview_damage(previous_outline.subtracted(outline))

    def clear(self):
        self.hide()
        previous_outline, self._outline = self._outline, QRegion()
        self.rectangles = {}
        self.guides = {}
        self.parentWidget()._repaint_preview_damage(previous_outline)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setClipRegion(self._outline)
        painter.fillRect(event.rect(), self.COLOR)


class WallGrid(QWidget):
    """画面墙：自动网格或指定布局方案。"""

    tileClicked = Signal(dict)
    tileCreated = Signal(object)
    roomDropped = Signal(object, str)      # 目标格子, 房间号
    tileSwapped = Signal(str, object)      # 来源房间号, 目标格子
    cornerRatiosChanged = Signal()         # 松开或重置后通知外层保存，不在拖动帧中写配置
    layoutRatiosChanged = Signal()
    paneEditRequested = Signal(int)
    paneApplyRequested = Signal(object)
    danmakuPanelCreated = Signal(object)
    paneConfigurationChanged = Signal()

    def __init__(self, rooms: list[dict], layout_id: str = "", parent=None, *, prepare_room=None,
                 corner_ratios=None, layout_ratios=None, pane_layouts=None):
        super().__init__(parent)
        self._prepare_room = prepare_room
        self.setObjectName("WallGrid")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._quick_danmaku_layer = None
        self._quick_danmaku_attempted = False
        self._quick_danmaku_requested = (
            os.environ.get("DDM_QTQUICK_DANMAKU") == "1" and sys.platform == "win32"
            and QApplication.platformName() == "windows")
        if self._quick_danmaku_requested:
            self.setAttribute(Qt.WA_NativeWindow, True)
        # 老配置里可能存着已经删掉的布局，回落到自动布局
        self.layout_id = layout_id if layout_id in layouts.BY_ID else layouts.DEFAULT_LAYOUT
        self.tiles: list[Tile] = []
        self.picture_in_picture_tiles = None
        self.picture_in_picture_columns = 0
        self.picture_in_picture_primary = 0
        self.picture_in_picture_aspects = []
        self.fullscreen_tile: Tile | None = None
        #: 退出全屏时「布局先算好、格子分批露面」用的状态（见 reveal_tiles_staggered）
        self._defer_show = False
        self._pending_reveal: list[Tile] = []
        self._fullscreen_layout_pending = False
        self._stagger_first: Tile | None = None
        self._sidebar_animating = False
        self._sidebar_layout = None
        self._interactive_resize = False
        self._resize_pending = False
        self._resize_on_show = False
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._resize_timer.setInterval(33)
        self._resize_timer.timeout.connect(self._flush_resize)
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

        # 一大五小保留原播放格及父窗口，边框交互只改变几何。
        self._corner_width_ratio = 2 / 3
        self._corner_height_ratio = 2 / 3
        self._corner_right_ratio = 1 / 2
        self._corner_bottom_ratios = [1 / 3, 2 / 3]  # 底部两条分隔线的累计宽度比例
        self.restore_corner_ratios(corner_ratios)

        self._partitions = {}
        for identifier, preset in layouts.BY_ID.items():
            if identifier == "corner":
                continue
            cells = preset["spec"][2]
            if layouts.is_portrait_layout(identifier):
                small = len(cells) - 1 - int(preset.get("danmaku") is not None)
                tree = resize_layout.portrait_partition(
                    small, preset.get("danmaku") is not None, layouts.PORTRAIT_SMALL_COLUMNS)
            else:
                tree = resize_layout.build_partition(cells)
            self._partitions[identifier] = tree
        saved = layout_ratios if isinstance(layout_ratios, dict) else {}
        self._layout_ratios = {
            identifier: resize_layout.validated_weights(saved.get(identifier), tree)
            for identifier, tree in self._partitions.items()}
        self._preset_dividers = {}
        self._divider_rects = {}

        self._pane_borders = {}
        self._hover_border = None
        self._hover_edges = {}
        self._border_drag = None
        self._border_pending = None
        self._border_drag_timer = QTimer(self)
        self._border_drag_timer.setSingleShot(True)
        self._border_drag_timer.setTimerType(Qt.PreciseTimer)
        self._border_drag_timer.setInterval(32)
        self._border_drag_timer.timeout.connect(self._flush_border_drag)
        self._border_preview = WallResizePreview(self)

        # 弹幕格：占一整格，只在带弹幕的布局里出现（可以拖到别的格子上）
        self.danmaku = DanmakuPanel(self)
        self.danmaku.setVisible(False)
        self._danmaku_cell = layouts.danmaku_cell(layout_id)
        from .pane_danmaku import PaneDanmaku
        self.pane_danmaku = PaneDanmaku(self, pane_layouts)

        for room in rooms:
            self._make_tile(room)
        self.ensure_slots()
        self.pane_danmaku.restore_sources()
        self.relayout(force=True)

    def refresh_theme(self):
        self.grid.setSpacing(8)
        # Finish theme-driven geometry before snapshot overlays start watching
        # video surfaces; a delayed Resize would cancel the reveal immediately.
        self.grid.activate()

    def ensure_quick_danmaku_layer(self):
        if self._quick_danmaku_layer is not None or not self._quick_danmaku_requested:
            return self._quick_danmaku_layer
        if self._quick_danmaku_attempted:
            return None
        self._quick_danmaku_attempted = True
        try:
            from .video_danmaku_quick import QuickDanmakuLayer
            self._quick_danmaku_layer = QuickDanmakuLayer(self)
            for tile in self.tiles:
                tile.video_danmaku.attach_quick_layer(self._quick_danmaku_layer)
            if self.fullscreen_tile is not None and self.fullscreen_tile.isWindow():
                self._quick_danmaku_layer.set_presentation_window(self.fullscreen_tile)
                tile._update_quick_danmaku_mask()
            if self.isVisible():
                self._quick_danmaku_layer.show()
            motion = ("XAnimator" if self._quick_danmaku_layer.render_thread_animation
                      else "Python timer")
            print(f"[弹幕] Qt Quick共享层，位置更新：{motion}", file=sys.stderr)
        except Exception as exc:
            self._quick_danmaku_layer = None
            print(f"[弹幕] Qt Quick原型初始化失败，回退到QPainter：{exc}", file=sys.stderr)
        return self._quick_danmaku_layer

    def set_picture_in_picture(self, tiles, columns=0, aspects=None, primary=0):
        self.set_interactive_resize(False)
        self._clear()
        self._resize_on_show = False
        self._relayout_timer.stop()
        self.picture_in_picture_tiles = list(tiles) if tiles is not None else None
        self.picture_in_picture_columns = columns
        self.picture_in_picture_primary = primary
        self.picture_in_picture_aspects = aspects or []
        selected = set(tiles or [])
        for tile in self.tiles:
            tile.setProperty('pictureInPicture', tile in selected)
            _repolish(tile)
            if tile in selected:
                tile.set_controls_visible(False)
            if tiles is not None:
                tile.setMinimumSize(0, 0)
        self._sync_danmaku_controls()
        self.relayout(force=True)
        for tile in self.tiles:
            tile._layout_areas()

    def _relayout_picture_in_picture(self):
        from .picture_in_picture import pane_rectangles
        self.setMinimumSize(0, 0)
        for panel in self.pane_danmaku.all_panels():
            panel.hide()
        self._divider_rects = {}
        for border in self._pane_borders.values():
            border.hide()
        selected = self.picture_in_picture_tiles
        for tile in self.tiles:
            tile.setVisible(tile in selected)
        window = self._quick_danmaku_layer.window if self._quick_danmaku_layer is not None else None
        if window is not None:
            window.begin_mask_batch()
        try:
            for tile, rect in zip(selected, pane_rectangles(
                    len(selected), self.rect(), self.picture_in_picture_columns,
                    self.picture_in_picture_aspects, self.picture_in_picture_primary)):
                tile.setGeometry(rect)
        finally:
            if window is not None:
                window.end_mask_batch()

    def set_layout(self, layout_id: str, *, relayout: bool = True) -> None:
        if layout_id == self.layout_id:
            return
        self.set_interactive_resize(False)
        self._resize_on_show = False
        self._relayout_timer.stop()
        self._cancel_border_drag()
        self._preset_dividers = {}
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
        self.set_interactive_resize(False)
        self._resize_on_show = False
        self._cancel_border_drag()
        self._relayout_timer.stop()
        self._defer_show = bool(stagger)
        self._pending_reveal = []
        self._stagger_first = first
        previous = self.fullscreen_tile
        if previous is not tile and self._quick_danmaku_layer is not None:
            self._quick_danmaku_layer.reset_surface()
        self.fullscreen_tile = tile
        if previous is not None and previous is not tile:
            previous.setProperty("fullscreen", False)
            _repolish(previous)
            if not self._fullscreen_layout_pending:
                previous._layout_areas()
        if tile is not None:
            tile.setProperty("fullscreen", True)
            _repolish(tile)
            if not self._fullscreen_layout_pending:
                tile._layout_areas()
        margin = 0 if tile else 16
        self.grid.setContentsMargins(margin, margin, margin, margin)
        if not self._fullscreen_layout_pending:
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
        if self._prepare_room is not None:
            room = self._prepare_room(room)
        # 竖屏布局是手动 setGeometry，不经过 QGridLayout 的 addWidget；
        # 先挂到画面墙，新增空格才不会在 setVisible() 时变成顶层悬浮窗。
        tile = Tile(room, self)
        if self._quick_danmaku_layer is not None:
            tile.video_danmaku.attach_quick_layer(self._quick_danmaku_layer)
        tile.clicked.connect(self.tileClicked.emit)
        tile.roomDropped.connect(lambda rid, t=tile: self.roomDropped.emit(t, rid))
        tile.tileDropped.connect(lambda rid, t=tile: self.tileSwapped.emit(rid, t))
        tile.danmakuDropped.connect(lambda t=tile: self.move_danmaku_to_tile(t))
        tile.danmakuPaneDropped.connect(lambda cell, t=tile: self.pane_danmaku.move(cell, t))
        tile.paneEditRequested.connect(lambda t=tile: self.paneEditRequested.emit(
            self.pane_danmaku.cell_for_tile(t) if self.pane_danmaku.cell_for_tile(t) is not None else -1))
        tile.set_interactive_resize(self._interactive_resize)
        self.tiles.append(tile)
        self.tileCreated.emit(tile)
        return tile

    def _drop_tile(self, tile: Tile) -> None:
        controls = getattr(tile, '_plugin_controls', None)
        if controls is not None:
            controls.shutdown()
        border = self._pane_borders.pop(tile, None)
        if border is not None and (self._hover_border is border or
                                   self._border_drag is not None and self._border_drag["border"] is border):
            self._cancel_border_drag()
        self.grid.removeWidget(tile)
        if self._quick_danmaku_layer is not None:
            group = tile.video_danmaku._quick_group
            if group is not None:
                self._quick_danmaku_layer.remove_group(group)
                tile.video_danmaku._quick_group = None
                tile.video_danmaku._quick_layer = None
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
        if self.pane_danmaku.custom:
            return list(range(len(cells)))
        return [index for index in range(len(cells)) if index != self._danmaku_cell]

    def main_index(self) -> int | None:
        """当前布局里"主画面"是第几路画面（弹幕格不算）；等分布局返回 None。"""
        cells = self._cells()
        order = self._cell_order()
        if not cells or not order:
            return None
        areas = [0 if cell in self.pane_danmaku.bindings() else cells[cell][2] * cells[cell][3]
                 for cell in order]
        if len(set(areas)) <= 1:
            return None
        return areas.index(max(areas))

    @property
    def has_danmaku(self) -> bool:
        return self.picture_in_picture_tiles is None and bool(self.pane_danmaku.bindings()) and bool(self._cells())

    def danmaku_target_tile(self):
        if self.pane_danmaku.custom:
            return self.pane_danmaku.target(self.danmaku)
        main = self.main_index()
        if main is not None and 0 <= main < len(self.tiles):
            return self.tiles[main]
        return next((tile for tile in self.tiles if tile.room.get('room_id')), None)

    def sync_sc_placement(self):
        targets = {self.pane_danmaku.target(panel) for panel in self.pane_danmaku.rendered()} if (
            self.has_danmaku and self.fullscreen_tile is None) else set()
        for tile in self.tiles:
            tile.video_danmaku.set_sc_independent(self.has_danmaku)
            tile.video_danmaku.set_sc_in_panel(tile in targets)

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
        self._cancel_border_drag()
        for border in self._pane_borders.values():
            border.hide()
        self._preset_dividers = {}
        self.setMinimumSize(0, 0)
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

    def set_sidebar_animating(self, active: bool) -> None:
        """收缩期间保持原生视频窗口尺寸，结束后统一调整。"""
        if self.picture_in_picture_tiles is not None:
            return
        if active == self._sidebar_animating:
            return
        self._sidebar_animating = active
        if active:
            self._sidebar_layout = (self.layout_id, tuple(self.tiles),
                                    self.fullscreen_tile, self._danmaku_cell)
            self._sidebar_updates_enabled = self.updatesEnabled()
            self.setUpdatesEnabled(False)
        self._resize_timer.stop()
        self._resize_pending = False
        self._relayout_timer.stop()
        self.grid.setEnabled(not active)
        if not active:
            try:
                layout_state = (self.layout_id, tuple(self.tiles),
                                self.fullscreen_tile, self._danmaku_cell)
                if (layout_state == self._sidebar_layout and self.fullscreen_tile is None
                        and (self.layout_id == 'corner' or self.layout_id in self._partitions)):
                    # Width-only settlement keeps pane visibility and native stacking intact.
                    self._resize_pending = True
                    self._flush_resize()
                    QTimer.singleShot(0, self._sync_danmaku_controls)
                else:
                    self.relayout(force=True)
                self.grid.activate()
                if self._quick_danmaku_layer is not None:
                    self._quick_danmaku_layer.resize()
            finally:
                self._sidebar_layout = None
                self.setUpdatesEnabled(self._sidebar_updates_enabled)

    def relayout(self, force: bool = False) -> None:
        if self.picture_in_picture_tiles is not None:
            self._relayout_picture_in_picture()
            return
        if self._fullscreen_layout_pending:
            return
        self.pane_danmaku.prepare()
        self.sync_sc_placement()
        if self._sidebar_animating:
            return
        if force:
            self._relayout_timer.stop()
            self._resize_timer.stop()
            self._resize_pending = False
        self.ensure_slots()          # 按布局补空位
        self._sync_danmaku_controls()
        if not self.tiles:
            return
        layout = layouts.BY_ID.get(self.layout_id)     # 老配置可能存着已经删掉的布局
        spec = None if layout is None else layout.get("spec")
        if not force and spec is None:
            # 自动模式：列数没变就不用重排
            if self._auto_columns() == self._columns:
                return
        self._clear()
        for panel in self.pane_danmaku.all_panels():
            panel.hide()

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

        if self.layout_id == "corner":
            self._relayout_corner(apply_visibility=True)
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

        self._relayout_preset(apply_visibility=True)

    def _sync_danmaku_controls(self) -> None:
        desired = dict.fromkeys(self.pane_danmaku.all_panels())
        shared = {}
        panels = sorted(self.pane_danmaku.rendered(),
                        key=lambda panel: (panel.geometry().bottom(), panel.geometry().right()), reverse=True)
        for panel in panels:
            tile = self.pane_danmaku.target(panel) if self.has_danmaku and self.fullscreen_tile is None else None
            target = getattr(tile, '_plugin_controls', None)
            room = str(tile.room.get('room_id') or '') if tile is not None else ''
            if target is not None and not target._disposed and room not in shared:
                desired[panel] = target
                shared[room] = target
        for panel in self.pane_danmaku.all_panels():
            tile = self.pane_danmaku.target(panel)
            room = str(tile.room.get('room_id') or '') if tile is not None else ''
            panel._linked_controls = shared.get(room)
        # Detach all old owners first: two panels may exchange their input widgets.
        for panel, target in desired.items():
            previous = panel._tile_controls
            if previous is not None and previous is not target:
                previous.set_panel(None)
        for panel, target in desired.items():
            panel._tile_controls = target
            if target is not None:
                target.set_panel(panel)
                target.layout_panel()

    # ---- 其余预设：分区树只计算几何，视频始终是 WallGrid 的直接子窗口 ----
    def layout_ratios(self) -> dict:
        return {identifier: {key: list(values) for key, values in ratios.items()}
                for identifier, ratios in self._layout_ratios.items() if ratios}

    def reset_layout_ratios(self) -> None:
        """只恢复当前预设，不影响其他预设保存的比例。"""
        self._cancel_border_drag()
        if self.layout_id == "corner":
            self.reset_corner_ratios()
            return
        changed = bool(self._layout_ratios.get(self.layout_id))
        self._layout_ratios[self.layout_id] = {}
        if self.fullscreen_tile is None:
            self._relayout_preset()
        if changed:
            self.layoutRatiosChanged.emit()

    def _preset_defaults(self, node, area):
        if node.key != "root" or not layouts.is_portrait_layout(self.layout_id):
            return node.weights
        gap = self.grid.spacing()
        main = max(80, int(area.width() * 9 / 16))
        danmaku = max(140, int(area.height() * .22)) if layouts.danmaku_cell(self.layout_id) is not None else 0
        small = max(1, area.height() - main - danmaku - gap * (len(node.children) - 1))
        return [main, small, danmaku] if layouts.danmaku_cell(self.layout_id) is not None else [main, small]

    def _preset_widgets(self):
        if self.pane_danmaku.custom:
            widgets = self.pane_danmaku.cell_tiles()
            widgets.update(self.pane_danmaku.panels)
            return widgets
        if layouts.is_portrait_layout(self.layout_id):
            # 竖屏弹幕始终占底部，与原竖屏规则一致。
            count = self._capacity()
            widgets = {index: tile for index, tile in enumerate(self.tiles[:count])}
            if self.has_danmaku:
                widgets[count] = self.danmaku
            return widgets
        widgets = {cell: tile for cell, tile in zip(self._cell_order(), self.tiles)}
        if self.has_danmaku:
            widgets[self._danmaku_cell] = self.danmaku
        return widgets

    def _preset_minimum(self, cell):
        widget = self._preset_widgets().get(cell)
        if widget in self.pane_danmaku.all_panels():
            return QSize(max(200, widget.minimumWidth()), max(140, widget.minimumHeight()))
        return QSize(max(200, widget.minimumWidth()), max(150, widget.minimumHeight()))

    def _relayout_preset(self, apply_visibility=False):
        if self.picture_in_picture_tiles is not None:
            self._relayout_picture_in_picture()
            return
        if self.fullscreen_tile is not None or self.layout_id not in self._partitions:
            return
        widgets = self._preset_widgets()
        if len(widgets) < len(self._cells()):
            # 应用切方向时先选预设、再调整窗口、最后补齐格子；中间的 resize 不排布。
            return
        tree = self._partitions[self.layout_id]
        gap = self.grid.spacing()
        margins = self.grid.contentsMargins()
        minimum = tree.minimum(gap, self._preset_minimum)
        self.setMinimumSize(minimum.width() + margins.left() + margins.right(),
                            minimum.height() + margins.top() + margins.bottom())
        area = self._corner_area()
        # 顶层窗口尺寸变更可能在下一次事件循环才完成，计算区域也遵守最小尺寸。
        area.setWidth(max(area.width(), minimum.width()))
        area.setHeight(max(area.height(), minimum.height()))
        leaves, dividers = resize_layout.geometry(
            tree, area, gap, self._preset_minimum,
            self._layout_ratios[self.layout_id], self._preset_defaults)
        for cell, rect in leaves.items():
            widget = widgets[cell]
            same_size = widget.size() == rect.size()
            widget.setGeometry(rect)
            if isinstance(widget, Tile) and same_size:
                # One equal cell can retain its size while its neighbour gains
                # the last pixel. Resized cells use their existing resize path.
                widget._layout_bottom_controls()
        self.pane_danmaku.dividers = dividers
        widgets = self.pane_danmaku.arrange(leaves, widgets)
        self._resize_on_show = False
        if apply_visibility:
            active = set(widgets.values())
            for tile in self.tiles:
                if tile not in active:
                    tile.hide()
                elif self._defer_show and tile is not self._stagger_first:
                    self._pending_reveal.append(tile)
                else:
                    tile.show()
            for panel in self.pane_danmaku.all_panels():
                panel.setVisible(panel in active)
        old_regions = list(self._divider_rects.values())
        self._preset_dividers = {}
        self._divider_rects = {}
        for node, index, rect, node_area, sizes in dividers:
            key = (node.key, index)
            self._preset_dividers[key] = (node, node_area, sizes)
            self._divider_rects[key] = rect
        for rect in old_regions + list(self._divider_rects.values()):
            self.update(rect)
        self._columns = layouts.BY_ID[self.layout_id]["spec"][1]
        self._sync_pane_borders(widgets, dividers)

    def _sync_pane_borders(self, widgets, dividers):
        for pane, border in list(self._pane_borders.items()):
            if pane not in self.tiles and pane not in self.pane_danmaku.all_panels():
                del self._pane_borders[pane]
            elif pane not in widgets.values() or pane.isHidden():
                border.hide()
        for pane in widgets.values():
            if pane not in self._pane_borders:
                self._pane_borders[pane] = WallPaneBorder(pane, self)
            targets = resize_layout.border_targets(pane.geometry(), dividers)
            self._pane_borders[pane].sync(targets)
        self._set_hover_border(self._hover_border, self._hover_edges)

    def _repaint_preview_damage(self, region):
        if region.isEmpty():
            return
        # Native mask changes expose stale Qt backing-store pixels unless owners repaint them.
        self.update(region)
        for pane, border in self._pane_borders.items():
            if pane.isVisible():
                local = region.translated(-pane.pos()).intersected(pane.rect())
                if not local.isEmpty():
                    pane.update(local)
                    if border.isVisible():
                        border.update(local.intersected(border.mask()))

    def _set_hover_border(self, border=None, edges=None):
        if (self._border_drag is not None or border is None or
                border not in self._pane_borders.values() or not border.isVisible()):
            border, edges = None, {}
        else:
            edges = {edge: key for edge, key in (edges or {}).items()
                     if border.targets.get(edge) == key and key in self._divider_rects}
        self._hover_border, self._hover_edges = border, edges
        # A corner names the pane as a whole; an edge names only that side.
        displayed = border.targets if border is not None and len(edges) > 1 else edges
        for candidate in self._pane_borders.values():
            candidate.set_highlights([candidate._edge_rect(edge) for edge in displayed]
                                     if candidate is border else [])

    def _border_model(self):
        if self.layout_id == "corner":
            tree = resize_layout.build_partition(layouts.BY_ID["corner"]["spec"][2])
            first, second = self._corner_bottom_ratios
            weights = {"root": [self._corner_height_ratio, 1 - self._corner_height_ratio],
                       "root/0": [self._corner_width_ratio, 1 - self._corner_width_ratio],
                       "root/0/1": [self._corner_right_ratio, 1 - self._corner_right_ratio],
                       "root/1": [first, second - first, 1 - second]}
            widgets = self._preset_widgets()
            minimum = lambda cell: widgets[cell].minimumSize()
            return tree, weights, widgets, minimum, None
        return (self._partitions[self.layout_id], self._layout_ratios[self.layout_id],
                self._preset_widgets(), self._preset_minimum, self._preset_defaults)

    def _begin_border_drag(self, border, edges, position):
        if not edges or self.fullscreen_tile is not None:
            return
        self._cancel_border_drag()
        tree, weights, widgets, minimum, defaults = self._border_model()
        cell = next(cell for cell, pane in widgets.items() if pane is border.parentWidget())
        minimums = {index: minimum(index) for index in widgets}
        geometry_weights = {key: list(values) for key, values in weights.items()}
        if self.layout_id == "corner" and any(key[0] == "root/1" for key in edges.values()):
            # Match cumulative corner rounding so the untouched bottom boundary stays fixed.
            widths = [pane.width() for pane in self.tiles[3:6]]
            geometry_weights["root/1"] = [width / sum(widths) for width in widths]
        self._border_drag = dict(border=border, edges=edges, origin=position,
                                 rect=QRect(border.parentWidget().geometry()), cell=cell,
                                 tree=tree, weights={key: list(values) for key, values in weights.items()},
                                 geometry_weights=geometry_weights,
                                 dividers={key: QRect(rect) for key, rect in self._divider_rects.items()},
                                 minimum=minimums.__getitem__, defaults=defaults, area=self._corner_area(),
                                 before=self.corner_ratios() if self.layout_id == "corner" else self.layout_ratios(),
                                 preview_weights=None)
        border.setFocus(Qt.MouseFocusReason)
        self._set_hover_border()
        border.update()

    def _move_border_drag(self, position):
        if self._border_drag is None:
            return
        self._border_pending = position
        if not self._border_drag_timer.isActive():
            self._border_drag_timer.start()

    def _apply_border_weights(self, weights):
        if self.layout_id == "corner":
            self._corner_height_ratio = weights["root"][0]
            self._corner_width_ratio = weights["root/0"][0]
            self._corner_right_ratio = weights["root/0/1"][0]
            bottom = weights["root/1"]
            self._corner_bottom_ratios = [bottom[0], bottom[0] + bottom[1]]
            self._relayout_corner()
        else:
            self._layout_ratios[self.layout_id] = weights
            self._relayout_preset()

    def _flush_border_drag(self):
        position, self._border_pending = self._border_pending, None
        state = self._border_drag
        if state is None or position is None or self.fullscreen_tile is not None:
            return
        if position == state["origin"]:
            state["preview_weights"] = None
            self._border_preview.clear()
            return
        weights = resize_layout.resize_borders(
            state["tree"], state["area"], self.grid.spacing(), state["minimum"],
            state["geometry_weights"], state["defaults"], state["cell"], state["edges"],
            state["rect"], position - state["origin"])
        state["preview_weights"] = weights
        if self.layout_id == "corner":
            rectangles, dividers = self._corner_rectangles(weights, state["area"])
        else:
            rectangles, divider_items = resize_layout.geometry(
                state["tree"], state["area"], self.grid.spacing(), state["minimum"],
                weights, state["defaults"])
            dividers = {(node.key, index): rect
                        for node, index, rect, _area, _sizes in divider_items}
        self._border_preview.show_guides(rectangles, dividers, state["dividers"])

    def _finish_border_drag(self, border, position):
        state = self._border_drag
        if state is None or state["border"] is not border:
            return
        self._border_pending = position
        self._border_drag_timer.stop()
        self._flush_border_drag()
        before = state["before"]
        self._border_drag = None
        self._border_preview.clear()
        border.update()
        if state["preview_weights"] is not None:
            self._apply_border_weights(state["preview_weights"])
        if self.layout_id == "corner":
            if before != self.corner_ratios():
                self.cornerRatiosChanged.emit()
        elif before != self.layout_ratios():
            self.layoutRatiosChanged.emit()

    def _cancel_border_drag(self):
        if not hasattr(self, "_border_drag_timer"):
            return
        self._border_drag_timer.stop()
        self._border_pending = None
        self._border_preview.clear()
        state, self._border_drag = self._border_drag, None
        if state is not None:
            border = state["border"]
            if QWidget.mouseGrabber() is border:
                border.releaseMouse()
            border.update()
        self._set_hover_border()

    def _reset_border(self, border, edges):
        if self.fullscreen_tile is not None or not border.isVisible() or not edges:
            return
        self._cancel_border_drag()
        keys = list(dict.fromkeys(value for edge, value in edges.items()
                                  if border.targets.get(edge) == value))
        before = self.corner_ratios() if self.layout_id == "corner" else self.layout_ratios()
        if self.layout_id == "corner":
            targets = {("root", 0): Qt.Vertical, ("root/0", 0): Qt.Horizontal,
                       ("root/0/1", 0): "right", ("root/1", 0): "bottom_left",
                       ("root/1", 1): "bottom_right"}
            for key in keys:
                self._reset_corner(targets[key])
            if self.corner_ratios() != before:
                self.cornerRatiosChanged.emit()
        else:
            for key in keys:
                self._reset_preset_pair(key)
            if self.layout_ratios() != before:
                self.layoutRatiosChanged.emit()

    def _reset_preset_pair(self, key):
        node, area, current = self._preset_dividers[key]
        index = key[1]
        defaults = self._preset_defaults(node, area)
        sizes = list(current)
        pair = current[index] + current[index + 1]
        minimums = [child.minimum(self.grid.spacing(), self._preset_minimum) for child in node.children]
        spans = [size.width() if node.axis == Qt.Horizontal else size.height() for size in minimums]
        sizes[index] = max(spans[index], min(pair - spans[index + 1],
                           round(pair * defaults[index] / (defaults[index] + defaults[index + 1]))))
        sizes[index + 1] = pair - sizes[index]
        self._layout_ratios[self.layout_id][node.key] = [size / sum(sizes) for size in sizes]
        self._relayout_preset()

    # ---- 一大五小：手动几何保持视频 HWND 不变，拖动只调整区域比例 ----
    def corner_ratios(self) -> dict:
        """导出独立比例；不依赖当前布局是否显示、窗口尺寸或全屏状态。"""
        return {"width": self._corner_width_ratio, "height": self._corner_height_ratio,
                "right": self._corner_right_ratio, "bottom": list(self._corner_bottom_ratios)}

    def restore_corner_ratios(self, saved) -> None:
        """旧配置或非法字段使用默认值；边界也排除 NaN、无穷值和布尔值。"""
        saved = saved if isinstance(saved, dict) else {}

        def valid(value):
            return type(value) in (int, float) and 0 < value < 1

        for name, attribute, default in (("width", "_corner_width_ratio", 2 / 3),
                                         ("height", "_corner_height_ratio", 2 / 3),
                                         ("right", "_corner_right_ratio", 1 / 2)):
            value = saved.get(name)
            setattr(self, attribute, float(value) if valid(value) else default)
        bottom = saved.get("bottom")
        if (isinstance(bottom, (list, tuple)) and len(bottom) == 2
                and all(valid(value) for value in bottom) and bottom[0] < bottom[1]):
            self._corner_bottom_ratios = [float(value) for value in bottom]
        else:
            self._corner_bottom_ratios = [1 / 3, 2 / 3]
        if self.tiles and self.layout_id == "corner" and self.fullscreen_tile is None:
            self._relayout_corner()

    def reset_corner_ratios(self) -> None:
        """恢复全部区域比例；保留房间、播放器和每个格子的音频设置。"""
        before = self.corner_ratios()
        self._cancel_border_drag()
        self.restore_corner_ratios(None)
        if self.corner_ratios() != before:
            self.cornerRatiosChanged.emit()

    def _corner_area(self) -> QRect:
        margins = self.grid.contentsMargins()
        return self.rect().adjusted(margins.left(), margins.top(),
                                    -margins.right(), -margins.bottom())

    def _reset_corner(self, target) -> None:
        if target == Qt.Horizontal:
            self._corner_width_ratio = 2 / 3
        elif target == Qt.Vertical:
            self._corner_height_ratio = 2 / 3
        elif target == "right":
            self._corner_right_ratio = 1 / 2
        elif target in ("bottom_left", "bottom_right"):
            left, middle, right = self.tiles[3:6]
            span = max(1, left.width() + middle.width() + right.width())
            first, second = left.width() / span, (left.width() + middle.width()) / span
            if target == "bottom_left":
                first = second / 2
            else:
                second = (1 + first) / 2
            self._corner_bottom_ratios = [first, second]
        if self.layout_id == "corner" and self.fullscreen_tile is None:
            self._relayout_corner()

    def _corner_rectangles(self, weights, area):
        main, right_top, right_bottom, *bottom = self.tiles[:6]
        gap = self.grid.spacing()
        minimum_top = max(main.minimumHeight(),
                          right_top.minimumHeight() + gap + right_bottom.minimumHeight())
        minimum_bottom = max(tile.minimumHeight() for tile in bottom)
        minimum_right = max(right_top.minimumWidth(), right_bottom.minimumWidth())
        width, height = max(1, area.width() - gap), max(1, area.height() - gap)
        main_width = max(main.minimumWidth(),
                         min(width - minimum_right, round(width * weights["root/0"][0])))
        top_height = max(minimum_top,
                         min(height - minimum_bottom, round(height * weights["root"][0])))
        x, y = area.left(), area.top()
        right_x, bottom_y = x + main_width + gap, y + top_height + gap
        right_span = top_height - gap
        right_height = max(right_top.minimumHeight(),
                           min(right_span - right_bottom.minimumHeight(),
                               round(right_span * weights["root/0/1"][0])))
        bottom_width = area.width() - 2 * gap
        first = max(bottom[0].minimumWidth(),
                    min(bottom_width - bottom[1].minimumWidth() - bottom[2].minimumWidth(),
                        round(bottom_width * weights["root/1"][0])))
        second = max(first + bottom[1].minimumWidth(),
                     min(bottom_width - bottom[2].minimumWidth(),
                         round(bottom_width * sum(weights["root/1"][:2]))))
        boundaries = (0, first, second, bottom_width)
        if weights["root/0"][0] == 2 / 3:
            # Default columns share one pixel boundary despite different gap counts.
            main_width = max(main.minimumWidth(),
                             min(width - minimum_right, round(bottom_width * 2 / 3) + gap))
            right_x = x + main_width + gap
        rectangles = {
            0: QRect(x, y, main_width, top_height),
            1: QRect(right_x, y, width - main_width, right_height),
            2: QRect(right_x, y + right_height + gap,
                     width - main_width, top_height - gap - right_height),
        }
        for index in range(3):
            start, end = boundaries[index:index + 2]
            rectangles[index + 3] = QRect(x + start + index * gap, bottom_y,
                                          end - start, height - top_height)
        dividers = {
            ("root", 0): QRect(x, y + top_height, area.width(), gap),
            ("root/0", 0): QRect(x + main_width, y, gap, top_height),
            ("root/0/1", 0): QRect(right_x, y + right_height, width - main_width, gap),
            **{("root/1", index): QRect(x + boundaries[index + 1] + index * gap,
                                       bottom_y, gap, height - top_height)
               for index in range(2)},
        }
        return rectangles, dividers

    def _relayout_corner(self, *, apply_visibility: bool = False) -> None:
        if self.picture_in_picture_tiles is not None:
            self._relayout_picture_in_picture()
            return
        if len(self.tiles) < 6:
            return
        old_regions = list(self._divider_rects.values())
        gap = self.grid.spacing()
        if apply_visibility:
            main, right_top, right_bottom, *bottom = self.tiles[:6]
            minimum_top = max(main.minimumHeight(),
                              right_top.minimumHeight() + gap + right_bottom.minimumHeight())
            minimum_bottom = max(tile.minimumHeight() for tile in bottom)
            minimum_right = max(right_top.minimumWidth(), right_bottom.minimumWidth())
            margins = self.grid.contentsMargins()
            minimum_width = max(main.minimumWidth() + gap + minimum_right,
                                sum(tile.minimumWidth() for tile in bottom) + 2 * gap)
            self.setMinimumSize(minimum_width + margins.left() + margins.right(),
                                minimum_top + gap + minimum_bottom + margins.top() + margins.bottom())
        area = self._corner_area()
        tree, weights, widgets, minimum, defaults = self._border_model()
        rectangles, self._divider_rects = self._corner_rectangles(weights, area)
        for cell, rect in rectangles.items():
            widgets[cell].setGeometry(rect)
        widgets = self.pane_danmaku.arrange(rectangles, widgets)
        self._resize_on_show = False
        if apply_visibility:
            for panel in self.pane_danmaku.all_panels():
                panel.setVisible(panel in widgets.values())
            for index, tile in enumerate(self.tiles):
                if tile not in widgets.values():
                    tile.hide()
                elif self._defer_show and tile is not self._stagger_first:
                    self._pending_reveal.append(tile)
                else:
                    tile.show()
        # Repaint exposed gaps without creating another set of interactive widgets.
        for rect in old_regions + list(self._divider_rects.values()):
            self.update(rect)
        self._columns = 3
        _, dividers = resize_layout.geometry(tree, area, gap, minimum, weights, defaults)
        # Use the rendered coordinates (corner rounding differs from the generic allocator).
        dividers = [(node, index, self._divider_rects[(node.key, index)], rect, sizes)
                    for node, index, _handle, rect, sizes in dividers]
        self.pane_danmaku.dividers = dividers
        self._sync_pane_borders(widgets, dividers)

    def visible_tiles(self) -> list[Tile]:
        return [tile for tile in self.tiles if tile.isVisible()]

    def hidden_count(self) -> int:
        return sum(1 for tile in self.tiles if not tile.isVisible())

    def paintEvent(self, event) -> None:
        # 原生视频移动后重绘空隙；皮肤启用时保留背景层的透明通路。
        if not theme._skin_active:
            painter = QPainter(self)
            painter.fillRect(event.rect(), theme.qcolor(theme.BG))
            option = QStyleOption()
            option.initFrom(self)
            self.style().drawPrimitive(QStyle.PE_Widget, option, painter, self)

    def set_interactive_resize(self, active: bool) -> None:
        active = bool(active)
        if not active:
            self._resize_timer.stop()
            self._resize_on_show = self._resize_on_show or self._resize_pending
            self._resize_pending = False
        if active == self._interactive_resize:
            return
        self._interactive_resize = active
        for tile in self.tiles:
            tile.set_interactive_resize(active)

    def finish_resize(self) -> None:
        self._resize_timer.stop()
        self._flush_resize()
        self.set_interactive_resize(False)

    def _flush_resize(self) -> None:
        if not self._resize_pending:
            return
        self._resize_pending = False
        if self._sidebar_animating or self.fullscreen_tile is not None:
            return
        if self.layout_id == "corner":
            self._relayout_corner()
        elif self.layout_id in self._partitions:
            self._relayout_preset()

    def hideEvent(self, event) -> None:
        self.set_interactive_resize(False)
        self._relayout_timer.stop()
        self._cancel_border_drag()
        super().hideEvent(event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if self._quick_danmaku_layer is not None:
            self._quick_danmaku_layer.show()
        if self._resize_on_show:
            self._resize_pending = True
            self._flush_resize()

    def closeEvent(self, event) -> None:
        self.set_interactive_resize(False)
        self._relayout_timer.stop()
        self._cancel_border_drag()
        super().closeEvent(event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if getattr(self, '_fullscreen_layout_pending', False):
            return
        if self.picture_in_picture_tiles is not None:
            self._relayout_picture_in_picture()
            if self._quick_danmaku_layer is not None:
                self._quick_danmaku_layer.resize()
            return
        if self._sidebar_animating:
            if self._quick_danmaku_layer is not None:
                self._quick_danmaku_layer.move_window()
            return
        if self._quick_danmaku_layer is not None:
            self._quick_danmaku_layer.resize()
        self._cancel_border_drag()
        if (self._interactive_resize and self.fullscreen_tile is None
                and (self.layout_id == "corner" or self.layout_id in self._partitions)):
            self._resize_pending = True
            if not self._resize_timer.isActive():
                self._resize_timer.start()
            return
        if self.fullscreen_tile is None and self.layout_id == "corner":
            self._relayout_corner()
            return
        if (self.fullscreen_tile is None and hasattr(self, "_partitions")
                and self.layout_id in self._partitions):
            self._relayout_preset()
            return
        # 兼容未指定预设的旧自动模式，仍由网格布局管理。
        if self.fullscreen_tile is None and self.layout_id == "auto":
            self._relayout_timer.start()
