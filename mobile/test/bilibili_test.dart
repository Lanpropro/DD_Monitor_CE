import 'dart:convert';

import 'package:ddmonitor/platforms/bilibili.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

Map<String, dynamic> source(String protocol, {String codec = 'avc'}) => {
  'protocol_name': protocol,
  'format': [
    {
      'codec': [
        {
          'codec_name': codec,
          'current_qn': 150,
          'base_url': '/live.m3u8',
          'url_info': [
            {'host': 'https://cdn.example.com', 'extra': '?token=test'},
            {'host': 'https://cdn.example.com', 'extra': '?token=test'},
            {'host': 'https://backup.example.com', 'extra': '?token=test'},
          ],
        },
      ],
    },
  ],
};
http.Response payload(Map<String, dynamic> data) =>
    http.Response(jsonEncode({'code': 0, 'data': data}), 200);

void main() {
  test('Room ID validation normalizes short IDs', () {
    expect(validateRoomId(' 006 '), '6');
    for (final invalid in [
      '',
      '0',
      '-1',
      'https://live.bilibili.com/6',
      '1234567890123',
    ]) {
      expect(
        () => validateRoomId(invalid),
        throwsA(isA<LiveLookupException>()),
      );
    }
  });
  test('HLS AVC is preferred, actual quality retained, CDNs deduplicated', () {
    final stream = selectStream({
      'stream': [source('http_stream'), source('http_hls')],
    }, '6');
    expect(stream.protocol, 'http_hls');
    expect(stream.quality, 150);
    expect(stream.urls.length, 2);
    expect(
      stream.urls.first.toString(),
      'https://cdn.example.com/live.m3u8?token=test',
    );
    expect(stream.headers, {'User-Agent': appUserAgent});
  });
  test('Android allows FLV fallback and iOS refuses FLV', () {
    final play = {
      'stream': [source('http_stream')],
    };
    expect(selectStream(play, '6').protocol, 'http_stream');
    expect(
      () => selectStream(play, '6', allowFlv: false),
      throwsA(isA<LiveLookupException>()),
    );
  });
  test('HEVC-only and empty stream responses fail clearly', () {
    for (final play in <Map<String, dynamic>>[
      {},
      {
        'stream': [source('http_hls', codec: 'hevc')],
      },
    ]) {
      expect(
        () => selectStream(play, '6'),
        throwsA(isA<LiveLookupException>()),
      );
    }
  });
  test(
    'Short room conversion and app-room protocol use anonymous requests',
    () async {
      var calls = 0;
      final provider = BilibiliProvider(
        client: MockClient((request) async {
          calls++;
          expect(request.headers.containsKey('cookie'), isFalse);
          if (request.url.path.endsWith('room_init')) {
            expect(request.url.queryParameters['id'], '6');
            return payload({'room_id': 7734200, 'live_status': 1});
          }
          expect(request.url.queryParameters['room_id'], '7734200');
          expect(request.url.queryParameters['qn'], '250');
          expect(request.url.queryParameters['codec'], '0');
          return payload({
            'playurl_info': {
              'playurl': {
                'stream': [source('http_hls')],
              },
            },
          });
        }),
      );
      addTearDown(provider.close);
      expect((await provider.resolve('6')).roomId, '7734200');
      expect(calls, 2);
    },
  );
  test('Offline room stops before requesting a stream', () async {
    var calls = 0;
    final provider = BilibiliProvider(
      client: MockClient((_) async {
        calls++;
        return payload({'room_id': 6, 'live_status': 0});
      }),
    );
    addTearDown(provider.close);
    await expectLater(
      provider.resolve('6'),
      throwsA(isA<LiveLookupException>()),
    );
    expect(calls, 1);
  });
  test('Invalid ID never sends HTTP', () async {
    final provider = BilibiliProvider(
      client: MockClient((_) async => fail('unexpected network')),
    );
    addTearDown(provider.close);
    await expectLater(
      provider.resolve('invalid'),
      throwsA(isA<LiveLookupException>()),
    );
  });
  test('Network, HTTP, API and malformed JSON become lookup errors', () async {
    for (final client in [
      MockClient((_) async => throw http.ClientException('offline')),
      MockClient((_) async => http.Response('error', 503)),
      MockClient((_) async => http.Response('{"code":-400}', 200)),
      MockClient((_) async => http.Response('invalid json', 200)),
    ]) {
      final provider = BilibiliProvider(client: client);
      await expectLater(
        provider.resolve('6'),
        throwsA(isA<LiveLookupException>()),
      );
      provider.close();
    }
  });
}
