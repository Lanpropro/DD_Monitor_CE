"""Ownership and persistence for the host recording preferences editor."""
from PySide6.QtCore import QObject, QTimer, Signal

from . import config
from .settings_recording import RecordingSettingsPage


RECORDING_DEFAULTS = {key: value for key, value in config.DEFAULT_SETTINGS.items() if key.startswith('recording_')}


class RecordingSettingsAccess(QObject):
    changed = Signal()

    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.owner = None

    @property
    def managed(self):
        return self.owner is not None

    def settings_entry(self):
        owner = self.owner
        plugin = next((plugin for plugin in owner._manager.plugins if plugin.context is owner), None)
        name = (plugin.name or owner.name) if plugin is not None else owner.name
        open_settings = getattr(plugin, 'open_managed_recording_settings', None)

        def open_if_managed():
            if self.owner is owner and owner._active and not getattr(self.host, '_closing', False):
                open_settings()

        return name, open_if_managed if callable(open_settings) else None

    def values(self):
        return {key: self.host.settings.get(key, default) for key, default in RECORDING_DEFAULTS.items()}

    def set_managed(self, context, enabled):
        if enabled:
            if not context._active or getattr(self.host, '_closing', False):
                raise RuntimeError('录制设置已关闭')
            if self.owner is context:
                return
            if self.managed:
                raise RuntimeError('录制设置已由其他插件管理')
            self.owner = context
            self.changed.emit()
        elif self.owner is context:
            self.owner = None
            self.changed.emit()

    def save(self, context, values):
        if self.owner is not context or not context._active:
            raise RuntimeError('请先启用接管本体录制设置')
        changes = {key: value for key, value in values.items() if key in RECORDING_DEFAULTS
                   and self.host.settings.get(key) != value}
        if not changes:
            return
        state = self.host.current_state()
        state['settings'].update(changes)
        config.save(state, raise_errors=True)
        self.host.settings.update(changes)
        self.host.state['settings'] = dict(self.host.settings)
        self.host._sync_recording_switch()
        self.host._sync_replay_scope()
        self.changed.emit()


class PluginRecordingPreferencesEditor(RecordingSettingsPage):
    save_error = Signal(str)

    def __init__(self, access, context, parent):
        super().__init__(access.values(), parent)
        self.access = access
        self.context = context
        self.timer = QTimer(self, singleShot=True, interval=250)
        self.timer.timeout.connect(self.flush)
        self.settings_edited.connect(self.timer.start)

    def refresh(self):
        self.set_values(self.access.values())

    def flush(self):
        self.timer.stop()
        if self.access.owner is not self.context or not self.context._active:
            return True
        try:
            self.access.save(self.context, self.values())
        except (OSError, RuntimeError, ValueError) as error:
            self.save_error.emit(str(error))
            return False
        self.save_error.emit('')
        return True
