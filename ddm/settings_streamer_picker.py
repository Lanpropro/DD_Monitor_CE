"""Followed-room search for streamer monitoring, painted by the shared room picker."""
from PySide6.QtWidgets import QCheckBox

from .avatar_widgets import AVATAR_COLORS
from .room_add_followed import RoomCardPicker, _RoomCard


class StreamerPicker(RoomCardPicker):
    def __init__(self, rooms):
        super().__init__(None, search_label='搜索关注主播 / 房间号', list_label='可添加的关注主播')
        self.occupied = set()
        self.live_only = QCheckBox('直播中', self)
        self.live_only.toggled.connect(self._arrange)
        self.filters.addWidget(self.live_only)
        self.scroll.setObjectName('StreamerFollowedList')
        self.scroll.viewport().setAutoFillBackground(False)
        self.scroll.setStyleSheet('#StreamerFollowedList {background: transparent;}')
        grouped = {}
        followed = sorted(((key, room) for key, room in rooms.items() if room['followed']),
                          key=lambda item: item[1].get('folder_order', 0))
        self.row_height = 84 if any(room.get('platform') for _, room in followed) else 68
        for index, (key, room) in enumerate(followed):
            folder = room.get('folder') or '未分组'
            _, cards = grouped.setdefault(room.get('folder_id') or folder, (folder, []))
            name, platform = room['name'], room.get('platform', '')
            terms = ' '.join((name, key, room.get('display_room_id', ''), folder, platform))
            cards.append(_RoomCard(key, name, terms, room, None, AVATAR_COLORS[index % len(AVATAR_COLORS)],
                                   detail=' · '.join(filter(None, (name, key, platform))),
                                   avatar_path=room.get('avatar') or '', platform=platform))
        self.groups = list(grouped.values())
        self._arrange()

    def set_occupied(self, rooms):
        self.occupied = set(rooms)
        self._arrange()

    def _matches(self, card, query):
        return (card.room_id not in self.occupied and (not self.live_only.isChecked() or card.room.get('live'))
                and super()._matches(card, query))

    def _empty_text(self, query):
        return '没有匹配的关注主播' if query or self.live_only.isChecked() else '暂无可添加的关注主播'

    def _arrange(self):
        super()._arrange()
        height = self.scroll.verticalHeader().length()
        self.scroll.setFixedHeight(min(height, 2 * (self.row_height + self.scroll.fontMetrics().height() + 8)))
        self.scroll.setVisible(bool(height))
