"""Recently sent emotes shared by the host profile's Bilibili controls."""
import re

from PySide6.QtCore import QObject, Signal


class RecentEmoticons(QObject):
    changed = Signal()
    LIMIT = 30
    SETTING = "recent_emoticons"

    def __init__(self, context=None):
        super().__init__()
        self.context = context
        saved = context.setting(self.SETTING, []) if context is not None else []
        self.keys = []
        if isinstance(saved, list):
            for key in saved:
                if (isinstance(key, str) and key.startswith(("text:", "id:"))
                        and key.partition(":")[2] and key not in self.keys):
                    self.keys.append(key)
                    if len(self.keys) == self.LIMIT:
                        break

    def sent_keys(self, message, dm_type, packages):
        if dm_type == 1:
            return ("id:" + message,)
        tokens = {key[5:] for key in self.keys if key.startswith("text:")}
        for package in packages:
            if package.get("pkg_type") == 3:
                tokens.update(item["emoji"] for item in package.get("emoticons") or []
                              if isinstance(item, dict) and isinstance(item.get("emoji"), str))
        matches = sorted((t for t in tokens if t and t in message), key=len, reverse=True)
        if not matches:
            return ()
        return tuple("text:" + token for token in re.findall("|".join(map(re.escape, matches)), message))

    def record(self, keys):
        updated = list(dict.fromkeys([*reversed(keys), *self.keys]))[:self.LIMIT]
        if updated != self.keys:
            self.keys = updated
            if self.context is not None:
                self.context.set_setting(self.SETTING, list(updated))
            self.changed.emit()

    def available_items(self, packages):
        # Only the current catalog supplies display data, send type and permissions.
        if not self.keys:
            return []
        items = {}
        for package in packages:
            kind = package["pkg_type"]
            for emote in package.get("emoticons") or []:
                if not isinstance(emote, dict):
                    continue
                value = emote.get("emoji" if kind == 3 else "emoticon_unique")
                if isinstance(value, str) and value:
                    key = ("text:" if kind == 3 else "id:") + value
                    if key in self.keys and (key not in items or emote.get("perm") == 1):
                        items[key] = dict(emote, _pkg_type=kind)
        return [items[key] for key in self.keys if key in items]
