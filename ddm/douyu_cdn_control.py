"""Explicit, per-room CDN control for diagnostic comparisons; no credentials in the file."""
import json
from pathlib import Path
import re
import time
from urllib.parse import urlsplit


def install(platform, path, emit):
    original = platform._request_source
    path = Path(path)

    def fetch(parser, raw, cdn, rate):
        data = original(parser, raw, cdn, rate=rate)
        room = 'douyu:' + str(raw)
        now = time.monotonic()
        with platform._cdn_lock:
            failures = {key: round(now - stamp, 3)
                        for key, stamp in platform._failed_cdns.get(room, {}).items()
                        if now - stamp < 60}
        emit('source.cdn-result', room=room, requested_cdn=cdn,
             requested_rate=rate, actual_cdn=data.get('rtmp_cdn', ''),
             actual_rate=data.get('rate'),
             host=urlsplit(data.get('rtmp_url', '')).hostname,
             available_cdns=[item.get('cdn') for item in data.get('cdnsWithName', [])],
             failed_age_seconds=failures)
        return data

    def request(parser, raw, cdn='', *, rate=0):
        try:
            with path.open(encoding='utf-8-sig') as stream:
                text = stream.read(1025)
        except FileNotFoundError:
            return fetch(parser, raw, cdn, rate)
        if len(text) > 1024:
            raise RuntimeError('斗鱼诊断线路控制文件过大')
        try:
            control = json.loads(text)
            room = str(control.get('room') or '').removeprefix('douyu:')
            selected = str(control.get('cdn') or '')
        except (ValueError, AttributeError) as error:
            raise RuntimeError('斗鱼诊断线路控制文件格式无效') from error
        if not selected or room != str(raw):
            return fetch(parser, raw, cdn, rate)
        if not re.fullmatch(r'[0-9]{1,20}', room) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', selected):
            raise RuntimeError('斗鱼诊断房间或线路编号无效')
        data = fetch(parser, raw, selected, rate)
        available = [item.get('cdn') for item in data.get('cdnsWithName', [])]
        emit('source.cdn-control', room='douyu:' + room, requested_cdn=selected,
             requested_rate=rate, actual_rate=data.get('rate'),
             host=urlsplit(data.get('rtmp_url', '')).hostname, available_cdns=available)
        if selected not in available:
            raise RuntimeError('斗鱼接口未提供指定诊断线路，请清空 cdn 恢复自动选择')
        return data

    platform._request_source = request

    original_failure = platform.report_playback_failure

    def report_failure(room_id, url, reason):
        result = original_failure(room_id, url, reason)
        room = platform.normalize(room_id)
        host = urlsplit(url).hostname or ''
        with platform._cdn_lock:
            mapped = platform._source_cdns.get(room, {}).get(host, '')
            failed = list(platform._failed_cdns.get(room, {}))
        mapped_cdns = [mapped] if isinstance(mapped, str) and mapped else list(mapped)
        emit('source.cdn-failure', room=room, host=host, reason=reason,
             mapped_cdn=mapped_cdns[0] if mapped_cdns else '',
             mapped_cdns=mapped_cdns, failed_keys=failed)
        return result

    platform.report_playback_failure = report_failure
