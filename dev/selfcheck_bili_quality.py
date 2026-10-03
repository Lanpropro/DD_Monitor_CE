"""离线验证 B站实际 FLV 档位、2K 名称、旧接口回退和格子选择。"""
import os
from pathlib import Path
import sys
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["DDM_NO_SAVE"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402
from ddm import bili  # noqa: E402
from ddm.widgets import Tile  # noqa: E402


def response(data):
    return Mock(json=Mock(return_value=data))


def app_payload(accepted):
    return {"code": 0, "data": {"playurl_info": {"playurl": {
        # 全局名称表含有当前房间没有的杜比/4K，不能全加入菜单。
        "g_qn_desc": [
            {"qn": 30000, "desc": "杜比"}, {"qn": 20000, "desc": "4K"},
            {"qn": 25000, "desc": "原画真彩", "media_base_desc": {
                "detail_desc": {"desc": "2K 原画"}, "brief_desc": {"desc": "2K"}}},
            {"qn": 15000, "desc": "2K"}, {"qn": 10000, "desc": "原画", "media_base_desc": {
                "detail_desc": {"desc": "1080P 高码率"}, "brief_desc": {"desc": "1080P"}}},
            {"qn": 400, "desc": "蓝光"}, {"qn": 250, "desc": "超清"},
        ],
        "stream": [
            {"protocol_name": "http_hls", "format": [{"codec": [{"accept_qn": [30000]}]}]},
            {"protocol_name": "http_stream", "format": [{"format_name": "flv", "codec": [{
                "codec_name": "avc", "accept_qn": accepted, "current_qn": 25000,
                "base_url": "/live.flv", "url_info": [{"host": "https://cdn", "extra": ""}],
            }]}]},
        ],
    }}}}


def main():
    application = QApplication([])
    payload = app_payload([25000, 10000, 400, 250])
    with patch.object(bili.requests, "get", return_value=response(payload)) as get:
        options = bili.room_quality_options("27183290")
        assert [item["qn"] for item in options] == [25000, 10000, 400, 250], options
        assert options[0] == {"qn": 25000, "desc": "2K 原画", "label": "2K"}
        assert options[1]["label"] == "原画", "常用档位的按钮名称应保持可区分"
        assert get.call_count == 1
        assert "getRoomPlayInfo" in get.call_args.args[0]
        assert bili._app_play_urls("27183290", 25000) == (["https://cdn/live.flv"], 25000)
        assert get.call_args.kwargs["params"]["qn"] == 25000

    # 未登录/普通直播间只展示服务端允许的档位；不能把全局的2K名称硬加进去。
    with patch.object(bili.requests, "get", return_value=response(app_payload([250]))):
        assert [item["qn"] for item in bili.room_quality_options("27183290")] == [250]
    with patch.object(bili.requests, "get", return_value=response(app_payload([15000, 10000]))):
        assert bili.room_quality_options("27183290")[0] == {"qn": 15000, "desc": "2K"}

    web = {"code": 0, "data": {"quality_description": [
        {"qn": 10000, "desc": "原画"}, {"qn": "invalid"}, {"qn": 250, "desc": "超清"}]}}
    for app in (response({"code": -1}), response(app_payload([])), RuntimeError("network")):
        with patch.object(bili.requests, "get", side_effect=[app, response(web)]):
            assert bili.room_quality_options("27183290") == [
                {"qn": 10000, "desc": "原画"}, {"qn": 250, "desc": "超清"}]
    with patch.object(bili.requests, "get", side_effect=RuntimeError("network")):
        assert bili.room_quality_options("27183290") == []

    # Qt 菜单实际选中2K，把真实 qn 传给取流；降档不能仍显示2K。
    tile = Tile({"room_id": "27183290", "live": True, "uname": "测试"})
    tile.set_quality_options(options)
    selected = []
    tile.qualityChanged.connect(lambda *args: selected.append(args))
    def choose(menu, *_):
        action = next(action for action in menu.actions() if action.text() == "2K 原画")
        action.trigger()
        menu.close()
    def create_menu(parent):
        menu = QMenu(parent)
        QTimer.singleShot(0, lambda: choose(menu))
        return menu
    with patch("ddm.widgets.QMenu", side_effect=create_menu):
        tile._open_quality_menu()
    assert tile.quality == 25000 and selected
    tile.set_actual_quality(25000)
    assert tile._quality_text() == "2K"
    tile.set_actual_quality(10000)
    assert tile._quality_text() == "原画"
    assert "2K 原画" in tile.quality_button.toolTip(), tile.quality_button.toolTip()
    assert "1080P 高码率" in tile.quality_button.toolTip()
    resolved = []
    resolver = bili.StreamResolver("27183290", 25000)
    resolver.resolved.connect(lambda *args: resolved.append(args))
    with patch.object(bili, "play_url", return_value=(
            "http://cdn/live.flv", 25000, "app", bili.STREAM_APP)) as play, \
            patch.object(bili, "room_quality_options", return_value=options):
        resolver.run()
    assert play.call_args.args == ("27183290", 25000)
    assert resolved[0][2] == 25000 and resolved[0][-1] == options
    tile.close()
    application.processEvents()
    print("PASS: Bili 2K FLV options, names, unsupported tiers, fallback, Qt selection and resolver")


if __name__ == "__main__":
    main()
