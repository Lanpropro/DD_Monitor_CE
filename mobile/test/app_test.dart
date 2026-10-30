import 'package:ddmonitor/app.dart';
import 'package:ddmonitor/monitor_model.dart';
import 'package:ddmonitor/platforms/bilibili.dart';
import 'package:ddmonitor/wall_view.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:video_player/video_player.dart';

import 'model_test.dart' show TestProvider, liveRoom, offlineRoom;

void main() {
  Future<MonitorModel> boot(
    WidgetTester tester, {
    Size size = const Size(390, 844),
    bool followed = false,
  }) async {
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = 1;
    final model = MonitorModel(
      catalog: TestProvider(),
      providerFactory: TestProvider.new,
    );
    if (followed) {
      model.follows.addAll([liveRoom, offlineRoom]);
    }
    addTearDown(() async {
      await tester.pumpWidget(const SizedBox());
      model.dispose();
      tester.view.resetPhysicalSize();
      tester.view.resetDevicePixelRatio();
    });
    await tester.pumpWidget(MonitorApp(model: model));
    await tester.pumpAndSettle();
    return model;
  }

  testWidgets(
    'Dock preserves a three-slot wall and exposes the four sections',
    (tester) async {
      await boot(tester);
      expect(find.byKey(const Key('portrait-wall')), findsOneWidget);
      expect(find.byKey(const Key('video-slot-2')), findsOneWidget);
      await tester.tap(find.byKey(const Key('dock-1')));
      await tester.pumpAndSettle();
      expect(find.text('把喜欢的主播放在这里'), findsOneWidget);
      await tester.tap(find.byKey(const Key('dock-2')));
      await tester.pumpAndSettle();
      expect(find.text('B站直播'), findsOneWidget);
      await tester.tap(find.byKey(const Key('dock-3')));
      await tester.pumpAndSettle();
      expect(find.text('减少透明效果'), findsOneWidget);
      await tester.tap(find.byKey(const Key('dock-0')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('wall-layout')), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );
  testWidgets('Invalid follow ID stays in the form and does not send HTTP', (
    tester,
  ) async {
    final model = await boot(tester);
    await tester.tap(find.byKey(const Key('dock-1')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('add-follow')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('room-input')), '0');
    await tester.tap(find.byKey(const Key('save-follow')));
    await tester.pumpAndSettle();
    expect(find.text('请输入有效的 B 站直播间数字房间号'), findsOneWidget);
    expect(model.follows, isEmpty);
    expect(tester.takeException(), isNull);
  });
  for (final size in [
    const Size(390, 844),
    const Size(1280, 800),
    const Size(844, 390),
  ]) {
    testWidgets('Cover cards and spatial picker fit $size', (tester) async {
      final model = await boot(tester, size: size, followed: true);
      final wall = tester.getRect(
        find.byKey(Key(size.width >= 720 ? 'regular-wall' : 'portrait-wall')),
      );
      final slot = tester.getRect(find.byKey(const Key('video-slot-0')));
      expect(slot.bottom, lessThanOrEqualTo(wall.bottom));
      final lastSlot = tester.getRect(
        find.byKey(
          Key(
            'video-slot-${layoutCells(model.effectiveLayout(size.width >= 720)).length - 1}',
          ),
        ),
      );
      final dock = tester.getRect(find.byKey(const Key('dock-0')));
      expect(lastSlot.bottom, lessThanOrEqualTo(dock.top));
      await tester.tap(find.byKey(const Key('dock-1')));
      await tester.pumpAndSettle();
      final cover = tester.getSize(find.byKey(const Key('cover-6')));
      expect(cover.width / cover.height, closeTo(16 / 9, 0.001));
      await tester.tapAt(
        tester.getTopLeft(find.byKey(const Key('follow-6'))) +
            const Offset(60, 40),
      );
      await tester.pumpAndSettle();
      final miniature = tester.widget<SlotLayout>(
        find.byKey(const Key('placement-layout')),
      );
      expect(miniature.layout, model.effectiveLayout(size.width >= 720));
      expect(find.byKey(const Key('place-2')), findsOneWidget);
      await tester.ensureVisible(find.byKey(const Key('place-2')));
      await tester.tap(find.byKey(const Key('place-2')));
      await tester.pump();
      expect(model.rooms[2]?.roomId, '6');
      expect(
        find.byKey(const Key('portrait-wall')).evaluate().isNotEmpty ||
            find.byKey(const Key('regular-wall')).evaluate().isNotEmpty,
        isTrue,
      );
      expect(tester.takeException(), isNull);
    });
  }
  testWidgets(
    'Live filter excludes offline creators and search matches titles',
    (tester) async {
      await boot(tester, followed: true);
      await tester.tap(find.byKey(const Key('dock-1')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('follow-filter-1')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('follow-6')), findsOneWidget);
      expect(find.byKey(const Key('follow-7')), findsNothing);
      await tester.enterText(find.byKey(const Key('follow-search')), '不存在');
      await tester.pumpAndSettle();
      expect(find.text('没有匹配的主播'), findsOneWidget);
    },
  );
  testWidgets('Replacing an occupied position requires explicit confirmation', (
    tester,
  ) async {
    final model = await boot(tester, followed: true);
    const another = RoomInfo(roomId: '8', name: '另一个主播', live: true);
    model.rooms[0] = another;
    await tester.tap(find.byKey(const Key('dock-1')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('follow-6')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('place-0')));
    await tester.pumpAndSettle();
    expect(find.text('替换当前画面？'), findsOneWidget);
    await tester.tap(find.text('取消'));
    await tester.pumpAndSettle();
    expect(model.rooms[0], same(another));
  });
  testWidgets(
    'Large text and empty follow state remain usable on a landscape phone',
    (tester) async {
      tester.platformDispatcher.textScaleFactorTestValue = 2;
      addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
      await boot(tester, size: const Size(844, 390));
      await tester.tap(find.byKey(const Key('dock-1')));
      await tester.pumpAndSettle();
      expect(tester.takeException(), isNull);
    },
  );
  testWidgets('Small live tiles keep all controls reachable without overflow', (
    tester,
  ) async {
    final model = await boot(tester, size: const Size(844, 320));
    model.rooms[0] = liveRoom;
    model.sessions[0].controller = VideoPlayerController.networkUrl(
      Uri.parse('https://example.com/live.m3u8'),
    );
    await tester.pumpWidget(MonitorApp(model: model));
    expect(find.byKey(const Key('tile-menu-0')), findsOneWidget);
    await tester.tap(find.byKey(const Key('tile-menu-0')));
    await tester.pumpAndSettle();
    expect(find.text('全屏'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
  testWidgets('Cold start waits for usable viewport dimensions', (
    tester,
  ) async {
    await boot(tester, size: Size.zero);
    expect(tester.takeException(), isNull);
    tester.view.physicalSize = const Size(1280, 800);
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('regular-wall')), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}
