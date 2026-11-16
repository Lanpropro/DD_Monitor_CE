"""Tint over the live compositor blur; never substitute a wallpaper image."""
from PySide6.QtGui import QColor


def glass_tint(widget, tint=None, *, card=False):
    from . import theme
    light = theme.is_light()
    if card:
        # BewlyCat SettingsItemGroup uses --bew-fill-alt, not a translucent
        # version of the opaque card colour: rgb(131 131 145 / 10% or 15%).
        return QColor(131, 131, 145, round(255 * (.15 if light else .10)))
    color = QColor(tint or ('#ffffff' if light else '#21262d'))
    opacity = widget.window().property('settings_glass_opacity')
    opacity = 70 if opacity is None else int(opacity)
    color.setAlpha(round(255 * opacity / 100))
    return color


def sync_text_contrast(root):
    """Give text a small dark halo over live, bright content without shading cards."""
    from PySide6.QtWidgets import QGraphicsDropShadowEffect, QLabel
    from . import theme
    from .settings_backdrop import blur_available
    window = root.window()
    enabled = bool(window.property('settings_glass_enabled')) and not theme.is_light() and blur_available()
    for label in root.findChildren(QLabel):
        if label.objectName() == 'SettingsHint' and label.property('settingsTextContrast') != enabled:
            label.setProperty('settingsTextContrast', enabled)
            label.style().unpolish(label)
            label.style().polish(label)
        effect = label.graphicsEffect()
        owned = effect is not None and effect.objectName() == 'SettingsTextContrast'
        if enabled and label.text() and effect is None:
            effect = QGraphicsDropShadowEffect(label)
            effect.setObjectName('SettingsTextContrast')
            effect.setOffset(0, 0)
            effect.setBlurRadius(4)
            effect.setColor(QColor(0, 0, 0, 230))
            label.setGraphicsEffect(effect)
        elif not enabled and owned:
            label.setGraphicsEffect(None)
