"""Deep capture regression with fragmented FLV and one local HTTP connection; not live evidence."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from contextlib import ExitStack

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ddm.douyu_capture import Capture, TransportObserver
from ddm.douyu_flv import FlvInspector
from ddm.hls_proxy import HlsProxy
from ddm.douyu_cdn_control import install as install_cdn_control
import requests


def tag(kind, dts, data, previous=None):
    header = bytes([kind]) + len(data).to_bytes(3, 'big') + (dts & 0xffffff).to_bytes(3, 'big')
    header += bytes([dts >> 24]) + b'\0\0\0'
    return header + data + (len(data) + 11 if previous is None else previous).to_bytes(4, 'big')


def fixture():
    header = b'FLV\1\5\0\0\0\x09\0\0\0\0'
    avcc = b'\1\x64\0\x28\xff\xe1\0\2\x67\x64\1\0\2\x68\x01'
    config = tag(9, 100, b'\x17\0\0\0\0' + avcc)
    idr = tag(9, 120, b'\x17\1\xff\xff\xfe\0\0\0\2\x65\x01')
    audio = tag(8, 121, b'\xaf\1private-audio-payload')
    frame = tag(9, 160, b'\x27\1\0\0\x05\0\0\0\2\x41\x01')
    return header + config + idr + audio + frame


class CaptureTests(unittest.TestCase):
    def test_cdn_control_is_room_scoped_keeps_rate_and_logs_no_signed_url(self):
        from types import SimpleNamespace
        calls, rows = [], []
        def source(parser, raw, cdn='', *, rate=0):
            calls.append((raw, cdn, rate))
            return {'rtmp_url': 'https://alternate.invalid', 'rtmp_live': 'private?token=secret',
                    'rate': rate, 'cdnsWithName': [{'cdn': 'hw-h5'}, {'cdn': 'scdncttbej'}]}
        platform = SimpleNamespace(_request_source=source)
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'control.json'
            install_cdn_control(platform, path, lambda stage, **v: rows.append(dict(stage=stage, **v)))
            platform._request_source(None, '123', 'hw-h5', rate=15)
            self.assertEqual(calls[-1], ('123', 'hw-h5', 15))
            path.write_text(json.dumps({'room': 'douyu:123', 'cdn': 'scdncttbej'}), encoding='utf-8')
            platform._request_source(None, '123', 'hw-h5', rate=0)
            self.assertEqual(calls[-1], ('123', 'scdncttbej', 0))
            platform._request_source(None, '456', 'hw-h5', rate=15)
            self.assertEqual(calls[-1], ('456', 'hw-h5', 15))
            self.assertNotIn('secret', json.dumps(rows))
            self.assertEqual(rows[0]['host'], 'alternate.invalid')
            path.write_text(json.dumps({'room': '123', 'cdn': 'not-offered'}), encoding='utf-8')
            with self.assertRaisesRegex(RuntimeError, '未提供指定诊断线路'):
                platform._request_source(None, '123', rate=0)
            path.write_text(json.dumps({'room': '123', 'cdn': ''}), encoding='utf-8')
            platform._request_source(None, '123', 'hw-h5', rate=0)
            self.assertEqual(calls[-1], ('123', 'hw-h5', 0))

    def test_deep_playback_and_transport_attempt_ids_do_not_collide(self):
        os.environ['DDM_NO_SAVE'] = '1'
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PySide6.QtWidgets import QApplication, QWidget
        from ddm.app import MainWindow
        from ddm.player import TilePlayer
        from ddm.bili import StreamResolver
        from ddm.douyu_diagnostics import install
        app = QApplication.instance() or QApplication([])
        widget = QWidget()
        player = TilePlayer(widget)
        player.diagnostic_room = 'douyu:fixture'
        class Relay:
            url = 'http://127.0.0.1/fixture'
            stopped = False
            def __init__(self, source, headers, proxy, *, stream_observer, diagnostic, session_factory):
                with session_factory() as session:
                    assert session.verify is True
                observer = stream_observer(source)
                observer('response', status=200, attempt=1, headers={})
                observer('chunk', data=fixture(), read_ms=.1)
                diagnostic(host='cdn.invalid', attempt=1, status=200)
            def stop(self):
                self.stopped = True
        def play(player, url, profile, headers, options):
            player._stop_media()
            player.play_session = 'play-session'
            player._media = url
        with tempfile.TemporaryDirectory() as root, ExitStack() as stack:
            for owner, names in ((TilePlayer, ('_play_media', '_stop_media', 'bind', '_log', '_check')),
                                 (MainWindow, ('__init__', '_on_player_state', 'start_tile', '_schedule_retry',
                                               '_on_picture_frozen', '_on_resolve_failed')),
                                 (StreamResolver, ('_platform_play_url',))):
                for name in names:
                    stack.enter_context(patch.object(owner, name, getattr(owner, name)))
            stack.enter_context(patch.object(TilePlayer, '_play_media', play))
            stack.enter_context(patch('ddm.hls_proxy.HlsProxy', Relay))
            stack.enter_context(patch('ddm.global_danmaku.request_proxy', return_value=None))
            path = Path(root) / 'capture.jsonl'
            capture = install(path, deep=True)
            try:
                player._play_media('https://cdn.invalid/stream?token=secret', 'douyu', {}, ())
                relay = player._douyu_capture_relay
                player._stop_media()
                self.assertTrue(relay.stopped)
                capture.flush()
                records = [json.loads(s) for s in path.read_text(encoding='utf-8').splitlines()]
                response = next(r for r in records if r['stage'] == 'network.response')
                started = next(r for r in records if r['stage'] == 'playback.started')
                self.assertEqual(response['attempt'], 1)
                self.assertEqual(response['playback_attempt'], started['playback_attempt'])
                self.assertNotIn('token=secret', path.read_text(encoding='utf-8'))
            finally:
                player.release()
                capture.close()
        widget.close()
        app.processEvents()

    def test_fragmented_flv_timestamps_parameter_sets_and_no_payload_logging(self):
        rows = []
        parser = FlvInspector(lambda stage, **v: rows.append(dict(stage=stage, **v)))
        data = fixture()
        for i in range(0, len(data), 3):
            parser.feed(data[i:i + 3])
        parser.finish()
        tags = [r for r in rows if r['stage'] == 'flv.tag']
        self.assertEqual(len(tags), 4)
        self.assertEqual((tags[0]['sps_count'], tags[0]['pps_count']), (1, 1))
        self.assertEqual(tags[1]['pts_ms'], 118)
        self.assertTrue(tags[1]['idr'])
        self.assertEqual(tags[3]['pts_ms'], 165)
        self.assertEqual(tags[3]['since_idr_ms'], 40)
        self.assertEqual(rows[-1]['unparsed_bytes'], 0)
        self.assertNotIn('private-audio-payload', json.dumps(rows))

    def test_corruption_nal_bounds_and_unsupported_formats_are_explicit(self):
        rows = []
        emit = lambda stage, **v: rows.append(dict(stage=stage, **v))
        parser = FlvInspector(emit)
        parser.feed(fixture() + tag(9, 200, b'\x27\1\0\0\0\0\0\0\xff\x41'))
        self.assertEqual(rows[-1]['nal_error'], 'invalid-nal-size')
        parser.feed(tag(8, 200, b'\xaf\1x', previous=1))
        self.assertTrue(parser.disabled)
        self.assertEqual(rows[-1]['reason'], 'previous-tag-size-mismatch')
        parser = FlvInspector(emit)
        parser.feed(b'not-flv-at-all')
        self.assertTrue(parser.disabled)
        parser = FlvInspector(emit)
        parser.feed(fixture()[:13] + b'\x09\xff\xff\xff' + b'\0' * 7)
        self.assertTrue(parser.disabled)
        self.assertLessEqual(len(parser.buffer), parser.MAX_TAG)
        parser = FlvInspector(emit)
        parser.feed(fixture()[:13] + tag(9, 0, b'\x91hvc1'))
        self.assertEqual(rows[-1]['inspection'], 'enhanced-flv-not-parsed')
        parser = FlvInspector(emit)
        parser.feed(fixture()[:13] + tag(9, 0, b'\x27\1\0\0\0\0\0\0\1\x41'))
        self.assertEqual(rows[-1]['inspection'], 'missing-avc-config')

    def test_relay_uses_one_upstream_and_forwards_bytes_and_range_unchanged(self):
        data = fixture()
        connections = []
        class Origin(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass
            def do_GET(self):
                connections.append(self.headers.get('Range'))
                self.send_response(200)
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Content-Type', 'video/x-flv')
                self.send_header('Set-Cookie', 'secret=must-not-log')
                self.end_headers()
                self.wfile.write(data[:20])
                self.wfile.flush()
                time.sleep(.025)
                self.wfile.write(data[20:])
        origin = ThreadingHTTPServer(('127.0.0.1', 0), Origin)
        thread = threading.Thread(target=origin.serve_forever, daemon=True)
        thread.start()
        try:
            for broken in (False, True):
                with tempfile.TemporaryDirectory() as root:
                    path = Path(root) / 'capture.jsonl'
                    capture = Capture(path)
                    def factory(source):
                        if broken:
                            def fail(*a, **k):
                                raise ValueError('broken observer')
                            return fail
                        return TransportObserver(capture.emit, source)
                    relay = HlsProxy(f'http://127.0.0.1:{origin.server_port}/live.flv?sign=private', {},
                                     stream_observer=factory)
                    try:
                        with requests.get(relay.url, headers={'Range': 'bytes=0-'}, timeout=4) as response:
                            self.assertEqual(response.content, data)
                        relay.stop()
                        relay._thread.join(2)
                        capture.flush()
                        records = [json.loads(s) for s in path.read_text(encoding='utf-8').splitlines()]
                        if not broken:
                            self.assertTrue(any(r['stage'] == 'flv.tag' for r in records))
                            self.assertTrue(any(r['stage'] == 'network.delivered' for r in records))
                            self.assertEqual(next(r for r in records if r['stage'] == 'network.chunk')['total_bytes'], len(data))
                        self.assertNotIn('must-not-log', path.read_text(encoding='utf-8'))
                        self.assertNotIn('sign=private', path.read_text(encoding='utf-8'))
                    finally:
                        relay.stop()
                        capture.close()
            self.assertEqual(connections, ['bytes=0-', 'bytes=0-'])
        finally:
            origin.shutdown()
            origin.server_close()
            thread.join(2)

    def test_writer_reports_loss_and_flushes_before_close(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'capture.jsonl'
            capture = Capture(path)
            capture.emit('fixture', session='test')
            import queue
            with patch.object(capture.queue, 'put_nowait', side_effect=queue.Full):
                capture.emit('lost-fixture')
            capture.close()
            rows = [json.loads(s) for s in path.read_text(encoding='utf-8').splitlines()]
            self.assertEqual(rows[-1]['stage'], 'capture-stop')
            self.assertEqual(rows[-1]['dropped_records'], 1)
            self.assertFalse(capture.thread.is_alive())

    def test_byte_event_metadata_does_not_stop_following_records(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'capture.jsonl'
            capture = Capture(path)
            capture.emit('mpv.event', details={'reason': b'error', 'unexpected': b'must-not-save-binary'})
            capture.emit('after-byte-event', value=1)
            capture.close()
            text = path.read_text(encoding='utf-8')
            rows = [json.loads(s) for s in text.splitlines()]
            self.assertIn('after-byte-event', [r['stage'] for r in rows])
            self.assertNotIn('must-not-save-binary', text)
            self.assertEqual(rows[-1]['dropped_records'], 0)

    def test_transport_error_details_redact_signed_media_urls(self):
        records = []
        observer = TransportObserver(lambda stage, **v: records.append(dict(stage=stage, **v)),
                                     'https://node.edgesrv.com/private')
        error = RuntimeError('Failed https://node.edgesrv.com/private?token=secret')
        error.reason = ValueError('inner https://node.edgesrv.com/private?token=secret')
        observer('request-error', error='SSLError', exception=error)
        self.assertEqual(records[0]['error_chain'][0]['error'], 'RuntimeError')
        self.assertNotIn('private', json.dumps(records))
        self.assertNotIn('secret', json.dumps(records))

    def test_unserializable_record_is_reported_without_killing_writer(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'capture.jsonl'
            capture = Capture(path)
            capture.emit('bad-fixture', unsupported=object())
            capture.emit('after-bad-record', value=1)
            capture.close()
            rows = [json.loads(s) for s in path.read_text(encoding='utf-8').splitlines()]
            self.assertEqual([r['stage'] for r in rows], [
                'capture.serialization-error', 'after-bad-record', 'capture-stop'])
            self.assertEqual(rows[0]['original_stage'], 'bad-fixture')
            self.assertEqual(rows[-1]['dropped_records'], 1)


if __name__ == '__main__':
    unittest.main()
