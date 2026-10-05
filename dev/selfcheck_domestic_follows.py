"""国内平台关注：官网协议、离线分页和真实 WebEngine 请求桥回归。"""
import json
import os
from pathlib import Path
import struct
import sys
from unittest.mock import MagicMock, Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["DDM_NO_SAVE"] = "1"
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--disable-gpu")
import requests
from PySide6.QtCore import QUrl, Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEngineSettings
from ddm.live_danmaku import tars_bytes, tars_fields, tars_int
from ddm.platform_login import PlatformFollowDialog
from plugins_user.domestic_live.plugin import HuyaPlatform, DouyinPlatform, huya_string
from dev.selfcheck_account_dialog import dispose
from dev.selfcheck_platform_follows import wait_for


def encode(tag, value):
    if isinstance(value, int):
        return tars_int(tag, value)
    if isinstance(value, str):
        return huya_string(tag, value)
    if isinstance(value, list):
        return bytes([tag << 4 | 9]) + tars_int(0, len(value)) + b"".join(encode(0, v) for v in value)
    return bytes([tag << 4 | 10]) + b"".join(encode(k, v) for k, v in value.items()) + b"\x0b"


def reply(payload=None, *, binary=None):
    result = MagicMock(status_code=200)
    result.content = binary if binary is not None else json.dumps(payload).encode()
    result.json.return_value = payload
    result.__enter__.return_value = result
    return result


def wup(method, fields, code=0):
    entries = [("", tars_int(0, code))]
    if fields is not None:
        entries.append(("tRsp", encode(0, fields)))
    values = b"\x08" + tars_int(0, len(entries)) + b"".join(
        huya_string(0, key) + tars_bytes(1, value) for key, value in entries)
    body = tars_int(1, 3) + huya_string(6, method) + tars_bytes(7, values)
    return reply(binary=struct.pack(">I", len(body) + 4) + body)


def fails(action):
    try:
        action()
    except (RuntimeError, ValueError):
        return
    raise AssertionError("Invalid follow response returned a successful list")


def check_huya():
    provider = HuyaPlatform()
    provider.account_info = Mock(return_value={"uid": "42"})
    with requests.Session() as session:
        session.cookies.set("fixture", "valid", domain=".huya.com")
        session.cookies.set("foreign", "excluded", domain="huya.com.evil.invalid")
        session.post = Mock(side_effect=[
            wup("getAllSubscribeToUidList", {1: [101, 102, 101, 103]}),
            wup("getUserProfile", {0: {0: {0: 101, 1: "Live"}, 1: {10: 1001}}}),
            wup("getUserProfile", {0: {0: {0: 102, 1: "Offline"}, 1: {10: 1002}}}),
            wup("getUserProfile", {0: {0: {0: 103, 1: "User"}, 1: {10: 0}}}),
        ])
        rooms = provider.follow_rooms(session, lambda: False)
        assert [r["room_id"] for r in rooms] == ["huya:1001", "huya:1002"]
        assert all(r["platform"] == "huya" and not r["live_known"] for r in rooms)
        assert session.post.call_count == 4
        request = session.post.call_args_list[0].kwargs["data"]
        envelope = tars_fields(request[4:])
        assert envelope[5] == "huyauserui" and envelope[6] == "getAllSubscribeToUidList"
        entries = tars_fields(envelope[7])[0]
        user = tars_fields(entries[1])[0][0]
        assert user[0] == 42 and user[4] == "fixture=valid"
        session.post = Mock(return_value=wup("getAllSubscribeToUidList", {1: []}))
        assert provider.follow_rooms(session, lambda: False) == []
        for response in [wup("getAllSubscribeToUidList", None, 905),
                         wup("getAllSubscribeToUidList", {}), reply(binary=b"bad packet")]:
            session.post = Mock(return_value=response)
            fails(lambda: provider.follow_rooms(session, lambda: False))
        session.post = Mock(side_effect=[wup("getAllSubscribeToUidList", {1: [101]}),
            wup("getUserProfile", {0: {0: {0: 999}, 1: {10: 1001}}})])
        fails(lambda: provider.follow_rooms(session, lambda: False))
        session.post = Mock(return_value=wup("getAllSubscribeToUidList", {1: [101]}))
        assert provider.follow_rooms(session, Mock(side_effect=[False, False, True])) == []
        assert session.post.call_count == 1


