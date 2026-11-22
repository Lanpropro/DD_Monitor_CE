"""Bilibili composer lifecycle and registration with the host's tile controls."""
import weakref

from PySide6.QtCore import Qt

from ..plugin_controls import TileControl
from ..plugin_types import PluginContext
from .composer import DanmakuComposer
from .gift_controller import GiftCoordinator
from .notifications import NotificationReporter
from .session import BiliSession
from .workers import wait_for_requests


class BiliTileControl(TileControl):
    def __init__(self, widget, context):
        super().__init__(widget, minimum_width=90, preferred_width=240)
        self._invalidate_layout = context.invalidate_layout

    def set_room(self, room):
        room_id = room.get('room_id') if room.get('platform', 'bilibili') == 'bilibili' else ''
        self.widget.set_room(room_id, room=room)
        self._invalidate_layout()

    def interaction_active(self):
        return self.widget.interaction_active()

    def focus_input(self):
        if not self.widget.edit.isEnabled():
            return False
        self.widget.edit.setFocus(Qt.ShortcutFocusReason)
        return True

    def shutdown(self):
        self.widget.shutdown()

    def repeat_message(self, event):
        return self.widget.repeat_message(event)


class BiliInteraction:
    name = 'B 站直播互动'

    def __init__(self, manager):
        self.context = PluginContext(manager, 'bili_live')
        self.session = BiliSession(self.context)
        self.coordinator = GiftCoordinator()
        self.controls = weakref.WeakSet()
        self.context.register_tile_control('interaction', self._make_control, priority=100)

    def _make_control(self, context):
        composer = DanmakuComposer(self.session, context.parent, coordinator=self.coordinator,
                                   notifier=NotificationReporter(self.context))
        control = BiliTileControl(composer, context)
        self.controls.add(control)
        return control

    def on_event(self, event, payload):
        if event == 'app.closing':
            self._close_controls()
        self.session.on_event(event, payload)

    def _close_controls(self):
        for control in tuple(self.controls):
            try:
                control.shutdown()
            except RuntimeError:
                pass  # Qt may already have destroyed a closing tile's widget.

    def on_unload(self):
        self._close_controls()
        wait_for_requests()
