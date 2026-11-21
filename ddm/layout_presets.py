"""Saved divider geometry and shortcuts for layout-only presets."""
from copy import deepcopy

from PySide6.QtGui import QKeySequence

from . import layouts
from .room_presets import validate_ratios
from .shortcut_actions import WHEEL_SHORTCUTS


def _shortcut(text):
    sequence = QKeySequence(text) if isinstance(text, str) else QKeySequence()
    return sequence.toString() if sequence.count() == 1 else ''


class LayoutPresets:
    def __init__(self, host, saved, overrides=None):
        self.host = host
        self.overrides = {}
        for base, record in (overrides.items() if isinstance(overrides, dict) else ()):
            if base not in layouts.BY_ID or not isinstance(record, dict):
                continue
            try:
                self.overrides[base] = dict(shortcut=_shortcut(record.get('shortcut')))
                if 'ratios' in record:
                    self.overrides[base]['ratios'] = validate_ratios(base, record['ratios'])
            except ValueError:
                self.overrides.pop(base, None)
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

    def override_state(self):
        return deepcopy(self.overrides)

    def save_override(self, base, ratios):
        ratios = validate_ratios(base, ratios)
        self.overrides.setdefault(base, {'shortcut': ''})['ratios'] = ratios
        if base == self.host.wall.layout_id:
            self.apply(base)
        self.host._save_timer.start()

    def edit(self, base):
        host = self.host
        wall = host.wall
        if host._closing or host._fullscreen_tile is not None or wall.picture_in_picture_tiles is not None:
            return None
        from .layout_preset_editor import LayoutPresetEditor
        ratios = self.overrides.get(base, {}).get('ratios') if base != wall.layout_id else None
        if ratios is None:
            ratios = wall.corner_ratios() if base == 'corner' else wall.layout_ratios().get(base, {})
        editor = LayoutPresetEditor(host, base, ratios)
        editor.accepted.connect(lambda: self.save_override(base, editor.ratios()))
        editor.show()
        return editor

    def select_builtin(self, base):
        if layouts.snap_grid_size(base) or 'ratios' in self.overrides.get(base, {}):
            return self.apply(base)
        self.host._on_layout_changed(base)

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
        for key, item in (self.items | self.overrides).items():
            shortcut = item['shortcut']
            if shortcut and shortcut not in reserved:
                result.setdefault(shortcut, key)
        return result

    def bind(self, key, text):
        shortcut = _shortcut(text)
        if shortcut and (shortcut in self._reserved_shortcuts() or any(
                item['shortcut'] == shortcut and other != key
                for other, item in (self.items | self.overrides).items())):
            raise ValueError('此快捷键已被占用')
        record = (self.overrides.setdefault(key, {}) if key in layouts.BY_ID else self.items[key])
        record['shortcut'] = shortcut
        self.host._refresh_shortcuts()
        self.host._save_timer.start()

    def apply(self, key):
        host = self.host
        if host._fullscreen_tile is not None or host._closing:
            return False
        item = self.overrides.get(key, {}) if key in layouts.BY_ID else self.items[key]
        if host.picture_in_picture.moves_main_wall:
            host.picture_in_picture.restore()
        host.wall._cancel_border_drag()
        base = item.get('base', key)
        if 'ratios' in item:
            host.wall.layout_control.set_preset_ratios(base, item['ratios'])
        host.window_layout.on_layout_changed(base, preserve_rooms=True)
        host._save_timer.start()
        return True
