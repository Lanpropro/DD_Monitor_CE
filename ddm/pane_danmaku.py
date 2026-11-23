"""Per-layout chat panes; bindings retain Tile identity when videos exchange places."""
from dataclasses import dataclass

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QMenu

from . import layouts
from .danmaku_sources import is_live_danmaku_source
from .window_fullscreen import set_presentation_owner


@dataclass
class FloatingPane:
    window: object
    slot: object
    cell: int | None
    released: dict
    source: object
    reserved: tuple = ()


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
        self.floating = {}
        self._pending_returns = set()
        self._layout_changed_in_fullscreen = False
        self._docking_panel = None
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
            return tile if tile is not None and is_live_danmaku_source(tile.room) else None
        tiles = self.cell_tiles()
        visible = {cell: tile for cell, tile in tiles.items() if cell not in self.bindings()}
        main = self.wall.main_index()
        if main is not None and main < len(self.wall.tiles):
            tile = self.wall.tiles[main]
            if tile in visible.values() and is_live_danmaku_source(tile.room):
                return tile
        return next((tile for tile in visible.values() if is_live_danmaku_source(tile.room)), None)

    def target(self, panel):
        floating = self.floating.get(panel)
        if floating is not None and (floating.cell is None or floating.released):
            source = floating.source
        else:
            cell = self.panel_cell(panel)
            if cell is None:
                return None
            source = self.bindings().get(cell)
            if source is None:
                return self.automatic_target()
        source_cell = self.cell_for_tile(source)
        if (source_cell is not None and is_live_danmaku_source(source.room)
                and (source_cell not in self.bindings() or self.panels.get(source_cell) is panel)):
            # A pane can replace its own video and continue showing that room's chat.
            return source
        return None

    def panel_cell(self, panel):
        return next((cell for cell, item in self.panels.items() if item is panel), None)

    def all_panels(self):
        return [self.wall.danmaku, *self.extra,
                *(panel for panel, floating in self.floating.items() if floating.cell is None)]

    def wall_widget(self, panel):
        floating = self.floating.get(panel)
        return floating.slot if floating is not None else panel

    def wall_widgets(self):
        return [widget for panel in self.all_panels() if (widget := self.wall_widget(panel)) is not None]

    def rendered(self):
        if not self.groups:
            docked = self.panels.values()
        else:
            docked = [self.panels[cell] for cell in self.groups if cell in self.panels]
        return list(dict.fromkeys((*docked, *self.floating)))

    def cells_for(self, cell):
        return next((cells for cells in self.groups.values() if cell in cells), (cell,))

    def cell_at(self, panel, global_point):
        cell = self.panel_cell(panel)
        if cell is None:
            return None
        cells = self.cells_for(cell)
        if len(cells) == 1:
            return cell
        point = self.wall.mapFromGlobal(global_point)

        def distance(index):
            rect = self.rectangles[index]
            dx = max(rect.left() - point.x(), point.x() - rect.right(), 0)
            dy = max(rect.top() - point.y(), point.y() - rect.bottom(), 0)
            return dx * dx + dy * dy

        return min(cells, key=distance)

    def remove_at(self, global_point):
        for panel in self.rendered():
            if panel in self.floating or not panel.isVisible():
                continue
            if panel.rect().contains(panel.mapFromGlobal(global_point)):
                cell = self.cell_at(panel, global_point)
                if cell in self.bindings():
                    self.request(cell, video=True)
                    return True
        return False

    def reset_preset(self, identifier):
        if identifier == self.wall.layout_id:
            self.return_all_floating()
        changed = identifier in self.settings
        self.settings.pop(identifier, None)
        if identifier == self.wall.layout_id:
            default = layouts.danmaku_cell(identifier)
            changed |= self.wall._danmaku_cell != default
            self.wall._danmaku_cell = default
            self.prepare()
        return changed

    def arrange(self, rectangles, widgets, *, gap=None):
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
        gap = self.wall.grid.spacing() if gap is None else gap
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
                self.wall_widget(self.panels[cell]).setGeometry(rect)
        for cells, rect, room in areas:
            # Keep an existing message document when an adjacent pane is added.
            keeping = [cell for cell in cells if self.panels[cell] in previous and
                       getattr(self.panels[cell], '_linked_room_id', '') == room]
            docked = next((cell for cell in cells if self.panels[cell] is self._docking_panel), None)
            leader = (docked if docked is not None else
                      max(keeping or cells, key=lambda cell: (rectangles[cell].bottom(), rectangles[cell].right())))
            self.groups[leader] = tuple(sorted(cells))
            self.wall_widget(self.panels[leader]).setGeometry(rect)
            for cell in cells:
                if cell != leader:
                    visible.pop(cell, None)
        active = set(visible.values())
        for widget in self.wall_widgets():
            widget.setVisible(widget in active)
        self.wall._sync_danmaku_controls()
        self.wall.sync_sc_placement()
        return visible

    def prepare(self):
        from .danmaku_widgets import DanmakuPanel
        cells = sorted(self.bindings())
        unavailable = {panel for panel, floating in self.floating.items()
                       if floating.cell is None or floating.released}
        while len(self.all_panels()) - len(unavailable) < len(cells):
            panel = DanmakuPanel(self.wall)
            panel.hide()
            self.extra.append(panel)
            self.wall.danmakuPanelCreated.emit(panel)
        retained = {cell: panel for cell, panel in self.panels.items() if cell in cells and panel not in unavailable}
        if not self.custom:
            retained = {cell: self.wall.danmaku for cell in cells}
        available = iter(panel for panel in self.all_panels() if panel not in retained.values() and panel not in unavailable)
        self.panels = {cell: retained[cell] if cell in retained else next(available) for cell in cells}
        for panel in self.all_panels():
            self._install_panel_menu(panel)
            cell = next((cell for cell, item in self.panels.items() if item is panel), None)
            panel.setProperty('paneCell', cell if self.custom else None)
            if panel not in self.panels.values() and panel in self.floating and panel not in unavailable:
                self._detach_window(panel)
            if panel not in self.panels.values() and panel not in self.floating:
                panel.hide()

    def _install_panel_menu(self, panel):
        if panel.property('paneMenuInstalled'):
            return
        from .pane_source_picker import SourcePicker
        from .sidebar_navigation import NavigationButton
        panel.source_picker = SourcePicker(panel, self)
        panel.float_button = NavigationButton('弹出弹幕栏', 'pip', panel.header)
        panel.float_button.setFixedSize(24, 24)
        panel.float_button.clicked.connect(lambda: self.toggle_floating(panel))
        layout = panel.header.layout()
        layout.insertWidget(layout.indexOf(panel.source_picker), panel.float_button)
        panel.float_button.hide()
        panel.header.setContextMenuPolicy(Qt.CustomContextMenu)
        panel.header.customContextMenuRequested.connect(
            lambda point: self.menu(panel, panel.header.mapToGlobal(point)))
        panel.body.setContextMenuPolicy(Qt.CustomContextMenu)
        panel.body.customContextMenuRequested.connect(
            lambda point: self.menu(panel, panel.body.viewport().mapToGlobal(point)))
        panel.roomDropped.connect(lambda rid: self.room_dropped(panel, rid))
        panel.tileDropped.connect(lambda rid, point: self.tile_dropped(panel, rid, point))
        panel.setProperty('paneMenuInstalled', True)

    def open_for_tile(self, tile):
        if not tile.isVisible() or not tile.room.get('room_id'):
            return
        for panel, floating in self.floating.items():
            if self.target(panel) is tile:
                if panel in self._pending_returns:
                    self._pending_returns.remove(panel)
                    floating.window.attach_panel(panel)
                floating.window.select_panel(panel)
                floating.window.show()
                floating.window.raise_()
                floating.window.activateWindow()
                return
        for panel in self.rendered():
            if panel.isVisible() and self.target(panel) is tile:
                self.toggle_floating(panel)
                return

        from .danmaku_widgets import DanmakuPanel
        panel = DanmakuPanel(self.wall)
        self._install_panel_menu(panel)
        self.wall.danmakuPanelCreated.emit(panel)
        size = tile.size().boundedTo(QSize(360, 480))
        self._open_window(panel, None, QRect(tile.mapToGlobal(QPoint()), size), {}, tile).show()
        self.wall.floatingDanmakuChanged.emit()

    def toggle_floating(self, panel):
        if panel in self.floating:
            self.return_floating(panel)
            return
        cell = self.panel_cell(panel)
        if cell is None or not panel.isVisible():
            return
        from .danmaku_float_window import DanmakuFloatSlot
        owner = self.wall.window()
        reuse = bool(getattr(owner, 'settings', {}).get('danmaku_float_reuse_cell', False))
        bindings = self.bindings()
        group = self.cells_for(cell)
        released = {index: bindings[index] for index in group} if reuse else {}
        rect = QRect(panel.mapToGlobal(QPoint()), panel.size())
        slot = None if reuse else DanmakuFloatSlot(self.wall, lambda: self.return_floating(panel))
        window = self._open_window(panel, cell, rect, released, self.target(panel), slot, () if reuse else group)
        if released:
            self.apply({index: source for index, source in bindings.items() if index not in released})
        else:
            self.wall.relayout(force=True)
        window.show()
        self.wall.paneConfigurationChanged.emit()

    def _open_window(self, panel, cell, rect, released, source, slot=None, reserved=()):
        window = self._create_floating_window(rect)
        self.floating[panel] = FloatingPane(window, slot, cell, released, source, reserved)
        self._set_float_button(panel, True)
        # Return the composer to the source tile before reparenting its chat panel.
        self.wall._sync_danmaku_controls()
        window.attach_panel(panel)
        return window

    def _create_floating_window(self, rect):
        from .danmaku_float_window import DanmakuFloatWindow
        window = DanmakuFloatWindow(self.wall.window(), self, rect)
        window.returnRequested.connect(lambda: self._return_window(window))
        tile = self.wall.fullscreen_tile
        if tile is not None and tile.isWindow():
            set_presentation_owner(window, tile)
        return window

    def floating_windows(self):
        return tuple(dict.fromkeys(entry.window for entry in self.floating.values()))

    def set_floating_owner(self, owner):
        for window in self.floating_windows():
            set_presentation_owner(window, owner)

    def move_floating_tab(self, panel, destination, index):
        source = self.floating[panel].window
        if source is destination:
            original = source.tabs.panels().index(panel)
            source.tabs.moveTab(original, index - int(index > original))
            source.select_panel(panel)
            return
        scroll = panel.scroll_control.scroll_state()
        source.release_panel(panel, self.wall)
        self.floating[panel].window = destination
        destination.attach_panel(panel, index)
        panel.scroll_control.restore_scroll_state(scroll)
        self._discard_empty_window(source)
        destination.show()
        destination.raise_()
        destination.activateWindow()

    def split_floating_tab(self, panel, position):
        source = self.floating[panel].window
        if source.tabs.count() > 1:
            rect = QRect(position - QPoint(24, 16), source.size())
            self.move_floating_tab(panel, self._create_floating_window(rect), 0)

    def floating_dock_available(self):
        wall = self.wall
        return (wall.fullscreen_tile is None and not wall._fullscreen_layout_pending
                and wall.picture_in_picture_tiles is None and bool(wall._cells()))

    def _floating_dock_target(self, point):
        if not self.floating_dock_available():
            return None
        wall = self.wall
        tiles = self.cell_tiles()
        bindings = self.bindings()
        target = next(((cell, tile.geometry(), None) for cell, tile in tiles.items()
                       if cell not in bindings and tile.isVisible() and tile.geometry().contains(point)), None)
        if target is None and wall.snap_grid.interactive():
            target = wall.snap_grid.floating_chat_target(point)
        if target is not None:
            cell, _, _ = target
            tile = tiles.get(cell)
            if tile is not None and cell not in bindings:
                host = wall.window()
                session = host.recorder.sessions.get(tile)
                if not (session is not None and session.recording) and not host._pending_capture.get(tile):
                    return target
        return None

    def show_floating_dock(self, point):
        grid = self.wall.snap_grid
        target = self._floating_dock_target(point)
        if target is not None or grid.interactive():
            grid.present_drag_guide(grid.drag_units() if grid.interactive() else (),
                                    target[1] if target is not None else None)
        else:
            grid.hide_drag_guide()

    def dock_floating_tab(self, panel, point):
        target = self._floating_dock_target(point)
        if target is None or panel not in self.floating:
            return False
        cell, _, grid_cells = target
        source = self.target(panel) or -1
        scroll = panel.scroll_control.scroll_state()
        bindings = dict(self.bindings())
        for index in self.floating[panel].reserved:
            resident = self.panels.get(index)
            if resident is None or resident is panel or resident not in self.floating:
                bindings.pop(index, None)
                self.panels.pop(index, None)
        self._detach_window(panel)
        if panel is not self.wall.danmaku and panel not in self.extra:
            self.extra.append(panel)
        self.panels[cell] = panel
        bindings[cell] = source
        if grid_cells is not None:
            self.wall.layout_control.set_preset_ratios(self.wall.layout_id, {'grid': grid_cells})
        self._docking_panel = panel
        try:
            self.apply(bindings)
        finally:
            self._docking_panel = None
        panel.scroll_control.restore_scroll_state(scroll)
        if grid_cells is not None:
            self.wall.layoutRatiosChanged.emit()
        self.wall.paneConfigurationChanged.emit()
        return True

    def _return_window(self, window):
        for panel in window.tabs.panels():
            self.return_floating(panel)

    def _discard_empty_window(self, window):
        if not window.tabs.count() and window not in self.floating_windows():
            window.deleteLater()

    @staticmethod
    def _set_float_button(panel, floating):
        button = panel.float_button
        button.kind = 'close' if floating else 'pip'
        label = '关闭弹幕浮窗' if floating else '弹出弹幕栏'
        button.setToolTip(label)
        button.setAccessibleName(label)
        button.update()

    def _detach_window(self, panel):
        floating = self.floating.pop(panel)
        self._pending_returns.discard(panel)
        floating.window.release_panel(panel, self.wall)
        self._set_float_button(panel, False)
        if floating.slot is not None:
            floating.slot.hide()
            floating.slot.deleteLater()
        self._discard_empty_window(floating.window)
        return floating

    def return_floating(self, panel, *, notify=True):
        if panel not in self.floating:
            return
        if notify and self.floating[panel].cell is not None and self.wall._fullscreen_layout_pending:
            # Fullscreen keeps a snapshot of wall widgets until its original layout returns.
            self._pending_returns.add(panel)
            self.floating[panel].window.release_panel(panel, self.wall)
            return
        floating = self._detach_window(panel)
        if floating.cell is None:
            panel.deleteLater()
            self.wall._sync_danmaku_controls()
            if notify:
                self.wall.floatingDanmakuChanged.emit()
            return
        bindings = self.bindings()
        tiles = self.cell_tiles()
        keep_video = notify and getattr(self.wall.window(), 'settings', {}).get('danmaku_float_keep_video_slots', False)
        if floating.released and not keep_video and all(
                cell not in bindings and cell in tiles and not tiles[cell].room.get('room_id')
                for cell in floating.released):
            self.panels[floating.cell] = panel
            self.apply({**bindings, **floating.released})
        elif floating.released:
            self.wall._sync_danmaku_controls()
            if notify:
                self.wall.floatingDanmakuChanged.emit()
            return
        else:
            self.wall.relayout(force=True)
        if notify:
            self.wall.paneConfigurationChanged.emit()

    def return_all_floating(self):
        for panel in tuple(self.floating):
            self.return_floating(panel, notify=False)

    def finish_pending_returns(self):
        for panel in tuple(self._pending_returns):
            self.return_floating(panel)
        if self._layout_changed_in_fullscreen:
            self._layout_changed_in_fullscreen = False
            self.wall.relayout(force=True)

    def refresh_sources(self):
        for panel in self.all_panels():
            if hasattr(panel, 'source_picker'):
                panel.source_picker.refresh()
            entry = self.floating.get(panel)
            if entry is not None and panel not in self._pending_returns:
                entry.window.tabs.refresh_source(panel)

    def apply(self, bindings, *, exchange=None):
        wall = self.wall
        previous = self.bindings()
        layout_changed = not self.custom or set(bindings) != set(previous)
        old = dict(self.cell_tiles())
        if not self.custom and wall._danmaku_cell is not None:
            # Give the legacy chat position its own empty backing video slot once.
            cell = wall._danmaku_cell
            tile = wall._make_tile({})
            old[cell] = tile
            active = [old[index] for index in sorted(old)]
            wall.tiles = active + [item for item in wall.tiles if item not in active]
        if exchange is not None:
            first, second = (wall.tiles.index(old[cell]) for cell in exchange)
            wall.tiles[first], wall.tiles[second] = wall.tiles[second], wall.tiles[first]
        for leader, cells in self.groups.items():
            panel = self.panels.get(leader)
            if panel is None or panel in self.floating or leader not in previous or leader in bindings:
                continue
            remaining = next((cell for cell in cells if cell in bindings and cell in previous
                              and bindings[cell] is previous[cell]), None)
            if remaining is not None:
                # Keep the visible message document when the clicked part was its original cell.
                self.panels[remaining] = self.panels.pop(leader)
        self.settings[wall.layout_id] = dict(bindings)
        self.prepare()
        if wall._fullscreen_layout_pending:
            # Keep the fullscreen visibility snapshot intact while changing sources.
            if layout_changed:
                self._layout_changed_in_fullscreen = True
            wall._sync_danmaku_controls()
        elif layout_changed:
            wall.relayout(force=True)
        else:
            widgets = self.arrange(self.rectangles, wall._preset_widgets())
            wall._sync_pane_borders(widgets, self.dividers)

    def swap_sources(self, first, second):
        for floating in self.floating.values():
            if floating.source is first:
                floating.source = second
            elif floating.source is second:
                floating.source = first
        released = (floating.released for floating in self.floating.values())
        for bindings in (*self.settings.values(), *released):
            for cell, tile in list(bindings.items()):
                if tile is first:
                    bindings[cell] = second
                elif tile is second:
                    bindings[cell] = first

    def move(self, cell, tile):
        destination = self.cell_for_tile(tile)
        bindings = dict(self.bindings())
        if cell not in bindings or destination is None or destination in bindings:
            return
        source = bindings.pop(cell)
        bindings[destination] = (self.target(self.panels[cell]) or -1) if source is None else source
        if len(self.cells_for(cell)) == 1:
            self.panels[destination] = self.panels.pop(cell)
        self.apply(bindings, exchange=(cell, destination))
        self.wall.paneConfigurationChanged.emit()

    def tile_dropped(self, panel, room_id, point):
        bindings = self.bindings()
        tile = next((tile for cell, tile in self.cell_tiles().items()
                     if cell not in bindings and str(tile.room.get('room_id') or '') == room_id), None)
        if tile is None:
            return
        key = 'danmaku_drag_linked_swap' if self.target(panel) is not None else 'danmaku_drag_unlinked_swap'
        settings = getattr(self.wall.window(), 'settings', {})
        if panel not in self.floating and settings.get(key, False):
            if (cell := self.cell_at(panel, point)) is not None:
                self.move(cell, tile)
        else:
            self.choose_source(panel, tile)

    def room_dropped(self, panel, room_id):
        source = next((tile for tile in self.cell_tiles().values()
                       if str(tile.room.get('room_id') or '') == str(room_id)), None)
        if source is not None and not is_live_danmaku_source(source.room):
            return
        if not self.custom and panel not in self.floating:
            self.wall._on_danmaku_room_dropped(room_id)
            return
        if source is None or self.cell_for_tile(source) in self.bindings():
            return
        self.choose_source(panel, source)

    def choose_source(self, panel, source):
        if not is_live_danmaku_source(source.room):
            return
        floating = self.floating.get(panel)
        if floating is not None and (floating.cell is None or floating.released):
            floating.source = source
            if floating.released:
                floating.released = dict.fromkeys(floating.released, source)
            self.wall._sync_danmaku_controls()
            if floating.cell is None:
                self.wall.floatingDanmakuChanged.emit()
            else:
                self.wall.paneConfigurationChanged.emit()
        elif (cell := self.panel_cell(panel)) is not None:
            self.request(cell, source)

    def menu(self, panel, point):
        if panel in self.floating:
            menu = QMenu(panel)
            menu.addAction('关闭弹幕浮窗', lambda: self.return_floating(panel))
            menu.exec(point)
            menu.deleteLater()
        elif (cell := self.cell_at(panel, point)) is not None:
            self.open_menu(cell, point)

    def create_menu(self, cell):
        menu = QMenu(self.wall)
        if cell not in range(len(self.wall._cells())):
            return menu
        if cell in self.bindings():
            label = '移除弹幕格' if self.wall.snap_grid.size else '恢复直播画面'
            menu.addAction(label, lambda: self.request(cell, video=True))
        return menu

    def request(self, cell, source=None, *, video=False):
        if not video and source not in (None, -1) and not is_live_danmaku_source(source.room):
            return
        bindings = dict(self.bindings())
        if video:
            bindings.pop(cell, None)
        else:
            cells = self.cells_for(cell) if cell in bindings else (cell,)
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
