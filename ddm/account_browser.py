"""A short-lived, application-owned Chrome/Edge profile for explicit website login."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
from urllib.parse import urlsplit
from urllib.request import getproxies

import aiohttp


def find_browser():
    for base in (os.environ.get('PROGRAMFILES', r'C:\Program Files'),
                 os.environ.get('PROGRAMFILES(X86)', r'C:\Program Files (x86)'),
                 os.environ.get('LOCALAPPDATA', '')):
        if not base:
            continue
        for relative in ('Google/Chrome/Application/chrome.exe', 'Microsoft/Edge/Application/msedge.exe'):
            path = Path(base) / relative
            if path.is_file():
                return str(path)
    raise RuntimeError('未找到 Chrome 或 Edge，请安装其中一个浏览器，或使用 OAuth 授权')


def browser_proxy():
    proxies = getproxies()
    endpoint = proxies.get('https') or proxies.get('all') or proxies.get('http')
    if not endpoint:
        return None
    parts = urlsplit(endpoint if '://' in endpoint else 'http://' + endpoint)
    if parts.scheme not in ('http', 'https', 'socks5') or not parts.hostname or parts.username or parts.password:
        raise RuntimeError('当前代理地址不支持浏览器登录，请使用本机 HTTP/SOCKS5 代理入口')
    return parts.geturl()


class AccountBrowser:
    def __init__(self, url, domains, cancelled):
        self.url, self.domains, self.cancelled = url, tuple(domains), cancelled
        self.directory = None
        self.process = None
        self.socket_url = ''
        self.login_closed = False

    def __enter__(self):
        self.executable = find_browser()
        self.proxy = browser_proxy()
        self.directory = tempfile.TemporaryDirectory(prefix='ddm-account-')
        try:
            self._launch(headless=False)
            return self
        except Exception:
            self.__exit__(None, None, None)
            raise

    def _launch(self, *, headless):
        args = [self.executable, '--user-data-dir=' + self.directory.name,
                '--no-first-run', '--no-default-browser-check', '--disable-sync', '--disable-background-mode']
        if self.proxy:
            # The built-in proxy changes process environment, rather than system browser settings.
            args.extend(['--proxy-server=' + self.proxy, '--proxy-bypass-list=localhost;127.0.0.1;[::1]'])
        if headless:
            args.extend(['--headless=new', '--remote-debugging-port=0', '--remote-debugging-address=127.0.0.1',
                         'about:blank'])
        else:
            # User login happens in a normal browser. Read the dedicated profile only after it closes.
            args.extend(['--new-window', self.url])
        self.process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if headless:
            active = Path(self.directory.name) / 'DevToolsActivePort'
            deadline = time.monotonic() + 15
            while not self.cancelled.wait(.1):
                if self.process.poll() is not None:
                    raise RuntimeError('独立登录窗口未能启动，请重试或使用 OAuth 授权')
                if active.is_file():
                    lines = active.read_text(encoding='utf-8').splitlines()
                    if (len(lines) >= 2 and lines[0].isdigit() and 0 < int(lines[0]) < 65536
                            and lines[1].startswith('/devtools/browser/')):
                        self.socket_url = f'ws://127.0.0.1:{lines[0]}{lines[1]}'
                        return
                if time.monotonic() >= deadline:
                    raise RuntimeError('登录窗口启动超时，请重试或使用 OAuth 授权')

    async def _command(self, method):
        # This control connection must remain local, even when HTTP(S)_PROXY is enabled.
        async with aiohttp.ClientSession(trust_env=False, timeout=aiohttp.ClientTimeout(total=3)) as client:
            async with client.ws_connect(self.socket_url, max_msg_size=4 * 1024 * 1024) as socket:
                await socket.send_json({'id': 1, 'method': method})
                async for message in socket:
                    if message.type == aiohttp.WSMsgType.TEXT:
                        data = json.loads(message.data)
                        if data.get('id') == 1:
                            if data.get('error'):
                                raise RuntimeError('无法读取本次登录窗口，请重试或使用 OAuth 授权')
                            return data.get('result', {})
                    elif message.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                        break
        raise RuntimeError('登录窗口已关闭，请重新打开并完成登录')

    def cookies(self):
        if self.cancelled.is_set():
            return []
        if not self.login_closed:
            if self.process.poll() is None:
                return []
            self.login_closed = True
            self._launch(headless=True)
        if self.cancelled.is_set():
            return []
        if self.process.poll() is not None:
            raise RuntimeError('登录窗口已关闭，请重新打开并完成登录')
        data = asyncio.run(self._command('Storage.getCookies'))
        return [cookie for cookie in data.get('cookies', []) if
                any(cookie.get('domain', '').lstrip('.') == domain or
                    cookie.get('domain', '').lstrip('.').endswith('.' + domain) for domain in self.domains)
                and (cookie.get('expires', -1) <= 0 or cookie['expires'] > time.time())]

    def __exit__(self, *_args):
        if self.process is not None and self.process.poll() is None:
            if self.socket_url:
                try:
                    asyncio.run(self._command('Browser.close'))
                except (RuntimeError, OSError, TimeoutError, aiohttp.ClientError):
                    pass
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                if os.name == 'nt':
                    subprocess.run(['taskkill', '/PID', str(self.process.pid), '/T', '/F'],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=subprocess.CREATE_NO_WINDOW, timeout=5)
                else:
                    self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=3)
        if self.directory is not None:
            self.directory.cleanup()
