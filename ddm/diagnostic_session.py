"""Explicit diagnostic sessions for unresolved issues; no capture on normal launch."""
import atexit
import json
from pathlib import Path
import sys

MODES = ('folders', 'responsiveness', 'notices', 'danmaku', 'drag',
         'douyu', 'douyu-deep', 'theme', 'fullscreen')
PROTOCOL = 1


def requested_mode(arguments):
    values = [arg.split('=', 1)[1] for arg in arguments if arg.startswith('--diagnose-session=')]
    if not values:
        return None
    if len(values) != 1 or values[0] not in MODES:
        raise ValueError('Unknown or repeated diagnostic session mode')
    return values[0]


def install(mode, directory):
    if mode not in MODES:
        raise ValueError('Unknown diagnostic session mode')
    from .app import MainWindow
    from .douyu_capture import Capture
    directory = Path(directory)
    metadata = Capture(directory / 'diagnostic-session.jsonl')
    build = {}
    build_path = Path(sys.executable).parent / 'ddm-build.json'
    if getattr(sys, 'frozen', False) and build_path.is_file():
        build = json.loads(build_path.read_text(encoding='utf-8-sig'))
    metadata.emit('session-start', mode=mode, protocol=PROTOCOL,
                  version=build.get('version'), source_commit=build.get('source_commit'))
    atexit.register(metadata.close)
    if mode == 'folders':
        from .responsiveness import install_folder_capture
        install_folder_capture(directory / 'folder-motion.jsonl', extended=True)
    elif mode == 'responsiveness':
        from .responsiveness import install as install_responsiveness
        install_responsiveness(directory / 'responsiveness.jsonl', extended_folders=True)
    elif mode in ('notices', 'danmaku'):
        if mode == 'notices':
            from .notice_diagnostics import NoticeCloseTrace as Trace
            path = directory / 'notice-close.jsonl'
        else:
            from .danmaku_diagnostics import MotionTrace as Trace
            path = directory / 'danmaku-motion.jsonl'
        capture = Capture(path)
        trace = Trace(path, emit=capture.emit)
        trace.install()
        atexit.register(capture.close)
        metadata.trace = trace
    elif mode == 'drag':
        from .drag_diagnostics import Recorder
        metadata.recorder = Recorder(directory / 'drag-windows.jsonl', profile_first_drag=True)
        metadata.recorder.install()
        atexit.register(metadata.recorder.handler.close)
    elif mode in ('douyu', 'douyu-deep'):
        from .douyu_diagnostics import install as install_douyu
        install_douyu(directory / 'douyu-playback.jsonl', deep=mode == 'douyu-deep')
    elif mode == 'theme':
        from .responsiveness import install_theme_capture, install_theme_animation_capture
        metadata.probe = install_theme_capture(directory / 'theme-switch.jsonl')
        install_theme_animation_capture(metadata.probe)
    elif mode == 'fullscreen':
        from .fullscreen_diagnostics import install as install_fullscreen
        metadata.probe = install_fullscreen(directory / 'fullscreen.jsonl')

    original = MainWindow.__init__
    def initialize(window, *args, **kwargs):
        original(window, *args, **kwargs)
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QKeySequence, QShortcut
        folder_capture = getattr(window, '_folder_motion_probe', None)
        shortcut = QShortcut(QKeySequence('Ctrl+Alt+F8'), window)
        shortcut.setContext(Qt.ApplicationShortcut)
        def snapshot():
            metadata.emit('user-marker', mode=mode)
            if folder_capture is not None:
                folder_capture.snapshot()
            if mode == 'danmaku':
                metadata.trace.arm()
            elif mode == 'notices':
                from .online_ui import UpdateNotice
                for notice in QApplication.topLevelWidgets():
                    if isinstance(notice, UpdateNotice) and notice.parentWidget() is window:
                        metadata.trace.watch(notice)
                        metadata.trace.record('manual-snapshot', notice)
        shortcut.activated.connect(snapshot)
        window._diagnostic_shortcut = shortcut
        window._diagnostic_session = metadata
        links = {}
        if folder_capture is not None:
            links['folders'] = folder_capture.probe.session
        if hasattr(metadata, 'trace'):
            links[mode] = metadata.trace.session
        if hasattr(metadata, 'recorder'):
            links[mode] = metadata.recorder.session
        if hasattr(metadata, 'probe'):
            links[mode] = metadata.probe.session
        if hasattr(window, '_douyu_capture'):
            links['douyu'] = window._douyu_capture.run
        metadata.emit('window-ready', mode=mode, linked_sessions=links)
        from PySide6.QtWidgets import QApplication
        QApplication.instance().aboutToQuit.connect(metadata.close)
    MainWindow.__init__ = initialize
    return metadata
