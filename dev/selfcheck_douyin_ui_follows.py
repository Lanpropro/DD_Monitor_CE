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
const mode = '__MODE__';
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
    if (mode.startsWith('rendered')) {
        // 模拟官网已渲染的 React DOM 契约，数据在打开面板之前已经取得，不经过监听接口。
        const first = {uid:'101', secUid:'sec101', nickname:'Live', remarkName:'Remark',
            avatarUri:'https://p3.douyinpic.com/a.png',
            roomData:{status:2, title:'Live fixture', owner:{web_rid:'1001'}, stream_url:'must-not-export'}};
        const second = {uid:'102', nickname:'Offline', roomData:{web_rid:'1002', status:4}};
        const props = {userList:[first], isSelf:true, activeTab:0, searchVal:'',
            currentUserInfo:{uid:mode === 'rendered_other' ? '999' : '42'},
            refIsLoadingShow:{current:true}, refNoMoreText:{current:''}};
        if (mode === 'rendered_fans') props.activeTab = 1;
        if (mode === 'rendered_search') props.searchVal = 'Live';
        const footer = document.createElement('div');
        footer.dataset.e2e = 'user-fans-footer';
        panel.appendChild(footer);
        function render(users, complete) {
            props.userList = users;
            props.refIsLoadingShow.current = !complete;
            props.refNoMoreText.current = complete ? '暂时没有更多了' : '';
            footer.textContent = complete ? (users.length ? '暂时没有更多了' : '你还没有关注') : '';
            const current = {...props};
            if (mode === 'rendered_fiber') panel.__reactFiber$fixture = {memoizedProps:{},
                return:{memoizedProps:current}};
            else panel.__reactProps$fixture = {children:{props:current}};
        }
        render(mode === 'rendered_empty' || mode === 'rendered_invalid_empty' ? [] : [first],
            mode === 'rendered_empty' || mode === 'rendered_invalid_empty');
        if (mode === 'rendered_invalid_empty') footer.textContent = '请登录后重试';
        let timer;
        panel.addEventListener('scroll', () => {
            clearTimeout(timer);
            timer = setTimeout(() => {
                if (mode === 'rendered' || mode === 'rendered_fiber') render([first, second], true);
            }, 250);
        });
        return;
    }
    const xhr = new XMLHttpRequest();
    xhr.open('GET', endpoint(999, 0));
    xhr.onload = () => {
        const own = new XMLHttpRequest();
        own.open('GET', endpoint(42, 0));
        own.onload = () => { panel.ready = true; };
        own.send();
    };
    xhr.send();
    let timer;
    panel.addEventListener('scroll', () => {
        clearTimeout(timer);
        timer = setTimeout(() => {
            if (panel.ready && !panel.next) {
                panel.next = true;
                fetch(new Request(endpoint(42, 1)));
            }
        }, 250);
    });
}
if (mode.startsWith('rendered')) openPanel();
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
                html = HTML.replace('__MODE__', state['mode'])
                if state['mode'] == 'no_panel':
                    html = html.replace('<button onclick="openPanel()">3关注</button>', '')
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
        for mode in ('normal', 'empty', 'error', 'second_error', 'no_panel', 'pending',
                     'rendered', 'rendered_fiber', 'rendered_empty', 'rendered_other',
                     'rendered_fans', 'rendered_search', 'rendered_stall', 'rendered_invalid_empty', 'rendered_pending'):
            state.update(mode=mode, requests=[])
            provider.follow_browser_init_script = DouyinPlatform.follow_browser_init_script.replace(
                'Date.now() + 25000', 'Date.now() + 900') if mode in (
                    'no_panel', 'rendered_stall', 'rendered_invalid_empty') else DouyinPlatform.follow_browser_init_script
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
                if mode in ('pending', 'rendered_pending'):
                    started = []
                    def request_started():
                        dialog.browser.page().runJavaScript('window.opened > 0', started.append)
                        return any(started)
                    wait_for(app, request_started)
                    dialog.reject()
                wait_for(app, lambda: dialog._worker is None)
            if mode in ('normal', 'rendered', 'rendered_fiber'):
                assert [room['room_id'] for room in dialog.rooms] == ['douyin:1001', 'douyin:1002']
                assert dialog.rooms[0]['live'] and not dialog.rooms[1]['live']
                if mode == 'normal':
                    assert not dialog.rooms[1]['live_known']
                    assert state['requests'] == [('999', '0'), ('42', '0'), ('42', '1')]
                else:
                    assert not state['requests']
                    assert dialog.rooms[0]['uname'] == 'Remark'
                    assert dialog.rooms[0]['face'] == 'https://p3.douyinpic.com/a.png'
                result = []
                dialog.browser.page().runJavaScript('JSON.stringify(window.__ddmFollowResult)', result.append)
                wait_for(app, lambda: bool(result))
                assert 'must-not-export' not in result[0] and 'stream_url' not in result[0]
            elif mode in ('error', 'second_error'):
                assert len(failed) == 1 and '状态 8' in failed[0] and not dialog.rooms
            elif mode == 'no_panel':
                assert len(failed) == 1 and '点开' in failed[0] and not dialog.rooms
            elif mode in ('rendered_other', 'rendered_fans', 'rendered_search'):
                assert len(failed) == 1 and '清空列表搜索' in failed[0] and not dialog.rooms
            elif mode in ('rendered_stall', 'rendered_invalid_empty'):
                assert len(failed) == 1 and '没有加载完成' in failed[0] and not dialog.rooms
            else:
                assert not failed and not dialog.rooms
            changed = []
            dialog.browser.page().runJavaScript('window.mutated === true', changed.append)
            wait_for(app, lambda: bool(changed))
            assert changed == [False]
            if mode.startswith('rendered'):
                opened = []
                dialog.browser.page().runJavaScript('window.opened', opened.append)
                wait_for(app, lambda: bool(opened))
                assert opened == [1]  # 已显示的面板直接读取，不重新打开或触发关注操作。
            dispose(app, dialog)
            state['gate'].set()
    finally:
        state['gate'].set()
        server.shutdown()
        server.server_close()
        thread.join(2)
    print('PASS: rendered props/fiber without API capture, debounced pagination, complete/empty/error/cancel, account/tab/search isolation, no follow mutation or signed URLs')


if __name__ == '__main__':
    main()
