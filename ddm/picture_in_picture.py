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
from .pip_composition import focus_chat_cells, focus_slots
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
        saved = host.state.get('ui', {}).get('picture_in_picture', {})
        self.selection = list(saved.get('selection', []))
        self.columns = saved.get('columns', 0)
        self.primary = saved.get('primary')
        self.external_rooms = list(saved.get('external_rooms', []))
        self.external_primary = saved.get('external_primary', '')
        self._choice_order = list(saved.get('choice_order', []))
        self._extra_tiles = {}
        self.pinned = bool(saved.get('pinned', True))
        self.geometry = saved.get('geometry', '')
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

    def _refresh_theme(self, *_args):
        if self.active:
            self.floating.tools.update()
            for button in self.floating.tools.findChildren(PictureInPictureButton):
                button.update()

    def manage(self):
        if self.active:
            self.floating.audio_panel.hide()
        if self.dialog is not None:
            self.dialog.raise_()
            self.dialog.activateWindow()
            return
        if not self.selection and not self.external_rooms:
            capacity = self.host.wall._capacity() or len(self.host.wall.tiles)
            self.selection = [index for index, _room in self._wall_candidates() if index < capacity]
            if self.chat_cells(FOCUS_LAYOUT):
                self.columns = FOCUS_LAYOUT
        self.dialog = PictureInPictureDialog(self)
        self.dialog.finished.connect(self._finish_manage)
        self.dialog.open()

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
        choices = [self.choice_for_index(index) for index in self.selection]
        choices += [rid for rid in self.external_rooms if rid not in choices]
        if self.active:
            return choices
        return ([key for key in self._choice_order if key in choices]
                + [key for key in choices if key not in self._choice_order])

    def primary_choice(self):
        return self.external_primary or self.choice_for_index(self.primary)

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

    def chat_cells(self, columns):
        return focus_chat_cells(self.host.wall, columns)

    def composition(self, selection, columns, primary=None):
        aspects = self.aspects_for(selection)
        chat = self.chat_cells(columns)
        if chat:
            values = dict(zip(selection, aspects))
            slots = focus_slots(selection, chat, primary)
            return slots, [values.get(key, 16 / 9) for key in slots], 0
        return list(selection), aspects, selection.index(primary) if primary in selection else 0

    def aspects_for(self, selection):
        aspects = []
        for index in selection:
            tile = self._extra_tiles.get(index) if isinstance(index, str) else self.host.wall.tiles[index]
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
        if not self.active or self.floating._gesture is not None or self.floating._reorder_drag is not None:
            return
        wall = self.host.wall
        _slots, aspects, primary = self.composition(self.selection, self.columns, self.primary)
        if aspects == wall.picture_in_picture_aspects:
            return
        wall.picture_in_picture_aspects = aspects
        self.floating.set_composition(aspects, self.columns, primary)
        wall.relayout(force=True)

    def swap_positions(self, source, target):
        tiles = self.host.wall.picture_in_picture_tiles
        if source is target or source not in tiles or target not in tiles:
            return
        first, second = tiles.index(source), tiles.index(target)
        primary = self.selection.index(self.primary)
        self.selection[first], self.selection[second] = self.selection[second], self.selection[first]
        if self.columns == FOCUS_LAYOUT:
            self.primary = self.selection[primary]
        self.start(self.selection, self.columns, self.primary)

    def start(self, selection, columns=0, primary=None):
        wall = self.host.wall
        candidates = {key: room for _title, entries in self.candidate_groups() for key, room in entries}
        for key in selection:
            if self.choice_for_index(key) not in candidates:
                return False
        chat = self.chat_cells(columns)
        if chat and len({self.choice_for_index(key) for key in selection}) != 6 - len(chat):
            return False
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
        opened = not self.active
        if opened:
            wall.set_sidebar_animating(False)
            self.floating = PictureInPictureWindow(self)
            if self.geometry:
                self.floating.restoreGeometry(QByteArray.fromBase64(self.geometry.encode('ascii')))
            else:
                width = 480 if len(tiles) == 1 else 640
                self.floating.resize_to_width(width)
            self._minimums = {tile: tile.minimumSize() for tile in wall.tiles}
            content = self.host._content.layout()
            content.removeWidget(wall)
            content.insertWidget(0, self.placeholder, 1)
            self.placeholder.show()
            self.floating.box.addWidget(wall, 1)
        else:
            self.floating.track_tiles(starting)
            self._minimums.update((tile, tile.minimumSize()) for tile in starting)
        _slots, aspects, composition_primary = self.composition(selection, columns, primary)
        wall.set_picture_in_picture(tiles, columns, aspects, selection.index(primary))
        self.floating.set_composition(aspects, columns, composition_primary)
        self.floating.show()
        wall.show()
        for rid, tile in list(self._extra_tiles.items()):
            if tile not in tiles:
                self._remove_extra(rid)
        self.selection = [wall.tiles.index(tile) for tile in tiles]
        self.primary = wall.tiles.index(primary_tile) if primary_tile in tiles else self.selection[0]
        for tile in starting:
            self.host.start_tile(tile)
        if chat:
            self.host.sync_danmaku()
        self.floating.audio_panel.hide()
        self._sync_overlays()
        self._aspect_timer.start()
        self.host.sidebar.picture_in_picture_button.setToolTip(f'管理画中画（{len(tiles)} 路）')
        if opened:
            QTimer.singleShot(0, self, self._minimize_host)
        self.host._save_timer.start()
        return True

    def _minimize_host(self):
        if self.active and not self.host._closing:
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

    def restore(self, *, activate=False):
        floating = self.floating
        if floating is None:
            return
        if self.dialog is not None:
            self.dialog.reject()
        self.geometry = str(floating.saveGeometry().toBase64(), 'ascii')
        floating.stop()
        self._aspect_timer.stop()
        self.floating = None
        wall = self.host.wall
        selected = [wall.tiles[index] for index in self.selection]
        primary_tile = wall.tiles[self.primary]
        for rid in list(self._extra_tiles):
            self._remove_extra(rid)
        self.selection = [wall.tiles.index(tile) for tile in selected if tile in wall.tiles]
        self.primary = wall.tiles.index(primary_tile) if primary_tile in wall.tiles else None
        floating.box.removeWidget(wall)
        content = self.host._content.layout()
        content.removeWidget(self.placeholder)
        self.placeholder.hide()
        content.insertWidget(0, wall, 1)
        for tile, minimum in self._minimums.items():
            tile.setMinimumSize(minimum)
        wall.set_picture_in_picture(None)
        floating.hide()
        floating.deleteLater()
        wall.show()
        self._sync_overlays()
        self.host.sidebar.picture_in_picture_button.setToolTip('选择多路画面，组合为置顶小窗')
        self.host._refresh_meta()
        if activate:
            self.host._tray.restore()

    def state(self):
        geometry = (str(self.floating.saveGeometry().toBase64(), 'ascii')
                    if self.active else self.geometry)
        selection = [index for index in self.selection if 0 <= index < len(self.host.wall.tiles)
                     and not self.host.wall.tiles[index].property('pictureInPictureTemporary')]
        primary = self.primary if self.primary in selection else None
        return dict(selection=selection, columns=self.columns, primary=primary, pinned=self.pinned,
                    geometry=geometry, external_rooms=list(self.external_rooms), external_primary=self.external_primary,
                    choice_order=self.selected_choices())
