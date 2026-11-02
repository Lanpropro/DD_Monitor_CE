"""Douyu edge TLS policy scope, certificate checks and relay session injection; loopback only."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import ssl
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ddm.douyu_transport import EdgeTLSAdapter, session_for
from ddm.hls_proxy import HlsProxy
import requests


class TransportTests(unittest.TestCase):
    def test_only_the_exact_edge_origin_receives_cipher_compatibility(self):
        with session_for('https://node.edgesrv.com/live?sign=private') as session:
            adapter = session.get_adapter('https://node.edgesrv.com/media')
            self.assertIsInstance(adapter, EdgeTLSAdapter)
            context = adapter.poolmanager.connection_pool_kw['ssl_context']
            baseline = ssl.create_default_context()
            self.assertTrue(session.verify)
            self.assertTrue(context.check_hostname)
            self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
            self.assertEqual(context.minimum_version, baseline.minimum_version)
            self.assertEqual(context.security_level, baseline.security_level)
            self.assertIn('AES256-GCM-SHA384', {row['name'] for row in context.get_ciphers()})
            self.assertEqual({row['name'] for row in context.get_ciphers()} -
                             {row['name'] for row in baseline.get_ciphers()}, {'AES256-GCM-SHA384'})
            proxy = adapter.proxy_manager_for('http://127.0.0.1:9')
            self.assertIs(proxy.connection_pool_kw['ssl_context'], context)
            for url in ('https://www.douyu.com/', 'https://hw1a.douyucdn2.cn/',
                        'https://other.edgesrv.com/', 'https://node.edgesrv.com.evil.invalid/'):
                self.assertNotIsInstance(session.get_adapter(url), EdgeTLSAdapter)
        with session_for('https://hw1a.douyucdn2.cn/live') as session:
            self.assertNotIsInstance(session.get_adapter('https://hw1a.douyucdn2.cn/live'), EdgeTLSAdapter)

    def test_relay_uses_injected_session_without_an_extra_media_request(self):
        hits, sessions = [], []
        class Origin(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass
            def do_GET(self):
                hits.append(self.path)
                self.send_response(200)
                self.send_header('Content-Length', '7')
                self.end_headers()
                self.wfile.write(b'FLVtest')
        server = ThreadingHTTPServer(('127.0.0.1', 0), Origin)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        source = f'http://127.0.0.1:{server.server_port}/media'
        def factory():
            session = session_for(source)
            sessions.append(session)
            return session
        relay = HlsProxy(source, {}, session_factory=factory)
        try:
            with requests.get(relay.url, timeout=3) as response:
                self.assertEqual(response.content, b'FLVtest')
            self.assertEqual(hits, ['/media'])
            self.assertEqual(len(sessions), 1)
        finally:
            relay.stop()
            relay._thread.join(2)
            server.shutdown()
            server.server_close()
            thread.join(2)


if __name__ == '__main__':
    unittest.main()
