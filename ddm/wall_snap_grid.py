"""Placement and gestures for the wall's two free-placement layouts."""
from dataclasses import dataclass
from time import monotonic

from PySide6.QtWidgets import QMenu, QWidget

from . import layouts, snap_grid
from .sidebar_drag import GRID_GRAB_MIME, ROOM_MIME, TILE_MIME
from .widget_support import DANMAKU_CELL_MIME, DANMAKU_MIME


@dataclass
class _Placement:
    index: int
    target: tuple
    cells: list
    changed: bool
    new_room: str | None


@dataclass
class _TileSwap:
    source: QWidget
    destination: QWidget


class WallSnapGrid:
    def __init__(self, wall):
        self.wall = wall
        self.guide = None
        self._orientation_checks = {}
        self._orientations = {}
        self._pending_drops = {}

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
            if cell is not None and cell[2] == cell[3]:
                tile.state_control.pending_grid_aspect = self.wall.layout_id

    def wants_video_aspect(self, tile):
        return tile.state_control.pending_grid_aspect is not None

    def cancel_aspect_requests(self, base):
        if base == self.wall.layout_id:
            self.cancel_pending_drops()
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
        if cell is None or cell[2] != cell[3]:
            return
        plan = self._portrait_placement(cells, self.occupied(), index, cell)
        if plan is not None and plan.changed:
            self._commit(plan.cells)

    def _portrait_placement(self, cells, occupied, index, anchor, room_id=None):
        for rows in ((3, 2) if self.size == 4 else (2,)):
            target = snap_grid.portrait_cell(self.size, anchor, rows)
            result = snap_grid.place(self.size, cells, index, target, occupied)
            if result != cells or target == cells[index]:
                return _Placement(index, target, result, result != cells, room_id)
        return None

    def prepare_room_drag(self, mime):
        if not mime.hasFormat(ROOM_MIME):
            return
        room_id = bytes(mime.data(ROOM_MIME)).decode('utf-8', 'ignore')
        host = self.wall.window()
        if not room_id.isdigit() or not hasattr(host, 'sidebar') or host._tile_of(room_id) is not None:
            return
        room = next((item for item in host.sidebar.rooms() if str(item.get('room_id')) == room_id), None)
        if room is None or not room.get('live'):
            return
        started = room.get('live_start_ts')
        cached = self._orientations.get(room_id)
        if room_id in self._orientation_checks or (cached and cached[0] == started and cached[1] > monotonic()):
            return
        self._orientations.pop(room_id, None)
        from .bili_workers import RoomOrientation
        worker = RoomOrientation(room_id, host)
        self._orientation_checks[room_id] = worker
        host._platform_info_running.add(worker)
        worker.finished.connect(lambda: self._orientation_ready(worker, started))
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _orientation_ready(self, worker, started):
        host = self.wall.window()
        host._platform_info_running.discard(worker)
        room_id = worker.room_id
        self._orientation_checks.pop(room_id, None)
        unit = self._pending_drops.pop(room_id, None)
        if host._closing:
            return
        if worker.portrait is not None:
            self._orientations[room_id] = (started, monotonic() + 60, worker.portrait)
        host.sidebar.drag_session.refresh_snap_target(self)
        if unit is not None and self.interactive() and host._tile_of(room_id) is None:
            if plan := self._new_room_placement(room_id, unit, self.cells(), self.occupied()):
                self._place_room(plan, self.wall.roomDropped.emit)

    def cancel_pending_drops(self):
        self._pending_drops.clear()

    def _commit(self, cells):
        wall = self.wall
        hidden = [tile for tile in wall.tiles if tile.isHidden() and tile.room.get('room_id')]
        wall.layout_control.set_preset_ratios(wall.layout_id, {'grid': cells})
        wall._relayout_preset(apply_visibility=True)
        wall.layoutRatiosChanged.emit()
        if any(not tile.isHidden() for tile in hidden):
            wall.paneConfigurationChanged.emit()

    def _room_cell(self, tile):
        if self.interactive() and tile.room.get('room_id') and not tile.isHidden():
            return self.wall.pane_danmaku.cell_for_tile(tile)
        return None

    def resize_tile(self, tile, step, *, height_only=False):
        index = self._room_cell(tile)
        if index is None:
            return False
        cells = self.cells()
        cell = cells[index]
        if cell is not None:
            tile.state_control.pending_grid_aspect = None
            resize = snap_grid.resize_height if height_only else snap_grid.resize
            resized = resize(self.size, cell, step)
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

    def _vacancy(self, unit):
        if unit is None or not self.interactive():
            return None
        row, column, _, _ = unit
        cells = self.cells()
        index = next(i for i, cell in enumerate(cells)
                     if cell is not None and cell[0] <= row < cell[0] + cell[2]
                     and cell[1] <= column < cell[1] + cell[3])
        if index not in self.occupied():
            return index, cells
        return None

    def vacant_unit_at(self, point):
        unit = self._unit_at(point)
        return unit if self._vacancy(unit) is not None else None

    def place_room_in_unit(self, unit, room_id, assign):
        vacancy = self._vacancy(unit)
        if vacancy is None:
            return False
        index, cells = vacancy
        result = snap_grid.place(self.size, cells, index, unit, self.occupied())
        return self._place_room(_Placement(index, unit, result, result != cells, room_id), assign)

    def floating_chat_target(self, point):
        unit = self._unit_at(point)
        vacancy = self._vacancy(unit)
        if vacancy is None:
            return None
        index, cells = vacancy
        planned = snap_grid.place(self.size, cells, index, unit, self.occupied())
        if planned[index] == unit:
            wall = self.wall
            rect = snap_grid.geometry(self.size, [unit], wall._corner_area(), wall.grid.spacing())[0]
            return index, rect, planned

    def drag_units(self):
        wall = self.wall
        return tuple(snap_grid.geometry(self.size, wall._cells(), wall._corner_area(), wall.grid.spacing()).values())

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
        wall = self.wall
        area, gap = wall._corner_area(), wall.grid.spacing()
        units = self.drag_units()
        plan = self._placement(mime, point)
        if isinstance(plan, _TileSwap):
            self.present_drag_guide(units, plan.destination.geometry(), swap_source=plan.source.geometry())
            return
        target = (snap_grid.geometry(self.size, [plan.target], area, gap)[0]
                  if plan and plan.new_room not in self._orientation_checks else None)
        self.present_drag_guide(units, target)

    def present_drag_guide(self, units, target, *, swap_source=None):
        if self.guide is None:
            from .snap_grid_guide import SnapGridGuide
            self.guide = SnapGridGuide(self.wall)
        self.guide.present(units, target, swap_source=swap_source)

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
            if kind == TILE_MIME and index is not None and (swap := self._swap_at(tiles, index, point)):
                return swap
        else:
            return None
        row, column, height, width = unit
        if index is None:
            return self._new_room_placement(room_id, unit, cells, occupied)
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
            return _Placement(index, target, result, changed, None)
        return None

    def _swap_at(self, tiles, source_index, point):
        chat_cells = self.wall.pane_danmaku.bindings()
        if source_index not in chat_cells:
            for index, tile in tiles.items():
                if (index != source_index and index not in chat_cells and not tile.isHidden()
                        and tile.room.get('room_id') and tile.geometry().contains(point)):
                    return _TileSwap(tiles[source_index], tile)
        return None

    def _new_room_placement(self, room_id, unit, cells, occupied):
        index = next((i for i in range(len(cells)) if i not in occupied), None)
        if index is None:
            return None
        if (orientation := self._orientations.get(room_id)) and orientation[1] > monotonic() and orientation[2]:
            if plan := self._portrait_placement(cells, occupied, index, unit, room_id):
                return plan
        result = snap_grid.place(self.size, cells, index, unit, occupied)
        if result != cells or unit == cells[index]:
            return _Placement(index, unit, result, result != cells, room_id)
        return None

    def drop(self, mime, point):
        plan = self._placement(mime, point)
        if plan is None:
            return False
        if isinstance(plan, _TileSwap):
            # An explicit swap keeps both slots, even if either first video frame is still pending.
            for tile in (plan.source, plan.destination):
                tile.state_control.pending_grid_aspect = None
            self.wall.tilePairSwapRequested.emit(plan.source, plan.destination)
            return True
        if plan.new_room is not None:
            if plan.new_room in self._orientation_checks:
                self._pending_drops[plan.new_room] = self._unit_at(point)
                return True
            return self._place_room(plan, self.wall.roomDropped.emit)
        if plan.changed:
            self._commit(plan.cells)
        return True

    def _place_room(self, plan, assign):
        wall = self.wall
        base = wall.layout_id
        previous = wall._layout_ratios[base]
        if plan.changed:
            wall.layout_control.set_preset_ratios(base, {'grid': plan.cells})
        tile = wall.tiles[plan.index]
        assign(tile, plan.new_room)
        if str(tile.room.get('room_id') or '') != plan.new_room:
            wall._layout_ratios[base] = previous
            return False
        wall.layoutRatiosChanged.emit()
        return True

    def open_menu(self, point, global_point):
        if self.vacant_unit_at(point) is None:
            return False
        menu = QMenu(self.wall)
        menu.addAction('添加弹幕格', lambda: self.add_danmaku(point))
        menu.aboutToHide.connect(menu.deleteLater)
        menu.popup(global_point)
        return True

    def add_danmaku(self, point):
        unit = self._unit_at(point)
        vacancy = self._vacancy(unit)
        if vacancy is not None:
            _, cells = vacancy
            occupied = self.occupied()
            index = next(i for i in reversed(range(len(cells))) if i not in occupied)
            result = snap_grid.place(self.size, cells, index, unit, occupied)
            if result != cells:
                self._commit(result)
            self.wall.pane_danmaku.request(index, -1)
