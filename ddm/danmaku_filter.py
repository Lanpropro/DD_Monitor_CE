"""Platform-scoped user identities and shared incoming-comment filtering."""
import re


def _text(value):
    return str(value).strip() if isinstance(value, (str, int)) and not isinstance(value, bool) else ''


def platform_name(room_id):
    room_id = _text(room_id)
    return 'bilibili' if room_id.isdigit() else room_id.partition(':')[0] if ':' in room_id else ''


def user_identity(event, room_id=''):
    platform = platform_name(room_id) or _text(event.get('platform'))
    uid = _text(event.get('uid') or event.get('user_id') or event.get('author_id'))
    if uid == '0':
        uid = ''
    uname = _text(event.get('uname'))
    return {'platform': platform, 'uid': uid, 'uname': uname} if platform and (uid or uname) else None


def normalize_users(users):
    result, seen = [], set()
    for item in users if isinstance(users, list) else []:
        if not isinstance(item, dict):
            continue
        identity = user_identity(item)
        if identity is None:
            continue
        key = (identity['platform'], 'uid' if identity['uid'] else 'uname', identity['uid'] or identity['uname'])
        if key not in seen:
            seen.add(key)
            for field in ('blocked_at', 'source', 'source_text', 'source_room_id', 'source_kind'):
                if isinstance(item.get(field), str):
                    identity[field] = item[field]
            result.append(identity)
    return result


def manual_user_error(platform, uid):
    """Validate only the identity shape used by current adapters, never existence."""
    uid = _text(uid)
    if not uid:
        return '请填写该平台的用户 ID，不是昵称'
    if platform in ('bilibili', 'douyin', 'douyu', 'huya', 'twitch'):
        if not re.fullmatch(r'[1-9][0-9]*', uid):
            return '该平台需要正整数用户 ID，请勿填写昵称、账号名或链接'
        return ''
    if platform == 'youtube':
        if not re.fullmatch(r'UC[A-Za-z0-9_-]+', uid):
            return 'YouTube 需要 UC 开头的频道 ID，不是 @名称或频道链接'
        return ''
    return '该平台尚未提供手动 ID 格式，请从弹幕菜单屏蔽用户'


def block_phrase(text):
    return ' '.join(str(text or '').strip().splitlines())


def text_blocked(text, words):
    if not words:
        return False
    lowered = block_phrase(text).lower()
    return any(block_phrase(word).lower() in lowered for word in (words or []) if block_phrase(word))


def user_blocked(event, room_id, users):
    if not users:
        return False
    identity = user_identity(event, room_id)
    if identity is None:
        return False
    for rule in users if isinstance(users, list) else []:
        if not isinstance(rule, dict) or rule.get('platform') != identity['platform']:
            continue
        if rule.get('uid'):
            if _text(rule['uid']) == identity['uid']:
                return True
        elif rule.get('uname') and _text(rule['uname']) == identity['uname']:
            return True
    return False


def event_blocked(event, room_id, settings):
    if event.get('kind') == 'super_chat_delete':
        return False
    return (user_blocked(event, room_id, settings.get('danmaku_blocked_users')) or
            ((event.get('kind') or 'danmaku') == 'danmaku' and
             text_blocked(event.get('text'), settings.get('danmaku_block_words'))))
