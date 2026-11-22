"""GUI-thread binding to the host-owned account and conditional device store."""
from PySide6.QtCore import QObject, Slot
from PySide6.QtCore import Signal

class BiliSession(QObject):
    changed = Signal(object)

    def __init__(self, context, parent=None):
        super().__init__(parent)
        self.context = context

    def snapshot(self):
        return self.context.credentials('bilibili')

    @Slot(int, str)
    def publish_device(self, generation, value):
        self.context.update_credentials('bilibili', {'buvid3': value}, expected_generation=generation)

    def on_event(self, event, payload):
        if payload.get('platform') == 'bilibili' and event in ('account.changed', 'account.credentials_updated'):
            self.changed.emit(self.snapshot())
