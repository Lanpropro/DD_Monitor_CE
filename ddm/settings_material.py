"""Settings material preferences and derived widget presentation properties."""

DEFAULTS = {
    'settings_glass_enabled': False,
    'settings_glass_blur': 24,
    'settings_glass_opacity': 70,
    'settings_no_shadows': False,
}

# Flat colours sampled from the user's light/dark BewlyCat recordings.
# Regular and embedded settings roots share this opaque foundation.
BASE_COLORS = {
    False: {'background': '#33373b', 'card': '#3c4044', 'control': '#43444b'},
    True: {'background': '#eeedf4', 'card': '#ffffff', 'control': '#edecef'},
}


def base_color(widget, role, fallback):
    from . import theme
    window = widget.window()
    if window.property('settingsGlassWindow') or window.property('settingsGlassContent'):
        return BASE_COLORS[theme.is_light()][role]
    return fallback


def control_stylesheet():
    rules = []
    for light, colors in BASE_COLORS.items():
        scopes = [f'QWidget[{flag}="true"][appearanceLight="{str(light).lower()}"]'
                  for flag in ('settingsGlassWindow', 'settingsGlassContent')]
        controls = ('QLineEdit', 'QSpinBox', 'QDoubleSpinBox', 'QComboBox', 'QFontComboBox',
                    'QPlainTextEdit', '#StepButton', '#IconButton', 'QPushButton#AppearanceChoice:!checked',
                    'QCheckBox::indicator:!checked')
        selectors = ', '.join(f'{scope} {control}' for scope in scopes for control in controls)
        rules.append(f'{selectors} {{background: {colors["control"]};}}')
        # Explicit zero radius lets the continuous-corner painter own flat list fills too.
        rules.append(', '.join(f'{scope} QAbstractItemView' for scope in scopes)
                     + f' {{background: {colors["card"]}; border-radius: 0px;}}')
    return '\n'.join(rules)


def normalize(values):
    result = {key: values.get(key, default) for key, default in DEFAULTS.items()}
    for key in ('settings_glass_enabled', 'settings_no_shadows'):
        if type(result[key]) is not bool:
            result[key] = DEFAULTS[key]
    # Retired temporarily: old saved values must not restore glass rendering.
    result['settings_glass_enabled'] = False
    for key, maximum in (('settings_glass_blur', 40), ('settings_glass_opacity', 100)):
        try:
            result[key] = max(0, min(maximum, int(result[key])))
        except (TypeError, ValueError, OverflowError):
            result[key] = DEFAULTS[key]
    return result


def properties(widget):
    return normalize({key: widget.property(key) for key in DEFAULTS
                      if widget.property(key) is not None})


def apply_properties(widget, values):
    changed = False
    for key, value in normalize(values).items():
        if widget.property(key) != value:
            widget.setProperty(key, value)
            changed = True
    if changed:
        widget.update()
    return changed


def shadows_enabled(widget):
    return not bool(widget.window().property('settings_no_shadows'))
