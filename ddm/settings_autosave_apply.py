"""Apply acknowledged settings deltas without closing or restarting the host."""
from types import SimpleNamespace


def apply_changes(host, changes, dialog=None):
    before = (None if host.plugins.enabled is None else set(host.plugins.enabled),
              dict(host.plugins._platform_owner), set(host.plugins._removed))
    controls = changes.get('plugin_controls', {})
    if dialog is not None:
        from PySide6.QtWidgets import QCheckBox
        for check in dialog.general_page.findChildren(QCheckBox):
            if check.objectName() in controls:
                previous = check.blockSignals(True)
                check.setChecked(controls[check.objectName()])
                check.blockSignals(previous)
    adapter = SimpleNamespace(
        settings=lambda: changes.get('settings', {}),
        shortcuts=lambda: {**host.shortcuts, **changes.get('shortcuts', {})},
        enabled_plugins=lambda: changes.get('enabled_plugins', host.plugins.enabled),
        _loaded_pages={}, restart_requested=False, auto_saving=True)
    host._apply_settings_dialog(adapter, before)
    if controls and dialog is not None:
        # Released platform plugins use accepted as their save notification.
        # Emitting the signal preserves their persistence hook without closing.
        dialog.accepted.emit()


def bind_dialog(host, dialog):
    dialog._auto_save_enabled = True
    def save(changes):
        if getattr(host, '_closing', False):
            dialog.auto_save.active = False
            dialog.auto_save.pending = None
            return
        try:
            apply_changes(host, changes, dialog)
        except (OSError, ValueError) as error:
            dialog.auto_save.acknowledge(str(error))
        else:
            dialog.auto_save.acknowledge()
    dialog.auto_save.requested.connect(save)


def handle_request(host, message):
    if getattr(host, '_closing', False):
        return
    session = getattr(host, '_settings_host', None)
    try:
        apply_changes(host, message['changes'], session.dialog if session is not None else None)
    except (OSError, ValueError) as error:
        host._settings_process._send({'kind': 'auto-saved', 'error': str(error)})
    else:
        if session is not None:
            session.dialog.auto_save.adopt('plugin_controls', message['changes'].get('plugin_controls', {}))
        host._settings_process._send({'kind': 'auto-saved', 'error': ''})
