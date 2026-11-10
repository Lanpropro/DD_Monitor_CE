"""Video choices and existing chat cells in the six-cell PiP composition."""

FOCUS_LAYOUT = -1


def focus_chat_cells(wall, columns):
    if columns != FOCUS_LAYOUT or wall.layout_id != 'corner':
        return ()
    cells = tuple(sorted(wall.pane_danmaku.bindings()))
    return cells if 0 not in cells else ()


def focus_slots(choices, chat_cells, primary=None):
    videos = list(choices)
    if primary in videos:
        videos.remove(primary)
        videos.insert(0, primary)
    videos = iter(videos)
    return [None if cell in chat_cells else next(videos, None) for cell in range(6)]
