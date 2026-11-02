"""Offline CDN decision metadata and override; no real playback stability conclusion."""
import os
from pathlib import Path
import sys
import tempfile
import json
import threading
from types import SimpleNamespace
from unittest.mock import patch

os.environ['DDM_NO_SAVE'] = '1'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ddm import plugins
from ddm.douyu_cdn_control import install


def main():
    manager = plugins.PluginManager(enabled=['domestic_live'])
    manager.load()
    platform = manager.platforms['douyu']
    module = sys.modules[type(platform).__module__]
    calls, records = [], []
    def request(parser, raw, cdn='', *, rate=0):
        calls.append((cdn, rate))
        return {'rtmp_url': 'https://stream.test.edgesrv.com',
                'rtmp_live': f'rate-{rate}.flv?token=must-not-log', 'rtmp_cdn': 'scdncttbej',
                'unused_private': 'must-not-log',
                'rate': rate, 'cdnsWithName': [{'cdn': 'scdncttbej'}, {'cdn': 'hw-h5'}],
                'multirates': [{'rate': 0, 'bit': 16000, 'name': '原画1080P60'},
                              {'rate': 15, 'bit': 15000, 'name': '2K超高清'},
                              {'rate': 4, 'bit': 4000, 'name': '蓝光4M'}]}
    session = module.Streamlink()
    try:
        with tempfile.TemporaryDirectory() as root, \
                patch.object(platform, 'room_info', return_value=plugins.RoomInfo('douyu:123', live=True)), \
                patch.object(platform, '_request_source', side_effect=request):
            path = Path(root) / 'control.json'
            path.write_text(json.dumps({'room': 'douyu:123', 'cdn': 'scdncttbej'}), encoding='utf-8')
            install(platform, path, lambda stage, **v: records.append(dict(stage=stage, **v)))
            path.unlink()
            platform._streams(session, 'douyu:123', 10000)
            automatic = [r for r in records if r['stage'] == 'source.cdn-result']
            assert [r['requested_cdn'] for r in automatic] == ['', 'hw-h5']
            assert automatic[-1]['actual_cdn'] == 'scdncttbej'
            assert automatic[-1]['available_cdns'] == ['scdncttbej', 'hw-h5']
            path.write_text(json.dumps({'room': 'douyu:123', 'cdn': 'scdncttbej'}), encoding='utf-8')
            for qn, rate in ((10000, 0), (2000015, 15)):
                calls.clear()
                stream = platform._streams(session, 'douyu:123', qn)['source']
                assert len(calls) == 2 and all(cdn == 'scdncttbej' for cdn, _ in calls)
                assert calls[-1][1] == rate and stream.ddm_quality == qn
                assert f'/rate-{rate}.flv?' in stream.to_url()
            path.write_text(json.dumps({'room': 'douyu:123', 'cdn': ''}), encoding='utf-8')
            calls.clear()
            platform._streams(session, 'douyu:123', 10000)
            assert calls[-1] == ('hw-h5', 0), 'Clearing the control must restore normal CDN policy'
            platform.report_playback_failure('douyu:123', stream.to_url(), 'LIVE_EOF')
            failure = records[-1]
            assert failure['stage'] == 'source.cdn-failure'
            assert failure['host'] == 'stream.test.edgesrv.com'
            assert failure['mapped_cdn'] == 'scdncttbej', 'Actual returned CDN is the primary failure mapping'
            assert failure['mapped_cdns'] == ['scdncttbej', 'hw-h5']
            assert set(failure['failed_keys']) == {'scdncttbej', 'hw-h5', 'stream.test.edgesrv.com'}
            calls.clear()
            platform._streams(session, 'douyu:123', 2000015)
            assert calls[-1] == ('scdncttbej', 15), 'Sampling must preserve failover and native quality'
            result = records[-1]
            assert result['requested_cdn'] == result['actual_cdn'] == 'scdncttbej'
            assert 'hw-h5' in result['failed_age_seconds']
            assert all(0 <= age < 60 for age in result['failed_age_seconds'].values())
            assert 'must-not-log' not in json.dumps(records), 'No signed path or response body in metadata'
            legacy = SimpleNamespace(_request_source=request, normalize=lambda room: room,
                report_playback_failure=lambda *args: None, _cdn_lock=threading.Lock(),
                _source_cdns={'douyu:123': {'legacy.test': 'hw-h5'}}, _failed_cdns={})
            install(legacy, path, lambda stage, **v: records.append(dict(stage=stage, **v)))
            legacy.report_playback_failure('douyu:123', 'https://legacy.test/live?token=must-not-log', 'STALL')
            assert records[-1]['mapped_cdn'] == 'hw-h5' and records[-1]['mapped_cdns'] == ['hw-h5']
            assert 'must-not-log' not in json.dumps(records)
    finally:
        session.http.close()
        manager.unload()
    print('PASS: automatic/override CDN requests, actual CDN, failure mapping and ages; no signed paths; quality unchanged')


if __name__ == '__main__':
    main()
