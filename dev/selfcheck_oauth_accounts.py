"""海外账号真实 Qt 流程、API 分页、加密恢复、授权取消和指定退出。"""
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import threading
import time
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import requests
from PySide6.QtWidgets import QApplication
from ddm.app import MainWindow
from ddm.account_store import AccountStore
from ddm.account_dialog import AccountPlatformDialog
from ddm.dialogs import FollowImportDialog
from ddm.oauth_login import OAuthAccountDialog
from dev.selfcheck_platform_follows import wait_for
from dev.selfcheck_account_dialog import dispose


def response(payload, status=200):
    result = requests.Response()
    result.status_code = status
    result._content = json.dumps(payload).encode()
    return result


def main():
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    client_ids = {'twitch': 'fixture-client', 'youtube': 'fixture.apps.googleusercontent.com'}
    channel = 'UC' + 'a' * 22
    def get(session, url, **kwargs):
        if url == 'https://id.twitch.tv/oauth2/validate':
            assert kwargs['headers']['Authorization'] == 'OAuth fixture-twitch-access'
            return response({'user_id': '123', 'client_id': client_ids['twitch'], 'login': 'Fixture',
                             'scopes': ['user:read:follows']})
        if url == 'https://api.twitch.tv/helix/users':
            return response({'data': [{'id': '123', 'display_name': 'Twitch Fixture',
                                      'profile_image_url': 'https://static-cdn.jtvnw.net/avatar.png'}]})
        if url == 'https://api.twitch.tv/helix/channels/followed':
            return response({'data': [{'broadcaster_login': 'fixturechannel', 'broadcaster_name': 'Channel'}],
                             'pagination': {}})
        assert session.headers['Authorization'] == 'Bearer fixture-youtube-access'
        if url == 'https://openidconnect.googleapis.com/v1/userinfo':
            return response({'sub': 'google-fixture', 'name': 'Google Fixture',
                             'picture': 'https://lh3.googleusercontent.com/avatar.png'})
        assert url == 'https://www.googleapis.com/youtube/v3/subscriptions'
        item = {'snippet': {'title': 'Subscribed channel', 'resourceId': {'channelId': channel},
                           'thumbnails': {'default': {'url': 'https://yt3.ggpht.com/avatar.png'}}}}
        assert kwargs['params']['mine'] == 'true'
        return response({'items': [item], **({} if kwargs['params'].get('pageToken') else {'nextPageToken': 'next'})})
    def tokens(kind, *_args):
        return {'access_token': 'fixture-' + kind + '-access', 'refresh_token': 'fixture-' + kind + '-refresh',
                'expires_at': time.time() + 3600, 'client_id': client_ids[kind]}
    with TemporaryDirectory() as root, patch('ddm.account_store.AccountStore',
            side_effect=lambda kind: AccountStore(kind, root=root)), patch('ddm.oauth_login.AccountStore',
            side_effect=lambda kind: AccountStore(kind, root=root)), patch('ddm.platform_login.AccountStore',
            side_effect=lambda kind: AccountStore(kind, root=root)), patch('ddm.app.QTimer.singleShot'):
        owner = MainWindow([], [], state={'plugins_enabled': ['global_live']})
        owner._start_avatar_loader = lambda *_args: None
        owner._render_account = lambda **_kwargs: None
        try:
            assert set(owner._account_platforms()) == {'YouTube', 'Twitch'}
            assert set(owner._follow_platforms()) == {'YouTube', 'Twitch'}
            for kind in ('twitch', 'youtube'):
                with patch('ddm.platform_login.PlatformFollowDialog', side_effect=AssertionError('Embedded browser')):
                    dialog = AccountPlatformDialog(owner, owner._account_platforms(), platform_kind=kind)
                    page = dialog.page
                    assert isinstance(page, OAuthAccountDialog) and not hasattr(page, 'browser')
                    page._read()
                    assert page._worker is None and kind not in owner._accounts
                page.client_id.setText(client_ids[kind])
                with patch.dict(os.environ, DDM_NO_SAVE='0'), patch('ddm.oauth_login.authorize', side_effect=tokens), \
                        patch.object(requests.Session, 'get', get):
                    page._read()
                    wait_for(app, lambda: page._worker is None)
                assert owner._accounts[kind]['uname'] == ('Twitch Fixture' if kind == 'twitch' else 'Google Fixture')
                saved = AccountStore(kind, root=root)
                assert saved.load_auth()['access_token'] == 'fixture-' + kind + '-access'
                assert 'access_token' not in saved.load_account()
                assert b'fixture-' not in saved.path.read_bytes()
                dispose(app, dialog)
                # 已登录页不会再次拉起授权或浏览器。
                with patch('ddm.oauth_login.OAuthAccountDialog', side_effect=AssertionError('Logged account authorized again')):
                    dialog = AccountPlatformDialog(owner, owner._account_platforms(), platform_kind=kind)
                    assert dialog.platform_buttons[kind].property('loggedIn')
                    dispose(app, dialog)
                with patch('ddm.oauth_login.authorize', side_effect=tokens), patch.object(requests.Session, 'get', get):
                    dialog = AccountPlatformDialog(owner, owner._follow_platforms(), import_follows=True, platform_kind=kind)
                    wait_for(app, lambda: isinstance(dialog.page, FollowImportDialog) and owner._follow_loader is None)
                    assert [room['room_id'] for room in dialog.page.rooms] == [
                        'twitch:fixturechannel' if kind == 'twitch' else 'youtube:' + channel]
                    assert dialog.platform_buttons[kind].property('loggedIn')
                    assert all(button.isEnabled() for button in dialog.platform_buttons.values())
                    dispose(app, dialog)
            # 刷新后即使订阅读取失败，也要保留已确认身份和轮换后的令牌。
            with patch.dict(os.environ, DDM_NO_SAVE='0'), patch('ddm.oauth_login.authorize', side_effect=tokens), \
                    patch.object(requests.Session, 'get', get), patch.object(
                        owner.plugins.platforms['youtube'], 'follow_rooms', side_effect=RuntimeError('Fixture API unavailable')):
                dialog = AccountPlatformDialog(owner, owner._follow_platforms(), import_follows=True, platform_kind='youtube')
                page = dialog._platform_pages['youtube']
                wait_for(app, lambda: page._worker is None)
                assert 'Fixture API unavailable' in page.status.text()
                assert owner._accounts['youtube']['uid'] == 'google-fixture'
                assert AccountStore('youtube', root=root).load_auth()['refresh_token'] == 'fixture-youtube-refresh'
                assert dialog.platform_buttons['youtube'].property('loggedIn')
                dispose(app, dialog)
            # 独立应用实例恢复两个身份，令牌不会进入配置或界面账号字段。
            with patch.dict(os.environ, DDM_NO_SAVE='0'):
                other = MainWindow([], [], state={'plugins_enabled': ['global_live']})
            assert set(other._accounts) == {'twitch', 'youtube'}
            assert 'access_token' not in json.dumps(other.current_state())
            other.close()
            app.processEvents()
            with patch.dict(os.environ, DDM_NO_SAVE='0'):
                owner.logout('youtube')
            assert 'twitch' in owner._accounts and 'youtube' not in owner._accounts
            assert not AccountStore('youtube', root=root).path.exists()
            assert AccountStore('twitch', root=root).path.exists()

            with patch('ddm.oauth_login.authorize', side_effect=tokens), patch.object(requests.Session, 'get', get):
                dialog = AccountPlatformDialog(owner, owner._account_platforms(), platform_kind='youtube')
                page = dialog.page
                page.remember.setChecked(False)
                with patch.dict(os.environ, DDM_NO_SAVE='0'):
                    page._read()
                    wait_for(app, lambda: page._worker is None)
                assert 'youtube' in owner._accounts and not AccountStore('youtube', root=root).path.exists()
                assert not owner._platform_login_sessions['youtube']['remember']
                dispose(app, dialog)
                owner._clear_platform_account('youtube')

            # 授权等待可切平台、关闭；迟到结果不能保存或覆盖其他账号。
            entered = threading.Event()
            def pending(_kind, _session, _client, _saved, cancelled, _show):
                entered.set()
                assert cancelled.wait(2)
                return tokens('youtube')
            with patch('ddm.oauth_login.authorize', side_effect=pending):
                dialog = AccountPlatformDialog(owner, owner._account_platforms(), platform_kind='youtube')
                page = dialog.page
                page._read()
                assert entered.wait(1)
                dialog.select_platform('twitch')
                wait_for(app, lambda: page._worker is None)
                assert dialog.kind == 'twitch' and 'youtube' not in owner._accounts
                assert not AccountStore('youtube', root=root).path.exists()
                dialog.select_platform('youtube')
                assert '开始授权' in page.status.text() and '系统浏览器' in page.status.text()
                dispose(app, dialog)
        finally:
            owner.close()
            app.processEvents()
    print('PASS: overseas Qt authorization/import; Google subscriptions pagination; encrypted restart; no embedded browser; separate logout; switch/cancel/late-result isolation')


if __name__ == '__main__':
    main()
