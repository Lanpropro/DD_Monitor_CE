"""Tint over the live compositor blur; never substitute a wallpaper image."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QLinearGradient, QPen


def glass_active(widget):
    from .settings_backdrop import blur_available
    window = widget.window()
    return bool(window.property('settings_glass_enabled') and (
        getattr(window, '_native_glass', False)
        or window.property('settingsGlassContent') and blur_available()))


def window_background_tint(widget):
    from .skin_parts import resolve_values, values_for
    preview = getattr(widget.window(), '_settings_material_preview', None)
    values = resolve_values('settings', preview[1], preview[0]) if preview is not None else values_for('settings')
    return values.get('background')


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


def paint_glass_border(painter, path):
    from . import theme
    rect = path.boundingRect()
    edge = QLinearGradient(rect.topLeft(), rect.bottomRight())
    edge.setColorAt(0, QColor(255, 255, 255, 87 if theme.is_light() else 15))
    edge.setColorAt(1, QColor(255, 255, 255, 36 if theme.is_light() else 8))
    painter.setPen(QPen(edge, 1))
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(path)


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
