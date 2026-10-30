import 'package:ddmonitor/app.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('Dock switches pages and returns to the watching wall', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(const MonitorApp());
    expect(find.byKey(const Key('portrait-wall')), findsOneWidget);
    await tester.tap(find.byKey(const Key('dock-1')));
    await tester.pumpAndSettle();
    expect(find.text('关注管理尚未接入此预览版'), findsOneWidget);
    await tester.tap(find.byKey(const Key('dock-2')));
    await tester.pumpAndSettle();
    expect(find.text('插件商店尚未接入此预览版'), findsOneWidget);
    await tester.tap(find.byKey(const Key('dock-0')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('video-slot')), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('Invalid input remains in the sheet without a network request', (
    tester,
  ) async {
    await tester.pumpWidget(const MonitorApp());
    await tester.tap(find.byKey(const Key('add-room')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('room-input')), '0');
    await tester.tap(find.byKey(const Key('start-watch')));
    await tester.pumpAndSettle();
    expect(find.text('请输入有效的 B 站直播间数字房间号'), findsOneWidget);
    expect(find.byKey(const Key('room-input')), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('Tablet width uses regular layout and keeps video at 16:9', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1280, 800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(const MonitorApp());
    expect(find.byKey(const Key('regular-wall')), findsOneWidget);
    final size = tester.getSize(find.byKey(const Key('video-slot')));
    expect(size.width / size.height, closeTo(16 / 9, 0.001));
    expect(tester.takeException(), isNull);
  });
}
