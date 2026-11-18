"""Input-only room validation shared by inline adding and the legacy dialog."""
import re
from .room_input import bili_room_id, extract_room_input, is_bili_short_url


def normalize_room_text(text, resolver):
    text = extract_room_input(text)
    room_id = resolver(text) if resolver is not None else None
    if room_id:
        return room_id
    room_id = text if is_bili_short_url(text) else bili_room_id(text)
    if not room_id and '://' not in text and '/' not in text:
        digits = re.findall(r'\d+', text)
        room_id = digits[0] if len(digits) == 1 else ''
    if not room_id:
        raise ValueError('没识别到房间号，请检查输入')
    return room_id


def normalize_room_lines(text, normalize):
    rooms = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            room_id = normalize(line.strip())
        except ValueError as error:
            raise ValueError(f'第 {number} 行：{error}') from error
        if room_id not in rooms:
            rooms.append(room_id)
    if not rooms:
        raise ValueError('请输入房间号或直播间链接')
    return rooms
