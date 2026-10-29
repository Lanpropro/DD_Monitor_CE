"""Owned, platform-neutral controls in a centered tile bottom-bar region."""
from copy import deepcopy
from dataclasses import dataclass, field
import traceback
import weakref

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLineEdit, QSizePolicy, QWidget


@dataclass
class TileControlContext:
    parent: QWidget
    room: dict
    invalidate_layout: object
    _active: bool = field(default=True, init=False, repr=False)


class TileControl:
    def __init__(self, widget, *, minimum_width=0, preferred_width=240):
        self.widget = widget
        self.minimum_width = max(0, int(minimum_width))
        self.preferred_width = max(self.minimum_width, int(preferred_width))

    def set_room(self, room):
        pass

    def interaction_active(self):
        return False

    def focus_input(self):
        """Focus this control's input for the host shortcut, if supported."""
        return False

    def shutdown(self):
        pass


@dataclass
class _Entry:
    owner: str
    key: str
    priority: int
    order: int
    wrapper: QWidget
    context: TileControlContext
    control: TileControl


class TileControls:
    def __init__(self, tile, *, on_shutdown=None):
        self._tile = weakref.ref(tile)
        self._on_shutdown = on_shutdown
        self.entries = []
        self._disposed = False
        self._panel = None
        self.widget = QWidget(tile.bottom)
        self.widget.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)
        self.widget.hide()
        layout = QHBoxLayout(self.widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.spacer = QWidget(tile.bottom)
        self.spacer.setFixedWidth(0)
        self.spacer.hide()
        bar = tile.bottom.layout()
        index = bar.indexOf(tile.status_label) + 1
        bar.insertWidget(index, self.widget)
        bar.insertWidget(index + 1, self.spacer)

    def room_id(self):
        tile = self._tile()
        return str(tile.room.get('room_id') or '') if tile is not None else ''

    def can_repeat(self):
        return self._repeat_editor() is not None

    def _repeat_editor(self):
        if self._disposed:
            return None
        for entry in self.applicable():
            widget = entry.control.widget
            if not widget.isEnabled() or type(entry.control).focus_input is TileControl.focus_input:
                continue
            editors = ([widget] if isinstance(widget, QLineEdit) else widget.findChildren(QLineEdit))
            editors = [editor for editor in editors if editor.window() is widget.window()
                       and editor.isEnabled() and not editor.isReadOnly() and not editor.isHidden()]
            if len(editors) == 1:
                return editors[0]
        return None

    def repeat_text(self, text, room_id):
        if not room_id or room_id != self.room_id():
            return False
        editor = self._repeat_editor()
        if editor is None or len(text) > editor.maxLength():
            return False
        editor.setText(text)
        # Match Enter in the existing composer, including its login/busy checks.
        QApplication.sendEvent(editor, QKeyEvent(QEvent.KeyPress, Qt.Key_Return, Qt.NoModifier))
        QApplication.sendEvent(editor, QKeyEvent(QEvent.KeyRelease, Qt.Key_Return, Qt.NoModifier))
        return True

    def invalidate(self):
        tile = self._tile()
        if tile is not None and not self._disposed:
            wall = tile.parentWidget()
            if hasattr(wall, '_sync_danmaku_controls'):
                wall._sync_danmaku_controls()
            if self._panel is not None:
                self.layout_panel()
            tile._bottom_layout_signature_value = None
            tile._layout_bottom_controls()

    def set_panel(self, panel):
        """Move the same controls, keeping drafts and plugin ownership intact."""
        if panel is self._panel:
            return
        tile = self._tile()
        if self._panel is not None:
            self._panel.composer_bar.layout().removeWidget(self.widget)
            self._panel.composer_bar.hide()
            self._panel._tile_controls = None
        else:
            tile.bottom.layout().removeWidget(self.widget)
        self._panel = panel
        self.widget.hide()
        if panel is not None:
            self.widget.setParent(panel.composer_bar)
            panel.composer_bar.layout().addWidget(self.widget)
            panel._tile_controls = self
            self.spacer.hide()
            self.layout_panel()
        else:
            self.widget.setParent(tile.bottom)
            bar = tile.bottom.layout()
            bar.insertWidget(bar.indexOf(self.spacer), self.widget)
        tile._bottom_layout_signature_value = None
        tile._layout_bottom_controls()

    def layout_panel(self):
        if self._panel is not None and not self._disposed:
            width = max(0, self._panel.width() - 16)
            fitted = self._allocate(width)
            self._panel.composer_bar.setVisible(bool(fitted))
            self.spacer.hide()

    def add(self, owner, key, factory, priority, order):
        if self._disposed or any(e.owner == owner and e.key == key for e in self.entries):
            return
        tile = self._tile()
        wrapper = QWidget(self.widget)
        layout = QHBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        ref = weakref.ref(self)

        def invalidate():
            controls = ref()
            if controls is not None and ctx._active:
                controls.invalidate()

        ctx = TileControlContext(wrapper, deepcopy(tile.room), invalidate)
        try:
            control = factory(ctx)
            if not isinstance(control, TileControl) or not isinstance(control.widget, QWidget):
                raise ValueError('tile control factory must return TileControl with a QWidget')
            control.widget.setParent(wrapper)
            layout.addWidget(control.widget)
            control.widget.setMinimumWidth(0)
        except Exception:
            ctx._active = False
            traceback.print_exc()
            wrapper.hide()
            wrapper.deleteLater()
            return
        entry = _Entry(owner, key, priority, order, wrapper, ctx, control)
        self.entries.append(entry)
        self.entries.sort(key=lambda e: (-e.priority, e.order))
        for item in self.entries:
            self.widget.layout().removeWidget(item.wrapper)
        for item in self.entries:
            self.widget.layout().addWidget(item.wrapper)
        self._deliver(entry, tile.room)
        self.invalidate()

    def _deliver(self, entry, room):
        entry.context.room = deepcopy(room)
        try:
            entry.control.set_room(deepcopy(room))
        except Exception:
            traceback.print_exc()

    def set_room(self, room):
        for entry in tuple(self.entries):
            self._deliver(entry, room)
        self.invalidate()

    def applicable(self):
        return [e for e in self.entries if not e.control.widget.isHidden()]

    def allocate(self, width):
        """Fit prioritized minima, then preferred widths, returning group width."""
        if self._panel is not None:
            self.spacer.hide()
            return 0
        return self._allocate(width)

    def _allocate(self, width):
        if self._disposed:
            return 0
        width = max(0, int(width))
        remaining = width
        selected = []
        sizes = []
        for entry in self.applicable():
            if remaining >= entry.control.minimum_width:
                selected.append(entry)
                sizes.append(entry.control.minimum_width)
                remaining -= entry.control.minimum_width
        for index, entry in enumerate(selected):
            extra = min(remaining, entry.control.preferred_width - sizes[index])
            sizes[index] += extra
            remaining -= extra
        if selected:
            sizes[0] += remaining
        for entry in self.entries:
            entry.wrapper.setVisible(entry in selected)
        for entry, size in zip(selected, sizes):
            entry.wrapper.setFixedWidth(size)
        fitted = sum(sizes)
        self.widget.setFixedWidth(fitted)
        self.widget.setVisible(bool(selected))
        self.spacer.setVisible(bool(selected))
        self.widget.layout().activate()
        return fitted

    def focus_input(self):
        for entry in tuple(self.entries):
            if entry.wrapper.isVisible() and entry.control.widget.isVisible() and entry.control.widget.isEnabled():
                try:
                    if entry.control.focus_input():
                        return True
                except Exception:
                    traceback.print_exc()
        return False

    def interaction_active(self):
        for entry in tuple(self.entries):
            if entry.wrapper.isVisible() and entry.control.widget.isVisible() and entry.control.widget.isEnabled():
                try:
                    if entry.control.interaction_active():
                        return True
                except Exception:
                    traceback.print_exc()
        return False

    def remove_owner(self, owner=None):
        for entry in tuple(self.entries):
            if owner is not None and entry.owner != owner:
                continue
            self.entries.remove(entry)
            entry.context._active = False
            entry.context.invalidate_layout = lambda: None
            try:
                entry.control.shutdown()
            except Exception:
                traceback.print_exc()
            try:
                self.widget.layout().removeWidget(entry.wrapper)
                entry.wrapper.hide()
                entry.wrapper.setParent(None)
                entry.wrapper.deleteLater()
            except RuntimeError:
                pass  # Qt already disposed the tile.
        self.invalidate()

    def shutdown(self):
        if self._disposed:
            return
        self._disposed = True
        if self._panel is not None:
            try:
                self._panel.composer_bar.hide()
                self._panel._tile_controls = None
            except RuntimeError:
                pass  # The wall can destroy the panel before its tiles.
            self._panel = None
        tile = self._tile()
        callback, self._on_shutdown = self._on_shutdown, None
        if callback is not None and tile is not None:
            # Qt deletion can precede collection of a retained Python wrapper.
            callback(tile)
        self.remove_owner()
        for widget in (self.widget, self.spacer):
            try:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
            except RuntimeError:
                pass
        if tile is not None:
            try:
                tile._bottom_layout_signature_value = None
                tile._layout_bottom_controls()
            except RuntimeError:
                pass  # The tile's destroyed signal also calls shutdown.
