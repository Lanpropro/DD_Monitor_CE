"""离线验证：发送参数、Cookie、接口拒绝，以及扫码登录的 CSRF Cookie。"""
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

os.environ["DDM_NO_SAVE"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests
from ddm import bili, login


class SendingTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(callable(getattr(bili, "send_danmaku", None)), "缺少 Python 弹幕发送接口")
        self.saved = (bili.SESSION_DATA, bili.BILI_JCT)
        bili.set_sessdata("session%2Fraw")
        bili.set_bili_jct("csrf-token")
        self.resolve = patch.object(bili, "_resolve_room_id", return_value="90001")
        self.resolve.start()
        self.addCleanup(self.resolve.stop)
        self.addCleanup(self.restore)

    def restore(self):
        bili.set_sessdata(self.saved[0])
        bili.set_bili_jct(self.saved[1])

    def test_text_payload_has_matching_csrf_and_raw_cookies(self):
        with patch.object(bili.requests, "post", return_value=Mock(status_code=200,
                json=lambda: {"code": 0, "message": "", "data": {}})) as post:
            result = bili.send_danmaku("213", "你好[doge]")
        self.assertEqual(result["code"], 0)
        self.assertEqual(post.call_args.args, ("https://api.live.bilibili.com/msg/send",))
        args = post.call_args.kwargs
        self.assertEqual(args["cookies"], {"SESSDATA": "session%2Fraw", "bili_jct": "csrf-token"})
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
            bili.set_bili_jct("")
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

    def test_request_can_use_a_credential_snapshot(self):
        with patch.object(bili.requests, "post", return_value=Mock(status_code=200, json=lambda: {"code": 0})) as post:
            bili.send_danmaku("1", "test", cookies={"SESSDATA": "old", "bili_jct": "old-csrf"})
        self.assertEqual(post.call_args.kwargs["cookies"]["SESSDATA"], "old")
        self.assertEqual(post.call_args.kwargs["data"]["csrf"], "old-csrf")

    def test_emoticon_catalog_preserves_package_type_and_permissions(self):
        packages = [{"pkg_type": 3, "pkg_name": "小表情", "emoticons": [
            {"emoji": "[doge]", "perm": 1, "emoticon_unique": "emoji_1"}]},
            {"pkg_type": 2, "pkg_name": "主播", "emoticons": [
                {"emoji": "好", "perm": 0, "emoticon_unique": "room_90001_77"}]}]
        spi = Mock(status_code=200, json=lambda: {"code": 0, "data": {"b_3": "device-buvid3"}})
        catalog = Mock(status_code=200, json=lambda: {"code": 0, "data": {"data": packages}})
        with patch.object(bili, "_BUVID3", ""), \
                patch.object(bili.requests, "get", side_effect=[spi, catalog]) as get:
            self.assertEqual(bili.get_emoticons("213"), packages)
        self.assertEqual([call.args[0] for call in get.call_args_list],
                         ["https://api.bilibili.com/x/frontend/finger/spi",
                          "https://api.live.bilibili.com/xlive/web-ucenter/v2/emoticon/GetEmoticons"])
        self.assertEqual(get.call_args.kwargs["params"], {"platform": "pc", "room_id": "90001"})
        self.assertEqual(get.call_args.kwargs["cookies"]["bili_jct"], "csrf-token")
        self.assertEqual(get.call_args.kwargs["cookies"]["buvid3"], "device-buvid3")

    def test_emoticon_device_cookie_is_fetched_once_and_reused(self):
        spi = Mock(status_code=200, json=lambda: {"code": 0, "data": {"b_3": "cached-buvid3"}})
        catalog = Mock(status_code=200, json=lambda: {"code": 0, "data": {"data": []}})
        with patch.object(bili, "_BUVID3", ""), \
                patch.object(bili.requests, "get", side_effect=[spi, catalog, catalog]) as get:
            bili.get_emoticons("213")
            bili.get_emoticons("214")
            self.assertEqual(bili._BUVID3, "cached-buvid3")
        self.assertEqual(get.call_count, 3, "第二次取表情不应再换新的设备 Cookie")
        self.assertTrue(all(call.kwargs["cookies"]["buvid3"] == "cached-buvid3"
                            for call in get.call_args_list[1:]))

    def test_emoticon_request_without_device_cookie_fails_loudly(self):
        with patch.object(bili, "_BUVID3", ""), \
                patch.object(bili.requests, "get", return_value=Mock(
                    status_code=200, json=lambda: {"code": 0, "data": {}})) as get:
            with self.assertRaisesRegex(ValueError, "buvid3"):
                bili.get_emoticons("213")
        self.assertEqual(get.call_count, 1, "拿不到设备 Cookie 时不该继续请求表情列表")

    def test_changing_account_or_logging_out_clears_old_csrf(self):
        bili.set_sessdata("session%2Fraw")
        self.assertEqual(bili.BILI_JCT, "csrf-token")
        bili.set_sessdata("another")
        self.assertEqual(bili.BILI_JCT, "")
        bili.set_bili_jct("new-csrf")
        bili.set_sessdata("")
        self.assertEqual(bili._cookies(), {})

    def test_http_redirect_and_failure_do_not_count_as_success(self):
        for status, error in ((302, ValueError), (503, requests.HTTPError)):
            response = requests.Response()
            response.status_code = status
            response._content = b'{"code":0}'
            with self.subTest(status=status), patch.object(bili.requests, "post", return_value=response):
                with self.assertRaises(error):
                    bili.send_danmaku("1", "test")


class QRAuthTests(unittest.TestCase):
    def test_success_keeps_bili_jct_from_poll_or_session(self):
        for cookie_source in ("poll", "session"):
            with self.subTest(cookie_source=cookie_source):
                worker = login.QRLogin()
                session = Mock()
                poll_cookies = requests.cookies.RequestsCookieJar()
                session.cookies = requests.cookies.RequestsCookieJar()
                jar = poll_cookies if cookie_source == "poll" else session.cookies
                jar.set("SESSDATA", "session%2Fraw")
                jar.set("bili_jct", "csrf-qr")
                session.get.side_effect = [Mock(json=lambda: {"data": {
                    "qrcode_key": "test", "url": "https://example.com/qr"}}),
                    Mock(cookies=poll_cookies, json=lambda: {"data": {"code": 0}})]
                with patch.object(login.requests, "Session", return_value=session):
                    worker.run()
                self.assertEqual(getattr(worker, "bili_jct", ""), "csrf-qr")
                self.assertEqual(worker.sessdata, "session%2Fraw")


if __name__ == "__main__":
    unittest.main()
