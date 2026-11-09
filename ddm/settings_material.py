"""Settings material preferences and derived widget presentation properties."""

DEFAULTS = {
    'settings_glass_enabled': True,
    'settings_glass_blur': 24,
    'settings_glass_opacity': 70,
    'settings_no_shadows': False,
}


def normalize(values):
    result = {key: values.get(key, default) for key, default in DEFAULTS.items()}
    for key in ('settings_glass_enabled', 'settings_no_shadows'):
        if type(result[key]) is not bool:
            result[key] = DEFAULTS[key]
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
