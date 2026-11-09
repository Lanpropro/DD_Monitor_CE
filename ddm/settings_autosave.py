"""Coalesced settings drafts; one in-flight save and explicit acknowledgement."""
from copy import deepcopy
from weakref import WeakSet

from PySide6.QtCore import QEvent, QObject, QTimer, Qt, Signal
from PySide6.QtWidgets import QAbstractButton, QComboBox, QDoubleSpinBox, QKeySequenceEdit, QLineEdit, QPlainTextEdit, QSlider, QSpinBox, QTextEdit, QWidget
from shiboken6 import isValid


class SettingsAutoSave(QObject):
    requested = Signal(dict)
    statusChanged = Signal(str, str)
    closeReady = Signal(int)

    def __init__(self, dialog):
        super().__init__(dialog)
        self.dialog = dialog
        self.active = False
        self.confirmed = {}
        self.pending = None
        self.failed = {}
        self.closing = None
        self.action = None
        self.observed = WeakSet()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.flush)
        self.closeReady.connect(dialog.done)
        dialog.pageCreated.connect(self.watch_page)

    def snapshot(self):
        dialog = self.dialog
        enabled = dialog.enabled_plugins()
        grid = dialog.general_page.layout().itemAt(1).layout()
        core = set(dialog.general_page._checks.values())
        from PySide6.QtWidgets import QCheckBox
        controls = {check.objectName(): check.isChecked()
                    for check in dialog.general_page.findChildren(QCheckBox)
                    if check not in core and check.objectName() and grid.indexOf(check) >= 0}
        return dict(settings=dialog.settings(), shortcuts=dialog.shortcuts(),
                    enabled_plugins=None if enabled is None else sorted(enabled), plugin_controls=controls)

    def start(self):
        if not self.active:
            self.confirmed = deepcopy(self.snapshot())
            self.active = True
            for widget in self.observed:
                if isValid(widget):
                    widget.installEventFilter(self)
            self.watch(self.dialog.general_page)
            for page in self.dialog._loaded_pages.values():
                self.watch(page)

    def stop(self):
        self.active = False
        self.timer.stop()
        for widget in self.observed:
            if isValid(widget):
                widget.removeEventFilter(self)

    def watch_page(self, index, page):
        if self.active:
            if hasattr(page, 'values'):
                self.adopt('shortcuts' if index == 5 else 'settings', page.values())
            if index == 7:
                self.confirmed['enabled_plugins'] = self.snapshot()['enabled_plugins']
            self.watch(page)

    def watch(self, widget):
        if widget in self.observed:
            return
        self.observed.add(widget)
        widget.installEventFilter(self)
        if isinstance(widget, QLineEdit):
            widget.editingFinished.connect(self.flush)
        elif isinstance(widget, (QPlainTextEdit, QTextEdit)):
            widget.textChanged.connect(self.schedule)
        elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
            widget.valueChanged.connect(self.schedule)
            widget.editingFinished.connect(self.flush)
        elif isinstance(widget, QSlider):
            widget.valueChanged.connect(self.schedule)
            widget.sliderReleased.connect(self.flush)
        elif isinstance(widget, QComboBox):
            widget.currentIndexChanged.connect(self.schedule)
        elif isinstance(widget, QAbstractButton):
            widget.toggled.connect(self.schedule)
        elif isinstance(widget, QKeySequenceEdit):
            widget.keySequenceChanged.connect(self.schedule)
        else:
            for name in ('changed', 'curveChanged', 'positionChanged', 'placementChanged', 'modeChanged'):
                signal = getattr(widget, name, None)
                if signal is not None and hasattr(signal, 'connect'):
                    signal.connect(self.schedule)
        for child in widget.findChildren(QWidget, options=Qt.FindDirectChildrenOnly):
            self.watch(child)

    def eventFilter(self, watched, event):
        if self.active and event.type() == QEvent.ChildPolished and isinstance(event.child(), QWidget):
            self.watch(event.child())
        return False

    def schedule(self, *args):
        if self.active:
            self.timer.start()

    def changes(self, snapshot):
        changes = {}
        for group, value in snapshot.items():
            if isinstance(value, dict):
                delta = {key: entry for key, entry in value.items()
                         if key in self.failed.get(group, {}) or key not in self.confirmed.get(group, {})
                         or entry != self.confirmed[group][key]}
                if delta:
                    changes[group] = dict(value) if group == 'plugin_controls' else delta
            elif group in self.failed or value != self.confirmed.get(group):
                changes[group] = value
        return changes

    def adopt(self, group, values):
        if self.active:
            self.confirmed.setdefault(group, {}).update(deepcopy(values))

    def flush(self, *args):
        self.timer.stop()
        if not self.active:
            return True
        if self.pending is not None:
            return False
        if any(isValid(widget) and isinstance(widget, QSlider) and widget.isSliderDown() for widget in self.observed):
            return False
        try:
            if any(isValid(widget) and isinstance(widget, QLineEdit) and widget.isVisible() and not widget.hasAcceptableInput()
                   for widget in self.observed):
                raise ValueError('请先修正输入内容')
            appearance = self.dialog._loaded_pages.get(1)
            if appearance is not None and appearance.parts_editor is not None and not appearance.parts_editor.save_changes():
                raise ValueError('请检查外观设置中的输入')
            snapshot = self.snapshot()
            changes = self.changes(snapshot)
        except (ValueError, OSError) as error:
            self.statusChanged.emit('error', str(error))
            return False
        if not changes:
            if self.action is not None:
                action, self.action = self.action, None
                action()
            elif self.closing is not None:
                result, self.closing = self.closing, None
                self.closeReady.emit(result)
            return True
        self.pending = deepcopy(changes)
        self.statusChanged.emit('saving', '')
        self.requested.emit(changes)
        return self.pending is None and not self.failed

    def acknowledge(self, error=''):
        if self.pending is None:
            return
        if error:
            self.failed = self.pending
            self.pending = None
            self.statusChanged.emit('error', error)
            return
        saved, self.pending = self.pending, None
        self.failed = {}
        for group, value in saved.items():
            if isinstance(value, dict):
                self.confirmed.setdefault(group, {}).update(value)
            else:
                self.confirmed[group] = value
        self.statusChanged.emit('saved', '')
        self.flush()

    def request_close(self, result):
        if not self.active:
            return True
        self.action = None
        self.closing = None
        if self.pending is None and self.flush():
            return True
        self.closing = int(result)
        return False

    def defer(self, action):
        if not self.active:
            return False
        self.action = None
        if self.pending is None and self.flush():
            return False
        self.action = action
        return True
