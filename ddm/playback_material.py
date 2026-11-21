"""Rounded playback popups and tint for the native video controls."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractButton, QMenu

from . import theme
from .continuous_corners import source_stylesheet, stylesheet
from .settings_material import BASE_COLORS, normalize


def sync_controls(tile, settings):
    values = normalize(settings)
    opacity = values['settings_glass_opacity'] if values['settings_glass_enabled'] else None
    if tile.controls.property('playbackGlassOpacity') == opacity:
        return
    tile.controls.setProperty('playbackGlassOpacity', opacity)
    for button in tile.controls.findChildren(QAbstractButton, options=Qt.FindDirectChildrenOnly):
        button.update()
    for menu in tile.findChildren(QMenu, options=Qt.FindDirectChildrenOnly):
        if hasattr(menu, '_playback_base_style'):
            style_menu(menu, opacity)


def style_menu(menu, opacity):
    if not hasattr(menu, '_playback_base_style'):
        menu._playback_base_style = source_stylesheet(menu.styleSheet())
        menu.setWindowFlag(Qt.FramelessWindowHint, True)
        menu.setAttribute(Qt.WA_TranslucentBackground)
    # A text-heavy popup needs a readable base over a changing video frame.
    rule = ''
    if opacity is not None:
        color = theme.qcolor(BASE_COLORS[theme.is_light()]['background'])
        alpha = .84 + .16 * opacity / 100
        rule = f'\nQMenu {{ background: rgba({color.red()}, {color.green()}, {color.blue()}, {alpha:.3f}); }}'
    styled = stylesheet(menu._playback_base_style + rule)
    if menu.styleSheet() != styled:
        menu.setStyleSheet(styled)


def tint_button(values, opacity):
    fill = values.get('background')
    if opacity is None or not fill or fill == 'transparent':
        return values
    # The native button HWNDs share an opaque backing store. Keep the video
    # hit regions and use a precomposited tint instead of changing ownership.
    tint = theme.mix(theme.qcolor(fill).name(), '#66748a', .62 - .42 * opacity / 100)
    return {**values, 'background': tint}
