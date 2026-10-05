"""真实 WebEngine/HTTP 验证官网关注面板读取，禁止软件自行请求关注 API。"""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import threading
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QTWEBENGINE_CHROMIUM_FLAGS', '--disable-gpu')
import requests
from PySide6.QtCore import QUrl, Qt
from PySide6.QtWidgets import QApplication
from ddm.platform_login import PlatformFollowDialog
from plugins_user.domestic_live.plugin import DouyinPlatform
from dev.selfcheck_platform_follows import wait_for
from dev.selfcheck_account_dialog import dispose

HTML = """<!doctype html><meta charset="utf-8">
<button onclick="window.mutated=true">关注</button>
<button onclick="openPanel()">3关注</button>
<script>
function endpoint(uid, offset) {
    return '/aweme/v1/web/user/following/list/?user_id=' + uid + '&offset=' + offset +
        '&min_time=' + (offset ? 100 : 0) + '&max_time=0';
}
function openPanel() {
    window.opened = (window.opened || 0) + 1;
    const panel = document.createElement('div');
    panel.dataset.e2e = 'user-fans-container';
    panel.style = 'height:100px;overflow-y:auto';
    panel.innerHTML = '<div style="height:600px">List</div>';
    document.body.appendChild(panel);
    const xhr = new XMLHttpRequest();
    xhr.open('GET', endpoint(999, 0));
    xhr.onload = () => {
        const own = new XMLHttpRequest();
        own.open('GET', endpoint(42, 0));
        own.onload = () => { panel.ready = true; };
        own.send();
    };
    xhr.send();
    panel.addEventListener('scroll', () => {
        if (panel.ready && !panel.next) {
            panel.next = true;
            fetch(new Request(endpoint(42, 1)));
        }
    });
}
</script>"""


def main():
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    state = {'mode': 'normal', 'requests': [], 'gate': threading.Event()}
    first = {'uid': '101', 'nickname': 'Live', 'room_data': json.dumps({
        'status': 2, 'title': 'Live fixture', 'owner': {'web_rid': '1001'},
        'stream_url': {'secret': 'must-not-export'}})}
    second = {'uid': '102', 'nickname': 'Offline', 'web_rid': '1002'}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            parts = urlsplit(self.path)
            if parts.path == '/user/self':
                html = HTML.replace('<button onclick="openPanel()">3关注</button>', '') if state['mode'] == 'no_panel' else HTML
                body, kind = html.encode(), 'text/html; charset=utf-8'
            elif parts.path == '/aweme/v1/web/user/following/list/':
                params = parse_qs(parts.query)
                uid, offset = params['user_id'][0], params['offset'][0]
                state['requests'].append((uid, offset))
                if state['mode'] == 'pending':
                    state['gate'].wait(3)
                if uid == '999':
                    payload = {'status_code': 0, 'followings': [{'web_rid': '9999'}], 'has_more': 0}
                elif state['mode'] == 'error' or (state['mode'] == 'second_error' and offset == '1'):
                    payload = {'status_code': 8}
                elif state['mode'] == 'empty':
                    payload = {'status_code': 0, 'followings': [], 'has_more': 0}
                elif offset == '0':
                    payload = {'status_code': 0, 'followings': [first], 'has_more': 1}
                else:
                    payload = {'status_code': 0, 'followings': [first, second], 'has_more': 0}
                body, kind = json.dumps(payload).encode(), 'application/json'
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    provider = DouyinPlatform()
    provider.follow_login_url = f'http://127.0.0.1:{server.server_port}/user/self'
    provider.account_info = Mock(return_value={'uid': '42', 'uname': 'Fixture'})
    try:
        for mode in ('normal', 'empty', 'error', 'second_error', 'no_panel', 'pending'):
            state.update(mode=mode, requests=[])
            provider.follow_browser_init_script = DouyinPlatform.follow_browser_init_script.replace(
                'Date.now() + 25000', 'Date.now() + 300') if mode == 'no_panel' else DouyinPlatform.follow_browser_init_script
            dialog = PlatformFollowDialog(provider, defer_login=True)
            loaded, failed = [], []
            dialog.browser.loadFinished.connect(loaded.append)
            dialog.readFailed.connect(failed.append)
            dialog.browser.load(QUrl(provider.follow_login_url))
            dialog.show()
            wait_for(app, lambda: bool(loaded))
            assert loaded[-1]
            with patch.object(requests.Session, 'get', side_effect=AssertionError('Software sent follow API request')):
                dialog._read()
                if mode == 'pending':
                    wait_for(app, lambda: bool(state['requests']))
                    dialog.reject()
                wait_for(app, lambda: dialog._worker is None)
            if mode == 'normal':
                assert [room['room_id'] for room in dialog.rooms] == ['douyin:1001', 'douyin:1002']
                assert dialog.rooms[0]['live'] and not dialog.rooms[1]['live_known']
                assert state['requests'] == [('999', '0'), ('42', '0'), ('42', '1')]
                result = []
                dialog.browser.page().runJavaScript('JSON.stringify(window.__ddmFollowResult)', result.append)
                wait_for(app, lambda: bool(result))
                assert 'must-not-export' not in result[0] and 'stream_url' not in result[0]
            elif mode in ('error', 'second_error'):
                assert len(failed) == 1 and '状态 8' in failed[0] and not dialog.rooms
            elif mode == 'no_panel':
                assert len(failed) == 1 and '点开' in failed[0] and not dialog.rooms
            else:
                assert not failed and not dialog.rooms
            changed = []
            dialog.browser.page().runJavaScript('window.mutated === true', changed.append)
            wait_for(app, lambda: bool(changed))
            assert changed == [False]
            dispose(app, dialog)
            state['gate'].set()
    finally:
        state['gate'].set()
        server.shutdown()
        server.server_close()
        thread.join(2)
    print('PASS: visible official UI, native XHR/fetch capture, full pagination, account isolation, no follow mutation, no signed URLs, empty/error/cancel')


if __name__ == '__main__':
    main()
