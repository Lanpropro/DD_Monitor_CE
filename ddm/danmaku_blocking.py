"""Host-owned block actions; settings remain the only persistent rule store."""
from .danmaku_filter import block_phrase, event_blocked, normalize_users, user_identity


class DanmakuBlocking:
    def __init__(self, host):
        self.host = host

    def block(self, event, room_id, *, user=False):
        host = self.host
        if host._closing:
            return False
        if user:
            identity = user_identity(event, room_id)
            if identity is None:
                return False
            key = 'danmaku_blocked_users'
            value = normalize_users([*(host.settings.get(key) or []), identity])
        else:
            word = block_phrase(event.get('text'))
            if not word:
                return False
            key = 'danmaku_block_words'
            value = list(host.settings.get(key) or [])
            if word.lower() not in {str(item).strip().lower() for item in value}:
                value.append(word)
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
        return True

    def apply(self):
        host = self.host
        def allowed(event, room_id):
            return not event_blocked(event, room_id, host.settings)
        for panel in host.wall.pane_danmaku.all_panels():
            room_id = getattr(panel, '_linked_room_id', '')
            panel.filter_events(lambda event, rid=room_id: allowed(event, rid))
        for tile in host.wall.tiles:
            room_id = str(tile.room.get('room_id') or '')
            tile.video_danmaku.filter_events(lambda event, rid=room_id: allowed(event, rid))
        for room_id in host._super_chats:
            host._publish_super_chats(room_id)
