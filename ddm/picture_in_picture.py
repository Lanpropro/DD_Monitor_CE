"""A selected group of existing playback panes in one independent floating window."""
import math
import sys

from PySide6.QtCore import QByteArray, QEvent, QObject, QPoint, QRect, QRectF, QSignalBlocker, QSize, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QCursor, QKeySequence, QPainter, QPainterPath, QPen, QRegion, QShortcut
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from . import follow_folders, theme
from .search import matches_text
from .pip_composition import FREE_LAYOUT, MAIN_LAYOUT, PipChat, composition_inputs, read_chat_slots
from .danmaku_sources import is_live_danmaku_source
from .pip_placement import validate_placement
from .pip_parallel import ParallelPictureInPicture
from .ui import ActionButton, Avatar, ElidedLabel, page_header


from .pip_geometry import (FOCUS_LAYOUT, composition_rows, composition_aspect, _focus_parts, composition_ratio, video_aspect, pane_rectangles)


from .pip_preview import (CompositionPreview)


from .pip_picker import (RoomChoice, PictureInPictureDialog)


from .pip_window import (PictureInPictureButton, PictureInPictureTools, PictureInPictureWindow)


class PictureInPicture(QObject):
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.floating = None
        self.dialog = None
        self._first_picker = True
        saved = host.state.get('ui', {}).get('picture_in_picture', {})
        self.selection = list(saved.get('selection', []))
        self.columns = saved.get('columns', 0)
        self.primary = saved.get('primary')
        self.external_rooms = list(saved.get('external_rooms', []))
        self.external_primary = saved.get('external_primary', '')
        self._choice_order = list(saved.get('choice_order', []))
        self.placement = validate_placement(saved.get('placement'))
        self._extra_tiles = {}
        self._parallel = None
        self.parallel_preference = bool(saved.get('parallel', False))
        self.chat_slots = read_chat_slots(saved['chat_slots']) if 'chat_slots' in saved else None
        self._legacy_chat = bool(saved.get('show_danmaku', False))
        self.move_wall_streams = bool(saved.get('move_wall_streams', True))
        self._start_serial = 0
        self._pending_start = None
        self.pinned = bool(saved.get('pinned', True))
        self.geometry = saved.get('geometry', '')
        size = saved.get('picker_size')
        self.picker_size = (tuple(size) if isinstance(size, (tuple, list)) and len(size) == 2
                            and all(type(value) is int and 0 < value <= 32767 for value in size) else ())
        self._video_aspects = {}
        self._aspect_timer = QTimer(self)
        self._aspect_timer.setInterval(1000)
        self._aspect_timer.timeout.connect(self._refresh_aspects)
        theme.signals().changed.connect(self._refresh_theme)
        self.placeholder = QFrame(host._content)
        self.placeholder.setObjectName('PluginCard')
        layout = QVBoxLayout(self.placeholder)
        layout.addStretch()
        text = QLabel('正在画中画中观看\n其他画面按原设置在后台播放\n返回后恢复原监控室布局', self.placeholder)
        text.setAlignment(Qt.AlignCenter)
        layout.addWidget(text)
        for title, action in (('管理画中画', self.manage), ('返回监控室', self.restore)):
            button = ActionButton(title, self.placeholder)
            button.clicked.connect(action)
            layout.addWidget(button, 0, Qt.AlignHCenter)
        layout.addStretch()
        self.placeholder.hide()

    @property
    def active(self):
        return self.floating is not None

    @property
    def moves_main_wall(self):
        return self.active and self._parallel is None

    @property
    def display_wall(self):
        return self._parallel.wall if self._parallel is not None else self.host.wall

    @property
    def parallel_tiles(self):
        return self._parallel.wall.tiles if self._parallel is not None else ()

    @property
    def danmaku_panels(self):
        return self.floating.danmaku_panels if self.active else {}

    def danmaku_targets(self):
        wall = self.display_wall
        tiles = wall.picture_in_picture_tiles or ()
        primary = tiles[wall.picture_in_picture_primary].room if tiles else {}
        targets = {}
        for _, chat in self.chat_slots or ():
            panel = self.danmaku_panels.get(chat.key)
            if panel is None:
                continue
            room = primary if chat.source is None else {'room_id': chat.source, 'uname': chat.name}
            targets[panel] = room if is_live_danmaku_source(room) else {}
        return targets

    def picker_chat_slots(self, selection):
        if self.chat_slots is not None:
            return self.chat_slots
        wall = self.host.wall
        panes = wall.pane_danmaku
        video_cells = {tile: cell for cell, tile in panes.cell_tiles().items()}
        positions = [video_cells.get(wall.tiles[key], float('inf')) for key in selection
                     if type(key) is int and 0 <= key < len(wall.tiles)]
        slots = []
        for cell in sorted(panes.groups or panes.bindings()):
            panel = panes.panels.get(cell)
            if panel in panes.floating:
                continue
            source = panes.target(panel) if panel is not None else None
            if source is None and panes.bindings().get(cell) is None:
                source = panes.automatic_target()
            room = source.room if source is not None else {}
            position = sum(video_cell < cell for video_cell in positions) + len(slots)
            slots.append((position, PipChat(f'wall:{cell}', str(room.get('room_id') or ''),
                                            str(room.get('uname') or ''))))
        if not slots and self._legacy_chat:
            slots.append((len(selection), PipChat('legacy', None)))
        return tuple(slots)

    @property
    def moved_room_ids(self):
        return self._parallel.moved.keys() if self._parallel is not None else ()

    @property
    def moved_tiles(self):
        moved = self.moved_room_ids
        return tuple(tile for tile in self.parallel_tiles if str(tile.room.get('room_id')) in moved)

    def audio_tiles(self):
        if self._parallel is not None:
            return list(self.display_wall.picture_in_picture_tiles or ())
        return [self.host.wall.tiles[index] for index in self.selection]

    def _refresh_theme(self, *_args):
        if self.active:
            self.floating.tools.update()
            for panel in self.danmaku_panels.values():
                panel.refresh_theme()
            for button in self.floating.tools.findChildren(PictureInPictureButton):
                button.update()

    def manage_from_sidebar(self):
        if self.dialog is not None and self.dialog.toolbar_panel is not None:
            self.dialog.reject()
            return
        sidebar = self.host.sidebar
        anchor = sidebar.picture_in_picture_button
        if not anchor.isVisible():
            anchor = sidebar.account_row
        self.manage(anchor=anchor if anchor.isVisible() else None, below=sidebar.side == 'top')

    def manage(self, *, anchor=None, below=False):
        if self.active:
            self.floating.audio_panel.hide()
        if self.dialog is not None:
            self.dialog.raise_()
            self.dialog.activateWindow()
            return
        if not self.active:
            choices = self.selected_choices()
            has_choices = any(key in choices for _, entries in self.candidate_groups() for key, _ in entries)
            if (self._first_picker and self.chat_slots is None) or not has_choices:
                capacity = self.host.wall._capacity() or len(self.host.wall.tiles)
                wall_selection = [index for index, _room in self._wall_candidates() if index < capacity]
                saved_positions = dict(zip(choices, self.placement)) if len(choices) == len(self.placement) else {}
                primary = self.primary_choice()
                self.selection = wall_selection
                self.primary = primary if primary in wall_selection else None
                self.external_rooms = []
                self.external_primary = ''
                self._choice_order = []
                self.placement = (tuple(saved_positions[key] for key in wall_selection)
                                  if not self.chat_slots and all(key in saved_positions for key in wall_selection)
                                  else ())
        self._first_picker = False
        self.dialog = PictureInPictureDialog(self, compact=True) if anchor is not None else PictureInPictureDialog(self)
        self.dialog.finished.connect(self._finish_manage)
        if anchor is None:
            self.dialog.open()
        elif self.dialog.attach_to_toolbar(anchor, below=below):
            self.dialog.show()
            self.dialog.activateWindow()

    def remember_picker_size(self, size):
        self.picker_size = (size.width(), size.height())
        self.host._save_timer.start()

    def _finish_manage(self, _result):
        self.dialog = None
        self._sync_overlays()

    def _wall_candidates(self):
        wall = self.host.wall
        panes = wall.pane_danmaku
        chat_cells = panes.bindings()
        chat_tiles = {tile for cell, tile in panes.cell_tiles().items() if cell in chat_cells}
        return [(index, tile.room) for index, tile in enumerate(wall.tiles)
                if tile not in chat_tiles and tile.room.get('room_id')
                and not tile.property('pictureInPictureTemporary')]

    def candidate_groups(self):
        wall = self._wall_candidates()
        wall_ids = {str(room['room_id']) for _index, room in wall}
        others = {}
        for room in self.host.sidebar.rooms():
            rid = str(room.get('room_id') or '')
            if rid and rid not in wall_ids and room.get('live') and room.get('live_known', True):
                others.setdefault(rid, room)
        for rid, tile in self._extra_tiles.items():
            if tile.room.get('room_id') and rid in self.external_rooms:
                others.setdefault(rid, tile.room)
        if self._parallel is not None:
            for rid, tile in self._parallel.tiles.items():
                if rid not in wall_ids:
                    others.setdefault(rid, tile.room)
        by_room = {}
        for key, room in wall + list(others.items()):
            by_room.setdefault(str(room['room_id']), []).append((key, room))
        sidebar = self.host.sidebar
        default = sidebar.default_folder()['id']
        groups = [('已入墙', wall)]
        for folder in sidebar.folders:
            copies = folder['type'] == 'smart' and folder['rule'].get('display') == 'copy'
            members = follow_folders.smart_members(sidebar.rooms(), sidebar.folders, folder,
                                                  sidebar._folder_pending) if copies else None
            entries = [entry for rid, choices in by_room.items()
                       if (rid in members if copies else (sidebar.folder_for(rid) or default) == folder['id'])
                       for entry in choices]
            if entries:
                groups.append((folder['name'], entries))
        return groups

    def choice_for_index(self, index):
        tiles = self.host.wall.tiles
        if isinstance(index, int) and 0 <= index < len(tiles) and tiles[index].property('pictureInPictureTemporary'):
            return str(tiles[index].room.get('room_id') or '')
        return index

    def selected_choices(self):
        if self._parallel is not None:
            return [self._parallel_choice(rid) for rid in self._parallel.room_ids]
        choices = [self.choice_for_index(index) for index in self.selection]
        choices += [rid for rid in self.external_rooms if rid not in choices]
        if self.active:
            return choices
        return ([key for key in self._choice_order if key in choices]
                + [key for key in choices if key not in self._choice_order])

    def primary_choice(self):
        if self._parallel is not None:
            return self._parallel_choice(self._parallel.primary)
        return self.external_primary or self.choice_for_index(self.primary)

    def _parallel_choice(self, room_id):
        return next((key for key, room in self._wall_candidates()
                     if str(room['room_id']) == room_id), room_id)

    def _remove_extra(self, rid):
        tile = self._extra_tiles.pop(rid)
        if self.floating is not None:
            self.floating.forget_tile(tile)
        self._video_aspects.pop(tile, None)
        self._minimums.pop(tile, None)
        dialog = self.host._stream_info_dialogs.get(tile)
        if dialog is not None:
            dialog.close()
        self.host._clear_tile_room(tile)
        if tile in self.host.recorder.sessions:
            tile.hide()
            self.host.wall.tiles.remove(tile)
            self.host._preset_retired_tiles.add(tile)
        else:
            self.host.wall._drop_tile(tile)

    def aspects_for(self, selection):
        aspects = []
        for index in selection:
            tile = self._extra_tiles.get(index) if isinstance(index, str) else self.host.wall.tiles[index]
            if self._parallel is not None:
                room_id = str(tile.room['room_id']) if tile is not None else index
                tile = self._parallel.tiles.get(room_id, tile)
            if tile is None:
                aspects.append(16 / 9)
                continue
            room = tile.room.get('room_id')
            aspect = video_aspect(self.host.players.get(tile))
            previous_room, previous_aspect = self._video_aspects.get(tile, (None, 16 / 9))
            aspect = aspect or (previous_aspect if previous_room == room else 16 / 9)
            self._video_aspects[tile] = (room, aspect)
            aspects.append(aspect)
        return aspects

    def _refresh_aspects(self):
        if (not self.active or self.columns == FREE_LAYOUT
                or self.floating._gesture is not None or self.floating._reorder_drag is not None):
            return
        wall = self.display_wall
        if self._parallel is not None:
            tiles = self.audio_tiles()
            if not tiles:
                return
            aspects = [video_aspect(self.host.players.get(tile)) or aspect
                       for tile, aspect in zip(tiles, wall.picture_in_picture_aspects)]
            primary = wall.picture_in_picture_primary
        else:
            aspects = self.aspects_for(self.selection)
            primary = self.selection.index(self.primary)
        if aspects == wall.picture_in_picture_aspects:
            return
        wall.picture_in_picture_aspects = aspects
        mixed, main = composition_inputs(aspects, self.chat_slots or (), primary)
        self.floating.set_composition(mixed, self.columns, main)
        wall.relayout(force=True)

    def swap_positions(self, source, target):
        tiles = self.display_wall.picture_in_picture_tiles
        if source is target or source not in tiles or target not in tiles:
            return
        first, second = tiles.index(source), tiles.index(target)
        if self._parallel is not None:
            selection = self.selected_choices()
            primary = selection.index(self.primary_choice())
            selection[first], selection[second] = selection[second], selection[first]
            self.start(selection, self.columns, selection[primary] if self.columns in (FOCUS_LAYOUT, MAIN_LAYOUT)
                       else self.primary_choice(), parallel=True, placement=self.placement)
            return
        primary = self.selection.index(self.primary)
        self.selection[first], self.selection[second] = self.selection[second], self.selection[first]
        if self.columns in (FOCUS_LAYOUT, MAIN_LAYOUT):
            self.primary = self.selection[primary]
        self.start(self.selection, self.columns, self.primary, placement=self.placement)

    def start(self, selection, columns=0, primary=None, *, parallel=False, placement=(),
              chat_slots=None, move_wall_streams=None):
        wall = self.host.wall
        candidates = {key: room for _title, entries in self.candidate_groups() for key, room in entries}
        if not selection:
            return False
        for key in selection:
            if self.choice_for_index(key) not in candidates:
                return False
        chats = (self.chat_slots or ()) if chat_slots is None else read_chat_slots(chat_slots)
        count = len(selection) + len(chats)
        if columns == FOCUS_LAYOUT and count != 6:
            columns = MAIN_LAYOUT if count >= 3 else 0
        placement = validate_placement(placement, count) if columns == FREE_LAYOUT else ()
        if columns == FREE_LAYOUT and not placement:
            columns = 0
        if self.active and parallel != (self._parallel is not None):
            moved = set(self.moved_room_ids)
            self.restore(activate=parallel, keep_dialog=True)
            matches = {str(room['room_id']): key for key, room in self._wall_candidates()
                       if str(room['room_id']) in moved}
            selection = [matches.get(key, key) for key in selection]
            primary = matches.get(primary, primary)
        if chat_slots is not None:
            self.chat_slots = chats
        self.placement = placement
        if parallel:
            if move_wall_streams is not None:
                self.move_wall_streams = move_wall_streams
            self._start_parallel(selection, columns, primary, candidates)
            return True
        self.host._cancel_interactive_resize()
        if self.host._fullscreen_tile is not None:
            self.host._exit_fullscreen()
        tiles, primary_tile, starting = [], None, []
        for key in selection:
            if isinstance(key, str):
                tile = self._extra_tiles.get(key)
                if tile is None:
                    tile = wall._make_tile(dict(candidates[key]))
                    tile.setProperty('pictureInPictureTemporary', True)
                    self._extra_tiles[key] = tile
                    starting.append(tile)
            else:
                tile = wall.tiles[key] if 0 <= key < len(wall.tiles) else None
            if tile is not None and tile.room.get('room_id'):
                if tile not in tiles:
                    tiles.append(tile)
                if key == primary:
                    primary_tile = tile
        if not tiles:
            return False
        selection = [wall.tiles.index(tile) for tile in tiles]
        primary = wall.tiles.index(primary_tile) if primary_tile in tiles else selection[0]
        self.selection, self.columns = list(selection), columns
        self.primary = primary
        self.external_rooms = [str(tile.room['room_id']) for tile in tiles if tile.property('pictureInPictureTemporary')]
        self.external_primary = (str(wall.tiles[primary].room['room_id'])
                                 if wall.tiles[primary].property('pictureInPictureTemporary') else '')
        self._choice_order = [self.choice_for_index(index) for index in self.selection]
        self.parallel_preference = False
        opened = not self.active
        if opened:
            wall.set_sidebar_animating(False)
            self._open_window(len(tiles))
            self.floating.track_tiles(wall.tiles)
            self._minimums = {tile: tile.minimumSize() for tile in wall.tiles}
            content = self.host._content.layout()
            # _apply_start shows the wall once the selected panes are in place.
            wall.hide()
            content.removeWidget(wall)
            content.insertWidget(0, self.placeholder, 1)
            self.placeholder.show()
            self.floating.box.addWidget(wall, 1)
        else:
            self.floating.track_tiles(starting)
            self._minimums.update((tile, tile.minimumSize()) for tile in starting)
        aspects, composition_primary = self.aspects_for(selection), selection.index(primary)
        self.floating.show()
        self.floating.audio_panel.hide()
        self.host.sidebar.picture_in_picture_button.setToolTip(f'管理画中画（{len(tiles)} 路）')
        for rid, tile in list(self._extra_tiles.items()):
            if tile not in tiles:
                self._remove_extra(rid)
        self.selection = [wall.tiles.index(tile) for tile in tiles]
        self.primary = wall.tiles.index(primary_tile) if primary_tile in tiles else self.selection[0]
        self._queue_start(tiles, columns, aspects, composition_primary, starting, opened)
        return True

    def _open_window(self, count):
        self.floating = PictureInPictureWindow(self)
        if self.geometry:
            self.floating.restoreGeometry(QByteArray.fromBase64(self.geometry.encode('ascii')))
        else:
            self.floating.resize_to_width(480 if count == 1 else 640)

    def _start_parallel(self, selection, columns, primary, candidates):
        rooms = {str(candidates[key]['room_id']): candidates[key] for key in selection}
        if columns == FREE_LAYOUT and len(rooms) != len(selection):
            self.placement = ()
            columns = 0
        primary_id = str(candidates[primary]['room_id']) if primary in selection else next(iter(rooms))
        if self._parallel is None:
            self._open_window(len(rooms))
            self._parallel = ParallelPictureInPicture(self.host, self.floating)
            self.floating.box.addWidget(self.display_wall, 1)
        pending = self._pending_start[1] if self._pending_start is not None else ()
        existing = set(self._parallel.tiles.values())
        wall_sources = {str(room['room_id']): self.host.wall.tiles[index]
                        for index, room in self._wall_candidates()} if self.move_wall_streams else {}
        tiles = self._parallel.update(rooms, primary_id, self.floating, wall_sources, self.move_wall_streams)
        starting = [tile for tile in tiles if tile not in existing or tile in pending]
        self.columns = columns
        self.parallel_preference = True
        aspects = [video_aspect(self.host.players.get(tile)) or 16 / 9 for tile in tiles]
        self.floating.show()
        self.floating.audio_panel.hide()
        self.host.sidebar.picture_in_picture_button.setToolTip(f'管理画中画（{len(tiles)} 路）')
        self.host._refresh_meta()
        self._queue_start(tiles, columns, aspects, list(rooms).index(primary_id), starting, False)

    def _queue_start(self, tiles, columns, aspects, composition_primary, starting, opened):
        """Yield once after showing the shell before touching native video panes."""
        self._start_serial += 1
        serial = self._start_serial
        self._pending_start = (serial, list(starting), bool(opened))
        if QApplication.platformName() != 'windows':
            self._apply_start(serial, tiles, columns, aspects, composition_primary)
            return
        if opened:
            QTimer.singleShot(0, self, self._minimize_host)
        QTimer.singleShot(0, self, lambda: self._apply_start(
            serial, tiles, columns, aspects, composition_primary))

    def _apply_start(self, serial, tiles, columns, aspects, composition_primary):
        pending = self._pending_start
        if self.floating is None or pending is None or pending[0] != serial:
            return
        wall = self.display_wall
        primary = (composition_primary if self._parallel is not None
                   else self.selection.index(self.primary))
        previous_panels = bool(self.danmaku_panels)
        chat_widgets = self.floating.set_danmaku_panes(self.chat_slots or (), wall)
        wall.presentation_control.set_picture_in_picture(
            tiles, columns, aspects, primary, placement=self.placement, chat_widgets=chat_widgets)
        mixed, main = composition_inputs(aspects, chat_widgets, primary)
        self.floating.set_composition(mixed, columns, main, placement=self.placement)
        wall.show()
        if previous_panels or chat_widgets:
            self.host.sync_danmaku()
        self.host._tray.sync_picture_in_picture()
        if pending[2]:
            QTimer.singleShot(0, self, self._minimize_host)
        self._start_next_tile(serial)

    def _start_next_tile(self, serial):
        pending = self._pending_start
        if self.floating is None or pending is None or pending[0] != serial:
            return
        starting = pending[1]
        if starting:
            self.host.start_tile(starting.pop(0))
            QTimer.singleShot(0, self, lambda: self._start_next_tile(serial))
            return
        self._pending_start = None
        self._sync_overlays()
        self._aspect_timer.start()
        self.host._save_timer.start()

    def _minimize_host(self):
        if self.moves_main_wall and not self.host._closing:
            self.host.showMinimized()

    def _sync_overlays(self):
        wall = self.host.wall
        layer = wall._quick_danmaku_layer
        if layer is not None:
            layer.set_presentation_window(self.host._fullscreen_tile)
            layer.show()
        for tile in wall.tiles:
            tile.video_danmaku.super_chat_overlay.set_presentation_changing(False)
            dialog = self.host._stream_info_dialogs.get(tile)
            if dialog is not None:
                dialog.set_presentation_owner(tile.window())

    def restore(self, *, activate=False, keep_dialog=False):
        floating = self.floating
        if floating is None:
            return
        self._start_serial += 1
        self._pending_start = None
        if self.dialog is not None and not keep_dialog:
            self.dialog.reject()
        self.geometry = str(floating.saveGeometry().toBase64(), 'ascii')
        floating.stop()
        self._aspect_timer.stop()
        had_chat = bool(floating.danmaku_panels)
        floating.set_danmaku_panes((), self.display_wall)
        self.floating = None
        if self._parallel is not None:
            self._parallel.close(floating)
            self._choice_order = self.selected_choices()
            primary = self.primary_choice()
            self.selection = [key for key in self._choice_order if isinstance(key, int)]
            self.external_rooms = [key for key in self._choice_order if isinstance(key, str)]
            self.primary = primary if isinstance(primary, int) else None
            self.external_primary = primary if isinstance(primary, str) else ''
            self._parallel = None
            if had_chat:
                self.host.sync_danmaku()
            floating.hide()
            floating.deleteLater()
            self.host.sidebar.picture_in_picture_button.setToolTip('选择多路画面，组合为置顶小窗')
            self.host._refresh_meta()
            self.host._save_timer.start()
            if activate:
                self.host._tray.restore()
            return
        wall = self.host.wall
        selected = [wall.tiles[index] for index in self.selection]
        primary_tile = wall.tiles[self.primary]
        for rid in list(self._extra_tiles):
            self._remove_extra(rid)
        self.selection = [wall.tiles.index(tile) for tile in selected if tile in wall.tiles]
        self.primary = wall.tiles.index(primary_tile) if primary_tile in wall.tiles else None
        # Restore the main window while it still contains only the placeholder.
        # Showing a minimized host after mounting the wall exposes every native pane twice.
        if activate and self.host.isMinimized():
            self.host.setWindowState(self.host.windowState() & ~Qt.WindowMinimized)
        wall.hide()
        floating.box.removeWidget(wall)
        content = self.host._content.layout()
        target_geometry = self.placeholder.geometry()
        content.removeWidget(self.placeholder)
        self.placeholder.hide()
        content.insertWidget(0, wall, 1)
        for tile, minimum in self._minimums.items():
            tile.setMinimumSize(minimum)
        # Resize and show events would each lay out native video and controls.
        # Apply their final geometry once, under the restored wall.
        previous = {tile: getattr(tile, '_presentation_changing', False) for tile in wall.tiles}
        for tile in previous:
            tile._presentation_changing = True
        try:
            wall.setGeometry(target_geometry)
            wall.set_picture_in_picture(None)
            floating.hide()
            floating.deleteLater()
            wall.show()
        finally:
            for tile, changing in previous.items():
                tile._presentation_changing = changing
        for tile in wall.tiles:
            tile._layout_areas()
        self.host._tray.sync_picture_in_picture()
        self._sync_overlays()
        self.host.sidebar.picture_in_picture_button.setToolTip('选择多路画面，组合为置顶小窗')
        self.host._refresh_meta()
        if activate:
            self.host._tray.restore()

    def state(self):
        geometry = (str(self.floating.saveGeometry().toBase64(), 'ascii')
                    if self.active else self.geometry)
        choices = self.selected_choices()
        selection = [key for key in choices if isinstance(key, int) and 0 <= key < len(self.host.wall.tiles)]
        selected_primary = self.primary_choice()
        primary = selected_primary if selected_primary in selection else None
        external = [key for key in choices if isinstance(key, str)]
        state = dict(selection=selection, columns=self.columns, primary=primary, pinned=self.pinned,
                    geometry=geometry, external_rooms=external,
                    external_primary=selected_primary if selected_primary in external else '',
                    choice_order=choices, parallel=self.parallel_preference, placement=self.placement,
                    picker_size=self.picker_size,
                    move_wall_streams=self.move_wall_streams)
        if self.chat_slots is not None:
            state['chat_slots'] = self.chat_slots
        elif self._legacy_chat:
            state['show_danmaku'] = True
        return state
