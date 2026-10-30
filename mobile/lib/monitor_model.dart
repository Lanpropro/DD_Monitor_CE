import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'platforms/bilibili.dart';
import 'watch_session.dart';

enum WallLayout {
  adaptive('自动布局', 4),
  single('单画面', 1),
  focus('主画面 + 双画面', 3),
  quad('四宫格', 4);

  const WallLayout(this.label, this.slots);
  final String label;
  final int slots;
}

// Normalized geometry is shared by the live wall and the placement miniature.
List<({double x, double y, double w, double h})> layoutCells(
  WallLayout layout,
) => switch (layout) {
  WallLayout.single => [(x: 0, y: 0, w: 1, h: 1)],
  WallLayout.focus => [
    (x: 0, y: 0, w: 1, h: 2 / 3),
    (x: 0, y: 2 / 3, w: 0.5, h: 1 / 3),
    (x: 0.5, y: 2 / 3, w: 0.5, h: 1 / 3),
  ],
  _ => [
    (x: 0, y: 0, w: 0.5, h: 0.5),
    (x: 0.5, y: 0, w: 0.5, h: 0.5),
    (x: 0, y: 0.5, w: 0.5, h: 0.5),
    (x: 0.5, y: 0.5, w: 0.5, h: 0.5),
  ],
};

class MonitorModel extends ChangeNotifier {
  MonitorModel({
    BilibiliProvider? catalog,
    BilibiliProvider Function()? providerFactory,
    this.preferences,
  }) : catalog = catalog ?? BilibiliProvider(),
       sessions = List.generate(
         4,
         (_) => WatchSession(
           (providerFactory ??
               () => BilibiliProvider(
                 allowFlv: defaultTargetPlatform != TargetPlatform.iOS,
               ))(),
         ),
       ) {
    for (var i = 0; i < sessions.length; i++) {
      sessions[i].volume = i == 0 ? 1 : 0;
      sessions[i].addListener(_changed);
    }
    final stored = preferences?.getString('mobile.follows');
    if (stored != null) {
      follows.addAll(
        (jsonDecode(stored) as List).map((item) => RoomInfo.fromJson(item)),
      );
    }
    final name = preferences?.getString('mobile.layout');
    layout =
        WallLayout.values.where((item) => item.name == name).firstOrNull ??
        WallLayout.adaptive;
    reduceTransparency =
        preferences?.getBool('mobile.reduceTransparency') ?? false;
  }
  final BilibiliProvider catalog;
  final SharedPreferences? preferences;
  final List<WatchSession> sessions;
  final rooms = List<RoomInfo?>.filled(4, null);
  final follows = <RoomInfo>[];
  WallLayout layout = WallLayout.adaptive;
  bool reduceTransparency = false;
  bool refreshing = false;
  String? followError;
  bool _disposed = false;

  WallLayout effectiveLayout(bool wide) => layout == WallLayout.adaptive
      ? (wide || rooms[3] != null ? WallLayout.quad : WallLayout.focus)
      : layout;
  void _changed() {
    if (!_disposed) notifyListeners();
  }

  Future<void> _saveFollows() async {
    await preferences?.setString(
      'mobile.follows',
      jsonEncode(follows.map((room) => room.toJson()).toList()),
    );
  }

  Future<RoomInfo> addFollow(String id) async {
    final room = await catalog.roomInfo(id);
    if (_disposed) return room;
    final index = follows.indexWhere((item) => item.roomId == room.roomId);
    if (index >= 0) {
      follows[index] = room;
    } else {
      follows.add(room);
    }
    followError = null;
    _changed();
    await _saveFollows();
    return room;
  }

  Future<void> removeFollow(RoomInfo room) async {
    follows.removeWhere((item) => item.roomId == room.roomId);
    _changed();
    await _saveFollows();
  }

  Future<void> refreshFollows() async {
    if (refreshing || follows.isEmpty) return;
    refreshing = true;
    followError = null;
    _changed();
    for (final old in List<RoomInfo>.of(follows)) {
      try {
        final updated = await catalog.roomInfo(old.roomId);
        if (_disposed) return;
        final index = follows.indexWhere((item) => item.roomId == old.roomId);
        if (index >= 0) follows[index] = updated;
      } catch (_) {
        if (_disposed) return;
        followError = '部分主播状态更新失败，请刷新重试';
        final index = follows.indexWhere((item) => item.roomId == old.roomId);
        if (index >= 0) {
          follows[index] = RoomInfo(
            roomId: old.roomId,
            name: old.name,
            title: old.title,
            cover: old.cover,
          );
        }
      }
    }
    refreshing = false;
    _changed();
    await _saveFollows();
  }

  Future<void> place(RoomInfo room, int index) async {
    if (rooms[index]?.roomId == room.roomId && sessions[index].stream != null) {
      return;
    }
    for (var i = 0; i < rooms.length; i++) {
      if (i != index && rooms[i]?.roomId == room.roomId) unawaited(clear(i));
    }
    rooms[index] = room;
    _changed();
    await sessions[index].watch(room.roomId);
  }

  Future<void> clear(int index) async {
    rooms[index] = null;
    await sessions[index].stop();
    _changed();
  }

  Future<void> changeLayout(WallLayout value) async {
    layout = value;
    for (var i = value.slots; i < rooms.length; i++) {
      unawaited(clear(i));
    }
    _changed();
    await preferences?.setString('mobile.layout', value.name);
  }

  Future<void> setTransparency(bool reduced) async {
    reduceTransparency = reduced;
    _changed();
    await preferences?.setBool('mobile.reduceTransparency', reduced);
  }

  Future<void> audio(int index) async {
    final turnOn = sessions[index].volume == 0;
    await Future.wait([
      for (var i = 0; i < sessions.length; i++)
        sessions[i].setVolume(i == index && turnOn ? 1 : 0),
    ]);
  }

  Future<void> suspend() async {
    await Future.wait(sessions.map((session) => session.suspend()));
  }

  Future<void> resume() async {
    await Future.wait(sessions.map((session) => session.resume()));
    if (!_disposed) unawaited(refreshFollows());
  }

  @override
  void dispose() {
    _disposed = true;
    for (final session in sessions) {
      session.removeListener(_changed);
      session.dispose();
    }
    catalog.close();
    super.dispose();
  }
}
