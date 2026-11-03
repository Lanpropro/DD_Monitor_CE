import 'package:ddmonitor/app.dart';
import 'package:ddmonitor/design.dart';
import 'package:ddmonitor/monitor_model.dart';
import 'package:ddmonitor/platforms/bilibili.dart';
import 'package:ddmonitor/wall_view.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:video_player/video_player.dart';
import 'package:video_player_platform_interface/video_player_platform_interface.dart';

import 'fake_video_platform.dart';
import 'model_test.dart' show TestProvider, liveRoom, offlineRoom;
import 'watch_session_test.dart' show QualityProvider;

void main() {
  Future<MonitorModel> boot(
    WidgetTester tester, {
    Size size = const Size(390, 844),
    bool followed = false,
    bool ready = false,
  }) async {
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = 1;
    final model = MonitorModel(
      catalog: TestProvider(),
      providerFactory: ready ? QualityProvider.new : TestProvider.new,
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
      expect(lastSlot.bottom, closeTo(wall.bottom - 6, 1));
      expect(wall.width, size.width);
      expect(wall.height, size.height);
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
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: Center(
            child: SizedBox(
              width: 120,
              height: 90,
              child: LiveTile(
                index: 0,
                session: model.sessions[0],
                room: liveRoom,
                onSelect: () {},
                onClear: () {},
                onAudio: () {},
              ),
            ),
          ),
        ),
      ),
    );
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

  testWidgets(
    'Restyled tablet keeps navigation states, readable controls and opaque fallback',
    (tester) async {
      final model = await boot(
        tester,
        size: const Size(1280, 800),
        followed: true,
      );
      double contrast(Color a, Color b) {
        final x = a.computeLuminance(), y = b.computeLuminance();
        return x > y ? (x + 0.05) / (y + 0.05) : (y + 0.05) / (x + 0.05);
      }

      final theme = Theme.of(tester.element(find.byKey(const Key('dock-0'))));
      expect(
        contrast(theme.colorScheme.onPrimary, theme.colorScheme.primary),
        greaterThanOrEqualTo(4.5),
      );
      expect(contrast(secondary, panel), greaterThanOrEqualTo(4.5));
      BoxDecoration iconSurface(int i) =>
          tester
                  .widget<AnimatedContainer>(find.byKey(Key('dock-icon-$i')))
                  .decoration!
              as BoxDecoration;
      expect(iconSurface(0).color, foreground);
      await tester.tap(find.byKey(const Key('dock-1')));
      await tester.pumpAndSettle();
      expect(iconSurface(1).color, foreground);
      expect(iconSurface(0).color, isNot(foreground));
      await tester.tap(find.byKey(const Key('follow-search')));
      await tester.enterText(find.byKey(const Key('follow-search')), '不存在');
      await tester.pumpAndSettle();
      expect(find.text('没有匹配的主播'), findsOneWidget);
      await tester.tap(find.byKey(const Key('dock-3')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('外观').first);
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('reduce-transparency')));
      await tester.pumpAndSettle();
      expect(model.reduceTransparency, isTrue);
      expect(find.byType(BackdropFilter), findsNothing);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('Empty wall is unmarked and remains selectable', (tester) async {
    await boot(tester, size: const Size(1280, 800));
    expect(find.textContaining('空位'), findsNothing);
    expect(find.byIcon(Icons.add_circle_outline), findsNothing);
    expect(find.bySemanticsLabel('从关注中选择主播，位置 1'), findsOneWidget);
    await tester.tap(find.byKey(const Key('empty-slot-0')));
    await tester.pumpAndSettle();
    expect(find.text('把喜欢的主播放在这里'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets(
    'Selected-pane toolbar controls one stream, preserves other playback and works fullscreen',
    (tester) async {
      final oldPlatform = VideoPlayerPlatform.instance;
      VideoPlayerPlatform.instance = FakeVideoPlatform();
      addTearDown(() => VideoPlayerPlatform.instance = oldPlatform);
      final model = await boot(
        tester,
        size: const Size(1280, 800),
        ready: true,
      );
      addTearDown(() async => model.suspend());
      const second = RoomInfo(roomId: '8', name: '另一位主播', live: true);
      await tester.runAsync(() => model.place(liveRoom, 0));
      await tester.runAsync(() => model.place(second, 1));
      await tester.pumpAndSettle();
      final other = model.sessions[1].controller!;
      await tester.tap(find.byKey(const Key('select-slot-0')));
      await tester.pumpAndSettle();
      expect(find.text('位置 1 · 星野'), findsOneWidget);
      expect(
        tester.getRect(find.byKey(const Key('playback-controls'))).bottom,
        lessThan(tester.getRect(find.byKey(const Key('dock-surface'))).top),
      );
      await tester.tap(find.byKey(const Key('control-pause')));
      await tester.tap(find.byKey(const Key('control-audio')));
      await tester.pumpAndSettle();
      expect(model.sessions[0].controller!.value.isPlaying, isFalse);
      expect(model.sessions[0].volume, 0);
      await tester.tap(find.byKey(const Key('control-quality')));
      await tester.pumpAndSettle();
      await tester.pump(const Duration(seconds: 6));
      expect(find.byKey(const Key('show-dock')), findsNothing);
      await tester.tap(find.byKey(const Key('quality-150')));
      for (var i = 0; i < 20 && model.sessions[0].loading; i++) {
        await tester.runAsync(
          () => Future<void>.delayed(const Duration(milliseconds: 10)),
        );
        await tester.pump();
      }
      await tester.pumpAndSettle();
      expect(model.sessions[0].stream!.quality, 150);
      expect(model.sessions[0].controller!.value.isPlaying, isFalse);
      expect(model.sessions[0].volume, 0);
      expect(model.sessions[1].controller, same(other));
      expect(other.value.isPlaying, isTrue);
      await tester.tap(find.byKey(const Key('control-fullscreen')));
      await tester.pumpAndSettle();
      expect(find.text('直播画面'), findsOneWidget);
      await tester.tap(find.byKey(const Key('control-pause')).hitTestable());
      await tester.pumpAndSettle();
      expect(model.sessions[0].controller!.value.isPlaying, isTrue);
      await tester.tap(
        find.byKey(const Key('control-fullscreen')).hitTestable(),
      );
      await tester.pumpAndSettle();
      model.swapPositions(0, 2);
      await tester.pumpAndSettle();
      expect(model.selectedIndex, 2);
      expect(find.text('位置 3 · 星野'), findsOneWidget);
      await tester.tap(find.byKey(const Key('control-remove')));
      await tester.pumpAndSettle();
      expect(model.rooms[2], isNull);
      expect(find.byKey(const Key('playback-controls')), findsNothing);
      expect(model.sessions[1].controller, same(other));
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'Long press swaps occupied panes, moves to empty panes and cancels outside',
    (tester) async {
      final model = await boot(tester, size: const Size(1280, 800));
      model.rooms[0] = liveRoom;
      model.rooms[1] = offlineRoom;
      await model.changeLayout(WallLayout.quad);
      await tester.pumpAndSettle();
      final playing = model.sessions[0], other = model.sessions[1];
      Future<void> drag(int source, Offset target, {bool hold = false}) async {
        final gesture = await tester.startGesture(
          tester.getCenter(find.byKey(Key('drag-slot-$source'))),
        );
        await tester.pump(const Duration(milliseconds: 600));
        await gesture.moveTo(target);
        await tester.pump();
        if (hold) {
          await tester.pump(const Duration(seconds: 6));
          expect(find.byKey(const Key('show-dock')), findsNothing);
        }
        await gesture.up();
        await tester.pumpAndSettle();
      }

      await drag(
        0,
        tester.getCenter(find.byKey(const Key('drop-slot-1'))),
        hold: true,
      );
      expect(model.rooms[0], same(offlineRoom));
      expect(model.rooms[1], same(liveRoom));
      expect(model.sessions[1], same(playing));
      expect(model.sessions[0], same(other));
      await drag(1, tester.getCenter(find.byKey(const Key('drop-slot-2'))));
      expect(model.rooms[1], isNull);
      expect(model.rooms[2], same(liveRoom));
      expect(model.sessions[2], same(playing));
      await drag(2, const Offset(-40, -40));
      expect(model.rooms[2], same(liveRoom));
      expect(model.sessions[2], same(playing));
      await tester.tap(find.byKey(const Key('choose-layout')));
      await tester.pumpAndSettle();
      for (final name in ['sixteen', 'main4', 'twoMain']) {
        expect(find.byKey(Key('layout-$name')), findsNothing);
      }
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'Selected toolbar stays usable with large text on a short landscape viewport',
    (tester) async {
      tester.platformDispatcher.textScaleFactorTestValue = 2;
      addTearDown(tester.platformDispatcher.clearTextScaleFactorTestValue);
      final model = await boot(tester, size: const Size(844, 320));
      model.rooms[0] = liveRoom;
      model.select(0);
      await tester.pumpAndSettle();
      final toolbar = tester.getRect(
        find.byKey(const Key('playback-controls')),
      );
      expect(toolbar.top, greaterThanOrEqualTo(0));
      expect(toolbar.bottom, lessThanOrEqualTo(320));
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'Dragging shared edges updates placement, keeps sessions and resets proportions',
    (tester) async {
      final model = await boot(
        tester,
        size: const Size(1280, 800),
        followed: true,
      );
      await model.changeLayout(WallLayout.main2);
      await tester.pumpAndSettle();
      final session = model.sessions.first;
      await tester.drag(
        find.byKey(const Key('divider-x-1-0.0')),
        const Offset(120, 0),
      );
      await tester.pumpAndSettle();
      expect(model.cells(WallLayout.main2).first.w, greaterThan(0.73));
      await tester.drag(
        find
            .byWidgetPredicate(
              (w) =>
                  w.key is ValueKey<String> &&
                  (w.key! as ValueKey<String>).value.startsWith('divider-y-1-'),
            )
            .first,
        const Offset(0, -100),
      );
      await tester.pumpAndSettle();
      expect(model.cuts(WallLayout.main2, false)[1], lessThan(0.42));
      expect(model.sessions.first, same(session));
      await tester.tap(find.byKey(const Key('dock-1')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('follow-6')));
      await tester.pumpAndSettle();
      final miniature = tester.widget<SlotLayout>(
        find.byKey(const Key('placement-layout')),
      );
      expect(miniature.cells, model.cells(WallLayout.main2));
      await tester.tap(find.byTooltip('关闭').last);
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('dock-0')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('choose-layout')));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.byKey(const Key('reset-layout-ratios')));
      await tester.tap(find.byKey(const Key('reset-layout-ratios')));
      await tester.pumpAndSettle();
      expect(model.cells(WallLayout.main2), layoutCells(WallLayout.main2));
      expect(model.sessions.first, same(session));
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'Nine-slot preset supports last-position placement and confirms shrinking',
    (tester) async {
      final model = await boot(
        tester,
        size: const Size(1280, 800),
        followed: true,
      );
      await tester.tap(find.byKey(const Key('choose-layout')));
      await tester.pumpAndSettle();
      await tester.ensureVisible(find.byKey(const Key('layout-nine')));
      await tester.tap(find.byKey(const Key('layout-nine')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('video-slot-8')), findsOneWidget);
      await tester.tap(find.byKey(const Key('empty-slot-8')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('follow-6')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('place-8')));
      await tester.pump();
      await model.sessions[8].stop();
      await tester.pumpAndSettle();
      expect(model.rooms[8]?.roomId, '6');
      await tester.tap(find.byKey(const Key('choose-layout')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('layout-single')));
      await tester.pumpAndSettle();
      expect(find.text('移除超出布局的画面？'), findsOneWidget);
      await tester.tap(find.text('取消'));
      await tester.pumpAndSettle();
      expect(model.layout, WallLayout.nine);
      expect(model.rooms[8]?.roomId, '6');
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'Layout cards show matching miniatures and select the real geometry',
    (tester) async {
      final model = await boot(tester, size: const Size(1280, 800));
      await tester.tap(find.byKey(const Key('choose-layout')));
      await tester.pumpAndSettle();
      for (final layout in WallLayout.values) {
        final preview = tester.widget<SlotLayout>(
          find.byKey(Key('layout-preview-${layout.name}')),
        );
        expect(
          preview.layout,
          layout == WallLayout.adaptive ? WallLayout.quad : layout,
        );
        expect(preview.fill, isTrue);
        expect(find.text(layout.label), findsOneWidget);
      }
      await tester.tap(find.byKey(const Key('layout-single')));
      await tester.pumpAndSettle();
      expect(model.layout, WallLayout.single);
      expect(find.byKey(const Key('video-slot-1')), findsNothing);
      await tester.tap(find.byKey(const Key('choose-layout')));
      await tester.pumpAndSettle();
      expect(
        tester
            .widget<SlotLayout>(
              find.byKey(const Key('layout-preview-adaptive')),
            )
            .layout,
        WallLayout.quad,
      );
      await tester.ensureVisible(find.byKey(const Key('layout-focus')));
      await tester.tap(find.byKey(const Key('layout-focus')));
      await tester.pumpAndSettle();
      expect(model.layout, WallLayout.focus);
      expect(find.byKey(const Key('video-slot-2')), findsOneWidget);
      expect(find.byKey(const Key('video-slot-3')), findsNothing);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'Tablet controls are compact, hide after inactivity and wake on touch',
    (tester) async {
      await boot(tester, size: const Size(1280, 800));
      expect(find.text('DD监控室'), findsNothing);
      expect(find.byType(AppBar), findsNothing);
      final dock = tester.getRect(find.byKey(const Key('dock-surface')));
      final layout = tester.getRect(find.byKey(const Key('choose-layout')));
      expect(dock.height, lessThanOrEqualTo(52));
      expect(layout.left, lessThan(24));
      expect(layout.bottom, greaterThan(760));
      expect(dock.left, greaterThan(layout.right));
      await tester.pump(const Duration(seconds: 4));
      await tester.tap(find.byKey(const Key('dock-2')));
      await tester.pumpAndSettle();
      await tester.pump(const Duration(seconds: 4));
      expect(find.byKey(const Key('show-dock')), findsNothing);
      await tester.pump(const Duration(seconds: 2));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('show-dock')), findsOneWidget);
      await tester.tap(find.byKey(const Key('show-dock')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('show-dock')), findsNothing);
      await tester.tap(find.byKey(const Key('dock-0')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('choose-layout')));
      await tester.pumpAndSettle();
      await tester.pump(const Duration(seconds: 6));
      expect(find.text('选择布局'), findsOneWidget);
      expect(find.byKey(const Key('show-dock')), findsNothing);
      await tester.tap(find.byKey(const Key('layout-quad')));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('video-slot-3')), findsOneWidget);
      await tester.pump(const Duration(seconds: 6));
      await tester.pumpAndSettle();
      await tester.tapAt(
        tester.getCenter(find.byKey(const Key('empty-slot-0'))),
      );
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('show-dock')), findsNothing);
      expect(find.byType(AppBar), findsNothing);
      expect(tester.takeException(), isNull);
    },
  );
}
