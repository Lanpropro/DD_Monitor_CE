"""抖音 FLV 失败时同画质 HLS 回退，以及原画/预览、HLS-only 和失败清理。"""
import json
from pathlib import Path
import sys
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import requests
from streamlink import Streamlink
from streamlink.exceptions import PluginError
from plugins_user.domestic_live import plugin as module


def reply(*, text='', body=b'FLV', url='https://cdn.test/live.flv'):
    response = Mock(text=text, url=url)
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.iter_content.side_effect = lambda size: iter([body[:size]])
    return response


def page(flv=True, hls=True, status=2):
    urls = {'flv_pull_url': {key: 'http://cdn.test/' + key + '.flv' for key in ('FULL_HD1', 'HD1', 'SD1')}
            if flv else {}, 'hls_pull_url_map': {key: 'http://cdn.test/' + key + '.m3u8'
            for key in ('FULL_HD1', 'HD1', 'SD1')} if hls else {}}
    room = {'status': status, 'id_str': 'fixture-room', 'stream_url': urls}
    state = {'state': {'roomStore': {'roomInfo': {'room': room}}, 'streamStore': {}}}
    return '<script>self.__pace_f.push([1,' + json.dumps('a:' + json.dumps([state])) + '])</script>'


def main():
    provider = module.DouyinPlatform()
    room_id = 'douyin:123'
    for failure in (PluginError('Fixture FLV 403'), requests.Timeout('Fixture timeout'),
                    reply(body=b'<html>')):
        session = Streamlink({'http-timeout': 1})
        manifest = reply(body=b'#EXTM3U\n', url='https://cdn.test/FULL_HD1.m3u8')
        with patch.object(module, 'Streamlink', return_value=session), patch.object(session.http, 'get',
                side_effect=[reply(text=page()), failure, manifest]) as get, patch.object(session.http, 'close') as close:
            result = provider.play_url(room_id)
            assert result[:3] == ('https://cdn.test/FULL_HD1.m3u8', 10000, 'douyin')
            assert [call.args[0] for call in get.call_args_list[1:]] == [
                'https://cdn.test/FULL_HD1.flv', 'https://cdn.test/FULL_HD1.m3u8']
            assert result[3]['Referer'] == 'https://live.douyin.com/'
            assert all(call.kwargs['stream'] for call in get.call_args_list[1:])
            close.assert_called_once()
        session.http.close()

    session = Streamlink({'http-timeout': 1})
    try:
        with patch.object(session.http, 'get', return_value=reply(text=page())):
            provider._streams(session, room_id)
            options = provider.room_quality_options(room_id)
            for option, key in zip(options, ('FULL_HD1', 'HD1', 'SD1')):
                streams = provider._streams(session, room_id, option['qn'])
                assert [stream.to_url() for stream in streams.values()] == [
                    'https://cdn.test/' + key + '.flv', 'https://cdn.test/' + key + '.m3u8']
                assert all(stream.ddm_quality == option['qn'] for stream in streams.values())
            preview = provider._streams(session, room_id, preview=True)
            assert all('SD1.' in stream.to_url() for stream in preview.values())
        for preview, quality, key, actual in ((True, 10000, 'SD1', options[-1]['qn']),
                                             (False, options[1]['qn'], 'HD1', options[1]['qn'])):
            url = 'https://cdn.test/' + key + '.m3u8'
            with patch.object(module, 'Streamlink', return_value=session), patch.object(session.http, 'get',
                    side_effect=[reply(text=page()), PluginError('Fixture FLV failed'),
                                 reply(body=b'#EXTM3U', url=url)]) as get:
                assert provider.play_url(room_id, quality, preview=preview)[:2] == (url, actual)
                assert get.call_args_list[1].args[0].endswith(key + '.flv')
        for flv, hls, body, extension in ((True, False, b'FLV', 'flv'), (False, True, b'#EXTM3U', 'm3u8')):
            url = 'https://cdn.test/FULL_HD1.' + extension
            with patch.object(module, 'Streamlink', return_value=session), patch.object(session.http, 'get',
                    side_effect=[reply(text=page(flv, hls)), reply(body=body, url=url)]) as get:
                assert provider.play_url(room_id)[:2] == (url, 10000)
                assert get.call_count == 2
        with patch.object(module, 'Streamlink', return_value=session), patch.object(session.http, 'get',
                side_effect=[reply(text=page()), PluginError('Fixture FLV failed'), reply(body=b'<html>')]):
            try:
                provider.play_url(room_id)
            except RuntimeError as error:
                assert '直播线路' in str(error)
            else:
                raise AssertionError('Invalid HLS response accepted')
        with patch.object(session.http, 'get', return_value=reply(text=page(status=4))):
            assert provider._streams(session, room_id) == {}
    finally:
        session.http.close()
    print('PASS: same-tier FLV to HLS fallback; source/preview quality; FLV-only/HLS-only; malformed/offline rejection; session cleanup')


if __name__ == '__main__':
    main()
