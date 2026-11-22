"""Room capability shared by live chat selection and subscriptions."""

ROOM_SUPPORTS_LIVE_DANMAKU = 'supports_live_danmaku'


def is_live_danmaku_source(room):
    """Keep legacy live/offline rooms eligible; media can explicitly opt out."""
    return bool(room and room.get('room_id')) and room.get(ROOM_SUPPORTS_LIVE_DANMAKU, True) is not False
