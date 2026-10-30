import 'dart:async';

import 'package:ddmonitor/monitor_model.dart';
import 'package:ddmonitor/platforms/bilibili.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

const liveRoom = RoomInfo(roomId: '6', name: '星野', title: '测试直播标题', live: true);
const offlineRoom = RoomInfo(roomId: '7', name: '小北', live: false);

class TestProvider extends BilibiliProvider {
  final Map<String, Completer<LiveStream>> pending = {};
  bool failRefresh = false;
  @override
  Future<RoomInfo> roomInfo(String value) async {
    if (failRefresh) throw const LiveLookupException('offline');
    return value == '7' ? offlineRoom : liveRoom;
  }

  @override
  Future<LiveStream> resolve(String value) =>
      (pending[value] ??= Completer<LiveStream>()).future;
}

void main() {
  test(
    'Follow preferences survive restart and statuses are revalidated',
    () async {
      SharedPreferences.setMockInitialValues({});
      final prefs = await SharedPreferences.getInstance();
      final model = MonitorModel(catalog: TestProvider(), preferences: prefs);
      await model.addFollow('6');
      await model.addFollow('6');
      expect(model.follows.length, 1);
      await model.changeLayout(WallLayout.quad);
      await model.setTransparency(true);
      model.dispose();
      final restored = MonitorModel(
        catalog: TestProvider(),
        preferences: prefs,
      );
      expect(restored.follows.single.name, '星野');
      expect(restored.follows.single.live, isNull);
      expect(restored.layout, WallLayout.quad);
      expect(restored.reduceTransparency, isTrue);
      await restored.refreshFollows();
      expect(restored.follows.single.live, isTrue);
      await restored.removeFollow(restored.follows.single);
      restored.dispose();
      final empty = MonitorModel(preferences: prefs);
      expect(empty.follows, isEmpty);
      empty.dispose();
    },
  );
  test(
    'Failed refresh marks status unknown instead of showing stale live state',
    () async {
      final provider = TestProvider();
      final model = MonitorModel(catalog: provider);
      await model.addFollow('6');
      provider.failRefresh = true;
      await model.refreshFollows();
      expect(model.follows.single.live, isNull);
      expect(model.followError, isNotNull);
      model.dispose();
    },
  );
  test('Moving a creator clears its old slot and cancelling a lookup ignores late data', () async {
    final providers = <TestProvider>[];
    final model = MonitorModel(
      providerFactory: () {
        final p = TestProvider();
        providers.add(p);
        return p;
      },
    );
    final first = model.place(liveRoom, 0);
    await Future<void>.delayed(Duration.zero);
    final second = model.place(liveRoom, 2);
    await Future<void>.delayed(Duration.zero);
    expect(model.rooms[0], isNull);
    expect(model.rooms[2], same(liveRoom));
    await model.changeLayout(WallLayout.single);
    expect(model.rooms[2], isNull);
    for (final p in providers) {
      for (final request in p.pending.values) {
        request.complete(
          const LiveStream(
            roomId: '6',
            urls: [],
            quality: 150,
            protocol: 'http_hls',
          ),
        );
      }
    }
    await Future.wait([first, second]);
    expect(
      model.sessions.every((s) => s.controller == null && s.stream == null),
      isTrue,
    );
    model.dispose();
  });
  test('Audio selection leaves at most one audible slot', () async {
    final model = MonitorModel();
    expect(model.sessions.map((s) => s.volume), [1, 0, 0, 0]);
    await model.audio(2);
    expect(model.sessions.map((s) => s.volume), [0, 0, 1, 0]);
    await model.audio(2);
    expect(model.sessions.every((s) => s.volume == 0), isTrue);
    model.dispose();
  });
  test(
    'Shared layout geometry provides exactly the visible destination slots',
    () {
      final model = MonitorModel();
      model.rooms[3] = liveRoom;
      expect(model.effectiveLayout(false), WallLayout.quad);
      model.dispose();
      expect(layoutCells(WallLayout.focus).length, 3);
      expect(layoutCells(WallLayout.quad).length, 4);
      for (final layout in [
        WallLayout.single,
        WallLayout.focus,
        WallLayout.quad,
      ]) {
        final cells = layoutCells(layout);
        expect(
          cells.fold<double>(0, (sum, cell) => sum + cell.w * cell.h),
          closeTo(1, 0.00001),
        );
        for (final cell in cells) {
          expect(cell.x + cell.w, lessThanOrEqualTo(1));
          expect(cell.y + cell.h, lessThanOrEqualTo(1));
        }
      }
    },
  );
}
