import 'dart:async';

import 'package:ddmonitor/platforms/bilibili.dart';
import 'package:ddmonitor/watch_session.dart';
import 'package:flutter_test/flutter_test.dart';

class PendingProvider extends BilibiliProvider {
  final result = Completer<LiveStream>();
  bool closed = false;
  @override
  Future<LiveStream> resolve(String value) => result.future;
  @override
  void close() {
    closed = true;
    super.close();
  }
}

void main() {
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
