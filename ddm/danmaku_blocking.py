"""Host-owned block actions; settings remain the only persistent rule store."""
from datetime import datetime, timezone
from .danmaku_filter import block_phrase, event_blocked, normalize_users, user_identity


class DanmakuBlocking:
    def __init__(self, host):
        self.host = host

    def block(self, event, room_id, *, user=False):
        host = self.host
        if host._closing:
            return None
        if user:
            identity = user_identity(event, room_id)
            if identity is None:
                return None
            identity.update(blocked_at=datetime.now(timezone.utc).isoformat(timespec='seconds'),
                            source='message', source_text=str(event.get('text') or event.get('message') or ''),
                            source_room_id=str(room_id or ''), source_kind=str(event.get('kind') or 'danmaku'))
            key = 'danmaku_blocked_users'
            previous = normalize_users(host.settings.get(key))
            value = normalize_users([*previous, identity])
            if len(value) == len(previous):
                return None
            rule = value[-1]
        else:
            word = block_phrase(event.get('text'))
            if not word:
                return None
            key = 'danmaku_block_words'
            value = list(host.settings.get(key) or [])
            if any(block_phrase(item).lower() == word.lower() for item in value):
                return None
            rule = word
            value.append(rule)
        self._set_rules(key, value)

        def undo():
            current = host.settings.get(key) or []
            if host._closing or not any(item is rule for item in current):
                return False
            self._set_rules(key, [item for item in current if item is not rule])
            return True

        return undo

    def _set_rules(self, key, value):
        host = self.host
        host.settings[key] = value
        settings_process = getattr(host, '_settings_process', None)
        if settings_process is not None:
            settings_process.push_settings({key: value})
        # An already open or lazy settings page must not restore the old rules.
        from .dialogs import SettingsDialog
        for dialog in host.findChildren(SettingsDialog):
            dialog._initial_settings[key] = value
            page = dialog._loaded_pages.get(2)
            if page is not None:
                page.sync_blocking({key: value})
            dialog.auto_save.adopt('settings', {key: value})
        self.apply()
        host._save_timer.start()

    def apply(self):
        host = self.host
        def allowed(event, room_id):
            return not event_blocked(event, room_id, host.settings)
        for panel in host.danmaku_lifecycle.panels():
            room_id = getattr(panel, '_linked_room_id', '')
            panel.filter_events(lambda event, rid=room_id: allowed(event, rid))
        for tile in host.wall.tiles:
            room_id = str(tile.room.get('room_id') or '')
            tile.video_danmaku.filter_events(lambda event, rid=room_id: allowed(event, rid))
        for room_id in host._super_chats:
            host._publish_super_chats(room_id)
