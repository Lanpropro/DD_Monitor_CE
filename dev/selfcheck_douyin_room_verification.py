"""抖音添加验证：本地官网替身、同房间身份、重试、取消与首次资料复用。"""
import json
import os
from pathlib import Path
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QTWEBENGINE_CHROMIUM_FLAGS', '--disable-gpu')
from PySide6.QtCore import Qt, QUrl
from PySide6.QtWidgets import QApplication, QDialog, QWidget
from PySide6.QtWebEngineWidgets import QWebEngineView
from ddm.app import MainWindow
from ddm.bili import InfoResolver
from ddm.profile_room import ProfileRoomDialog
from dev.selfcheck_account_dialog import dispose
from dev.selfcheck_platform_follows import wait_for
from plugins_user.domestic_live.plugin import DouyinPlatform, DouyinVerificationRequired


def main():
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    provider = DouyinPlatform()
    with patch.object(provider, 'room_info', side_effect=DouyinVerificationRequired('完成验证')):
        resolver = InfoResolver('douyin:123', platform=provider)
        resolver.run()
        assert resolver.browser_verification and resolver.error_message == '完成验证'
    with patch.object(provider, 'room_info', side_effect=RuntimeError('ordinary failure')):
        resolver.run()
        assert not resolver.browser_verification
    provider._anchor_uids['douyin:123'] = '101'
    with patch.object(provider, '_share_room', side_effect=RuntimeError('unavailable')), patch.object(
            provider, '_room_page', side_effect=DouyinVerificationRequired('完成验证')):
        try:
            provider.room_data('douyin:123')
        except DouyinVerificationRequired:
            pass
        else:
            raise AssertionError('Cached identity must retain verification classification')
    mode = ['valid']
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            room = {'id_str': '222', 'status': 2, 'title': 'Verified fixture',
                    'owner': {'id_str': '101', 'web_rid': '999' if mode[0] == 'wrong' else '123',
                              'nickname': 'Fixture'}}
            if self.path.startswith('/webcast/room/web/enter/'):
                page = json.dumps({'status_code': 0, 'data': {'data': [room]}})
            else:
                info = {'room': room}
                if mode[0] == 'inline':
                    room['owner'].pop('web_rid')
                    info['web_rid'] = '123'
                data = json.dumps([{'state': {'roomStore': {'roomInfo': info}}}])
                action = 'self.__pace_f=[[1,%s]]' % json.dumps(data)
                if mode[0] == 'inline':
                    action = 'self.__pace_f=[];self.__pace_f.push([1,%s]);self.__pace_f=[];' % json.dumps('d:' + data)
                elif mode[0] == 'fetch':
                    action = "fetch('/webcast/room/web/enter/?web_rid=123')"
                elif mode[0] == 'xhr':
                    action = "const x=new XMLHttpRequest();x.open('GET','/webcast/room/web/enter/?web_rid=123');x.send()"
                page = '<title>验证完成</title><script>' + action + '</script>'
                if mode[0] == 'loaded':
                    page = '<title>直播间</title><a data-e2e="live-room-nickname">Fixture</a>'
            body = page.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    owner = QWidget()
    owner._closing = False
    owner._platform_login_sessions = {}
    owner._add_room_id = Mock()
    # 仅测试替身使用本机域名；生产脚本仍严格要求抖音官网及原房间路径。
    provider.room_browser_init_script = provider.room_browser_init_script.replace(
        "location.hostname === 'live.douyin.com'", "location.hostname === '127.0.0.1'")
    try:
        for reading in ('valid', 'inline', 'fetch', 'xhr', 'wrong', 'loaded', 'cancel'):
            mode[0] = reading
            with patch.object(QWebEngineView, 'load'):
                dialog = ProfileRoomDialog(provider, '', owner, room_id='douyin:123')
            dialog._profile_url = f'http://127.0.0.1:{server.server_port}/123'
            if reading == 'cancel':
                dialog.reject()
                dialog._identity(json.dumps({'uid': '101', 'web_rid': '123'}))
                assert not dialog.room_id and dialog._worker is None
            else:
                dialog.browser.load(QUrl(dialog._profile_url))
                if reading in ('wrong', 'loaded'):
                    if reading == 'loaded':
                        wait_for(app, lambda: '无需寻找验证码' in dialog.status.text())
                    else:
                        wait_for(app, lambda: dialog.browser.title() == '验证完成')
                    for _ in range(10):
                        app.processEvents()
                        time.sleep(.05)
                    assert not dialog.room_id and dialog._worker is None
                    dialog._deadline = time.monotonic() - 1
                    dialog._poll()
                    assert not dialog.poll.isActive()
                    assert ('未识别房间资料' if reading == 'loaded' else '完成官网验证') in dialog.status.text()
                    mode[0] = 'valid'
                    dialog._read()
                wait_for(app, lambda: dialog.room_id == 'douyin:123' and dialog._worker is None)
                resolved = []
                resolver = InfoResolver(dialog.room_id, platform=provider)
                resolver.resolved.connect(resolved.append)
                with patch('requests.get', side_effect=AssertionError('Browser data must be reused')):
                    resolver.run()
                assert resolved[0]['uname'] == 'Fixture' and resolved[0]['anchor_uid'] == '101'
                assert resolved[0]['title'] == 'Verified fixture'
            dispose(app, dialog)
        # 正常错误仍显示原提示；只有验证分类打开浏览器，并保留添加目标文件夹。
        with patch('ddm.profile_room.ProfileRoomDialog') as factory, patch('ddm.app.QMessageBox.warning') as warning:
            factory.return_value.exec.return_value = QDialog.Accepted
            factory.return_value.room_id = 'douyin:123'
            failed = SimpleNamespace(browser_verification=True)
            MainWindow._on_platform_room_failed(owner, failed, provider, 'douyin:123', folder_id='folder')
            factory.assert_called_once_with(provider, '', owner, room_id='douyin:123')
            owner._add_room_id.assert_called_once_with('douyin:123', folder_id='folder')
            warning.assert_not_called()
            factory.reset_mock()
            owner._add_room_id.reset_mock()
            factory.return_value.exec.return_value = QDialog.Rejected
            MainWindow._on_platform_room_failed(owner, failed, provider, 'douyin:123')
            owner._add_room_id.assert_not_called()
            failed.browser_verification = False
            MainWindow._on_platform_room_failed(owner, failed, provider, 'douyin:123')
            warning.assert_called_once()
    finally:
        server.shutdown()
        server.server_close()
        owner.close()
    print('PASS: verification classification, local WebEngine room identity, retry, cancel, browser data reuse and add routing')


if __name__ == '__main__':
    main()
