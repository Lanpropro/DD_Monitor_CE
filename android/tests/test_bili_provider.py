"""Offline provider regression tests; no desktop config, credentials or network."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from urllib.error import URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app/src/main/python"))
import bili_provider as provider


def stream(protocol="http_hls", codec="avc", quality=250, hosts=None):
    return {"protocol_name": protocol, "format": [{"codec": [{
        "codec_name": codec, "base_url": "/live.m3u8", "current_qn": quality,
        "url_info": hosts if hosts is not None else [
            {"host": "https://cdn.example", "extra": "?token=a"},
            {"host": "https://backup.example", "extra": "?token=b"}],
    }]}]}


class ProviderTests(unittest.TestCase):
    def test_room_validation(self):
        self.assertEqual(provider.validate_room_id(" 000123 "), "123")
        for value in ("", "0", "abc", "-1", "１２３", "1/2", "9" * 13):
            with self.subTest(value=value), self.assertRaises(ValueError):
                provider.validate_room_id(value)

    def test_hls_avc_preferred_even_when_flv_and_hevc_come_first(self):
        result = provider.select_stream({"stream": [stream("http_stream"), stream(codec="hevc"), stream()]})
        self.assertEqual(result["protocol"], "http_hls")
        self.assertEqual(result["headers"], {"User-Agent": provider.APP_UA})
        self.assertEqual(result["urls"], ["https://cdn.example/live.m3u8?token=a",
                                          "https://backup.example/live.m3u8?token=b"])

    def test_flv_fallback_preserves_actual_quality_and_http(self):
        result = provider.select_stream({"stream": [stream("http_stream", quality=80,
            hosts=[{"host": "http://cdn.example", "extra": "?a=1"}])]})
        self.assertEqual(result["quality"], 80)
        self.assertTrue(result["urls"][0].startswith("http://"))

    def test_unavailable_avc_and_missing_candidates_fail(self):
        for play in ({}, {"stream": [stream(codec="hevc")]}, {"stream": [stream(hosts=[])]}):
            with self.subTest(play=play), self.assertRaises(ValueError):
                provider.select_stream(play)

    def test_cdn_candidates_are_deduplicated(self):
        result = provider.select_stream({"stream": [stream(hosts=[{"host": "https://a"}] * 2)]})
        self.assertEqual(result["urls"], ["https://a/live.m3u8"])

    def test_short_room_id_is_resolved_before_requesting_stream(self):
        responses = [{"room_id": 123456, "live_status": 1},
                     {"playurl_info": {"playurl": {"stream": [stream()]}}}]
        with patch.object(provider, "_get", side_effect=responses) as get:
            result = json.loads(provider.resolve_json("6"))
        self.assertTrue(result["ok"])
        self.assertEqual(result["room_id"], "123456")
        self.assertEqual(get.call_args_list[1].args[1]["room_id"], "123456")
        self.assertNotIn("Cookie", result["headers"])
        self.assertNotIn("Referer", result["headers"])

    def test_offline_room_does_not_request_stream(self):
        with patch.object(provider, "_get", return_value={"room_id": 123, "live_status": 0}) as get:
            result = json.loads(provider.resolve_json("123"))
        self.assertFalse(result["ok"])
        self.assertIn("尚未开播", result["error"])
        get.assert_called_once()

    def test_invalid_input_does_not_access_network(self):
        with patch.object(provider, "_get") as get:
            self.assertFalse(json.loads(provider.resolve_json("abc"))["ok"])
        get.assert_not_called()

    def test_network_error_is_actionable_and_does_not_expose_url(self):
        with patch.object(provider, "_get", side_effect=URLError("private diagnostic")):
            result = json.loads(provider.resolve_json("123"))
        self.assertEqual(result["error"], "网络连接失败，请检查网络后重试")

    def test_api_error_is_rejected(self):
        from io import BytesIO
        with patch.object(provider, "urlopen", return_value=BytesIO(b'{"code":-400}')):
            with self.assertRaisesRegex(ValueError, "-400"):
                provider._get("/test", {})


if __name__ == "__main__":
    unittest.main()
