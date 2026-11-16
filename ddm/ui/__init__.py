"""Public component imports; existing implementations load only when requested."""
from importlib import import_module

from .basics import ActionButton, HintLabel, TitleLabel, page_header, step_button

_MODULES = {
    'ui.disclosure': ('DisclosureButton',),
    'ui.settings_surface': ('SettingsSurface',),
    'ui.selection': ('ToggleSwitch', 'SegmentedControl'),
    'ui.select': ('SelectControl', 'FontSelectControl'),
    'ui.stepper': ('StepperControl',),
    'ui.slider': ('SettingsSlider', 'SettingsValueLabel'),
    'ui.color_dialog': ('ColorDialog',),
    'ui.scale_curve': ('ScaleCurveControl',),
    'corner_geometry': ('continuous_path',),
    'avatar_widgets': ('Avatar', 'RoomStrip', 'PinnedArc', 'circular_pixmap'),
    'motion': ('AnimatedDialog', 'AnimatedMenu', 'SlidingTabs', 'SettingsStack'),
    'playback_controls': ('TileButton', 'VolumeButton', 'RecordingButton', 'SidebarToggleButton',
                          'PauseButton', 'RefreshButton', 'DanmakuToggleButton'),
    'ui.labels': ('ElidedLabel',),
    'ui.toolbar': ('BarIconButton',),
}
_EXPORTS = {name: module for module, names in _MODULES.items() for name in names}
__all__ = ['ActionButton', 'HintLabel', 'TitleLabel', 'page_header', 'step_button', *_EXPORTS]


def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
    component = getattr(import_module('..' + _EXPORTS[name], __name__), name)
    globals()[name] = component
    return component


def __dir__():
    return sorted(set(globals()) | set(__all__))
