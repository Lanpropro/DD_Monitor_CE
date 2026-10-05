"""海外账号的系统浏览器授权；令牌只交给本机加密账号存储。"""
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import secrets
import time
from urllib.parse import parse_qs, urlencode, urlsplit

GOOGLE_SCOPE = 'openid profile https://www.googleapis.com/auth/youtube.readonly'
TWITCH_SCOPE = 'user:read:follows'


def token_request(session, url, data):
    with session.post(url, data=data, timeout=(4, 8)) as response:
        payload = response.json()
        if response.status_code != 200:
            reason = payload.get('error') or payload.get('message')
            if reason in ('authorization_pending', 'slow_down'):
                return {'pending': reason}
            if reason in ('invalid_grant', 'Invalid refresh token'):
                raise RuntimeError('登录授权已过期，请点击「重新授权」')
            raise RuntimeError('平台授权失败，请检查客户端配置或重新授权')
    if not isinstance(payload.get('access_token'), str) or not payload['access_token']:
        raise RuntimeError('平台未返回有效授权令牌')
    if not isinstance(payload.get('expires_in'), (int, float)) or payload['expires_in'] <= 0:
        raise RuntimeError('平台未返回有效授权期限')
    return {key: payload[key] for key in ('access_token', 'refresh_token', 'scope') if key in payload} | {
        'expires_at': time.time() + payload['expires_in']}


def authorize(kind, session, client, saved, cancelled, show_browser):
    client_id = client.get('client_id', '').strip()
    if not client_id:
        raise RuntimeError('请先配置自己的 OAuth 客户端')
    if cancelled.is_set():
        return {}
    endpoint = ('https://id.twitch.tv/oauth2/token' if kind == 'twitch' else
                'https://oauth2.googleapis.com/token')
    if saved.get('client_id') == client_id and saved.get('access_token'):
        if saved.get('expires_at', 0) > time.time() + 60:
            return dict(saved)
        if saved.get('refresh_token'):
            data = {'client_id': client_id, 'grant_type': 'refresh_token',
                    'refresh_token': saved['refresh_token']}
            if kind == 'youtube' and client.get('client_secret'):
                data['client_secret'] = client['client_secret']
            tokens = token_request(session, endpoint, data)
            return {'refresh_token': saved['refresh_token'], **tokens, 'client_id': client_id}
        raise RuntimeError('登录授权已过期，请点击「重新授权」')
    tokens = (twitch_device(session, client_id, cancelled, show_browser) if kind == 'twitch' else
              google_desktop(session, client, cancelled, show_browser))
    return {**tokens, 'client_id': client_id} if tokens else {}


def twitch_device(session, client_id, cancelled, show_browser):
    with session.post('https://id.twitch.tv/oauth2/device',
            data={'client_id': client_id, 'scopes': TWITCH_SCOPE}, timeout=(4, 8)) as response:
        if response.status_code != 200:
            raise RuntimeError('Twitch 设备授权失败，请使用已注册的公共客户端 ID')
        payload = response.json()
    uri = payload.get('verification_uri', '')
    parts = urlsplit(uri)
    if (parts.scheme != 'https' or parts.hostname != 'www.twitch.tv' or parts.path != '/activate'
            or parts.username or parts.password or parts.port not in (None, 443)
            or not payload.get('device_code') or not payload.get('user_code')):
        raise RuntimeError('Twitch 返回的授权地址无效')
    expires, interval = payload.get('expires_in'), payload.get('interval')
    if not isinstance(expires, int) or expires <= 0 or not isinstance(interval, int) or interval <= 0:
        raise RuntimeError('Twitch 返回的授权期限无效')
    show_browser(uri, payload['user_code'])
    deadline = time.monotonic() + expires
    while not cancelled.wait(interval):
        if time.monotonic() >= deadline:
            break
        result = token_request(session, 'https://id.twitch.tv/oauth2/token', {
            'client_id': client_id, 'scopes': TWITCH_SCOPE, 'device_code': payload['device_code'],
            'grant_type': 'urn:ietf:params:oauth:grant-type:device_code'})
        if result.get('pending') == 'slow_down':
            interval += 5
        elif not result.get('pending'):
            return result
    if cancelled.is_set():
        return {}
    raise RuntimeError('Twitch 授权已超时，请重新授权')


def google_desktop(session, client, cancelled, show_browser):
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
    result = {}
    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass  # 不记录带授权码的地址。
        def do_GET(self):
            parts = urlsplit(self.path)
            query = parse_qs(parts.query)
            valid = (parts.path == '/oauth/callback' and query.get('state') == [state]
                     and ((len(query.get('code', [])) == 1) != (len(query.get('error', [])) == 1)))
            self.send_response(200 if valid else 400)
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(('授权已返回，请回到软件。' if valid else '授权回调无效，请回到软件重试。').encode())
            if valid:
                result.update(query)
    class Loopback(HTTPServer):
        def get_request(self):
            connection, address = super().get_request()
            connection.settimeout(1)
            return connection, address
    with Loopback(('127.0.0.1', 0), Callback) as server:
        server.timeout = .2
        redirect = f'http://127.0.0.1:{server.server_port}/oauth/callback'
        show_browser('https://accounts.google.com/o/oauth2/v2/auth?' + urlencode({
            'client_id': client['client_id'], 'redirect_uri': redirect, 'response_type': 'code',
            'scope': GOOGLE_SCOPE, 'state': state, 'code_challenge': challenge,
            'code_challenge_method': 'S256', 'access_type': 'offline', 'prompt': 'consent'}), '')
        deadline = time.monotonic() + 180
        while not result and not cancelled.is_set() and time.monotonic() < deadline:
            server.handle_request()
    if cancelled.is_set():
        return {}
    if not result:
        raise RuntimeError('Google 授权已超时，请重新授权')
    if result.get('error'):
        raise RuntimeError('Google 授权未完成，请重新授权')
    data = {'client_id': client['client_id'], 'code': result['code'][0], 'code_verifier': verifier,
            'redirect_uri': redirect, 'grant_type': 'authorization_code'}
    if client.get('client_secret'):
        data['client_secret'] = client['client_secret']
    return token_request(session, 'https://oauth2.googleapis.com/token', data)
