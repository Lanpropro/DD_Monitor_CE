"""Placement and gestures for the wall's two free-placement layouts."""
from dataclasses import dataclass

from PySide6.QtWidgets import QMenu

from . import layouts, snap_grid
from .sidebar_drag import GRID_GRAB_MIME, ROOM_MIME, TILE_MIME
from .widget_support import DANMAKU_MIME

DANMAKU_CELL_MIME = 'application/x-ddm-danmaku-cell'


@dataclass
class _Placement:
    index: int
    target: tuple
    cells: list
    changed: bool
    new_room: str | None


class WallSnapGrid:
    def __init__(self, wall):
        self.wall = wall
        self.guide = None

    @property
    def size(self):
        return layouts.snap_grid_size(self.wall.layout_id)

    def interactive(self):
        wall = self.wall
        return bool(self.size and wall.fullscreen_tile is None and not wall._fullscreen_layout_pending
                    and wall.picture_in_picture_tiles is None)

    def occupied(self):
        panes = self.wall.pane_danmaku
        return set(panes.bindings()) | {cell for cell, tile in panes.cell_tiles().items()
                                        if tile.room.get('room_id')}

    def cells(self):
        wall = self.wall
        saved = wall._layout_ratios[wall.layout_id].get('grid', wall._cells())
        return snap_grid.with_occupied(saved, self.occupied())

    def free_tiles(self):
        occupied = self.occupied()
        cells = self.cells()
        return [tile for cell, tile in self.wall.pane_danmaku.cell_tiles().items()
                if cell not in occupied and cells[cell] is not None]

    def sync_visibility(self):
        if self.interactive():
            wall = self.wall
            wanted = set(wall._preset_widgets().values())
            if any(tile.isHidden() == (tile in wanted) for tile in wall.tiles):
                wall._relayout_preset(apply_visibility=True)

    def watch_new_room_aspect(self, tile):
        if self.interactive():
            cell = self.wall.layout_control.cell_of(tile)
            if cell is not None and cell[2:] == (1, 1):
                tile.state_control.pending_grid_aspect = self.wall.layout_id

    def wants_video_aspect(self, tile):
        return tile.state_control.pending_grid_aspect is not None

    def cancel_aspect_requests(self, base):
        for tile in self.wall.tiles:
            if tile.state_control.pending_grid_aspect == base:
                tile.state_control.pending_grid_aspect = None

    def apply_video_aspect(self, tile, aspect):
        base = tile.state_control.pending_grid_aspect
        tile.state_control.pending_grid_aspect = None
        if (base != self.wall.layout_id or not self.interactive() or tile.isHidden()
                or aspect is None or aspect >= 1):
            return
        index = self.wall.pane_danmaku.cell_for_tile(tile)
        if index is None or index in self.wall.pane_danmaku.bindings():
            return
        cells = self.cells()
        cell = cells[index]
        if cell is None or cell[2:] != (1, 1) or cell[0] + 2 > self.size:
            return
        row, column, _, _ = cell
        result = snap_grid.place(self.size, cells, index, (row, column, 2, 1), self.occupied())
        if result != cells:
            self._commit(result)

    def _commit(self, cells):
        wall = self.wall
        hidden = [tile for tile in wall.tiles if tile.isHidden() and tile.room.get('room_id')]
        wall.layout_control.set_preset_ratios(wall.layout_id, {'grid': cells})
        wall._relayout_preset(apply_visibility=True)
        wall.layoutRatiosChanged.emit()
        if any(not tile.isHidden() for tile in hidden):
            wall.paneConfigurationChanged.emit()

    def resize_tile(self, tile, step):
        if not self.interactive() or not tile.room.get('room_id') or tile.isHidden():
            return False
        index = self.wall.pane_danmaku.cell_for_tile(tile)
        if index is None:
            return False
        cells = self.cells()
        cell = cells[index]
        if cell is not None:
            tile.state_control.pending_grid_aspect = None
            resized = snap_grid.resize(self.size, cell, step)
            result = snap_grid.place(self.size, cells, index, resized, self.occupied())
            if result != cells:
                self._commit(result)
        return True

    def _unit_at(self, point):
        if not self.interactive():
            return None
        wall = self.wall
        area = wall._corner_area()
        if not area.contains(point):
            return None
        gap = wall.grid.spacing()
        defaults = wall._cells()
        units = snap_grid.geometry(self.size, defaults, area, gap)
        return next((defaults[i] for i, rect in units.items()
                     if rect.adjusted(-gap // 2, -gap // 2, gap // 2, gap // 2).contains(point)), None)

    def _vacancy(self, point):
        unit = self._unit_at(point)
        if unit is None:
            return None
        row, column, _, _ = unit
        cells = self.cells()
        index = next(i for i, cell in enumerate(cells)
                     if cell is not None and cell[0] <= row < cell[0] + cell[2]
                     and cell[1] <= column < cell[1] + cell[3])
        if index not in self.occupied():
            return unit, cells
        return None

    def mark_drag(self, mime, tile, press):
        if not self.interactive():
            return False
        index = self.wall.pane_danmaku.cell_for_tile(tile)
        unit = self._unit_at(tile.mapTo(self.wall, press))
        if index is None or unit is None or (cell := self.cells()[index]) is None:
            return False
        row, column, height, width = cell
        dy, dx = unit[0] - row, unit[1] - column
        if not (0 <= dy < height and 0 <= dx < width):
            return False
        mime.setData(GRID_GRAB_MIME, bytes((index, dy, dx)))
        return True

    def show_drag_guide(self, mime, point):
        if not self.interactive():
            self.hide_drag_guide()
            return
        if self.guide is None:
            from .snap_grid_guide import SnapGridGuide
            self.guide = SnapGridGuide(self.wall)
        wall = self.wall
        area, gap = wall._corner_area(), wall.grid.spacing()
        units = tuple(snap_grid.geometry(self.size, wall._cells(), area, gap).values())
        plan = self._placement(mime, point)
        target = snap_grid.geometry(self.size, [plan.target], area, gap)[0] if plan else None
        self.guide.present(units, target)

    def hide_drag_guide(self):
        if self.guide is not None:
            self.guide.hide()

    def can_drop(self, mime, point):
        return self._placement(mime, point) is not None

    def _placement(self, mime, point):
        unit = self._unit_at(point)
        if unit is None:
            return None
        wall = self.wall
        cells = self.cells()
        occupied = self.occupied()
        new_room = None
        dy, dx = 0, 0
        if mime.hasFormat(DANMAKU_MIME):
            value = bytes(mime.data(DANMAKU_CELL_MIME))
            if not value.isdigit() or (index := int(value)) not in wall.pane_danmaku.bindings():
                return None
        elif mime.hasFormat(TILE_MIME) or mime.hasFormat(ROOM_MIME):
            kind = TILE_MIME if mime.hasFormat(TILE_MIME) else ROOM_MIME
            room_id = bytes(mime.data(kind)).decode('utf-8', 'ignore')
            if not room_id:
                return None
            tiles = wall.pane_danmaku.cell_tiles()
            if mime.hasFormat(GRID_GRAB_MIME):
                grab = bytes(mime.data(GRID_GRAB_MIME))
                if len(grab) != 3:
                    return None
                index, dy, dx = grab
                tile = tiles.get(index)
                if tile is None or tile.isHidden() or str(tile.room.get('room_id') or '') != room_id:
                    return None
            else:
                index = next((i for i, tile in tiles.items() if not tile.isHidden()
                              and str(tile.room.get('room_id') or '') == room_id), None)
        else:
            return None
        row, column, height, width = unit
        if index is None:
            index = next((i for i in range(len(cells)) if i not in occupied), None)
            if index is None:
                return None
            new_room = room_id
        elif cells[index] is not None:
            height, width = cells[index][2:]
            row, column = row - dy, column - dx
        else:
            return None
        if not (0 <= row <= self.size - height and 0 <= column <= self.size - width):
            return None
        target = row, column, height, width
        result = snap_grid.place(self.size, cells, index, target, occupied)
        changed = result != cells
        if changed or target == cells[index]:
            return _Placement(index, target, result, changed, new_room)
        return None

    def drop(self, mime, point):
        plan = self._placement(mime, point)
        if plan is None:
            return False
        wall = self.wall
        if plan.new_room is None:
            if plan.changed:
                self._commit(plan.cells)
        else:
            base = wall.layout_id
            previous = wall._layout_ratios[base]
            if plan.changed:
                wall.layout_control.set_preset_ratios(base, {'grid': plan.cells})
            tile = wall.tiles[plan.index]
            wall.roomDropped.emit(tile, plan.new_room)
            if str(tile.room.get('room_id') or '') != plan.new_room:
                wall._layout_ratios[base] = previous
                return False
            wall.layoutRatiosChanged.emit()
        return True

    def open_menu(self, point, global_point):
        if self._vacancy(point) is None:
            return False
        menu = QMenu(self.wall)
        menu.addAction('添加弹幕格', lambda: self.add_danmaku(point))
        menu.aboutToHide.connect(menu.deleteLater)
        menu.popup(global_point)
        return True

    def add_danmaku(self, point):
        vacancy = self._vacancy(point)
        if vacancy is not None:
            unit, cells = vacancy
            occupied = self.occupied()
            index = next(i for i in reversed(range(len(cells))) if i not in occupied)
            result = snap_grid.place(self.size, cells, index, unit, occupied)
            if result != cells:
                self._commit(result)
            self.wall.pane_danmaku.request(index, -1)
