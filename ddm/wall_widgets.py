"""Video-wall composition, pane geometry and resize presentation."""
import math
import os
import sys

from PySide6.QtCore import QRect, QSize, QTimer, Qt, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QApplication, QGridLayout, QStyle, QStyleOption, QWidget

from . import layouts, resize_layout, theme
from .wall_border import WallBorderInteraction, WallPaneBorder, WallResizePreview
from .danmaku_widgets import DanmakuPanel
from .tile_widgets import Tile
from .widget_support import TILE_BAR_HEIGHT, _repolish
from .wall_layout import WallLayout
from .wall_presentation import WallPresentation


from .wall_geometry import (best_columns)


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
        self.presentation_control = WallPresentation(self)
        self.layout_control = WallLayout(self)
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
        self._border_interaction = WallBorderInteraction(self)

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
        return self.presentation_control.ensure_quick_danmaku_layer()

    def set_picture_in_picture(self, tiles, columns=0, aspects=None, primary=0):
        return self.presentation_control.set_picture_in_picture(tiles, columns, aspects, primary)

    def _relayout_picture_in_picture(self):
        return self.presentation_control.relayout_picture_in_picture()

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
        return self.presentation_control.set_fullscreen_tile(tile, stagger=stagger, first=first)

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
        return self.presentation_control.reveal_tiles_staggered(chunk)

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
        return self.layout_control.capacity()

    def _cells(self) -> list:
        return self.layout_control.cells()

    def _cell_order(self) -> list[int]:
        """画面格子依次用哪些 cell（跳过弹幕占的那一格）。"""
        return self.layout_control.cell_order()

    def main_index(self) -> int | None:
        """当前布局里"主画面"是第几路画面（弹幕格不算）；等分布局返回 None。"""
        return self.layout_control.main_index()

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
        return self.layout_control.cell_of(tile)

    def danmaku_geometry_cell(self):
        """弹幕格当前用的 cell。"""
        return self.layout_control.danmaku_geometry_cell()

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
        return self.layout_control.auto_columns(column_selector=best_columns)

    def set_sidebar_animating(self, active: bool) -> None:
        """收缩期间保持原生视频窗口尺寸，结束后统一调整。"""
        return self.presentation_control.set_sidebar_animating(active)

    def relayout(self, force: bool = False) -> None:
        return self.layout_control.relayout(force)

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
        return self.layout_control.layout_ratios()

    def reset_layout_ratios(self) -> None:
        """只恢复当前预设，不影响其他预设保存的比例。"""
        return self.layout_control.reset_layout_ratios()

    def _preset_defaults(self, node, area):
        return self.layout_control.preset_defaults(node, area)

    def _preset_widgets(self):
        return self.layout_control.preset_widgets()

    def _preset_minimum(self, cell):
        return self.layout_control.preset_minimum(cell)

    def _relayout_preset(self, apply_visibility=False):
        return self.layout_control.relayout_preset(apply_visibility)

    def _sync_pane_borders(self, widgets, dividers):
        return self.layout_control.sync_pane_borders(widgets, dividers, border_type=WallPaneBorder)

    def _repaint_preview_damage(self, region):
        return self.layout_control.repaint_preview_damage(region)

    @property
    def _hover_border(self):
        return self._border_interaction.hover_border

    @property
    def _hover_edges(self):
        return self._border_interaction.hover_edges

    @property
    def _border_drag(self):
        return self._border_interaction.drag

    @property
    def _border_pending(self):
        return self._border_interaction.pending

    @property
    def _border_drag_timer(self):
        return self._border_interaction.timer

    @property
    def _border_preview(self):
        return self._border_interaction.preview

    def _set_hover_border(self, border=None, edges=None):
        return self._border_interaction.set_hover(border, edges)

    def _border_model(self):
        return self.layout_control.border_model()

    def _begin_border_drag(self, border, edges, position):
        return self._border_interaction.begin(border, edges, position)

    def _move_border_drag(self, position):
        return self._border_interaction.move(position)

    def _apply_border_weights(self, weights):
        return self.layout_control.apply_border_weights(weights)

    def _flush_border_drag(self):
        return self._border_interaction.flush()

    def _finish_border_drag(self, border, position):
        return self._border_interaction.finish(border, position)

    def _cancel_border_drag(self):
        if hasattr(self, '_border_interaction'):
            self._border_interaction.cancel()

    def _reset_border(self, border, edges):
        return self.layout_control.reset_border(border, edges)

    def _reset_preset_pair(self, key):
        return self.layout_control.reset_preset_pair(key)

    # ---- 一大五小：手动几何保持视频 HWND 不变，拖动只调整区域比例 ----
    def corner_ratios(self) -> dict:
        """导出独立比例；不依赖当前布局是否显示、窗口尺寸或全屏状态。"""
        return self.layout_control.corner_ratios()

    def restore_corner_ratios(self, saved) -> None:
        """旧配置或非法字段使用默认值；边界也排除 NaN、无穷值和布尔值。"""
        return self.layout_control.restore_corner_ratios(saved)

    def reset_corner_ratios(self) -> None:
        """恢复全部区域比例；保留房间、播放器和每个格子的音频设置。"""
        return self.layout_control.reset_corner_ratios()

    def _corner_area(self) -> QRect:
        return self.layout_control.corner_area()

    def _reset_corner(self, target) -> None:
        return self.layout_control.reset_corner(target)

    def _corner_rectangles(self, weights, area):
        return self.layout_control.corner_rectangles(weights, area)

    def _relayout_corner(self, *, apply_visibility: bool = False) -> None:
        return self.layout_control.relayout_corner(apply_visibility=apply_visibility)

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
        return self.layout_control.set_interactive_resize(active)

    def finish_resize(self) -> None:
        return self.layout_control.finish_resize()

    def _flush_resize(self) -> None:
        return self.layout_control.flush_resize()

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
