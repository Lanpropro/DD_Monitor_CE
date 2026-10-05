"""海外 OAuth：真实本机回调、PKCE/state、设备轮询、刷新与取消。"""
import base64
import hashlib
import json
from pathlib import Path
import sys
import threading
import time
from urllib.parse import parse_qs, urlsplit
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import requests
from ddm import oauth


def response(payload, status=200):
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(payload).encode()
    return result


def main():
    client = {'client_id': 'fixture.apps.googleusercontent.com', 'client_secret': 'fixture-secret'}
    for action in ('success', 'denied', 'cancel'):
        pending, results, errors = [], [], []
        cancelled = threading.Event()
        session = Mock()
        session.post.return_value = response({'access_token': 'fixture-access', 'refresh_token': 'fixture-refresh',
                                             'expires_in': 3600})
        def authorize():
            try:
                results.append(oauth.authorize('youtube', session, client, {}, cancelled,
                                               lambda url, code: pending.append((url, code))))
            except RuntimeError as error:
                errors.append(str(error))
        thread = threading.Thread(target=authorize)
        thread.start()
        deadline = time.monotonic() + 2
        while not pending and time.monotonic() < deadline:
            time.sleep(.01)
        assert pending
        url, code = pending[0]
        query = parse_qs(urlsplit(url).query)
        assert url.startswith('https://accounts.google.com/o/oauth2/v2/auth?') and not code
        assert query['scope'] == [oauth.GOOGLE_SCOPE]
        assert query['code_challenge_method'] == ['S256']
        callback = query['redirect_uri'][0]
        assert urlsplit(callback).hostname == '127.0.0.1'
        # 错误 state 不消费回调；有效授权码不能写进响应或日志。
        bad = requests.get(callback, params={'state': 'invalid', 'code': 'secret-code'}, timeout=2)
        assert bad.status_code == 400 and 'secret-code' not in bad.text
        assert thread.is_alive() and not session.post.called
        if action == 'cancel':
            started = time.monotonic()
            cancelled.set()
            thread.join(1)
            assert not thread.is_alive() and results == [{}] and not errors
            assert time.monotonic() - started < .6
        else:
            params = {'state': query['state'][0], 'code': 'secret-code'} if action == 'success' else {
                'state': query['state'][0], 'error': 'access_denied'}
            reply = requests.get(callback, params=params, timeout=2)
            assert reply.status_code == 200 and 'secret-code' not in reply.text
            thread.join(2)
            assert not thread.is_alive()
            if action == 'success':
                assert not errors and results[0]['client_id'] == client['client_id']
                data = session.post.call_args.kwargs['data']
                challenge = base64.urlsafe_b64encode(hashlib.sha256(data['code_verifier'].encode()).digest()).decode().rstrip('=')
                assert query['code_challenge'] == [challenge] and data['redirect_uri'] == callback
                assert data['code'] == 'secret-code' and data['client_secret'] == 'fixture-secret'
            else:
                assert errors and not session.post.called
        try:
            requests.get(callback, timeout=.2)
        except requests.ConnectionError:
            pass
        else:
            raise AssertionError('Callback listener survived authorization')

    class FastCancel(threading.Event):
        def __init__(self):
            super().__init__()
            self.intervals = []
        def wait(self, interval):
            self.intervals.append(interval)
            return self.is_set()
    session, cancelled = Mock(), FastCancel()
    session.post.side_effect = [response({'verification_uri': 'https://www.twitch.tv/activate?device-code=FIXTURE',
        'device_code': 'fixture-device', 'user_code': 'FIXTURE', 'expires_in': 1800, 'interval': 5}),
        response({'message': 'authorization_pending'}, 400), response({'error': 'slow_down'}, 400),
        response({'access_token': 'fixture-access', 'refresh_token': 'fixture-refresh', 'expires_in': 3600})]
    opened = []
    tokens = oauth.authorize('twitch', session, {'client_id': 'fixture-client'}, {}, cancelled,
                             lambda *args: opened.append(args))
    assert tokens['client_id'] == 'fixture-client' and opened[0][1] == 'FIXTURE'
    assert cancelled.intervals == [5, 5, 10]
    assert session.post.call_args.kwargs['data']['scopes'] == 'user:read:follows'
    for kind in ('twitch', 'youtube'):
        session = Mock()
        saved = {'access_token': 'old-access', 'refresh_token': 'old-refresh',
                 'expires_at': time.time() + 3600, 'client_id': client['client_id']}
        assert oauth.authorize(kind, session, client, saved, threading.Event(), Mock()) == saved
        session.post.assert_not_called()
        saved['expires_at'] = 0
        session.post.return_value = response({'access_token': 'new-access', 'refresh_token': 'new-refresh',
                                             'expires_in': 3600})
        refreshed = oauth.authorize(kind, session, client, saved, threading.Event(), Mock())
        assert refreshed['refresh_token'] == 'new-refresh' and refreshed['access_token'] == 'new-access'
        assert session.post.call_args.kwargs['data']['grant_type'] == 'refresh_token'
        session.post.return_value = response({'error': 'invalid_grant'}, 400)
        try:
            oauth.authorize(kind, session, client, saved, threading.Event(), Mock())
        except RuntimeError as error:
            assert '重新授权' in str(error) and 'old-refresh' not in str(error)
        else:
            raise AssertionError('Expired refresh token accepted')
    print('PASS: Google loopback/PKCE/state/denial/cancel/cleanup; Twitch device polling/slow-down; valid-token reuse and refresh rotation')


if __name__ == '__main__':
    main()
