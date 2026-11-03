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
    expect(model.sessions.where((s) => s.volume > 0).length, 1);
    expect(model.sessions.first.volume, 1);
    await model.audio(2);
    expect(model.sessions.where((s) => s.volume > 0).length, 1);
    expect(model.sessions[2].volume, 1);
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
      for (final layout in WallLayout.values) {
        final cells = layoutCells(layout);
        expect(cells.length, layout.slots);
        expect(
          cells.fold<double>(0, (sum, cell) => sum + cell.w * cell.h),
          closeTo(1, 0.00001),
        );
        for (final cell in cells) {
          expect(cell.x + cell.w, lessThanOrEqualTo(1));
          expect(cell.y + cell.h, lessThanOrEqualTo(1));
        }
        for (var i = 0; i < cells.length; i++) {
          for (var j = i + 1; j < cells.length; j++) {
            final a = cells[i], b = cells[j];
            expect(
              a.x + a.w <= b.x + 0.000001 ||
                  b.x + b.w <= a.x + 0.000001 ||
                  a.y + a.h <= b.y + 0.000001 ||
                  b.y + b.h <= a.y + 0.000001,
              isTrue,
            );
          }
        }
      }
    },
  );

  test('Ratios clamp, survive restart per preset and reset without replacing sessions', () async {
    SharedPreferences.setMockInitialValues({});
    final prefs = await SharedPreferences.getInstance();
    final model = MonitorModel(preferences: prefs);
    final session = model.sessions.first;
    model.rooms[0] = liveRoom;
    model.moveDivider(WallLayout.main2, true, 1, 0.75);
    model.moveDivider(WallLayout.main2, false, 1, 0.35);
    await model.saveRatios();
    await model.changeLayout(WallLayout.six);
    model.moveDivider(WallLayout.six, true, 1, 1);
    final cuts = model.cuts(WallLayout.six, true);
    expect(cuts[2] - cuts[1], closeTo(0.08, 0.00001));
    await model.saveRatios();
    await model.changeLayout(WallLayout.main2);
    expect(model.cells(WallLayout.main2).first.w, 0.75);
    expect(model.sessions.first, same(session));
    expect(model.rooms.first, same(liveRoom));
    model.dispose();
    final restored = MonitorModel(preferences: prefs);
    expect(restored.cuts(WallLayout.main2, true)[1], 0.75);
    expect(restored.cuts(WallLayout.main2, false)[1], 0.35);
    expect(restored.cuts(WallLayout.six, true)[1], cuts[1]);
    await restored.resetRatios(WallLayout.main2);
    expect(restored.cells(WallLayout.main2), layoutCells(WallLayout.main2));
    expect(restored.cuts(WallLayout.six, true)[1], cuts[1]);
    restored.dispose();
  });

  test(
    'Sixteen positions are available and shrinking clears overflow',
    () async {
      final model = MonitorModel();
      await model.changeLayout(WallLayout.sixteen);
      expect(model.rooms.length, 16);
      expect(model.sessions.every((s) => s.controller == null), isTrue);
      model.rooms[15] = liveRoom;
      await model.audio(15);
      expect(model.sessions[15].volume, 1);
      await model.changeLayout(WallLayout.quad);
      expect(model.rooms[15], isNull);
      expect(model.sessions[15].controller, isNull);
      model.dispose();
    },
  );

  test('Spanning main panes have no internal resize handles', () {
    final cells = layoutCells(WallLayout.main3);
    final horizontal = dividerSegments(cells, 1 / 3, false);
    expect(horizontal, [(start: 2 / 3, end: 1.0)]);
    expect(dividerSegments(layoutCells(WallLayout.focus), 0.5, true), [
      (start: 0.5, end: 1.0),
    ]);
  });
}
