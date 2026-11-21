"""Placement and gestures for the wall's two free-placement layouts."""
from PySide6.QtWidgets import QMenu

from . import layouts, snap_grid
from .sidebar_drag import ROOM_MIME, TILE_MIME
from .widget_support import DANMAKU_MIME

DANMAKU_CELL_MIME = 'application/x-ddm-danmaku-cell'


class WallSnapGrid:
    def __init__(self, wall):
        self.wall = wall

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
            resized = snap_grid.resize(self.size, cell, step)
            result = snap_grid.place(self.size, cells, index, resized, self.occupied())
            if result != cells:
                self._commit(result)
        return True

    def _vacancy(self, point):
        if not self.interactive():
            return None
        wall = self.wall
        area = wall._corner_area()
        if not area.contains(point):
            return None
        gap = wall.grid.spacing()
        defaults = wall._cells()
        units = snap_grid.geometry(self.size, defaults, area, gap)
        unit = next((defaults[i] for i, rect in units.items()
                     if rect.adjusted(-gap // 2, -gap // 2, gap // 2, gap // 2).contains(point)), None)
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

    def can_drop(self, mime, point):
        return (any(mime.hasFormat(kind) for kind in (ROOM_MIME, TILE_MIME, DANMAKU_CELL_MIME))
                and self._vacancy(point) is not None)

    def drop(self, mime, point):
        vacancy = self._vacancy(point)
        if vacancy is None:
            return False
        wall = self.wall
        unit, cells = vacancy
        if mime.hasFormat(DANMAKU_MIME):
            value = bytes(mime.data(DANMAKU_CELL_MIME))
            if not value.isdigit() or (source := int(value)) not in wall.pane_danmaku.bindings():
                return False
        else:
            kind = TILE_MIME if mime.hasFormat(TILE_MIME) else ROOM_MIME
            room_id = bytes(mime.data(kind)).decode('utf-8', 'ignore')
            if not room_id:
                return False
            source = next((i for i, tile in wall.pane_danmaku.cell_tiles().items()
                           if str(tile.room.get('room_id') or '') == room_id
                           and not tile.isHidden()), None)
        if source is not None:
            if cells[source] is None:
                return False
            row, column, _, _ = unit
            height, width = cells[source][2:]
            if row + height > self.size or column + width > self.size:
                return False
            result = snap_grid.place(self.size, cells, source, (row, column, height, width), self.occupied())
            if result == cells:
                return False
            self._commit(result)
        else:
            index = next(i for i in range(len(cells)) if i not in self.occupied())
            result = snap_grid.place(self.size, cells, index, unit, self.occupied())
            base = wall.layout_id
            previous = wall._layout_ratios[base]
            if result != cells:
                wall.layout_control.set_preset_ratios(base, {'grid': result})
            tile = wall.tiles[index]
            wall.roomDropped.emit(tile, room_id)
            if str(tile.room.get('room_id') or '') != room_id:
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
