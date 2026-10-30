import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

const appUserAgent =
    'Mozilla/5.0 BiliDroid/6.25.0 (bbcallen@gmail.com) os/android model/MuMu '
    'mobi_app/android build/6250300 channel/bili innerVer/6250300 osVer/6.0.1 network/2';
const apiHeaders = {
  'User-Agent':
      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
  'Referer': 'https://live.bilibili.com/',
};

class LiveLookupException implements Exception {
  const LiveLookupException(this.message);
  final String message;
  @override
  String toString() => message;
}

class LiveStream {
  const LiveStream({
    required this.roomId,
    required this.urls,
    required this.quality,
    required this.protocol,
  });
  final String roomId;
  final List<Uri> urls;
  final int quality;
  final String protocol;
  Map<String, String> get headers => const {'User-Agent': appUserAgent};
}

class RoomInfo {
  const RoomInfo({
    required this.roomId,
    required this.name,
    this.title = '',
    this.cover = '',
    this.live,
  });
  final String roomId;
  final String name;
  final String title;
  final String cover;
  final bool? live;

  Map<String, dynamic> toJson() => {
    'roomId': roomId,
    'name': name,
    'title': title,
    'cover': cover,
  };

  factory RoomInfo.fromJson(Map<String, dynamic> json) => RoomInfo(
    roomId: validateRoomId('${json['roomId']}'),
    name: json['name'] as String,
    title: json['title'] as String? ?? '',
    cover: json['cover'] as String? ?? '',
  );
}

String validateRoomId(String value) {
  final room = value.trim();
  if (!RegExp(r'^[0-9]{1,12}$').hasMatch(room) || int.parse(room) == 0) {
    throw const LiveLookupException('请输入有效的 B 站直播间数字房间号');
  }
  return int.parse(room).toString();
}

// Keep the app-room protocol and CDN header distinction used by ddm/bili.py.
// Native codecs and Python/Qt imports never enter this shared provider.
class BilibiliProvider {
  BilibiliProvider({http.Client? client, this.allowFlv = true})
    : _client = client ?? http.Client();
  final http.Client _client;
  final bool allowFlv;

  Future<RoomInfo> roomInfo(String value) async {
    final room = await _get('/room/v1/Room/room_init', {
      'id': validateRoomId(value),
    });
    final id = validateRoomId('${room['room_id']}');
    // Same cover source and live keyframe preference as ddm/bili.py room_info.
    final data = await _get('/xlive/web-room/v1/index/getRoomBaseInfo', {
      'req_biz': 'web_room_componet',
      'room_ids': id,
    });
    final info = data['by_room_ids']?[id] as Map<String, dynamic>?;
    if (info == null) throw const LiveLookupException('暂时无法获取主播信息，请重试');
    final live = info['live_status'] == 1;
    final keyframe = '${info['keyframe'] ?? ''}';
    return RoomInfo(
      roomId: id,
      name: '${info['uname'] ?? '房间 $id'}',
      title: '${info['title'] ?? ''}',
      live: live,
      cover: live && keyframe.isNotEmpty ? keyframe : '${info['cover'] ?? ''}',
    );
  }

  Future<Map<String, dynamic>> _get(
    String path,
    Map<String, String> query,
  ) async {
    final response = await _client
        .get(
          Uri.https('api.live.bilibili.com', path, query),
          headers: apiHeaders,
        )
        .timeout(const Duration(seconds: 12));
    if (response.statusCode != 200) {
      throw const LiveLookupException('直播接口连接失败，请稍后重试');
    }
    final payload = jsonDecode(response.body) as Map<String, dynamic>;
    if (payload['code'] != 0) {
      throw LiveLookupException('B 站接口暂不可用（${payload['code']}）');
    }
    return (payload['data'] as Map<String, dynamic>?) ?? {};
  }

  Future<LiveStream> resolve(String value) async {
    final roomId = validateRoomId(value);
    try {
      final room = await _get('/room/v1/Room/room_init', {'id': roomId});
      if (room['live_status'] != 1) {
        throw const LiveLookupException('该直播间尚未开播');
      }
      final realId = validateRoomId('${room['room_id']}');
      final data = await _get('/xlive/app-room/v2/index/getRoomPlayInfo', {
        'appkey': 'iVGUTjsxvpLeuDCf',
        'build': '6250300',
        'c_locale': 'zh_CN',
        'channel': 'bili',
        'codec': '0',
        'device': 'android',
        'device_name': 'MuMu',
        'dolby': '1',
        'format': '0,2',
        'free_type': '0',
        'http': '1',
        'mask': '0',
        'mobi_app': 'android',
        'network': 'wifi',
        'no_playurl': '0',
        'only_audio': '0',
        'only_video': '0',
        'platform': 'android',
        'play_type': '0',
        'protocol': '0,1',
        'qn': '250',
        'room_id': realId,
        's_locale': 'zh_CN',
        'statistics': '{"appId":1,"platform":3,"version":"6.25.0","abtest":""}',
        'ts': '${DateTime.now().millisecondsSinceEpoch ~/ 1000}',
      });
      final play =
          (data['playurl_info']?['playurl'] as Map<String, dynamic>?) ?? {};
      return selectStream(play, realId, allowFlv: allowFlv);
    } on LiveLookupException {
      rethrow;
    } on TimeoutException {
      throw const LiveLookupException('连接超时，请重试');
    } on http.ClientException {
      throw const LiveLookupException('网络连接失败，请检查网络后重试');
    } on FormatException {
      throw const LiveLookupException('直播接口返回了无法识别的数据，请重试');
    }
  }

  void close() => _client.close();
}

LiveStream selectStream(
  Map<String, dynamic> play,
  String roomId, {
  bool allowFlv = true,
}) {
  for (final protocol in ['http_hls', if (allowFlv) 'http_stream']) {
    for (final stream in (play['stream'] as List?) ?? []) {
      if (stream['protocol_name'] != protocol) continue;
      for (final format in (stream['format'] as List?) ?? []) {
        for (final codec in (format['codec'] as List?) ?? []) {
          if (codec['codec_name'] != 'avc') continue;
          final urls = <Uri>{};
          for (final info in (codec['url_info'] as List?) ?? []) {
            if (info['host'] == null || codec['base_url'] == null) continue;
            final uri = Uri.tryParse(
              '${info['host']}${codec['base_url']}${info['extra'] ?? ''}',
            );
            if (uri != null &&
                ['http', 'https'].contains(uri.scheme) &&
                uri.host.isNotEmpty) {
              urls.add(uri);
            }
          }
          if (urls.isNotEmpty) {
            return LiveStream(
              roomId: roomId,
              urls: List.unmodifiable(urls),
              quality: int.tryParse('${codec['current_qn'] ?? 0}') ?? 0,
              protocol: protocol,
            );
          }
        }
      }
    }
  }
  throw const LiveLookupException('该直播间暂未提供可播放的 H.264 直播流');
}
