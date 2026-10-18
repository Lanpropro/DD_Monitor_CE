"""离线验证：发送参数、凭据快照、设备 Cookie、接口拒绝与不重复发送。"""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from urllib.parse import parse_qs

os.environ["DDM_NO_SAVE"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests
from ddm import bili


class SendingTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(callable(getattr(bili, "send_danmaku", None)), "缺少 Python 弹幕发送接口")
        self.saved = (bili.SESSION_DATA, bili.BILI_JCT, bili.BUVID3)
        bili.set_login_cookies("session%2Fraw", "csrf-token", "device-test")
        self.resolve = patch.object(bili, "_resolve_room_id", return_value="90001")
        self.resolve.start()
        self.addCleanup(self.resolve.stop)
        self.addCleanup(self.restore)

    def restore(self):
        bili.set_login_cookies(*self.saved)

    def test_text_payload_has_matching_csrf_and_raw_cookies(self):
        with patch.object(bili.requests, "post", return_value=Mock(status_code=200,
                json=lambda: {"code": 0, "message": "", "data": {}})) as post:
            result = bili.send_danmaku("213", "你好[doge]")
        self.assertEqual(result["code"], 0)
        self.assertEqual(post.call_args.args, ("https://api.live.bilibili.com/msg/send",))
        args = post.call_args.kwargs
        self.assertEqual(args["cookies"], {"SESSDATA": "session%2Fraw", "bili_jct": "csrf-token", "buvid3": "device-test"})
        self.assertEqual(args["data"]["roomid"], "90001")
        self.assertEqual(args["data"]["msg"], "你好[doge]")
        self.assertEqual(args["data"]["csrf"], "csrf-token")
        self.assertEqual(args["data"]["csrf_token"], "csrf-token")
        self.assertEqual(args["data"]["dm_type"], "0")
        self.assertEqual(args["headers"]["Origin"], "https://live.bilibili.com")
        self.assertEqual(args["headers"]["Referer"], "https://live.bilibili.com/90001")
        self.assertFalse(args["allow_redirects"])
        self.assertGreater(args["timeout"], 0)

    def test_large_emoticon_sends_full_identifier_as_message(self):
        with patch.object(bili.requests, "post", return_value=Mock(status_code=200, json=lambda: {"code": 0})) as post:
            bili.send_danmaku("90001", "room_90001_123456", dm_type=1)
        self.assertEqual(post.call_args.kwargs["data"]["msg"], "room_90001_123456")
        self.assertEqual(post.call_args.kwargs["data"]["dm_type"], "1")

    def test_missing_credentials_and_invalid_content_never_post(self):
        with patch.object(bili.requests, "post") as post:
            for room, msg, kind in (("", "a", 0), ("douyu:1", "a", 0), ("0", "a", 0),
                                    ("1", "  ", 0), ("1", "a", 2)):
                with self.subTest(room=room, msg=msg, kind=kind), self.assertRaises(ValueError):
                    bili.send_danmaku(room, msg, dm_type=kind)
            bili.set_login_cookies("session%2Fraw", "")
            with self.assertRaisesRegex(ValueError, "bili_jct|重新登录"):
                bili.send_danmaku("1", "a")
            bili.set_sessdata("")
            with self.assertRaisesRegex(ValueError, "登录"):
                bili.send_danmaku("1", "a")
        post.assert_not_called()

    def test_rejection_even_with_code_zero_is_not_success(self):
        for payload in ({"code": -101, "message": "账号未登录"},
                        {"code": 0, "message": "f"}, {"code": 0, "msg": "发送频率过快"},
                        {"data": {}}, [], {"code": 0, "data": {"msg": "弹幕被屏蔽"}}):
            with self.subTest(payload=payload), patch.object(bili.requests, "post", return_value=Mock(status_code=200,
                    json=lambda: payload)), self.assertRaises(ValueError):
                bili.send_danmaku("1", "test")

    def test_timeout_is_not_retried(self):
        with patch.object(bili.requests, "post", side_effect=requests.Timeout()) as post:
            with self.assertRaises(requests.Timeout):
                bili.send_danmaku("1", "test")
        self.assertEqual(post.call_count, 1)

    def test_emoticons_reuse_shared_device_cookie_and_do_not_mutate_snapshot(self):
        snapshot = {"SESSDATA": "snapshot-session", "bili_jct": "snapshot-csrf"}
        with patch.object(bili, "ensure_buvid3", return_value="shared-device") as ensure, \
                patch.object(bili.requests, "get", return_value=Mock(status_code=200,
                    json=lambda: {"code": 0, "data": {"data": []}})) as get:
            self.assertEqual(bili.get_emoticons("213", cookies=snapshot), [])
        ensure.assert_called_once_with()
        self.assertNotIn("buvid3", snapshot)
        self.assertEqual(get.call_args.kwargs["cookies"], {
            "SESSDATA": "snapshot-session", "bili_jct": "snapshot-csrf", "buvid3": "shared-device"})

    def test_malformed_catalog_is_an_error_instead_of_empty_success(self):
        for data in (None, [], {"data": {}}, {"data": [None]},
                     {"data": [{"emoticons": 123}]}, {"data": [{"emoticons": [None]}]}):
            with self.subTest(data=data), patch.object(bili.requests, "get", return_value=Mock(
                    status_code=200, json=lambda: {"code": 0, "data": data})), self.assertRaises(ValueError):
                bili.get_emoticons("213")

    def test_send_initializes_missing_device_cookie_using_shared_store(self):
        snapshot = {"SESSDATA": "old-session", "bili_jct": "old-csrf"}
        with patch.object(bili, "ensure_buvid3", return_value="shared-device") as ensure, \
                patch.object(bili.requests, "post", return_value=Mock(status_code=200,
                    json=lambda: {"code": 0})) as post:
            bili.send_danmaku("213", "设备身份", cookies=snapshot)
        ensure.assert_called_once_with()
        self.assertEqual(post.call_args.kwargs["cookies"]["buvid3"], "shared-device")
        self.assertNotIn("buvid3", snapshot)

    def test_request_can_use_a_credential_snapshot(self):
        with patch.object(bili.requests, "post", return_value=Mock(status_code=200, json=lambda: {"code": 0})) as post:
            bili.send_danmaku("1", "test", cookies={"SESSDATA": "old", "bili_jct": "old-csrf"})
        self.assertEqual(post.call_args.kwargs["cookies"]["SESSDATA"], "old")
        self.assertEqual(post.call_args.kwargs["data"]["csrf"], "old-csrf")

    def test_emoticon_catalog_preserves_package_type_cover_and_permissions(self):
        packages = [{"pkg_type": 3, "pkg_name": "小表情", "emoticons": [
            {"emoji": "[doge]", "perm": 1, "emoticon_unique": "emoji_1"}]},
            {"pkg_type": 2, "pkg_name": "主播", "current_cover": "https://example.invalid/cover.png", "emoticons": [
                {"emoji": "好", "perm": 0, "emoticon_unique": "room_90001_77"}]}]
        with patch.object(bili.requests, "get", return_value=Mock(status_code=200,
                json=lambda: {"code": 0, "data": {"data": packages}})) as get:
            self.assertEqual(bili.get_emoticons("213"), packages)
        self.assertEqual(get.call_args.kwargs["params"], {"platform": "pc", "room_id": "90001"})
        self.assertEqual(get.call_args.kwargs["cookies"]["bili_jct"], "csrf-token")
        self.assertEqual(get.call_args.kwargs["cookies"]["buvid3"], "device-test")

    def test_changing_account_or_logging_out_clears_old_csrf(self):
        bili.set_sessdata("session%2Fraw")
        self.assertEqual(bili.BILI_JCT, "csrf-token")
        bili.set_sessdata("another")
        self.assertEqual(bili.BILI_JCT, "")
        bili.set_login_cookies("another", "new-csrf")
        bili.set_sessdata("")
        self.assertEqual(bili._cookies(), {"buvid3": "device-test"})

    def test_http_redirect_and_failure_do_not_count_as_success(self):
        for status, error in ((302, ValueError), (503, requests.HTTPError)):
            response = requests.Response()
            response.status_code = status
            response._content = b'{"code":0}'
            with self.subTest(status=status), patch.object(bili.requests, "post", return_value=response):
                with self.assertRaises(error):
                    bili.send_danmaku("1", "test")

    def test_real_http_transport_sends_form_and_cookie_snapshot_to_local_server(self):
        received = []
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"])).decode()
                received.append((self.headers.get("Cookie", ""), parse_qs(body)))
                payload = json.dumps({"code": 0, "data": {}}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        transport = requests.Session()
        transport.trust_env = False
        def local_post(url, **kwargs):
            return transport.post(f"http://127.0.0.1:{server.server_port}/msg/send", **kwargs)
        try:
            with patch.object(bili.requests, "post", side_effect=local_post):
                bili.send_danmaku("213", "你好[doge]")
                bili.send_danmaku("213", "room_90001_123456", dm_type=1)
        finally:
            transport.close()
            server.shutdown()
            server.server_close()
            thread.join(2)
        self.assertEqual(len(received), 2)
        cookie, text = received[0]
        for item in ("SESSDATA=session%2Fraw", "bili_jct=csrf-token", "buvid3=device-test"):
            self.assertIn(item, cookie)
        self.assertEqual(text["msg"], ["你好[doge]"])
        self.assertEqual(text["roomid"], ["90001"])
        self.assertEqual(text["csrf"], ["csrf-token"])
        self.assertEqual(received[1][1]["msg"], ["room_90001_123456"])
        self.assertEqual(received[1][1]["dm_type"], ["1"])


if __name__ == "__main__":
    unittest.main()
