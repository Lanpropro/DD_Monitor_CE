"""Per-layout chat panes; bindings retain Tile identity when videos exchange places."""
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
            return self.wall.danmaku_target_tile()
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

    def prepare(self):
        from .widgets import DanmakuPanel
        cells = sorted(self.bindings())
        while len(self.all_panels()) < len(cells):
            panel = DanmakuPanel(self.wall)
            panel.hide()
            self.extra.append(panel)
            self.wall.danmakuPanelCreated.emit(panel)
        self.panels = dict(zip(cells, self.all_panels()))
        for panel in self.all_panels():
            if not panel.property('paneMenuInstalled'):
                from PySide6.QtCore import Qt
                panel.header.setContextMenuPolicy(Qt.CustomContextMenu)
                panel.header.customContextMenuRequested.connect(
                    lambda point, p=panel: self.menu(p, point))
                panel.roomDropped.connect(lambda rid, p=panel: self.room_dropped(p, rid))
                panel.setProperty('paneMenuInstalled', True)
            cell = next((cell for cell, item in self.panels.items() if item is panel), None)
            panel.setProperty('paneCell', cell if self.custom else None)
            if panel not in self.panels.values():
                panel.hide()

    def apply(self, bindings):
        wall = self.wall
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
        wall.relayout(force=True)

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
        bindings = dict(self.bindings())
        bindings[cell] = source
        self.apply(bindings)
        self.wall.paneConfigurationChanged.emit()

    def menu(self, panel, point):
        cell = next((cell for cell, item in self.panels.items() if item is panel), None)
        if cell is None:
            return
        self.open_menu(cell, panel.header.mapToGlobal(point))

    def create_menu(self, cell):
        menu = QMenu(self.wall)
        if cell not in range(len(self.wall._cells())):
            return menu
        bindings = self.bindings()
        heading = menu.addAction(f'第 {cell + 1} 格 · ' + ('弹幕栏' if cell in bindings else '直播画面'))
        heading.setEnabled(False)
        if cell in bindings:
            menu.addAction('恢复直播画面', lambda: self.request(cell, video=True))
        sources = menu.addMenu('关联画面' if cell in bindings else '改为弹幕栏')
        automatic = sources.addAction('自动跟随主画面', lambda: self.request(cell, None))
        automatic.setCheckable(True)
        automatic.setChecked(cell in bindings and bindings[cell] is None)
        sources.addSeparator()
        for index, tile in self.cell_tiles().items():
            if index == cell or index in bindings:
                continue
            name = str(tile.room.get('uname') or tile.room.get('room_id') or '空画面')
            action = sources.addAction(f'{index + 1} · {name}', lambda _checked=False, t=tile: self.request(cell, t))
            action.setCheckable(True)
            action.setChecked(cell in bindings and bindings[cell] is tile)
        return menu

    def request(self, cell, source=None, *, video=False):
        bindings = dict(self.bindings())
        if video:
            bindings.pop(cell, None)
        else:
            replaced = self.cell_tiles().get(cell)
            # A source replaced by a chat pane becomes unlinked, never silently retargeted.
            for index, target in list(bindings.items()):
                if replaced is not None and target is replaced:
                    bindings[index] = -1
            bindings[cell] = source
        self.wall.paneApplyRequested.emit(bindings)

    def open_menu(self, cell, point):
        menu = self.create_menu(cell)
        menu.exec(point)
        menu.deleteLater()
