"""真实 WebEngine/HTTP 验证官网关注面板读取，禁止软件自行请求关注 API。"""
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ['DDM_NO_SAVE'] = '1'
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QTWEBENGINE_CHROMIUM_FLAGS', '--disable-gpu')
import requests
from PySide6.QtCore import QUrl, Qt
from PySide6.QtWidgets import QApplication, QWidget
from ddm.account_dialog import AccountPlatformDialog
from ddm.dialogs import FollowImportDialog
from ddm.platform_login import PlatformFollowDialog
from plugins_user.domestic_live.plugin import DouyinPlatform
from dev.selfcheck_platform_follows import wait_for
from dev.selfcheck_account_dialog import dispose
from dev.selfcheck_live_platforms import dy_page

HTML = """<!doctype html><meta charset="utf-8">
<nav><a onclick="window.navigated=true"><div><div>关注1</div></div></a></nav>
<button onclick="window.mutated=true">关注</button>
<button onclick="openPanel()">3关注</button>
<script>
const mode = '__MODE__';
if (mode === 'profile_counter') {
    const counter = document.querySelector('button[onclick="openPanel()"]');
    counter.dataset.e2e = 'user-info-follow';
    counter.innerHTML = '关注3<span>1人正在直播</span>';
    const menuCounter = document.createElement('p');
    menuCounter.textContent = '关注3';
    menuCounter.onclick = () => { window.navigated = true; };
    counter.before(menuCounter);
}
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
        if (mode === 'rendered_resolve') {first.roomData = {}; second.roomData = {};}
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
                if (mode === 'rendered' || mode === 'rendered_fiber' || mode === 'rendered_resolve') render([first, second], true);
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
        for mode in ('normal', 'profile_counter', 'empty', 'error', 'second_error', 'no_panel', 'pending',
                     'rendered', 'rendered_fiber', 'rendered_resolve', 'rendered_empty', 'rendered_other',
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
            def room_lookup(url, **kwargs):
                assert mode == 'rendered_resolve' and url == 'https://live.douyin.com/webcast/room/info_by_user/'
                uid = kwargs['params']['user_id']
                assert uid in ('101', '102')
                response = requests.Response()
                response.status_code = 200
                response._content = json.dumps({'status_code': 0, 'data': {
                    'id_str': '9' + uid, 'owner_user_id': int(uid)}}).encode()
                return response
            def share_page(url, **kwargs):
                if url in ('https://live.douyin.com/1001', 'https://live.douyin.com/1002'):
                    response = requests.Response()
                    response.status_code = 200
                    response._content = dy_page(status=2 if url.endswith('1001') else 4).encode()
                    return response
                assert mode == 'rendered_resolve' and url.startswith('https://webcast.amemv.com/webcast/reflow/9')
                assert 'cookies' not in kwargs
                uid = url.rsplit('/', 1)[-1][1:]
                room = {'idStr': '9' + uid, 'status': 2 if uid == '101' else 4,
                    'title': 'Resolved ' + uid, 'owner': {'idStr': uid,
                        'webRid': '1001' if uid == '101' else '1002'}}
                response = requests.Response()
                response.status_code = 200
                chunk = '5:' + json.dumps(['$', '$L7', None, {'data': {'room': room}}])
                response._content = ('<script>self.__rsc_f.push([1,' + json.dumps(chunk) + '])</script>').encode()
                return response
            with patch.object(requests.Session, 'get', side_effect=room_lookup), patch.object(
                    requests, 'get', side_effect=share_page):
                dialog._read()
                if mode in ('pending', 'rendered_pending'):
                    started = []
                    def request_started():
                        dialog.browser.page().runJavaScript('window.opened > 0', started.append)
                        return any(started)
                    wait_for(app, request_started)
                    dialog.reject()
                wait_for(app, lambda: dialog._worker is None)
            if mode in ('normal', 'profile_counter', 'rendered', 'rendered_fiber', 'rendered_resolve'):
                assert [room['room_id'] for room in dialog.rooms] == ['douyin:1001', 'douyin:1002']
                assert dialog.rooms[0]['live'] and not dialog.rooms[1]['live']
                if mode in ('normal', 'profile_counter'):
                    assert dialog.rooms[1]['live_known']
                    assert state['requests'] == [('999', '0'), ('42', '0'), ('42', '1')]
                else:
                    assert not state['requests']
                    assert dialog.rooms[0]['uname'] == 'Remark'
                    assert dialog.rooms[0]['face'] == 'https://p3.douyinpic.com/a.png'
                    if mode == 'rendered_resolve':
                        assert all(room['live_known'] for room in dialog.rooms)
                        assert dialog.rooms[1]['uname'] == 'Offline' and dialog.rooms[1]['title'] == 'Resolved 102'
                        selection = FollowImportDialog(dialog.rooms, set())
                        assert '未开播' in selection.list.item(1).text()
                        selection._check_live()
                        assert [r['room_id'] for r in selection.selected()] == ['douyin:1001']
                        dispose(app, selection)
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
            dialog.browser.page().runJavaScript('window.mutated === true || window.navigated === true', changed.append)
            wait_for(app, lambda: bool(changed))
            assert changed == [False]
            if mode.startswith('rendered'):
                opened = []
                dialog.browser.page().runJavaScript('window.opened', opened.append)
                wait_for(app, lambda: bool(opened))
                assert opened == [1]  # 已显示的面板直接读取，不重新打开或触发关注操作。
            dispose(app, dialog)
            state['gate'].set()

        # 真实统一导入窗口：官网读取中仍可停止、退出或切到其他平台，不接收迟到结果。
        owner = QWidget()
        owner.plugins = SimpleNamespace(_platform_owner={})
        owner._accounts = {'douyin': {'uid': '42'}}
        owner._platform_login_sessions = {}
        owner._clear_platform_account = lambda kind: owner._accounts.pop(kind, None)
        owner._render_account = lambda: None
        owner._start_avatar_loader = lambda *_args: None
        owner.sidebar = SimpleNamespace(rooms=lambda: [], folder_state=lambda: [])
        other = SimpleNamespace(kind='huya', label='虎牙', follow_login_url='about:blank',
                                follow_cookie_domain='huya.com')
        for action in ('stop', 'retry', 'switch', 'forget'):
            owner._douyin_follow_cache = None
            state.update(mode='rendered_pending', requests=[])
            dialog = AccountPlatformDialog(owner, {'douyin': provider, 'huya': other},
                                           import_follows=True, platform_kind='douyin')
            dialog.show()
            page = dialog._platform_pages['douyin']
            assert page.read_button.isEnabled() and page.read_button.text() == '停止读取'
            assert page.forget_button.isEnabled()
            assert all(button.isEnabled() for button in dialog.platform_buttons.values())
            started = []
            def opened():
                page.browser.page().runJavaScript('window.opened > 0', started.append)
                return any(started)
            wait_for(app, opened)
            with patch.object(page.account_store, 'clear') as clear:
                if action in ('stop', 'retry'):
                    page.read_button.click()
                elif action == 'forget':
                    page.forget_button.click()
                else:
                    dialog.platform_buttons['huya'].click()
                wait_for(app, lambda: page._worker is None)
                assert not dialog.rooms and not dialog._follow_pages
                page._loaded([{'room_id': 'douyin:9999'}])
                assert not dialog.rooms and not dialog._follow_pages
                if action == 'switch':
                    assert dialog.kind == 'huya' and dialog.page is dialog._platform_pages['huya']
                else:
                    assert page.read_button.text() == '读取关注' and page.read_button.isEnabled()
                assert clear.call_count == (1 if action == 'forget' else 0)
                if action == 'retry':
                    ready = []
                    page.browser.page().runJavaScript('''(() => {
                        const panel = document.querySelector('[data-e2e="user-fans-container"]');
                        const props = panel.__reactProps$fixture.children.props;
                        props.refIsLoadingShow.current = false;
                        props.refNoMoreText.current = '暂时没有更多了';
                        panel.querySelector('[data-e2e="user-fans-footer"]').textContent = '暂时没有更多了';
                        return true;
                    })()''', ready.append)
                    wait_for(app, lambda: bool(ready))
                    with patch.object(requests, 'get', side_effect=share_page):
                        page.read_button.click()
                        wait_for(app, lambda: page._worker is None)
                    assert [r['room_id'] for r in dialog.page.rooms] == ['douyin:1001']
            dispose(app, dialog)
        owner.deleteLater()
    finally:
        state['gate'].set()
        server.shutdown()
        server.server_close()
        thread.join(2)
    print('PASS: profile entry excludes feed navigation; rendered/response pagination; stop/retry/switch/logout; account/tab/search isolation; no follow mutation or signed URLs')


if __name__ == '__main__':
    main()
