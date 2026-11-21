"""Shared emoticon preferences using stable package and sticker identities."""
import json
import os
from pathlib import Path
import tempfile

from PySide6.QtCore import QObject, Signal
from ddm import config


class EmoticonOrder(QObject):
    changed = Signal()

    def __init__(self, path=None):
        super().__init__()
        # Explicit paths opt into isolated persistence for tests. Ordinary host
        # checks must never read or write the user's preferences.
        relative = Path('utils/bili_live/emoticon_order.json')
        self.path = (Path(path) if path is not None else
                     None if os.environ.get('DDM_NO_SAVE') == '1' else
                     Path(config.data_root()) / relative)
        self.orders = {}
        if self.path is not None:
            try:
                source_path = self.path
                if path is None and not source_path.exists():
                    source_path = Path(config.REPO) / relative
                with source_path.open('r', encoding='utf-8') as source:
                    text = source.read(1024 * 1024 + 1)
                if len(text) <= 1024 * 1024:
                    payload = json.loads(text)
                    if isinstance(payload, dict) and payload.get('version') == 1:
                        self.load(payload.get('orders'))
            except (OSError, ValueError, UnicodeError):
                pass

    def load(self, orders):
        self.orders = {key: list(dict.fromkeys(value)) for key, value in orders.items()
                       if isinstance(key, str) and isinstance(value, list)
                       and all(isinstance(item, str) for item in value)} if isinstance(orders, dict) else {}

    @staticmethod
    def key(emote):
        return str(emote.get('emoticon_unique') or emote.get('emoji') or '')

    @staticmethod
    def package_key(package):
        return f"{package['pkg_type']}:{package.get('pkg_id') or package.get('pkg_name') or ''}"

    def arrange_packages(self, packages):
        ranks = {key: index for index, key in enumerate(self.orders.get('_tabs', []))}
        packages = list(packages)
        ordered = iter(sorted(
            (package for package in packages if self.package_key(package) in ranks),
            key=lambda package: ranks[self.package_key(package)]))
        # New room packages keep their server slots instead of following all
        # previously sorted purchased packages. Only known tabs exchange slots.
        return [next(ordered) if self.package_key(package) in ranks else package
                for package in packages]

    def save_packages(self, packages):
        self._save('_tabs', [self.package_key(package) for package in packages])

    def arrange(self, category, emotes):
        ranks = {key: index for index, key in enumerate(self.orders.get(category, []))}
        return sorted(emotes, key=lambda emote: ranks.get(self.key(emote), len(ranks)))

    def save(self, category, emotes):
        if isinstance(category, str):
            self._save(category, [self.key(emote) for emote in emotes])

    def _save(self, category, keys):
        keys = list(dict.fromkeys(key for key in keys if key))
        present = set(keys)
        pending = iter(keys)
        # Replace only slots belonging to this room. Categories and emotes
        # absent here keep their positions for rooms where they are available.
        merged = [next(pending) if key in present else key
                  for key in self.orders.get(category, [])]
        merged.extend(pending)
        if self.orders.get(category) == merged:
            return
        self.orders[category] = merged
        self._persist()
        self.changed.emit()

    def _persist(self):
        if self.path is None:
            return
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            handle, temporary = tempfile.mkstemp(prefix='.partial-', dir=self.path.parent)
            with os.fdopen(handle, 'w', encoding='utf-8') as output:
                json.dump({'version': 1, 'orders': self.orders}, output, ensure_ascii=False)
            os.replace(temporary, self.path)
        except OSError:
            pass  # Browsing and sorting remain usable on read-only storage.
        finally:
            if temporary is not None:
                try:
                    os.unlink(temporary)
                except OSError:
                    pass


emoticon_order = EmoticonOrder()
