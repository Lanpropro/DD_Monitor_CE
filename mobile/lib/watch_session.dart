import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:video_player/video_player.dart';

import 'platforms/bilibili.dart';

class WatchSession extends ChangeNotifier {
  WatchSession(this.provider);
  final BilibiliProvider provider;
  VideoPlayerController? controller;
  LiveStream? stream;
  bool loading = false;
  String? error;
  String? _resumeRoom;
  int _generation = 0;
  int _candidate = 0;
  int _windowRetries = 0;
  bool _recovering = false;
  double volume = 1;
  bool _userPaused = false;

  String get status {
    if (error != null) return error!;
    if (loading) return '正在连接直播…';
    final value = controller?.value;
    if (value?.isBuffering == true) return '正在缓冲…';
    if (value?.isPlaying == true) return '正在播放';
    if (stream != null) return '已暂停';
    return '添加直播间，开始观看';
  }

  Future<void> watch(String room, {bool autoplay = true}) async {
    final ticket = ++_generation;
    _resumeRoom = null;
    _userPaused = !autoplay;
    error = null;
    loading = true;
    stream = null;
    await _release();
    if (ticket != _generation) return;
    notifyListeners();
    try {
      final result = await provider.resolve(room);
      if (ticket != _generation) return;
      stream = result;
      _candidate = 0;
      _windowRetries = 0;
      _recovering = false;
      await _loadCandidate(ticket);
    } catch (exception) {
      if (ticket != _generation) return;
      loading = false;
      error = exception is LiveLookupException
          ? exception.message
          : '获取直播失败，请重试';
      notifyListeners();
    }
  }

  Future<void> _loadCandidate(int ticket) async {
    loading = true;
    await _release();
    if (ticket != _generation) return;
    notifyListeners();
    final current = stream!;
    while (_candidate < current.urls.length && ticket == _generation) {
      final next = VideoPlayerController.networkUrl(
        current.urls[_candidate],
        httpHeaders: current.headers,
        formatHint: current.protocol == 'http_hls' ? VideoFormat.hls : null,
        // Each wall slot must not steal audio focus and pause another slot.
        // MonitorModel controls which single stream is audible.
        videoPlayerOptions: VideoPlayerOptions(mixWithOthers: true),
      );
      try {
        await next.initialize().timeout(const Duration(seconds: 20));
        if (ticket != _generation) {
          await next.dispose();
          return;
        }
        if (current.protocol == 'http_hls' &&
            next.value.duration.inMilliseconds > 2500) {
          await next.seekTo(
            next.value.duration - const Duration(milliseconds: 2500),
          );
        }
        await next.setVolume(volume);
        if (!_userPaused) await next.play();
        if (ticket != _generation) {
          await next.dispose();
          return;
        }
        controller = next;
        next.addListener(_onPlayerValue);
        loading = false;
        error = null;
        debugPrint(
          'DDMonitorFlutter initialized room=${current.roomId} size=${next.value.size}',
        );
        notifyListeners();
        return;
      } catch (_) {
        await next.dispose();
        _candidate++;
      }
    }
    if (ticket != _generation) return;
    loading = false;
    error = '播放连接失败，请重新连接';
    notifyListeners();
  }

  void _onPlayerValue() {
    final value = controller?.value;
    if (value == null) return;
    if (value.hasError && !loading && !_recovering) {
      _recovering = true;
      final behindWindow = (value.errorDescription ?? '')
          .toLowerCase()
          .contains('behind');
      if (behindWindow && _windowRetries < 2) {
        _windowRetries++;
      } else {
        _candidate++;
        _windowRetries = 0;
      }
      final ticket = _generation;
      unawaited(
        _loadCandidate(ticket).whenComplete(() {
          if (ticket == _generation) _recovering = false;
        }),
      );
    }
    notifyListeners();
  }

  Future<void> togglePlayback() async {
    final current = controller;
    if (current == null) return;
    if (current.value.isPlaying) {
      _userPaused = true;
      await current.pause();
    } else {
      _userPaused = false;
      await current.play();
    }
  }

  Future<void> setVolume(double value) async {
    final ticket = _generation;
    volume = value;
    await controller?.setVolume(value);
    if (ticket == _generation) notifyListeners();
  }

  Future<void> _release() async {
    final previous = controller;
    controller = null;
    previous?.removeListener(_onPlayerValue);
    await previous?.dispose();
  }

  Future<void> stop() async {
    _generation++;
    _resumeRoom = null;
    stream = null;
    error = null;
    loading = false;
    final release = _release();
    notifyListeners();
    await release;
  }

  Future<void> suspend() async {
    final room = stream?.roomId;
    final ticket = ++_generation;
    _resumeRoom = room;
    loading = false;
    await _release();
    if (ticket != _generation) return;
    notifyListeners();
  }

  Future<void> resume() async {
    final room = _resumeRoom;
    _resumeRoom = null;
    if (room != null) await watch(room, autoplay: !_userPaused);
  }

  @override
  void dispose() {
    _generation++;
    controller?.removeListener(_onPlayerValue);
    unawaited(controller?.dispose());
    provider.close();
    super.dispose();
  }
}
