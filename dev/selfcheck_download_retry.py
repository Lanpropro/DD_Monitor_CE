"""本体/插件下载的瞬时 SSL/流中断重试与取消、校验边界。"""
import hashlib
from pathlib import Path
import sys
import tempfile
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ddm import online


class Response:
    def __init__(self, chunks, failure=None, status_error=None):
        self.chunks, self.failure, self.status_error = chunks, failure, status_error
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def raise_for_status(self):
        if self.status_error:
            raise self.status_error

    def iter_content(self, size):
        yield from self.chunks
        if self.failure:
            raise self.failure


def expect_error(kind, operation):
    try:
        operation()
    except kind:
        return
    raise AssertionError(f'expected {kind.__name__}')


def real_redirect_retry():
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading
    payload = b'local download probe'
    redirects, assets = [], []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path == '/release':
                redirects.append(self.path)
                self.send_response(302)
                self.send_header('Location', f'/asset?attempt={len(redirects)}')
                self.send_header('Content-Length', '0')
                self.end_headers()
            else:
                assets.append(self.path)
                if len(assets) == 1:
                    self.close_connection = True
                    return
                self.send_response(200)
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        with tempfile.TemporaryDirectory(prefix='ddm-redirect-retry-') as directory, online.session() as client:
            client.trust_env = False
            offer = {'url': f'http://127.0.0.1:{server.server_port}/release',
                     'size': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()}
            path = online.download(offer, Path(directory) / 'probe.zip', client)
            assert Path(path).read_bytes() == payload
            assert len(redirects) == 2 and assets == ['/asset?attempt=1', '/asset?attempt=2']
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)


def main():
    payload = b'verified release bytes'
    with tempfile.TemporaryDirectory(prefix='ddm-download-retry-') as directory, \
            patch.object(online.time, 'sleep', return_value=None):
        target = Path(directory) / 'download.zip'
        partial = target.with_suffix('.zip.part')
        for repository in (online.APP_REPOSITORY, online.PLUGIN_REPOSITORY):
            offer = {'url': f'https://github.com/{repository}/releases/download/v1/package.zip',
                     'size': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()}
            for error in (online.requests.exceptions.SSLError('SSL: UNEXPECTED_EOF_WHILE_READING'),
                          online.requests.exceptions.ConnectTimeout('timeout'),
                          online.requests.exceptions.ReadTimeout('timeout')):
                response = Response([payload])
                client = Mock()
                client.get.side_effect = [error, response]
                progress = []
                online.download(offer, target, client, progress=lambda *value: progress.append(value))
                assert target.read_bytes() == payload and not partial.exists() and response.closed
                assert client.get.call_count == 2
                assert all(call.args == (offer['url'],) and 'verify' not in call.kwargs
                           for call in client.get.call_args_list)
                assert progress.count((0, len(payload))) == 2 and progress[-1] == (len(payload), len(payload))
            # 中途断流后从头写入，不能拼接上次的数据或沿用旧摘要。
            interrupted = Response([payload[:7]], online.requests.exceptions.ChunkedEncodingError('EOF'))
            final = Response([payload])
            client = Mock()
            client.get.side_effect = [interrupted, final]
            online.download(offer, target, client)
            assert interrupted.closed and final.closed and target.read_bytes() == payload
            # 连续失败最多请求三次，旧目标文件不受影响。
            client = Mock()
            client.get.side_effect = online.requests.ConnectionError('offline')
            expect_error(online.requests.ConnectionError, lambda: online.download(offer, target, client))
            assert client.get.call_count == 3 and not partial.exists() and target.read_bytes() == payload
            # 校验失败和 HTTP 状态错误不当成短暂连接故障重试。
            for response, kind in ((Response([b'x' * len(payload)]), ValueError),
                                   (Response([], status_error=online.requests.HTTPError('403')), online.requests.HTTPError)):
                client = Mock()
                client.get.return_value = response
                expect_error(kind, lambda: online.download(offer, target, client))
                assert client.get.call_count == 1 and not partial.exists() and target.read_bytes() == payload
            # 重试等待期间可取消，不发送下一次请求。
            cancelled = [False]
            client = Mock()
            client.get.side_effect = online.requests.exceptions.SSLError('EOF')
            with patch.object(online.time, 'sleep', side_effect=lambda _: cancelled.__setitem__(0, True)):
                expect_error(InterruptedError, lambda: online.download(offer, target, client, cancelled=lambda: cancelled[0]))
            assert client.get.call_count == 1 and not partial.exists()
            client = Mock()
            expect_error(InterruptedError, lambda: online.download(offer, target, client, cancelled=lambda: True))
            client.get.assert_not_called()
    real_redirect_retry()
    print('PASS: app/plugin SSL and timeout retry, fresh redirect, interrupted stream restart, bounded failure, integrity and cancellable delay')


if __name__ == '__main__':
    main()
