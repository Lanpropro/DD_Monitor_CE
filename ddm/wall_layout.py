"""Video wall layout geometry, ratios and resize settlement; WallGrid owns all mutable state."""
import math
from PySide6.QtCore import QRect, QSize, QTimer, Qt, Signal
from . import layouts, resize_layout, theme
from .tile_widgets import Tile


class WallLayout:
    def __init__(self, host):
        self.host = host

    def capacity(self) -> int:
        """当前布局能放几路；自动布局返回 0（格子数跟着房间数走）。"""
        host = self.host
        if host.layout_id == "auto":
            return 0
        return len(host._cell_order())

    def cells(self) -> list:
        host = self.host
        layout = layouts.BY_ID.get(host.layout_id)
        if not layout or not layout.get("spec"):
            return []
        return layout["spec"][2]

    def cell_order(self) -> list[int]:
        """画面格子依次用哪些 cell（跳过弹幕占的那一格）。"""
        host = self.host
        cells = host._cells()
        if host.pane_danmaku.custom:
            return list(range(len(cells)))
        return [index for index in range(len(cells)) if index != host._danmaku_cell]

    def main_index(self) -> int | None:
        """当前布局里"主画面"是第几路画面（弹幕格不算）；等分布局返回 None。"""
        host = self.host
        cells = host._cells()
        order = host._cell_order()
        if not cells or not order:
            return None
        areas = [0 if cell in host.pane_danmaku.bindings() else cells[cell][2] * cells[cell][3]
                 for cell in order]
        if len(set(areas)) <= 1:
            return None
        return areas.index(max(areas))

    def cell_of(self, tile: Tile):
        """这一路画面用的是哪个 cell（排查布局问题时用）。"""
        host = self.host
        order = host._cell_order()
        try:
            index = host.tiles.index(tile)
        except ValueError:
            return None
        cells = host._cells()
        if not cells or index >= len(order):
            return None
        return cells[order[index]]

    def danmaku_geometry_cell(self):
        """弹幕格当前用的 cell。"""
        host = self.host
        cells = host._cells()
        if host._danmaku_cell is None or not cells:
            return None
        return cells[host._danmaku_cell]

    def auto_columns(self, *, column_selector) -> int:
        host = self.host
        best_columns = column_selector
        height = max(host.height(), 1)
        count = len(host.tiles)
        if host._columns > 0 and height == host._last_height and count == host._last_count:
            return host._columns          # 只有宽度变化（收起侧栏）时保持原布局
        host._last_height = height
        host._last_count = count
        return best_columns(count, max(host.width(), 1), height)

    def relayout(self, force: bool = False) -> None:
        host = self.host
        if host.picture_in_picture_tiles is not None:
            host._relayout_picture_in_picture()
            return
        if host._fullscreen_layout_pending:
            return
        host.pane_danmaku.prepare()
        host.sync_sc_placement()
        if host._sidebar_animating:
            return
        if force:
            host._relayout_timer.stop()
            host._resize_timer.stop()
            host._resize_pending = False
        host.ensure_slots()          # 按布局补空位
        host._sync_danmaku_controls()
        if not host.tiles:
            return
        layout = layouts.BY_ID.get(host.layout_id)     # 老配置可能存着已经删掉的布局
        spec = None if layout is None else layout.get("spec")
        if not force and spec is None:
            # 自动模式：列数没变就不用重排
            if host._auto_columns() == host._columns:
                return
        host._clear()
        for panel in host.pane_danmaku.all_panels():
            panel.hide()

        if host.fullscreen_tile is not None:
            host.danmaku.setVisible(False)
            for tile in host.tiles:
                if tile is host.fullscreen_tile:
                    host.grid.addWidget(tile, 0, 0)
                    tile.setVisible(True)
                else:
                    tile.setVisible(False)
            host.grid.setColumnStretch(0, 1)
            host.grid.setRowStretch(0, 1)
            return

        if host.layout_id == "corner":
            host._relayout_corner(apply_visibility=True)
            return

        if spec is None:
            host.danmaku.setVisible(False)
            columns = host._auto_columns()
            host._columns = columns
            for index, tile in enumerate(host.tiles):
                host.grid.addWidget(tile, index // columns, index % columns)
                tile.setVisible(True)
            for column in range(columns):
                host.grid.setColumnStretch(column, 1)
            for row in range(math.ceil(len(host.tiles) / columns)):
                host.grid.setRowStretch(row, 1)
            return

        host._relayout_preset(apply_visibility=True)

    def layout_ratios(self) -> dict:
        host = self.host
        return {identifier: {key: list(values) for key, values in ratios.items()}
                for identifier, ratios in host._layout_ratios.items() if ratios}

    def reset_layout_ratios(self) -> None:
        """只恢复当前预设，不影响其他预设保存的比例。"""
        host = self.host
        host._cancel_border_drag()
        if host.layout_id == "corner":
            host.reset_corner_ratios()
            return
        changed = bool(host._layout_ratios.get(host.layout_id))
        host._layout_ratios[host.layout_id] = {}
        if host.fullscreen_tile is None:
            host._relayout_preset()
        if changed:
            host.layoutRatiosChanged.emit()

    def preset_defaults(self, node, area):
        host = self.host
        if node.key != "root" or not layouts.is_portrait_layout(host.layout_id):
            return node.weights
        gap = host.grid.spacing()
        main = max(80, int(area.width() * 9 / 16))
        danmaku = max(140, int(area.height() * .22)) if layouts.danmaku_cell(host.layout_id) is not None else 0
        small = max(1, area.height() - main - danmaku - gap * (len(node.children) - 1))
        return [main, small, danmaku] if layouts.danmaku_cell(host.layout_id) is not None else [main, small]

    def preset_widgets(self):
        host = self.host
        if host.pane_danmaku.custom:
            widgets = host.pane_danmaku.cell_tiles()
            widgets.update(host.pane_danmaku.panels)
            return widgets
        if layouts.is_portrait_layout(host.layout_id):
            # 竖屏弹幕始终占底部，与原竖屏规则一致。
            count = host._capacity()
            widgets = {index: tile for index, tile in enumerate(host.tiles[:count])}
            if host.has_danmaku:
                widgets[count] = host.danmaku
            return widgets
        widgets = {cell: tile for cell, tile in zip(host._cell_order(), host.tiles)}
        if host.has_danmaku:
            widgets[host._danmaku_cell] = host.danmaku
        return widgets

    def preset_minimum(self, cell):
        host = self.host
        widget = host._preset_widgets().get(cell)
        if widget in host.pane_danmaku.all_panels():
            return QSize(max(200, widget.minimumWidth()), max(140, widget.minimumHeight()))
        return QSize(max(200, widget.minimumWidth()), max(150, widget.minimumHeight()))

    def relayout_preset(self, apply_visibility=False):
        host = self.host
        if host.picture_in_picture_tiles is not None:
            host._relayout_picture_in_picture()
            return
        if host.fullscreen_tile is not None or host.layout_id not in host._partitions:
            return
        widgets = host._preset_widgets()
        if len(widgets) < len(host._cells()):
            # 应用切方向时先选预设、再调整窗口、最后补齐格子；中间的 resize 不排布。
            return
        tree = host._partitions[host.layout_id]
        gap = host.grid.spacing()
        margins = host.grid.contentsMargins()
        minimum = tree.minimum(gap, host._preset_minimum)
        host.setMinimumSize(minimum.width() + margins.left() + margins.right(),
                            minimum.height() + margins.top() + margins.bottom())
        area = host._corner_area()
        # 顶层窗口尺寸变更可能在下一次事件循环才完成，计算区域也遵守最小尺寸。
        area.setWidth(max(area.width(), minimum.width()))
        area.setHeight(max(area.height(), minimum.height()))
        leaves, dividers = resize_layout.geometry(
            tree, area, gap, host._preset_minimum,
            host._layout_ratios[host.layout_id], host._preset_defaults)
        for cell, rect in leaves.items():
            widget = widgets[cell]
            same_size = widget.size() == rect.size()
            widget.setGeometry(rect)
            if isinstance(widget, Tile) and same_size:
                # One equal cell can retain its size while its neighbour gains
                # the last pixel. Resized cells use their existing resize path.
                widget._layout_bottom_controls()
        host.pane_danmaku.dividers = dividers
        widgets = host.pane_danmaku.arrange(leaves, widgets)
        host._resize_on_show = False
        if apply_visibility:
            active = set(widgets.values())
            for tile in host.tiles:
                if tile not in active:
                    tile.hide()
                elif host._defer_show and tile is not host._stagger_first:
                    host._pending_reveal.append(tile)
                else:
                    tile.show()
            for panel in host.pane_danmaku.all_panels():
                panel.setVisible(panel in active)
        old_regions = list(host._divider_rects.values())
        host._preset_dividers = {}
        host._divider_rects = {}
        for node, index, rect, node_area, sizes in dividers:
            key = (node.key, index)
            host._preset_dividers[key] = (node, node_area, sizes)
            host._divider_rects[key] = rect
        for rect in old_regions + list(host._divider_rects.values()):
            host.update(rect)
        host._columns = layouts.BY_ID[host.layout_id]["spec"][1]
        host._sync_pane_borders(widgets, dividers)

    def sync_pane_borders(self, widgets, dividers, *, border_type):
        host = self.host
        WallPaneBorder = border_type
        for pane, border in list(host._pane_borders.items()):
            if pane not in host.tiles and pane not in host.pane_danmaku.all_panels():
                del host._pane_borders[pane]
            elif pane not in widgets.values() or pane.isHidden():
                border.hide()
        for pane in widgets.values():
            if pane not in host._pane_borders:
                host._pane_borders[pane] = WallPaneBorder(pane, host)
            targets = resize_layout.border_targets(pane.geometry(), dividers)
            host._pane_borders[pane].sync(targets)
        host._set_hover_border(host._hover_border, host._hover_edges)

    def repaint_preview_damage(self, region):
        host = self.host
        if region.isEmpty():
            return
        # Native mask changes expose stale Qt backing-store pixels unless owners repaint them.
        host.update(region)
        for pane, border in host._pane_borders.items():
            if pane.isVisible():
                local = region.translated(-pane.pos()).intersected(pane.rect())
                if not local.isEmpty():
                    pane.update(local)
                    if border.isVisible():
                        border.update(local.intersected(border.mask()))

    def border_model(self):
        host = self.host
        if host.layout_id == "corner":
            tree = resize_layout.build_partition(layouts.BY_ID["corner"]["spec"][2])
            first, second = host._corner_bottom_ratios
            weights = {"root": [host._corner_height_ratio, 1 - host._corner_height_ratio],
                       "root/0": [host._corner_width_ratio, 1 - host._corner_width_ratio],
                       "root/0/1": [host._corner_right_ratio, 1 - host._corner_right_ratio],
                       "root/1": [first, second - first, 1 - second]}
            widgets = host._preset_widgets()
            minimum = lambda cell: widgets[cell].minimumSize()
            return tree, weights, widgets, minimum, None
        return (host._partitions[host.layout_id], host._layout_ratios[host.layout_id],
                host._preset_widgets(), host._preset_minimum, host._preset_defaults)

    def apply_border_weights(self, weights):
        host = self.host
        if host.layout_id == "corner":
            host._corner_height_ratio = weights["root"][0]
            host._corner_width_ratio = weights["root/0"][0]
            host._corner_right_ratio = weights["root/0/1"][0]
            bottom = weights["root/1"]
            host._corner_bottom_ratios = [bottom[0], bottom[0] + bottom[1]]
            host._relayout_corner()
        else:
            host._layout_ratios[host.layout_id] = weights
            host._relayout_preset()

    def reset_border(self, border, edges):
        host = self.host
        if host.fullscreen_tile is not None or not border.isVisible() or not edges:
            return
        host._cancel_border_drag()
        keys = list(dict.fromkeys(value for edge, value in edges.items()
                                  if border.targets.get(edge) == value))
        before = host.corner_ratios() if host.layout_id == "corner" else host.layout_ratios()
        if host.layout_id == "corner":
            targets = {("root", 0): Qt.Vertical, ("root/0", 0): Qt.Horizontal,
                       ("root/0/1", 0): "right", ("root/1", 0): "bottom_left",
                       ("root/1", 1): "bottom_right"}
            for key in keys:
                host._reset_corner(targets[key])
            if host.corner_ratios() != before:
                host.cornerRatiosChanged.emit()
        else:
            for key in keys:
                host._reset_preset_pair(key)
            if host.layout_ratios() != before:
                host.layoutRatiosChanged.emit()

    def reset_preset_pair(self, key):
        host = self.host
        node, area, current = host._preset_dividers[key]
        index = key[1]
        defaults = host._preset_defaults(node, area)
        sizes = list(current)
        pair = current[index] + current[index + 1]
        minimums = [child.minimum(host.grid.spacing(), host._preset_minimum) for child in node.children]
        spans = [size.width() if node.axis == Qt.Horizontal else size.height() for size in minimums]
        sizes[index] = max(spans[index], min(pair - spans[index + 1],
                           round(pair * defaults[index] / (defaults[index] + defaults[index + 1]))))
        sizes[index + 1] = pair - sizes[index]
        host._layout_ratios[host.layout_id][node.key] = [size / sum(sizes) for size in sizes]
        host._relayout_preset()

    def corner_ratios(self) -> dict:
        """导出独立比例；不依赖当前布局是否显示、窗口尺寸或全屏状态。"""
        host = self.host
        return {"width": host._corner_width_ratio, "height": host._corner_height_ratio,
                "right": host._corner_right_ratio, "bottom": list(host._corner_bottom_ratios)}

    def restore_corner_ratios(self, saved) -> None:
        """旧配置或非法字段使用默认值；边界也排除 NaN、无穷值和布尔值。"""
        host = self.host
        saved = saved if isinstance(saved, dict) else {}

        def valid(value):
            return type(value) in (int, float) and 0 < value < 1

        for name, attribute, default in (("width", "_corner_width_ratio", 2 / 3),
                                         ("height", "_corner_height_ratio", 2 / 3),
                                         ("right", "_corner_right_ratio", 1 / 2)):
            value = saved.get(name)
            setattr(host, attribute, float(value) if valid(value) else default)
        bottom = saved.get("bottom")
        if (isinstance(bottom, (list, tuple)) and len(bottom) == 2
                and all(valid(value) for value in bottom) and bottom[0] < bottom[1]):
            host._corner_bottom_ratios = [float(value) for value in bottom]
        else:
            host._corner_bottom_ratios = [1 / 3, 2 / 3]
        if host.tiles and host.layout_id == "corner" and host.fullscreen_tile is None:
            host._relayout_corner()

    def reset_corner_ratios(self) -> None:
        """恢复全部区域比例；保留房间、播放器和每个格子的音频设置。"""
        host = self.host
        before = host.corner_ratios()
        host._cancel_border_drag()
        host.restore_corner_ratios(None)
        if host.corner_ratios() != before:
            host.cornerRatiosChanged.emit()

    def corner_area(self) -> QRect:
        host = self.host
        margins = host.grid.contentsMargins()
        return host.rect().adjusted(margins.left(), margins.top(),
                                    -margins.right(), -margins.bottom())

    def reset_corner(self, target) -> None:
        host = self.host
        if target == Qt.Horizontal:
            host._corner_width_ratio = 2 / 3
        elif target == Qt.Vertical:
            host._corner_height_ratio = 2 / 3
        elif target == "right":
            host._corner_right_ratio = 1 / 2
        elif target in ("bottom_left", "bottom_right"):
            left, middle, right = host.tiles[3:6]
            span = max(1, left.width() + middle.width() + right.width())
            first, second = left.width() / span, (left.width() + middle.width()) / span
            if target == "bottom_left":
                first = second / 2
            else:
                second = (1 + first) / 2
            host._corner_bottom_ratios = [first, second]
        if host.layout_id == "corner" and host.fullscreen_tile is None:
            host._relayout_corner()

    def corner_rectangles(self, weights, area):
        host = self.host
        main, right_top, right_bottom, *bottom = host.tiles[:6]
        gap = host.grid.spacing()
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

    def relayout_corner(self, *, apply_visibility: bool = False) -> None:
        host = self.host
        if host.picture_in_picture_tiles is not None:
            host._relayout_picture_in_picture()
            return
        if len(host.tiles) < 6:
            return
        old_regions = list(host._divider_rects.values())
        gap = host.grid.spacing()
        if apply_visibility:
            main, right_top, right_bottom, *bottom = host.tiles[:6]
            minimum_top = max(main.minimumHeight(),
                              right_top.minimumHeight() + gap + right_bottom.minimumHeight())
            minimum_bottom = max(tile.minimumHeight() for tile in bottom)
            minimum_right = max(right_top.minimumWidth(), right_bottom.minimumWidth())
            margins = host.grid.contentsMargins()
            minimum_width = max(main.minimumWidth() + gap + minimum_right,
                                sum(tile.minimumWidth() for tile in bottom) + 2 * gap)
            host.setMinimumSize(minimum_width + margins.left() + margins.right(),
                                minimum_top + gap + minimum_bottom + margins.top() + margins.bottom())
        area = host._corner_area()
        tree, weights, widgets, minimum, defaults = host._border_model()
        rectangles, host._divider_rects = host._corner_rectangles(weights, area)
        for cell, rect in rectangles.items():
            widgets[cell].setGeometry(rect)
        widgets = host.pane_danmaku.arrange(rectangles, widgets)
        host._resize_on_show = False
        if apply_visibility:
            for panel in host.pane_danmaku.all_panels():
                panel.setVisible(panel in widgets.values())
            for index, tile in enumerate(host.tiles):
                if tile not in widgets.values():
                    tile.hide()
                elif host._defer_show and tile is not host._stagger_first:
                    host._pending_reveal.append(tile)
                else:
                    tile.show()
        # Repaint exposed gaps without creating another set of interactive widgets.
        for rect in old_regions + list(host._divider_rects.values()):
            host.update(rect)
        host._columns = 3
        _, dividers = resize_layout.geometry(tree, area, gap, minimum, weights, defaults)
        # Use the rendered coordinates (corner rounding differs from the generic allocator).
        dividers = [(node, index, host._divider_rects[(node.key, index)], rect, sizes)
                    for node, index, _handle, rect, sizes in dividers]
        host.pane_danmaku.dividers = dividers
        host._sync_pane_borders(widgets, dividers)

    def set_interactive_resize(self, active: bool) -> None:
        host = self.host
        active = bool(active)
        if not active:
            host._resize_timer.stop()
            host._resize_on_show = host._resize_on_show or host._resize_pending
            host._resize_pending = False
        if active == host._interactive_resize:
            return
        host._interactive_resize = active
        for tile in host.tiles:
            tile.set_interactive_resize(active)

    def finish_resize(self) -> None:
        host = self.host
        host._resize_timer.stop()
        host._flush_resize()
        host.set_interactive_resize(False)

    def flush_resize(self) -> None:
        host = self.host
        if not host._resize_pending:
            return
        host._resize_pending = False
        if host._sidebar_animating or host.fullscreen_tile is not None:
            return
        if host.layout_id == "corner":
            host._relayout_corner()
        elif host.layout_id in host._partitions:
            host._relayout_preset()
