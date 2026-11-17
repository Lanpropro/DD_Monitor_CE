"""Deliver native wheels across the foreign settings window boundary."""
import ctypes
from ctypes import wintypes

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication


def deliver(root, values):
    point = QPoint(values['x'], values['y'])
    if not root.isVisible() or not root.rect().contains(point):
        return
    target = root.childAt(point) or root
    global_point = root.mapToGlobal(point)
    event = QWheelEvent(QPointF(target.mapFromGlobal(global_point)), QPointF(global_point),
                        QPoint(), QPoint(0, values['delta']),
                        Qt.MouseButton(values['buttons']), Qt.KeyboardModifier(values['modifiers']),
                        Qt.NoScrollPhase, False)
    QApplication.sendEvent(target, event)


class EmbeddedSettingsWheel(QObject, QAbstractNativeEventFilter):
    def __init__(self, root, send):
        QObject.__init__(self, root)
        QAbstractNativeEventFilter.__init__(self)
        self.root, self.send = root, send
        self.app = QApplication.instance()
        self.native = root.nativeParentWidget() or root.window()
        self.app.installNativeEventFilter(self)
        root.destroyed.connect(self.stop)

    def stop(self):
        self.app.removeNativeEventFilter(self)

    def nativeEventFilter(self, event_type, message):
        msg = wintypes.MSG.from_address(int(message))
        if msg.message != 0x20A or not self.root.isVisible() or self.app.activePopupWidget() is not None:
            return False, 0
        native = QPoint(ctypes.c_short(msg.lParam & 0xffff).value,
                        ctypes.c_short((msg.lParam >> 16) & 0xffff).value)
        bounds = wintypes.RECT()
        if not ctypes.windll.user32.GetWindowRect(
                wintypes.HWND(int(self.native.effectiveWinId())), ctypes.byref(bounds)):
            return False, 0
        # Use the existing native ancestor; winId() on an alien container would
        # create an extra HWND and its cross-process native window hierarchy.
        point = ((QPointF(native) - QPointF(bounds.left, bounds.top))
                 / self.root.devicePixelRatioF()).toPoint() - self.root.mapTo(self.native, QPoint())
        if not self.root.rect().contains(point):
            return False, 0
        self.send(dict(x=point.x(), y=point.y(),
                       delta=ctypes.c_short((msg.wParam >> 16) & 0xffff).value,
                       buttons=self.app.mouseButtons().value,
                       modifiers=self.app.keyboardModifiers().value))
        # Stop Qt from redirecting the same wheel back into the foreign container.
        return True, 0
