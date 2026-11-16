"""Loopback Release fixtures for manual update presentation acceptance."""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import threading
import zipfile


class PreviewServer:
    def __init__(self, directory, unit=4 * 1024 * 1024, delay=.2):
        self.directory = Path(directory)
        self.delay = delay
        self.stopped = threading.Event()
        self.lock = threading.Lock()
        self.failures = {}
        self.corruptions = {}
        self.assets = {}
        for key, name, size in (('app', '软件更新', unit * 3),
                                ('preview_one', '测试插件一', unit),
                                ('preview_two', '测试插件二', unit * 2)):
            path = self.directory / (key + '.zip')
            self.package(path, key, name, '2.0', size)
            self.assets['/' + path.name] = path
        fixtures = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_GET(self):
                path = fixtures.assets.get(self.path)
                if path is None:
                    self.send_error(404)
                    return
                with fixtures.lock:
                    fail = fixtures.failures.get(self.path, 0) > 0
                    corrupt = fixtures.corruptions.get(self.path, 0) > 0
                    if fail:
                        fixtures.failures[self.path] -= 1
                    if corrupt:
                        fixtures.corruptions[self.path] -= 1
                self.send_response(200)
                self.send_header('Content-Length', str(path.stat().st_size))
                self.end_headers()
                try:
                    with path.open('rb') as source:
                        first = True
                        while chunk := source.read(128 * 1024):
                            if fixtures.stopped.wait(fixtures.delay):
                                break
                            if first and corrupt:
                                chunk = bytes([chunk[0] ^ 1]) + chunk[1:]
                            self.wfile.write(chunk)
                            self.wfile.flush()
                            if first and fail:
                                self.connection.shutdown(socket.SHUT_RDWR)
                                break
                            first = False
                except (BrokenPipeError, ConnectionResetError, OSError):
                    pass

        self.http = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.worker = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.worker.start()

    @staticmethod
    def package(path, key, name, version, size):
        with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_STORED) as archive:
            archive.writestr(key + '/plugin.json', json.dumps(dict(
                id=key, name=name, version=version, description='本地样式验收测试包', min_app_version='0.3')))
            archive.writestr(key + '/plugin.py', "raise RuntimeError('Preview package must never execute')")
            archive.writestr(key + '/preview.bin', b'\x7b' * size)

    def offer(self, key):
        path = self.assets['/' + key + '.zip']
        return dict(id=key, name={'app': '软件更新', 'preview_one': '测试插件一',
                                 'preview_two': '测试插件二'}[key],
                    version='2.0', description='本地样式验收测试包', available=True,
                    size=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    url=f'http://127.0.0.1:{self.http.server_port}/{path.name}',
                    notes='本地测试更新：用于检查下载进度、大小、速度和重试样式。')

    def scenario(self, index):
        with self.lock:
            self.delay = .65 if index == 1 else .2
            self.failures = {'/app.zip': 3} if index == 2 else {}
            self.corruptions = {'/app.zip': 1} if index == 3 else {}

    def stop(self):
        self.stopped.set()
        self.http.shutdown()
        self.http.server_close()
        self.worker.join(timeout=5)
