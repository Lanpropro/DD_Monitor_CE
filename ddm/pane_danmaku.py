"""Per-layout chat panes; bindings retain Tile identity when videos exchange places."""
from PySide6.QtCore import QRect
from PySide6.QtWidgets import QMenu

from . import layouts


def validate_panels(value, count):
    if not isinstance(value, list):
        raise ValueError('弹幕格配置无效')
    result, seen = [], set()
    for item in value:
        if not isinstance(item, dict):
            raise ValueError('弹幕格配置无效')
        cell, source = item.get('cell'), item.get('source')
        if type(cell) is not int or not 0 <= cell < count or cell in seen:
            raise ValueError('弹幕格位置重复或越界')
        if source is not None and (type(source) is not int or source < -1):
            raise ValueError('弹幕来源无效')
        seen.add(cell)
        result.append(dict(cell=cell, source=source))
    return sorted(result, key=lambda item: item['cell'])


class PaneDanmaku:
    def __init__(self, wall, saved):
        self.wall = wall
        self.settings = {}
        self.extra = []
        self.panels = {}
        self.groups = {}
        self.rectangles = {}
        self.dividers = []
        self._saved = saved if isinstance(saved, dict) else {}
        for identifier, value in self._saved.items():
            if identifier not in layouts.BY_ID:
                continue
            try:
                self.settings[identifier] = {item['cell']: item['source'] for item in
                    validate_panels(value, layouts.capacity(identifier))}
            except ValueError:
                continue

    @property
    def custom(self):
        return self.wall.layout_id in self.settings

    def restore_sources(self):
        for bindings in self.settings.values():
            for cell, index in list(bindings.items()):
                bindings[cell] = (self.wall.tiles[index] if type(index) is int and
                                  0 <= index < len(self.wall.tiles) else
                                  None if index is None else -1)

    def state(self):
        tiles = self.wall.tiles
        return {identifier: [dict(cell=cell, source=None if tile is None else
                                 tiles.index(tile) if tile in tiles else -1)
                             for cell, tile in sorted(bindings.items())]
                for identifier, bindings in self.settings.items()}

    def bindings(self):
        if self.custom:
            return self.settings[self.wall.layout_id]
        cell = self.wall._danmaku_cell
        return {cell: None} if cell is not None else {}

    def cell_tiles(self):
        return dict(zip(self.wall._cell_order(), self.wall.tiles))

    def cell_for_tile(self, tile):
        return next((cell for cell, item in self.cell_tiles().items() if item is tile), None)

    def automatic_target(self):
        if not self.custom:
            tile = self.wall.danmaku_target_tile()
            return tile if tile is not None and tile.room.get('room_id') else None
        tiles = self.cell_tiles()
        visible = {cell: tile for cell, tile in tiles.items() if cell not in self.bindings()}
        main = self.wall.main_index()
        if main is not None and main < len(self.wall.tiles):
            tile = self.wall.tiles[main]
            if tile in visible.values() and tile.room.get('room_id'):
                return tile
        return next((tile for tile in visible.values() if tile.room.get('room_id')), None)

    def target(self, panel):
        cell = next((cell for cell, item in self.panels.items() if item is panel), None)
        if cell is None:
            return None
        source = self.bindings().get(cell)
        if source is None:
            return self.automatic_target()
        visible = [tile for cell, tile in self.cell_tiles().items() if cell not in self.bindings()]
        return source if source in visible and source.room.get('room_id') else None

    def all_panels(self):
        return [self.wall.danmaku, *self.extra]

    def rendered(self):
        if not self.groups:
            return list(self.panels.values())
        return [self.panels[cell] for cell in self.groups if cell in self.panels]

    def cells_for(self, cell):
        return next((cells for cells in self.groups.values() if cell in cells), (cell,))

    def reset_preset(self, identifier):
        changed = identifier in self.settings
        self.settings.pop(identifier, None)
        if identifier == self.wall.layout_id:
            default = layouts.danmaku_cell(identifier)
            changed |= self.wall._danmaku_cell != default
            self.wall._danmaku_cell = default
            self.prepare()
        return changed

    def arrange(self, rectangles, widgets):
        """Join adjacent sources only when their bounding rectangle covers no other cell."""
        self.rectangles = {cell: QRect(rect) for cell, rect in rectangles.items()}
        if not self.panels:
            self.groups = {}
            return widgets
        previous = set(self.rendered())
        areas = []
        for cell, panel in self.panels.items():
            if cell not in rectangles:
                continue
            tile = self.target(panel)
            room = str(tile.room.get('room_id') or '') if tile is not None else ''
            areas.append(([cell], QRect(rectangles[cell]), room))
        gap = self.wall.grid.spacing()
        changed = True
        while changed:
            changed = False
            for first, (cells, rect, room) in enumerate(areas):
                if not room:
                    continue
                for second in range(first + 1, len(areas)):
                    others, other, source = areas[second]
                    horizontal = (max(rect.top(), other.top()) <= min(rect.bottom(), other.bottom()) and
                        (rect.right() + gap + 1 == other.left() or other.right() + gap + 1 == rect.left()))
                    vertical = (max(rect.left(), other.left()) <= min(rect.right(), other.right()) and
                        (rect.bottom() + gap + 1 == other.top() or other.bottom() + gap + 1 == rect.top()))
                    if source == room and (horizontal or vertical):
                        combined = rect.united(other)
                        joined = cells + others
                        if any(combined.intersects(area) for cell, area in rectangles.items() if cell not in joined):
                            continue
                        areas[first] = (joined, combined, room)
                        areas.pop(second)
                        changed = True
                        break
                if changed:
                    break
        self.groups = {}
        visible = dict(widgets)
        for cell, rect in rectangles.items():
            if cell in self.panels:
                self.panels[cell].setGeometry(rect)
        for cells, rect, room in areas:
            # Keep an existing message document when an adjacent pane is added.
            keeping = [cell for cell in cells if self.panels[cell] in previous and
                       getattr(self.panels[cell], '_linked_room_id', '') == room]
            leader = max(keeping or cells, key=lambda cell: (rectangles[cell].bottom(), rectangles[cell].right()))
            self.groups[leader] = tuple(sorted(cells))
            self.panels[leader].setGeometry(rect)
            for cell in cells:
                if cell != leader:
                    visible.pop(cell, None)
        active = set(visible.values())
        for panel in self.all_panels():
            panel.setVisible(panel in active)
        self.wall._sync_danmaku_controls()
        self.wall.sync_sc_placement()
        return visible

    def prepare(self):
        from .widgets import DanmakuPanel
        cells = sorted(self.bindings())
        while len(self.all_panels()) < len(cells):
            panel = DanmakuPanel(self.wall)
            panel.hide()
            self.extra.append(panel)
            self.wall.danmakuPanelCreated.emit(panel)
        retained = {cell: panel for cell, panel in self.panels.items() if cell in cells}
        if not self.custom:
            retained = {cell: self.wall.danmaku for cell in cells}
        available = iter(panel for panel in self.all_panels() if panel not in retained.values())
        self.panels = {cell: retained[cell] if cell in retained else next(available) for cell in cells}
        for panel in self.all_panels():
            if not panel.property('paneMenuInstalled'):
                from .pane_source_picker import SourcePicker
                panel.source_picker = SourcePicker(panel, self)
                from PySide6.QtCore import Qt
                panel.header.setContextMenuPolicy(Qt.CustomContextMenu)
                panel.header.customContextMenuRequested.connect(
                    lambda point, p=panel: self.menu(p, point))
                panel.body.setContextMenuPolicy(Qt.CustomContextMenu)
                panel.body.customContextMenuRequested.connect(lambda point, p=panel:
                    self.open_menu(next(cell for cell, item in self.panels.items() if item is p),
                                   p.body.viewport().mapToGlobal(point)))
                panel.roomDropped.connect(lambda rid, p=panel: self.room_dropped(p, rid))
                panel.setProperty('paneMenuInstalled', True)
            cell = next((cell for cell, item in self.panels.items() if item is panel), None)
            panel.setProperty('paneCell', cell if self.custom else None)
            if panel not in self.panels.values():
                panel.hide()

    def refresh_sources(self):
        for panel in self.all_panels():
            if hasattr(panel, 'source_picker'):
                panel.source_picker.refresh()

    def apply(self, bindings):
        wall = self.wall
        layout_changed = not self.custom or set(bindings) != set(self.bindings())
        old = dict(self.cell_tiles())
        if not self.custom and wall._danmaku_cell is not None:
            # Give the legacy chat position its own empty backing video slot once.
            cell = wall._danmaku_cell
            tile = wall._make_tile({})
            old[cell] = tile
            active = [old[index] for index in sorted(old)]
            wall.tiles = active + [item for item in wall.tiles if item not in active]
        self.settings[wall.layout_id] = dict(bindings)
        self.prepare()
        if layout_changed:
            wall.relayout(force=True)
        else:
            widgets = self.arrange(self.rectangles, wall._preset_widgets())
            wall._sync_pane_borders(widgets, self.dividers)

    def swap_sources(self, first, second):
        for bindings in self.settings.values():
            for cell, tile in list(bindings.items()):
                if tile is first:
                    bindings[cell] = second
                elif tile is second:
                    bindings[cell] = first

    def move(self, cell, tile):
        destination = self.cell_for_tile(tile)
        if not self.custom or cell not in self.bindings() or destination is None:
            return
        bindings = dict(self.bindings())
        bindings[destination] = bindings.pop(cell)
        slots = self.cell_tiles()
        first, second = self.wall.tiles.index(slots[cell]), self.wall.tiles.index(tile)
        self.wall.tiles[first], self.wall.tiles[second] = tile, slots[cell]
        self.apply(bindings)
        self.wall.paneConfigurationChanged.emit()

    def room_dropped(self, panel, room_id):
        if not self.custom:
            self.wall._on_danmaku_room_dropped(room_id)
            return
        source = next((tile for tile in self.cell_tiles().values()
                       if str(tile.room.get('room_id') or '') == str(room_id)), None)
        cell = next((cell for cell, item in self.panels.items() if item is panel), None)
        if source is None or cell is None or self.cell_for_tile(source) in self.bindings():
            return
        self.request(cell, source)

    def menu(self, panel, point):
        cell = next((cell for cell, item in self.panels.items() if item is panel), None)
        if cell is None:
            return
        self.open_menu(cell, panel.header.mapToGlobal(point))

    def create_menu(self, cell):
        menu = QMenu(self.wall)
        if cell not in range(len(self.wall._cells())):
            return menu
        if cell in self.bindings():
            menu.addAction('恢复直播画面', lambda: self.request(cell, video=True))
        return menu

    def request(self, cell, source=None, *, video=False):
        bindings = dict(self.bindings())
        cells = self.cells_for(cell) if cell in bindings else (cell,)
        if video:
            for index in cells:
                bindings.pop(index, None)
        else:
            for index in cells:
                replaced = self.cell_tiles().get(index)
                # A source replaced by a chat pane becomes unlinked, never silently retargeted.
                for other, target in list(bindings.items()):
                    if replaced is not None and target is replaced:
                        bindings[other] = -1
                bindings[index] = source
        self.wall.paneApplyRequested.emit(bindings)

    def open_menu(self, cell, point):
        menu = self.create_menu(cell)
        menu.exec(point)
        menu.deleteLater()
