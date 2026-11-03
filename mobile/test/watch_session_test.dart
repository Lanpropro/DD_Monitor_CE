import 'dart:async';

import 'package:ddmonitor/platforms/bilibili.dart';
import 'package:ddmonitor/watch_session.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:video_player_platform_interface/video_player_platform_interface.dart';

import 'fake_video_platform.dart';

class QualityProvider extends BilibiliProvider {
  final requests = <int>[];
  bool fail = false;
  @override
  Future<LiveStream> resolve(String value, {int quality = 250}) async {
    requests.add(quality);
    if (fail) throw const LiveLookupException('test unavailable');
    return LiveStream(
      roomId: value,
      urls: [Uri.parse('https://example.com/live.m3u8')],
      quality: quality,
      protocol: 'http_hls',
      qualities: const [LiveQuality(250, '超清'), LiveQuality(150, '高清')],
    );
  }
}

class PendingProvider extends BilibiliProvider {
  final result = Completer<LiveStream>();
  bool closed = false;
  @override
  Future<LiveStream> resolve(String value, {int quality = 250}) =>
      result.future;
  @override
  void close() {
    closed = true;
    super.close();
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  test('Quality reconnect keeps pause and volume, including background resume and retry', () async {
    final oldPlatform = VideoPlayerPlatform.instance;
    final platform = FakeVideoPlatform();
    VideoPlayerPlatform.instance = platform;
    final provider = QualityProvider();
    final session = WatchSession(provider);
    try {
      await session.watch('6');
      final first = session.controller!;
      await session.setVolume(0);
      await session.togglePlayback();
      expect(first.value.isPlaying, isFalse);
      await session.changeQuality(150);
      expect(session.controller, isNot(same(first)));
      expect(session.stream!.quality, 150);
      expect(session.controller!.value.isPlaying, isFalse);
      expect(session.controller!.value.volume, 0);
      expect(platform.disposed.length, 1);
      await session.suspend();
      await session.resume();
      expect(provider.requests.last, 150);
      expect(session.controller!.value.isPlaying, isFalse);
      expect(session.controller!.value.volume, 0);
      provider.fail = true;
      await session.changeQuality(250);
      expect(session.error, isNotNull);
      provider.fail = false;
      await session.reconnect();
      expect(provider.requests.last, 250);
      expect(session.error, isNull);
      expect(session.controller!.value.isPlaying, isFalse);
      expect(session.controller!.value.volume, 0);
      await session.stop();
      final calls = provider.requests.length;
      await session.reconnect();
      expect(provider.requests.length, calls);
    } finally {
      await session.stop();
      session.dispose();
      VideoPlayerPlatform.instance = oldPlatform;
    }
  });
  test('Stopping during a lookup ignores its late result', () async {
    final provider = PendingProvider();
    final session = WatchSession(provider);
    final lookup = session.watch('6');
    await Future<void>.delayed(Duration.zero);
    expect(session.loading, isTrue);
    await session.stop();
    provider.result.complete(
      const LiveStream(
        roomId: '6',
        urls: [],
        quality: 150,
        protocol: 'http_hls',
      ),
    );
    await lookup;
    expect(session.stream, isNull);
    expect(session.controller, isNull);
    expect(session.loading, isFalse);
    session.dispose();
    expect(provider.closed, isTrue);
  });

  test('Disposed session ignores a late lookup failure', () async {
    final provider = PendingProvider();
    final session = WatchSession(provider);
    final lookup = session.watch('6');
    await Future<void>.delayed(Duration.zero);
    session.dispose();
    provider.result.completeError(const LiveLookupException('offline'));
    await expectLater(lookup, completes);
    expect(provider.closed, isTrue);
  });
}
