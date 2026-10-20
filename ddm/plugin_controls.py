"""Owned, platform-neutral controls in a centered tile bottom-bar region."""
from copy import deepcopy
from dataclasses import dataclass, field
import traceback
import weakref

from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QWidget


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

    def invalidate(self):
        tile = self._tile()
        if tile is not None and not self._disposed:
            tile._bottom_layout_signature_value = None
            tile._layout_bottom_controls()

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
