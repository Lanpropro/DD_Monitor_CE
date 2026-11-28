"""Layout modes stored with the picture-in-picture configuration."""
from typing import NamedTuple

FOCUS_LAYOUT = -1
MAIN_LAYOUT = -2
GRID_LAYOUT = -3
FREE_LAYOUT = -4
DANMAKU_ASPECT = 0.8


class PipChat(NamedTuple):
    key: str
    source: str | None
    name: str = ''


def read_chat_slots(value):
    if not isinstance(value, (tuple, list)):
        return ()
    result, keys, positions = [], set(), set()
    for row in value:
        if not isinstance(row, (tuple, list)) or len(row) != 2:
            continue
        index, chat = row
        if (type(index) is not int or index < 0 or index in positions
                or not isinstance(chat, (tuple, list)) or len(chat) != 3):
            continue
        key, source, name = chat
        if (not isinstance(key, str) or not key or key in keys
                or (source is not None and not isinstance(source, str)) or not isinstance(name, str)):
            continue
        keys.add(key)
        positions.add(index)
        result.append((index, PipChat(key, source, name)))
    return tuple(sorted(result))


def insert_chat_slots(videos, chat_slots):
    combined = list(videos)
    for index, pane in chat_slots:
        combined.insert(index, pane)
    return combined


def composition_inputs(aspects, chat_slots, primary):
    positions = insert_chat_slots(range(len(aspects)), ((index, None) for index, _ in chat_slots))
    return ([DANMAKU_ASPECT if index is None else aspects[index] for index in positions],
            positions.index(primary))
