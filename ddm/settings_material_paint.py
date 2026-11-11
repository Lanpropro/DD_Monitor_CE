"""Tint over the live compositor blur; never substitute a wallpaper image."""
from PySide6.QtGui import QColor


def glass_tint(widget, tint=None, *, card=False):
    from . import theme
    light = theme.is_light()
    if card:
        # BewlyCat SettingsItemGroup uses --bew-fill-alt, not a translucent
        # version of the opaque card colour: rgb(131 131 145 / 10% or 15%).
        return QColor(131, 131, 145, round(255 * (.15 if light else .10)))
    color = QColor(tint or ('#ffffff' if light else '#35383d'))
    opacity = widget.window().property('settings_glass_opacity')
    opacity = 70 if opacity is None else int(opacity)
    color.setAlpha(round(255 * opacity / 100))
    return color
