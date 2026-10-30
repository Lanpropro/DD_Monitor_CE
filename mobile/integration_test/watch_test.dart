import 'package:ddmonitor/app.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets('Live playback survives Dock navigation and can stop', (
    tester,
  ) async {
    await tester.pumpWidget(const MonitorApp());
    final wall = tester.widget<WatchWall>(find.byType(WatchWall));
    await tester.tap(find.byKey(const Key('add-room')));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('room-input')), '0');
    await tester.tap(find.byKey(const Key('start-watch')));
    await tester.pumpAndSettle();
    expect(find.text('请输入有效的 B 站直播间数字房间号'), findsOneWidget);
    await tester.enterText(find.byKey(const Key('room-input')), '6');
    await tester.tap(find.byKey(const Key('start-watch')));
    await tester.pump();
    await tester.runAsync(() async {
      for (
        var i = 0;
        i < 90 && wall.session.controller == null && wall.session.error == null;
        i++
      ) {
        await Future<void>.delayed(const Duration(seconds: 1));
      }
    });
    await tester.pump();
    expect(wall.session.error, isNull);
    final controller = wall.session.controller!;
    expect(controller.value.isInitialized, isTrue);
    expect(controller.value.size.width, greaterThan(0));
    expect(controller.value.isPlaying, isTrue);
    await tester.tap(find.byKey(const Key('dock-1')));
    await tester.pumpAndSettle();
    expect(wall.session.controller, same(controller));
    expect(controller.value.isPlaying, isTrue);
    await tester.tap(find.byKey(const Key('dock-0')));
    await tester.pumpAndSettle();
    await tester.runAsync(
      () => Future<void>.delayed(const Duration(seconds: 30)),
    );
    await tester.pump();
    expect(wall.session.error, isNull);
    expect(wall.session.controller!.value.isPlaying, isTrue);
    await tester.runAsync(wall.session.suspend);
    expect(wall.session.controller, isNull);
    await tester.runAsync(wall.session.resume);
    await tester.pump();
    expect(wall.session.error, isNull);
    expect(wall.session.controller!.value.isPlaying, isTrue);
    await tester.runAsync(
      () => Future<void>.delayed(const Duration(seconds: 30)),
    );
    await tester.runAsync(wall.session.stop);
    await tester.pump();
    expect(wall.session.controller, isNull);
    expect(wall.session.stream, isNull);
  }, timeout: const Timeout(Duration(minutes: 4)));
}
