"""Opt-in BUG-070 capture: GUI heartbeat, selected calls and process counters."""
import cProfile
import ctypes
import functools
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys
import threading
import time

from .responsiveness_probe import (ROOT, process_counters, stack_locations, profile_functions, Probe)


from .folder_motion_capture import (FolderMotionCapture, install_folder_capture)


from .theme_capture import (install_theme_capture, install_theme_animation_capture)


def install(path, *, extended_folders=False, profile_sidebar=True):
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from .app import MainWindow
    from .preview import HoverPreview
    from .sidebar_widgets import Sidebar
    from .wall_widgets import WallGrid

    original = MainWindow.__init__
    probe = Probe(path)
    probe.start()
    # Hook before construction: Qt signal connections must receive the wrapped slots.
    for owner, names in ((MainWindow, ('_on_layout_changed', 'sync_danmaku', '_on_status_updated')),
                         (Sidebar, ('set_collapsed', 'set_card_mode', 'refresh_strip', 'reorder_items')),
                         (WallGrid, ('relayout',)), (HoverPreview, ('_check_hover', '_stop_now'))):
        for name in names:
            method = getattr(owner, name)
            label = f'{method.__module__}.{owner.__name__}.{name}'
            setattr(owner, name, probe.timed(method, label,
                    profile_sidebar=profile_sidebar and owner is Sidebar and name == 'set_collapsed'))

    @functools.wraps(original)
    def initialize(window, *args, **kwargs):
        original(window, *args, **kwargs)
        window._responsiveness_probe = probe
        window._folder_motion_probe = FolderMotionCapture(probe, window.sidebar, extended=extended_folders)
        timer = QTimer(window)
        timer.setInterval(100)
        timer.timeout.connect(lambda: probe.pulse(window))
        QApplication.instance().aboutToQuit.connect(window._folder_motion_probe.close)
        QApplication.instance().aboutToQuit.connect(probe.stop)
        window.destroyed.connect(probe.stop)
        probe.pulse(window)
        probe.write('window-ready', state=probe.state)
        timer.start()

    MainWindow.__init__ = initialize
    return probe
