"""GUI-thread credential adapters. Events carry identity generations, never secrets."""
from dataclasses import dataclass, field
import threading
from types import MappingProxyType

from PySide6.QtCore import QCoreApplication, QThread

EVENT_ACCOUNT_CHANGED = 'account.changed'
EVENT_CREDENTIALS_UPDATED = 'account.credentials_updated'


def _gui_thread():
    app = QCoreApplication.instance()
    if ((app is not None and QThread.currentThread() != app.thread()) or
            (app is None and threading.current_thread() is not threading.main_thread())):
        raise RuntimeError('credential access must run on the GUI thread')


@dataclass(frozen=True)
class CredentialSnapshot:
    platform: str
    generation: int
    values: object = field(repr=False)

    def __post_init__(self):
        object.__setattr__(self, 'values', MappingProxyType(dict(self.values)))


@dataclass
class _Provider:
    read: object
    update: object
    identity_keys: tuple
    writable_fields: frozenset
    values: dict
    generation: int = 1


class CredentialStore:
    def __init__(self, emit):
        self._providers = {}
        self._emit = emit

    def register(self, platform, read, *, update=None, identity_keys=(), writable_fields=()):
        _gui_thread()
        if not platform or platform in self._providers or not callable(read):
            raise ValueError('credential provider needs a unique platform and read callback')
        self._providers[platform] = _Provider(read, update, tuple(identity_keys),
            frozenset(writable_fields), dict(read() or {}))

    def notify(self, platform):
        _gui_thread()
        provider = self._providers.get(platform)
        if provider is None:
            return
        values = dict(provider.read() or {})
        fields = sorted(k for k in set(values) | set(provider.values)
                        if values.get(k) != provider.values.get(k))
        if not fields:
            return
        identity_changed = bool(set(fields) & set(provider.identity_keys))
        provider.values = values
        if identity_changed:
            provider.generation += 1
            self._emit(EVENT_ACCOUNT_CHANGED, platform=platform, generation=provider.generation)
        else:
            self._emit(EVENT_CREDENTIALS_UPDATED, platform=platform,
                       generation=provider.generation, fields=fields)

    def snapshot(self, platform):
        _gui_thread()
        self.notify(platform)
        provider = self._providers.get(platform)
        return CredentialSnapshot(platform, provider.generation, provider.values) if provider else None

    def update(self, platform, changes, *, expected_generation):
        _gui_thread()
        provider = self._providers.get(platform)
        if provider is None or provider.update is None:
            raise ValueError('credential provider does not accept updates')
        if not isinstance(changes, dict) or set(changes) - provider.writable_fields:
            raise ValueError('unsupported credential fields')
        if any(not isinstance(value, str) for value in changes.values()):
            raise ValueError('credential values must be strings')
        self.notify(platform)
        if expected_generation != provider.generation:
            return False
        provider.update(dict(changes))
        self.notify(platform)
        return True
