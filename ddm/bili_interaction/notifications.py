"""Report captured-room failures through the host's public notification/login APIs."""
from collections.abc import Mapping


def needs_login(error):
    """Explicit authentication failures and established host credential messages."""
    if bool(getattr(error, 'login_required', False)):
        return True
    text = str(error).lower()
    return any(word in text for word in (
        '未登录', '登录失效', '登录已失效', '登录过期', '请先登录',
        'csrf', 'bili_jct', '-101', '-111'))


class NotificationReporter:
    def __init__(self, context, *, active=None):
        self._context = context
        self._active = active
        self._closed = False

    def _available(self):
        return not self._closed and (self._active is None or bool(self._active()))

    def close(self):
        self._closed = True

    def error(self, message, *, room=None, login_required=None):
        if not self._available() or not str(message).strip():
            return False
        if isinstance(room, Mapping):
            captured = {key: str(room.get(key) or '') for key in ('room_id', 'uname', 'title', 'face')}
        else:
            captured = {'room_id': str(room or '')}
        room_id = captured.get('room_id', '')
        room_name = captured.get('uname') or captured.get('title') or ''
        label = (room_name + '（房间 ' + room_id + '）') if room_name and room_id else (
            '房间 ' + room_id if room_id else room_name)
        text = ('【' + label + '】' if label else '') + str(message)
        login = needs_login(message) if login_required is None else bool(login_required)
        action = None
        if login and callable(getattr(self._context, 'request_login', None)):
            text += '，点击此处重新登录'

            def action():
                if self._available():
                    request = getattr(self._context, 'request_login', None)
                    if callable(request):
                        request('bilibili', reauthenticate=True)

        notify = getattr(self._context, 'notify', None)
        if callable(notify):
            return bool(notify(text, rooms=(captured,) if room_id else (),
                               kind='warning', on_click=action))
        log = getattr(self._context, 'log', None)
        if callable(log):
            log(text)
        return False
