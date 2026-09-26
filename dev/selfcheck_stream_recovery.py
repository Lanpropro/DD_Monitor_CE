"""离线自检：备用 CDN、取流探测与实际播放器请求一致。"""
import os
import sys
from unittest import mock

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from ddm import bili  # noqa: E402


class Response:
    status_code = 200

    def iter_content(self, _size):
        yield b"FLV"

    def close(self):
        pass


class JsonResponse:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


def main() -> None:
    with mock.patch.object(bili.requests, "get", return_value=Response()) as get:
        assert bili._fetchable("http://cdn/live.flv", bili.STREAM_APP)
        assert "cookies" not in get.call_args.kwargs, \
            "探测请求不能用播放器没有发送的登录 cookie"

    candidates = ["https://cdn-a/live.flv", "https://cdn-b/live.flv"]
    app_payload = {"data": {"playurl_info": {"playurl": {"stream": [{
        "protocol_name": "http_stream", "format": [{"codec": [{
            "base_url": "/live.flv", "current_qn": 250,
            "url_info": [{"host": "https://cdn-a", "extra": ""},
                         {"host": "https://cdn-b", "extra": ""}],
        }]}],
    }]}}}}
    with mock.patch.object(bili.requests, "get", return_value=JsonResponse(app_payload)):
        assert bili._app_play_urls("1001", 250) == (candidates, 250)

    web_payload = {"code": 0, "data": {"current_qn": 250, "durl": [{
        "url": candidates[0], "backup_url": [candidates[1]],
    }]}}
    with mock.patch.object(bili.requests, "get", return_value=JsonResponse(web_payload)):
        assert bili._web_play_urls("1001", 250) == (candidates, 250)

    with mock.patch.object(bili, "_app_play_urls", return_value=(candidates, 250)), \
         mock.patch.object(bili, "_web_play_urls", side_effect=AssertionError("不应退回 web")), \
         mock.patch.object(bili, "_fetchable", return_value=True) as fetch:
        first = bili.play_url("1001", 250, source_offset=0)
        second = bili.play_url("1001", 250, source_offset=1)
    assert first[0] == "http://cdn-a/live.flv"
    assert second[0] == "http://cdn-b/live.flv", "重取流应试另一条 CDN"
    assert fetch.call_count == 2

    with mock.patch.object(bili, "_app_play_urls", return_value=(candidates, 250)), \
         mock.patch.object(bili, "_web_play_urls", side_effect=AssertionError("不应退回 web")), \
         mock.patch.object(bili, "_fetchable", side_effect=[False, True]) as fetch:
        fallback = bili.play_url("1001", 250)
    assert fallback[0] == "http://cdn-b/live.flv"
    assert fetch.call_count == 2, "第一条 CDN 不通时应试同通道备用地址"

    resolver = bili.StreamResolver("1001", 250, source_offset=1)
    with mock.patch.object(bili, "play_url", return_value=(
            "http://cdn-b/live.flv", 250, "app", bili.STREAM_APP)) as play, \
         mock.patch.object(bili, "room_quality_options", return_value=[]):
        resolver.run()
    assert play.call_args.kwargs["source_offset"] == 1, \
        "取流线程必须把轮换序号传给地址选择逻辑"
    print("取流探测、CDN 轮换与备用地址：通过")


if __name__ == "__main__":
    main()
