"""Application icon choices and Qt window icon updates."""
from pathlib import Path
import sys


RESOURCE_ROOT = (Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
                 else Path(__file__).resolve().parents[1])
DEFAULT_STYLE = 'd'
ICON_FILES = {
    'd': 'favicon.ico',
    'b': 'app-icons/badge.ico',
    'f': 'app-icons/classic.ico',
}


def normalize_style(value):
    return value if isinstance(value, str) and value in ICON_FILES else DEFAULT_STYLE


def load_icon(style):
    from PySide6.QtGui import QIcon

    icon = QIcon(str(RESOURCE_ROOT / 'assets' / ICON_FILES[normalize_style(style)]))
    if icon.isNull():
        icon = QIcon(str(RESOURCE_ROOT / 'assets' / ICON_FILES[DEFAULT_STYLE]))
    if icon.isNull():
        icon = QIcon(str(RESOURCE_ROOT / 'favicon.ico'))
    return icon


def icon_for_tray(style, window_icon):
    if style != DEFAULT_STYLE:
        return window_icon

    from PySide6.QtGui import QIcon

    icon = QIcon(str(RESOURCE_ROOT / 'assets/app-icons/character-tray.ico'))
    return window_icon if icon.isNull() else icon


def apply_icon(style, window=None):
    from PySide6.QtWidgets import QApplication

    icon = load_icon(style)
    if not icon.isNull():
        QApplication.setWindowIcon(icon)
        if window is not None:
            window.setWindowIcon(icon)
