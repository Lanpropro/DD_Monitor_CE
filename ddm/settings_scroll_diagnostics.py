"""Opt-in, bounded wheel delivery evidence for embedded settings pages."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import sys
import time

from PySide6.QtCore import QAbstractNativeEventFilter, QEvent, QObject
from PySide6.QtWidgets import QApplication, QAbstractScrollArea, QWidget


class SettingsScrollCapture(QObject, QAbstractNativeEventFilter):
    def __init__(self, app, path):
        QObject.__init__(self, app)
        QAbstractNativeEventFilter.__init__(self)
        self.path = Path(path)
        self.count = 0
        self.write('start')
        app.installEventFilter(self)
        app.installNativeEventFilter(self)

    def write(self, stage, **values):
        if self.count >= 1200:
            return
        self.count += 1
        record = dict(time=time.time(), pid=os.getpid(), stage=stage, **values)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open('a', encoding='utf-8') as output:
                output.write(json.dumps(record) + '\n')
        except OSError:
            pass

    def nativeEventFilter(self, event_type, message):
        if sys.platform == 'win32' and self.count < 1200:
            msg = wintypes.MSG.from_address(int(message))
            if msg.message in (0x20A, 0x20E):  # WM_MOUSEWHEEL / WM_MOUSEHWHEEL
                self.write('native-wheel', hwnd=int(msg.hWnd or 0), message=msg.message,
                           delta=ctypes.c_short((msg.wParam >> 16) & 0xffff).value)
        return False, 0

    def eventFilter(self, watched, event):
        if self.count >= 1200 or event.type() != QEvent.Wheel or not isinstance(watched, QWidget):
            return False
        areas = []
        owner = watched
        while owner is not None:
            if isinstance(owner, QAbstractScrollArea):
                bar = owner.verticalScrollBar()
                areas.append(dict(kind=type(owner).__name__, value=bar.value(),
                                  maximum=bar.maximum(), step=bar.singleStep()))
            owner = owner.parentWidget()
        focus = QApplication.focusWidget()
        self.write('qt-wheel', receiver=type(watched).__name__, areas=areas,
                   angle=event.angleDelta().y(), pixel=event.pixelDelta().y(),
                   focus=type(focus).__name__ if focus is not None else '')
        return False


def install():
    if os.environ.get('DDM_SETTINGS_SCROLL_CAPTURE') != '1':
        return
    app = QApplication.instance()
    if getattr(app, '_settings_scroll_capture', None) is None:
        from . import config
        root = os.environ.get('DDM_DIAGNOSTIC_APP_ROOT') or config.data_root()
        directory = os.environ.get('DDM_DIAGNOSTIC_LOG_DIR') or str(Path(root) / 'logs')
        path = Path(directory) / f'settings-scroll-{os.getpid()}.jsonl'
        app._settings_scroll_capture = SettingsScrollCapture(app, path)
