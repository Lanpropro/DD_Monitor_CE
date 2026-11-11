"""Tint over the live compositor blur; never substitute a wallpaper image."""
from PySide6.QtGui import QColor


def glass_tint(widget, tint, *, card=False):
    color = QColor(tint)
    opacity = widget.window().property('settings_glass_opacity')
    opacity = 70 if opacity is None else int(opacity)
    # Cards add a small surface tint over the shell, keeping its live backdrop.
    color.setAlpha(round(255 * (18 if card else opacity) / 100))
    return color
