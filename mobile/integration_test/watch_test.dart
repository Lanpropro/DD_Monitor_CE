import 'package:ddmonitor/app.dart';
import 'package:ddmonitor/monitor_model.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:integration_test/integration_test.dart';

void main() {
  IntegrationTestWidgetsFlutterBinding.ensureInitialized();
  testWidgets(
    'Real cover card -> spatial placement -> playback, Dock, background and stop',
    (tester) async {
      final model = MonitorModel();
      addTearDown(() async {
        await tester.pumpWidget(const SizedBox());
        model.dispose();
      });
      await tester.pumpWidget(MonitorApp(model: model));
      Future<void> wakeControls() async {
        if (find.byKey(const Key('show-dock')).evaluate().isNotEmpty) {
          await tester.tap(find.byKey(const Key('show-dock')));
          await tester.pumpAndSettle();
        }
      }

      await tester.tap(find.byKey(const Key('dock-1')));
      await tester.pumpAndSettle();
      await tester.tap(find.byKey(const Key('add-follow')));
      await tester.pumpAndSettle();
      await tester.enterText(find.byKey(const Key('room-input')), '0');
      await tester.tap(find.byKey(const Key('save-follow')));
      await tester.pumpAndSettle();
      expect(find.text('请输入有效的 B 站直播间数字房间号'), findsOneWidget);
      await tester.enterText(find.byKey(const Key('room-input')), '6');
      await tester.tap(find.byKey(const Key('save-follow')));
      await tester.pump();
      await tester.runAsync(() async {
        for (var i = 0; i < 45 && model.follows.isEmpty; i++) {
          await Future<void>.delayed(const Duration(seconds: 1));
        }
      });
      await tester.pumpAndSettle();
      expect(model.follows.length, 1);
      final room = model.follows.single;
      expect(room.live, isTrue);
      expect(room.cover, isNotEmpty);
      expect(find.byKey(Key('cover-${room.roomId}')), findsOneWidget);
      await wakeControls();
      await tester.tap(find.byKey(Key('follow-${room.roomId}')));
      await tester.pumpAndSettle();
      expect(find.text('放到哪个位置'), findsOneWidget);
      await tester.tap(find.byKey(const Key('place-0')));
      await tester.pump();
      await tester.runAsync(() async {
        for (
          var i = 0;
          i < 90 &&
              model.sessions[0].controller == null &&
              model.sessions[0].error == null;
          i++
        ) {
          await Future<void>.delayed(const Duration(seconds: 1));
        }
      });
      await tester.pump();
      expect(model.sessions[0].error, isNull);
      final controller = model.sessions[0].controller!;
      expect(controller.value.isInitialized, isTrue);
      expect(controller.value.size.width, greaterThan(0));
      expect(controller.value.isPlaying, isTrue);
      final second = await tester.runAsync(() => model.addFollow('55'));
      expect(second!.live, isTrue);
      await tester.runAsync(() => model.place(second, 1));
      expect(model.sessions[1].error, isNull);
      expect(model.sessions[1].controller!.value.isPlaying, isTrue);
      expect(model.sessions[0].controller!.value.isPlaying, isTrue);
      expect(model.sessions[1].controller!.value.volume, 0);
      await tester.pump(const Duration(seconds: 6));
      await tester.pumpAndSettle();
      expect(find.byKey(const Key('show-dock')), findsOneWidget);
      await wakeControls();
      await tester.tap(find.byKey(const Key('dock-1')));
      await tester.pumpAndSettle();
      expect(find.text('画面 1'), findsOneWidget);
      expect(model.sessions[0].controller, same(controller));
      await tester.tap(find.byKey(const Key('dock-0')));
      await tester.pumpAndSettle();
      await tester.runAsync(
        () => Future<void>.delayed(const Duration(seconds: 20)),
      );
      await tester.pump();
      expect(model.sessions[0].error, isNull);
      expect(model.sessions[0].controller!.value.isPlaying, isTrue);
      expect(model.sessions[1].controller!.value.isPlaying, isTrue);
      await tester.runAsync(() => model.audio(0));
      expect(model.sessions[0].controller!.value.volume, 0);
      expect(model.sessions[1].controller!.value.volume, 0);
      await tester.runAsync(model.sessions[0].togglePlayback);
      expect(model.sessions[0].controller!.value.isPlaying, isFalse);
      await tester.runAsync(model.suspend);
      expect(model.sessions[0].controller, isNull);
      await tester.runAsync(model.resume);
      await tester.pump();
      expect(model.sessions[0].error, isNull);
      expect(model.sessions[0].controller!.value.isPlaying, isFalse);
      expect(model.sessions[0].controller!.value.volume, 0);
      expect(model.sessions[1].controller!.value.isPlaying, isTrue);
      expect(model.sessions[1].controller!.value.volume, 0);
      await tester.runAsync(model.sessions[0].togglePlayback);
      expect(model.sessions[0].controller!.value.isPlaying, isTrue);
      await tester.runAsync(
        () => Future<void>.delayed(const Duration(seconds: 20)),
      );
      await tester.runAsync(() => model.clear(0));
      await tester.runAsync(() => model.clear(1));
      await tester.pump();
      expect(model.sessions[0].controller, isNull);
      expect(model.rooms[0], isNull);
    },
    timeout: const Timeout(Duration(minutes: 5)),
  );
}
