"""Playback popup material and the independent color of video overlay controls."""
from functools import lru_cache

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractButton, QMenu

from . import theme
from .continuous_corners import source_stylesheet, stylesheet
from .settings_material import BASE_COLORS, normalize


def sync_controls(tile, settings):
    values = normalize(settings)
    color = values['settings_playback_control_color']
    if tile.controls.property('playbackControlColor') != color:
        tile.controls.setProperty('playbackControlColor', color)
        for button in tile.controls.findChildren(QAbstractButton, options=Qt.FindDirectChildrenOnly):
            button.update()
    opacity = values['settings_glass_opacity'] if values['settings_glass_enabled'] else None
    if tile.controls.property('playbackGlassOpacity') == opacity:
        return
    tile.controls.setProperty('playbackGlassOpacity', opacity)
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


def button_colors(button):
    parent = button.parentWidget()
    color = parent.property('playbackControlColor') if parent is not None else None
    if not color or not button.isEnabled():
        return None
    active = button.underMouse() or button.property('hovered') or button.property('playbackPopupOpen')
    strength = .18 if button.isDown() else .10 if active else 0
    return _button_colors(color, strength)


@lru_cache(maxsize=32)
def _button_colors(color, strength):
    def ink_for(background):
        rgb = (component / 255 for component in theme.qcolor(background).getRgb()[:3])
        linear = (x / 12.92 if x <= .04045 else ((x + .055) / 1.055) ** 2.4 for x in rgb)
        luminance = sum(component * weight for component, weight in zip(linear, (.2126, .7152, .0722)))
        return '#000000' if luminance > .179 else '#ffffff'

    background = theme.mix(color, ink_for(color), strength) if strength else color
    return background, ink_for(background)
