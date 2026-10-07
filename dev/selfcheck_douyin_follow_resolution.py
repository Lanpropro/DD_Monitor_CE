"""官网关注资料优先使用；补充直播记录为空或超时不能吞掉有效房间。"""
import json
from pathlib import Path
import sys
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import requests
from plugins_user.domestic_live.plugin import DouyinPlatform


def response(users):
    result = requests.Response()
    result.status_code = 200
    result._content = json.dumps({'status_code': 0, 'followings': users, 'has_more': 0}).encode()
    return result


def read(provider, users, cancelled=lambda: False):
    session = Mock()
    session.get.return_value = response(users)
    with patch.object(provider, 'account_info', return_value={'uid': '42'}):
        return provider.follow_rooms(session, cancelled)


def main():
    provider = DouyinPlatform()
    users = [{'uid': '101', 'nickname': 'Live', 'room_data': json.dumps({
                 'status': 2, 'title': 'Live title', 'owner': {'web_rid': '1001', 'id_str': '101'}})},
             {'uid': '102', 'nickname': 'Offline', 'web_rid': '1002', 'room_data': {'status': 4}}]
    with patch.object(provider, '_share_room', side_effect=AssertionError('Unnecessary room lookup')):
        rooms = read(provider, users)
    assert [room['room_id'] for room in rooms] == ['douyin:1001', 'douyin:1002']
    assert rooms[0]['live'] and not rooms[1]['live'] and all(room['live_known'] for room in rooms)
    assert rooms[0]['title'] == 'Live title' and rooms[0]['anchor_uid'] == '101'
    assert provider._anchor_uids == {'douyin:1001': '101', 'douyin:1002': '102'}

    # 原实现会用空补充响应覆盖 web_rid，错误地返回空关注列表。
    known = [{'uid': '101', 'nickname': 'Known room', 'web_rid': '1001'}]
    for outcome in ({}, requests.Timeout('Fixture timeout')):
        with patch.object(provider, '_share_room', **({'side_effect': outcome} if isinstance(outcome, Exception)
                                                     else {'return_value': outcome})):
            rooms = read(provider, known)
        assert len(rooms) == 1 and rooms[0]['room_id'] == 'douyin:1001'
        assert not rooms[0]['live_known']  # 缺少状态不能猜测主播下播。
    with patch.object(provider, '_share_room', return_value={'status': 4, 'owner': {'web_rid': '1001'}}):
        rooms = read(provider, known)
    assert rooms[0]['live_known'] and not rooms[0]['live']

    # 缺少房间号时仍查询最近直播记录，保留未开播主播；普通账号没有记录则跳过。
    with patch.object(provider, '_share_room', side_effect=[
            {'status': 4, 'owner': {'web_rid': '1001'}}, {}]) as lookup:
        rooms = read(provider, [{'uid': '101'}, {'uid': '103'}])
    assert len(rooms) == 1 and not rooms[0]['live'] and lookup.call_count == 2
    with patch.object(provider, '_share_room', side_effect=requests.Timeout('Fixture timeout')):
        try:
            read(provider, [{'uid': '103'}])
        except requests.Timeout:
            pass
        else:
            raise AssertionError('Unresolved failure became an empty success')
    with patch.object(provider, '_share_room', return_value={'status': 2, 'owner': {'web_rid': '9999'}}):
        try:
            read(provider, known)
        except RuntimeError:
            pass
        else:
            raise AssertionError('Mismatched room replaced website room')
    with patch.object(provider, '_share_room', side_effect=AssertionError('Should be cancelled')):
        assert read(provider, known, lambda: True) == []
    print('PASS: website metadata; no redundant lookup; empty/timeout retains known room; offline fallback; unknown state; mismatch/cancel')


if __name__ == '__main__':
    main()
