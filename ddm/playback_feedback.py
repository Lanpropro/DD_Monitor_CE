"""User-facing failure descriptions from observed playback evidence."""
import re


def failure_detail(*, reason='', source_failure='', transport_error=False, decoder_error=False):
    if re.fullmatch(r'HTTP_[45]\d\d', source_failure):
        return f'直播源请求失败（HTTP {source_failure[5:]}），可尝试刷新或更换线路'
    if source_failure == 'LIVE_EOF':
        return '直播源连接已结束，正在重新获取直播流'
    if transport_error:
        return '直播数据传输中断，请检查网络或稍后重试'
    if reason:
        network_errors = ('timeout', 'timed out', 'connectionerror', 'sslerror',
                          'proxyerror', 'nameresolutionerror', '域名解析', '连接超时',
                          '连接失败', '网络', '代理')
        if any(word in reason.lower() for word in network_errors):
            return '网络或直播源连接异常，请检查网络或稍后重试'
        return '未取得可播放的直播流，具体原因暂未确定'
    if decoder_error:
        return '检测到解码异常，可尝试调整本机解码方式'
    return '持续缓冲或画面停滞，具体原因暂未确定'
