"""Owned GUI-thread delivery for the public plugin notice/login APIs."""
from copy import deepcopy
import traceback
import weakref

from PySide6.QtCore import QObject, Qt, Signal, Slot
import shiboken6


class PluginNotices(QObject):
    _requested = Signal(object)

    def __init__(self, window):
        super().__init__(window)
        self._window = weakref.ref(window)
        self._requested.connect(self._deliver, Qt.QueuedConnection)

    def available(self, context):
        window = self._window()
        return (context._active and not context._manager._unloaded
                and shiboken6.isValid(self) and window is not None
                and shiboken6.isValid(window) and not getattr(window, '_closing', False))

    def notify(self, context, message, *, rooms=(), kind='info', on_click=None):
        if kind not in ('info', 'warning', 'live'):
            raise ValueError('notice kind must be info, warning or live')
        if on_click is not None and not callable(on_click):
            raise ValueError('notice on_click must be callable')
        if not self.available(context) or not callable(getattr(self._window(), '_show_notice', None)):
            return False
        return self._queue(context, 'notice', str(message), {
            'rooms': deepcopy(tuple(rooms)), 'kind': kind, 'on_click': on_click})

    def request_login(self, context, platform, *, reauthenticate=False):
        if not self.available(context) or not callable(getattr(self._window(), 'open_login', None)):
            return False
        return self._queue(context, 'login', str(platform), {
            'reauthenticate': bool(reauthenticate)})

    def _queue(self, context, operation, value, options):
        if not self.available(context):
            return False
        try:
            self._requested.emit((weakref.ref(context), operation, value, options))
        except RuntimeError:
            return False  # Window deletion can race a worker's signal emission.
        return True

    def _guard_action(self, context_ref, callback):
        def guarded():
            context = context_ref()
            if context is not None and self.available(context):
                try:
                    callback()
                except Exception:
                    traceback.print_exc()
        return guarded

    @Slot(object)
    def _deliver(self, request):
        context_ref, operation, value, options = request
        context = context_ref()
        if context is None or not self.available(context):
            return
        try:
            if operation == 'login':
                self._window().open_login(value, **options)
            else:
                callback = options['on_click']
                if callback is not None:
                    options['on_click'] = self._guard_action(context_ref, callback)
                self._window()._show_notice(value, **options)
        except Exception:
            traceback.print_exc()
