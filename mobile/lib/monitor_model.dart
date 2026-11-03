import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'platforms/bilibili.dart';
import 'wall_layout.dart';
import 'watch_session.dart';
export 'wall_layout.dart';

class MonitorModel extends ChangeNotifier {
  MonitorModel({
    BilibiliProvider? catalog,
    BilibiliProvider Function()? providerFactory,
    this.preferences,
  }) : catalog = catalog ?? BilibiliProvider(),
       sessions = List.generate(
         16,
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
    final savedRatios = preferences?.getString('mobile.layoutRatios');
    if (savedRatios != null) {
      final stored = jsonDecode(savedRatios) as Map<String, dynamic>;
      for (final layout in WallLayout.values) {
        final value = stored[layout.name] as Map<String, dynamic>?;
        if (value != null) {
          _ratios[layout] = (
            x: (value['x'] as List).map((v) => (v as num).toDouble()).toList(),
            y: (value['y'] as List).map((v) => (v as num).toDouble()).toList(),
          );
        }
      }
    }
  }
  final BilibiliProvider catalog;
  final SharedPreferences? preferences;
  final List<WatchSession> sessions;
  final rooms = List<RoomInfo?>.filled(16, null);
  final follows = <RoomInfo>[];
  WallLayout layout = WallLayout.adaptive;
  bool reduceTransparency = false;
  bool refreshing = false;
  String? followError;
  bool _disposed = false;
  final _ratios = <WallLayout, ({List<double> x, List<double> y})>{};

  List<double> cuts(WallLayout layout, bool vertical) =>
      (vertical ? _ratios[layout]?.x : _ratios[layout]?.y) ??
      layoutCuts(layout, vertical);

  List<WallCell> cells(WallLayout layout) =>
      layoutCells(layout, x: cuts(layout, true), y: cuts(layout, false));

  void moveDivider(WallLayout layout, bool vertical, int index, double value) {
    final ratios = _ratios.putIfAbsent(
      layout,
      () => (x: layoutCuts(layout, true), y: layoutCuts(layout, false)),
    );
    final axis = vertical ? ratios.x : ratios.y;
    axis[index] = value.clamp(axis[index - 1] + 0.08, axis[index + 1] - 0.08);
    _changed();
  }

  Future<void> saveRatios() async {
    await preferences?.setString(
      'mobile.layoutRatios',
      jsonEncode({
        for (final entry in _ratios.entries)
          entry.key.name: {'x': entry.value.x, 'y': entry.value.y},
      }),
    );
  }

  Future<void> resetRatios(WallLayout layout) async {
    _ratios.remove(layout);
    _changed();
    await saveRatios();
  }

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
    await Future.wait([
      for (var i = value.slots; i < rooms.length; i++)
        if (rooms[i] != null) clear(i),
    ]);
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
