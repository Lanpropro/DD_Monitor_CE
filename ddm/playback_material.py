"""Material for the rounded playback popups."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QApplication, QMenu

from . import theme
from .continuous_corners import source_stylesheet, stylesheet
from .settings_material import BASE_COLORS, normalize


def _glass_opacity(settings):
    values = normalize(settings)
    return values['settings_glass_opacity'] if values['settings_glass_enabled'] else None


def _popup_tint(opacity):
    color = theme.qcolor(BASE_COLORS[theme.is_light()]['background'])
    color.setAlphaF(.84 + .16 * opacity / 100)
    return color


def _popup_settings(popup):
    owner = popup.parentWidget()
    while owner is not None:
        settings = getattr(owner, 'settings', None)
        if isinstance(settings, dict):
            return settings
        owner = owner.parentWidget()
    return None


def paint_playback_popup(popup, painter, rect, radius):
    """Paint a rounded plugin picker using its owning window's material settings."""
    opacity = _glass_opacity(_popup_settings(popup) or {})
    color = theme.qcolor(theme.ELEVATED) if opacity is None else _popup_tint(opacity)
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setBrush(color)
    painter.setPen(QPen(theme.qcolor(theme.BORDER), 1))
    painter.drawRoundedRect(rect, radius, radius)
    painter.restore()


def refresh_plugin_popups(owner):
    for popup in QApplication.topLevelWidgets():
        if (popup.isVisible() and popup.property('playbackGlassPopup')
                and _popup_settings(popup) is owner.settings):
            popup.update()


def sync_controls(tile, settings):
    opacity = _glass_opacity(settings)
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
        color = _popup_tint(opacity)
        rule = (f'\nQMenu {{ background: rgba({color.red()}, {color.green()}, '
                f'{color.blue()}, {color.alphaF():.3f}); }}')
    styled = stylesheet(menu._playback_base_style + rule)
    if menu.styleSheet() != styled:
        menu.setStyleSheet(styled)
