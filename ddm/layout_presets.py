"""Saved divider geometry and shortcuts for layout-only presets."""
from copy import deepcopy
from uuid import uuid4

from PySide6.QtGui import QKeySequence

from . import layouts
from .room_presets import snapshot_ratios, validate_ratios
from .shortcut_actions import WHEEL_SHORTCUTS


def _shortcut(text):
    sequence = QKeySequence(text) if isinstance(text, str) else QKeySequence()
    return sequence.toString() if sequence.count() == 1 else ''


class LayoutPresets:
    def __init__(self, host, saved):
        self.host = host
        self.items = {}
        for item in saved if isinstance(saved, list) else ():
            if not isinstance(item, dict):
                continue
            key, name, base = (item.get(field) for field in ('id', 'name', 'base'))
            if (not all(isinstance(value, str) and value.strip() for value in (key, name, base))
                    or key in self.items or base not in layouts.BY_ID):
                continue
            try:
                ratios = validate_ratios(base, item.get('ratios'))
            except ValueError:
                continue
            self.items[key] = dict(id=key, name=name, base=base, ratios=ratios,
                                   shortcut=_shortcut(item.get('shortcut')))

    def state(self):
        return deepcopy(list(self.items.values()))

    def _current_geometry(self):
        wall = self.host.wall
        if self.host._fullscreen_tile is not None or wall.picture_in_picture_tiles is not None:
            raise ValueError('请返回画面墙后保存布局')
        return wall.layout_id, validate_ratios(wall.layout_id, snapshot_ratios(wall))

    def save(self, name):
        name = name.strip()
        if not name:
            raise ValueError('请输入布局名称')
        if any(item['name'] == name for item in self.items.values()):
            raise ValueError('已有同名自定义布局')
        base, ratios = self._current_geometry()
        key = uuid4().hex
        self.items[key] = dict(id=key, name=name, base=base, ratios=ratios, shortcut='')
        self.host._save_timer.start()
        return key

    def update(self, key):
        base, ratios = self._current_geometry()
        item = self.items[key]
        if base != item['base']:
            raise ValueError('请先切到此自定义布局，再拖动分隔线')
        item['ratios'] = ratios
        self.host._save_timer.start()

    def delete(self, key):
        del self.items[key]
        self.host._refresh_shortcuts()
        self.host._save_timer.start()

    def _reserved_shortcuts(self):
        shortcuts = self.host.shortcuts
        reserved = set()
        for key, binding in shortcuts.items():
            if binding and key not in WHEEL_SHORTCUTS and not key.startswith('pip_'):
                sequence = QKeySequence(binding)
                if not sequence.isEmpty():
                    reserved.add(QKeySequence(sequence[0]).toString())
        if shortcuts.get('danmaku_input') == 'Return':
            reserved.add('Enter')
        return reserved

    def shortcuts(self):
        reserved = self._reserved_shortcuts()
        result = {}
        for key, item in self.items.items():
            shortcut = item['shortcut']
            if shortcut and shortcut not in reserved:
                result.setdefault(shortcut, key)
        return result

    def bind(self, key, text):
        shortcut = _shortcut(text)
        if shortcut and (shortcut in self._reserved_shortcuts() or any(
                item['shortcut'] == shortcut and other != key for other, item in self.items.items())):
            raise ValueError('此快捷键已被占用')
        self.items[key]['shortcut'] = shortcut
        self.host._refresh_shortcuts()
        self.host._save_timer.start()

    def apply(self, key):
        host = self.host
        if host._fullscreen_tile is not None or host._closing:
            return False
        item = self.items[key]
        if host.picture_in_picture.moves_main_wall:
            host.picture_in_picture.restore()
        host.wall._cancel_border_drag()
        host.wall.layout_control.set_preset_ratios(item['base'], item['ratios'])
        host.window_layout.on_layout_changed(item['base'], preserve_rooms=True)
        host._save_timer.start()
        return True
