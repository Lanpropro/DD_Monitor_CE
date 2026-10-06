"""关注身份恢复后，直播验证页不再阻断元数据、取流；内场 ID 每次更新。"""
import json
import asyncio
from copy import deepcopy
from pathlib import Path
import sys
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import requests
from streamlink import Streamlink
from plugins_user.domestic_live import plugin as module


def response(body):
    result = requests.Response()
    result.status_code = 200
    result.encoding = 'utf-8'
    result._content = (json.dumps(body) if isinstance(body, dict) else body).encode()
    return result


def main():
    provider = module.DouyinPlatform()
    provider.restore_follow_rooms([{'room_id': 'douyin:123', 'anchor_uid': '101'},
                                   {'room_id': 'douyin:bad', 'anchor_uid': 'invalid'}])
    assert provider._anchor_uids == {'douyin:123': '101'}
    internal, status, target = ['901'], [2], ['123']
    def public_get(url, **kwargs):
        assert 'cookies' not in kwargs, 'Account cookies leaked to public room resolver'
        if url.endswith('/info_by_user/'):
            assert kwargs['params']['user_id'] == '101'
            return response({'status_code': 0, 'data': {'id_str': internal[0], 'owner_user_id': 101}})
        assert url == 'https://webcast.amemv.com/webcast/reflow/' + internal[0]
        room = {'idStr': internal[0], 'status': status[0], 'title': 'Actual title',
                'owner': {'idStr': '101', 'webRid': target[0], 'nickname': 'Actual name',
                          'avatarThumb': {'urlList': ['https://p3.douyinpic.com/face.png']}},
                'cover': {'urlList': ['https://p3.douyinpic.com/cover.png']},
                'streamUrl': {'hlsPullUrlMap': {'FULL_HD1': 'https://cdn.test/live.m3u8'}}}
        chunk = '5:' + json.dumps(['$', '$L7', None, {'data': {'room': room}}])
        result = response('<script>self.__rsc_f.push([1,' + json.dumps(chunk) + '])</script>')
        result.cookies.set('ttwid', 'fixture-visitor')
        return result
    with patch.object(module.requests, 'get', side_effect=public_get) as get:
        info = provider.room_info('douyin:123').as_dict()
        assert info['live'] and info['title'] == 'Actual title' and info['uname'] == 'Actual name'
        assert info['anchor_uid'] == '101' and info['face'].endswith('/face.png')
        assert 'ttwid' not in info and 'stream_url' not in info
        assert provider.room_data('douyin:123')['ttwid'] == 'fixture-visitor'
        internal[0] = '902'
        assert provider.room_data('douyin:123')['room']['id_str'] == '902'
        # 普通媒体入口只探测媒体，绝不能再次获取带验证页的直播网页。
        session = Streamlink()
        manifest = Mock(url='https://cdn.test/live.m3u8')
        manifest.__enter__ = Mock(return_value=manifest)
        manifest.__exit__ = Mock(return_value=False)
        manifest.iter_content.return_value = iter([b'#EXTM3U'])
        with patch.object(module, 'Streamlink', return_value=session), patch.object(session.http, 'get',
                return_value=manifest) as media_get:
            result = provider.play_url('douyin:123')
            assert result[:3] == ('https://cdn.test/live.m3u8', 10000, 'douyin')
            assert media_get.call_args.args == ('https://cdn.test/live.m3u8',)
        status[0] = 4
        assert not provider.room_info('douyin:123').live
        target[0] = '999'
        try:
            provider.room_data('douyin:123')
        except ValueError:
            pass
        else:
            raise AssertionError('Different anchor room accepted')
        assert all('/live.douyin.com/123' not in call.args[0] for call in get.call_args_list)
    # 主页已提供固定房间号而历史记录为空时，同步取流和异步弹幕均可回退到官方直播页。
    page_info = {'room': {'id_str': '903', 'status': 2, 'owner': {'id_str': '101'}}}
    with patch.object(provider, '_share_room', return_value={}), patch.object(module.requests, 'get',
            return_value=response('fixture-page')) as get, patch.object(provider, '_page_info',
            side_effect=lambda _page: deepcopy(page_info)):
        assert provider.room_data('douyin:123')['room']['id_str'] == '903'
        assert get.call_args.args[0] == 'https://live.douyin.com/123'
        page_info['room']['owner']['id_str'] = '202'
        try:
            provider.room_data('douyin:123')
        except ValueError:
            pass
        else:
            raise AssertionError('Different fallback anchor accepted')
    async def fallback():
        recorded = []
        def get(url, **kwargs):
            recorded.append(url)
            item = Mock(cookies={})
            item.json = AsyncMock(return_value={'status_code': 0, 'data': {}})
            item.text = AsyncMock(return_value='fixture-page')
            context = AsyncMock()
            context.__aenter__.return_value = item
            return context
        session = Mock(get=get)
        with patch.object(provider, '_page_info', side_effect=lambda _page: deepcopy(page_info)):
            page_info['room']['owner']['id_str'] = '101'
            assert (await provider.room_data_async(session, 'douyin:123'))['room']['id_str'] == '903'
            assert recorded == ['https://live.douyin.com/webcast/room/info_by_user/', 'https://live.douyin.com/123']
            page_info['room']['owner']['id_str'] = '202'
            try:
                await provider.room_data_async(session, 'douyin:123')
            except ValueError:
                pass
            else:
                raise AssertionError('Different async fallback anchor accepted')
    asyncio.run(fallback())
    print('PASS: restored identity bypasses captcha; current internal ID; visitor cookie; normal HLS entry; offline/mismatch; no credential/media persistence')


if __name__ == '__main__':
    main()
