"""主页添加：真实 WebEngine 身份读取、未开播房间、错误身份和取消隔离。"""
import json
import os
from pathlib import Path
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock, patch
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QTWEBENGINE_CHROMIUM_FLAGS', '--disable-gpu')
from PySide6.QtCore import Qt, QUrl
from PySide6.QtWidgets import QApplication, QDialog, QWidget
from PySide6.QtWebEngineWidgets import QWebEngineView
from ddm.app import MainWindow
from ddm.dialogs import AddRoomDialog
from ddm.profile_room import ProfileRoomDialog
from dev.selfcheck_account_dialog import dispose
from dev.selfcheck_platform_follows import wait_for
from plugins_user.domestic_live.plugin import DouyinPlatform

SEC = 'MS4wLjABAAAAfixture_profile'
URL = 'https://www.douyin.com/user/' + SEC


def main():
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    provider = DouyinPlatform()
    assert provider.matches(URL) and provider.profile_sec_uid(URL + '?from_tab_name=main') == SEC
    assert provider.profile_sec_uid('https://live.douyin.com/123') == ''
    for url in (URL.replace('www.douyin.com', 'user@www.douyin.com'), URL + '/other',
                'https://www.douyin.com/user/self', URL.replace('www.douyin.com', 'www.douyin.com:1234')):
        try:
            provider.profile_sec_uid(url)
        except ValueError:
            pass
        else:
            raise AssertionError('Invalid profile accepted')
    with patch.object(provider, '_share_room', return_value={'status': 4, 'owner': {'web_rid': '123'}}):
        assert provider.profile_room('101', lambda: False) == 'douyin:123'
        assert provider._anchor_uids == {'douyin:123': '101'}
        assert provider.profile_room('101', lambda: True) == ''
    with patch.object(provider, '_share_room', return_value={}):
        try:
            provider.profile_room('101', lambda: False)
        except RuntimeError as error:
            assert '直播记录' in str(error) and '重试' in str(error)
        else:
            raise AssertionError('Ordinary user became a room')

    mode = ['fetch']
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass
        def do_GET(self):
            user = {'uid': '101', 'sec_uid': SEC, 'nickname': 'Fixture', 'unneeded': 'do-not-export'}
            if urlsplit(self.path).path.endswith('/other/'):
                content = json.dumps({'status_code': 0, 'user': user}).encode()
                content_type = 'application/json'
            else:
                endpoint = '/aweme/v1/web/user/profile/other/?sec_user_id=' + SEC
                if mode[0] == 'fetch':
                    content = f'<script>fetch("{endpoint}")</script>'.encode()
                elif mode[0] == 'xhr':
                    content = f'<script>let x=new XMLHttpRequest();x.open("GET","{endpoint}");x.send()</script>'.encode()
                else:
                    content = ('<script id="RENDER_DATA" type="application/json">' +
                               json.dumps({'user': user}) + '</script>').encode()
                content_type = 'text/html'
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.end_headers()
            self.wfile.write(content)
    with ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        owner = QWidget()
        owner._platform_login_sessions, owner._closing = {}, False
        try:
            for reading in ('fetch', 'xhr', 'ssr'):
                mode[0] = reading
                with patch.object(QWebEngineView, 'load'), patch.object(provider, 'profile_room', return_value='douyin:123') as resolve:
                    dialog = ProfileRoomDialog(provider, SEC, owner)
                dialog._profile_url = f'http://127.0.0.1:{server.server_port}/user/' + SEC
                dialog.browser.load(QUrl(dialog._profile_url))
                dialog.show()
                with patch.object(provider, 'profile_room', resolve), patch('ddm.platform_login.AccountStore.save',
                        side_effect=AssertionError('Profile overwrote login')):
                    wait_for(app, lambda: bool(dialog.room_id) and dialog._worker is None)
                assert dialog.room_id == 'douyin:123' and dialog.result() == QDialog.Accepted
                assert resolve.call_args.args[0] == '101'
                assert owner._platform_login_sessions == {}
                dispose(app, dialog)
            with patch.object(QWebEngineView, 'load'):
                dialog = ProfileRoomDialog(provider, SEC, owner)
            dialog.show()
            dialog._profile_url = dialog.browser.url().toString()
            with patch.object(provider, 'profile_room') as resolve:
                dialog._identity(json.dumps({'uid': '101', 'sec_uid': 'different'}))
                assert dialog._worker is None
                dialog.reject()
                dialog._identity(json.dumps({'uid': '101', 'sec_uid': SEC}))
                resolve.assert_not_called()
            dispose(app, dialog)
            # 查询已开始时关闭窗口会取消工作，迟到成功不能添加主播。
            entered = threading.Event()
            def pending(_uid, cancelled):
                entered.set()
                while not cancelled():
                    threading.Event().wait(.01)
                return 'douyin:late'
            with patch.object(QWebEngineView, 'load'), patch.object(provider, 'profile_room', side_effect=pending):
                dialog = ProfileRoomDialog(provider, SEC, owner)
                dialog._profile_url = dialog.browser.url().toString()
                dialog._identity({'uid': '101', 'sec_uid': SEC})
                assert entered.wait(1)
                dialog.reject()
                wait_for(app, lambda: dialog._worker is None)
                assert dialog.room_id == ''
                dispose(app, dialog)
        finally:
            owner.close()
            server.shutdown()
            thread.join(2)
    # 主窗口直接识别主页，确认后转成固定房间号；取消不能让链接中的数字变成 B 站房间。
    with patch('ddm.app.QTimer.singleShot'):
        main_window = MainWindow([], [], state={'plugins_enabled': ['domestic_live']})
    try:
        with patch('ddm.profile_room.ProfileRoomDialog') as dialog_type:
            dialog_type.return_value.exec.return_value = QDialog.Accepted
            dialog_type.return_value.room_id = 'douyin:123'
            add = AddRoomDialog(main_window, room_id_resolver=main_window._normalize_room_input)
            add.edit.setText(URL)
            add.accept()
            assert add.room_id == 'douyin:123'
            dialog_type.return_value.exec.return_value = QDialog.Rejected
            other = AddRoomDialog(main_window, room_id_resolver=main_window._normalize_room_input)
            other.edit.setText(URL)
            other.accept()
            assert other.room_id == '' and '取消' in other.hint.text()
            dispose(app, add)
            dispose(app, other)
    finally:
        main_window.close()
        app.processEvents()
    # 手动主页添加的主播身份也从房间配置恢复，不依赖账号关注缓存。
    room = {'room_id': 'douyin:123', 'anchor_uid': '101', 'uname': 'Fixture', 'live': False}
    with patch('ddm.app.QTimer.singleShot'):
        restored = MainWindow([room], [], state={'plugins_enabled': ['domestic_live']})
    assert restored.plugins.platforms['douyin']._anchor_uids['douyin:123'] == '101'
    restored.close()
    app.processEvents()
    print('PASS: profile input; offline fixed room; fetch/XHR/SSR browser identity; scoped results; account preservation; cancel; add dialog')


if __name__ == '__main__':
    main()