def check_douyin():
    provider = DouyinPlatform()
    provider.account_info = Mock(return_value={"uid": "42", "sec_uid": "fixture-sec"})
    live = {"uid": "101", "nickname": "Live", "room_data": json.dumps({
        "status": 2, "title": "Test", "owner": {"web_rid": "1001"}}),
        "avatar_medium": {"url_list": ["https://p3.douyinpic.com/a.png"]}}
    offline = {"uid": "102", "nickname": "Offline"}
    ordinary = {"uid": "103", "nickname": "User"}
    with requests.Session() as session:
        session.get = Mock(side_effect=[
            reply({"status_code": 0, "followings": [live, offline, ordinary], "has_more": 1,
                   "offset": 3, "min_time": 100, "max_time": 0}),
            reply({"status_code": 0, "data": {"id_str": "102", "web_rid": "1002"}}),
            reply({"status_code": 0, "data": {"id_str": "103", "web_rid": ""}}),
            reply({"status_code": 0, "followings": [live], "has_more": 0}),
        ])
        rooms = provider.follow_rooms(session, lambda: False)
        assert [r["room_id"] for r in rooms] == ["douyin:1001", "douyin:1002"]
        assert rooms[0]["live"] and rooms[0]["face"].endswith("/a.png")
        assert not rooms[1]["live_known"]
        assert session.get.call_args.kwargs["params"]["min_time"] == 100
        assert session.get.call_args.kwargs["params"]["sec_user_id"] == "fixture-sec"
        for payload in [
            {"status_code": 20003}, {"status_code": 0, "followings": []},
            {"status_code": 0, "followings": [], "has_more": 1, "offset": 0, "min_time": 0, "max_time": 0},
        ]:
            session.get = Mock(return_value=reply(payload))
            fails(lambda: provider.follow_rooms(session, lambda: False))
        session.get = Mock(return_value=reply({"status_code": 0, "followings": [], "has_more": 0}))
        assert provider.follow_rooms(session, lambda: False) == []
        session.get = Mock(return_value=reply({"status_code": 8}))
        try:
            provider.follow_rooms(session, lambda: False)
        except RuntimeError as error:
            assert "状态 8" in str(error) and "验证" in str(error)
        else:
            raise AssertionError("Unauthorized follow request accepted")
        session.get = Mock(side_effect=AssertionError("Cancelled request"))
        assert provider.follow_rooms(session, lambda: True) == []


def check_browser(app):
    provider = DouyinPlatform()
    payload = {"status_code": 0, "user": {"uid": "42", "sec_uid": "fixture-sec", "nickname": "Fixture"}}
    dialog = PlatformFollowDialog(provider, login_only=True, defer_login=True)
    assert dialog.browser.page().settings().unknownUrlSchemePolicy() == QWebEngineSettings.DisallowUnknownUrlSchemes
    loaded = []
    dialog.browser.loadFinished.connect(loaded.append)
    def official_client(action):
        return """<script>
            window.XMLHttpRequest = class { open() { throw new Error('Unsigned XHR'); } };
            setTimeout(() => {
                const values = {
                    101: {COMMON_SEARCH_PARAMS: {channel: 'channel_pc_web'}},
                    202: {U2: async (path, params, options) => {
                        window.fixtureStarted = true;
                        window.fixtureQuery = {path, params, options};
                        (window.fixtureQueries ||= []).push(path);
                        %s
                    }}
                };
                const require = id => values[id];
                require.m = {
                    101: function() { /* CHANNEL_PC_WEB:function COMMON_SEARCH_PARAMS:function */ },
                    202: function() { /* skipCheckCode securitySdkInitWeb withCredentials */ }
                };
                window.webpackChunkdouyin_web = {push: chunk => chunk[2](require)};
            }, 150);
        </script>""" % action
    html = official_client("return " + json.dumps(payload) + ";")
    dialog.browser.setHtml(html, QUrl("https://www.douyin.com/user/self"))
    wait_for(app, lambda: bool(loaded))
    assert loaded[-1]
    with patch.object(requests.Session, "get", side_effect=AssertionError("Signed request left browser")):
        dialog._read()
        wait_for(app, lambda: dialog._worker is None)
    assert not dialog.rooms
    assert dialog.account["uid"] == "42"
    query = []
    dialog.browser.page().runJavaScript("JSON.stringify(window.fixtureQuery)", query.append)
    wait_for(app, lambda: bool(query))
    captured = json.loads(query[0])
    assert captured["path"] == "/aweme/v1/web/user/profile/self/"
    assert captured["params"]["channel"] == "channel_pc_web"
    assert captured["options"]["timeout"] == 12000
    dispose(app, dialog)

    dialog = PlatformFollowDialog(provider, login_only=True, defer_login=True)
    loaded, started, failures = [], [], []
    dialog.browser.loadFinished.connect(loaded.append)
    dialog.readFailed.connect(failures.append)
    dialog.browser.setHtml(official_client("return new Promise(() => {});"), QUrl("https://www.douyin.com/user/self"))
    wait_for(app, lambda: bool(loaded))
    assert loaded[-1]
    with patch.object(requests.Session, "get", side_effect=AssertionError("Cancelled request left browser")):
        dialog._read()
        def request_started():
            dialog.browser.page().runJavaScript("window.fixtureStarted === true", started.append)
            return any(started)
        wait_for(app, request_started)
        dialog.reject()
        wait_for(app, lambda: dialog._worker is None)
    assert not dialog.rooms and not failures
    dispose(app, dialog)

    dialog = PlatformFollowDialog(provider, login_only=True, defer_login=True)
    loaded, failures = [], []
    dialog.browser.loadFinished.connect(loaded.append)
    dialog.readFailed.connect(failures.append)
    dialog.browser.setHtml(official_client("throw new Error('Verification required');"), QUrl("https://www.douyin.com/user/self"))
    wait_for(app, lambda: bool(loaded))
    with patch.object(requests.Session, "get", side_effect=AssertionError("Failed request left browser")):
        dialog._read()
        wait_for(app, lambda: dialog._worker is None)
    assert not dialog.rooms and len(failures) == 1 and "验证" in failures[0]
    dispose(app, dialog)


if __name__ == "__main__":
    check_huya()
    check_douyin()
    QApplication.setAttribute(Qt.AA_ShareOpenGLContexts)
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    check_browser(app)
    print("PASS: Huya WUP/all follows/profile IDs, Douyin live/offline pagination, dedup/expiry/cancel and WebEngine signed-request bridge")
