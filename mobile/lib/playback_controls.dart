import 'dart:async';

import 'package:flutter/material.dart';

import 'design.dart';
import 'monitor_model.dart';
import 'wall_view.dart';

class PlaybackControls extends StatelessWidget {
  const PlaybackControls({
    super.key,
    required this.model,
    required this.index,
    required this.onMenuState,
    this.fullscreen = false,
  });
  final MonitorModel model;
  final int index;
  final ValueChanged<bool> onMenuState;
  final bool fullscreen;

  Widget strip(String name, double minWidth, Widget child) => LayoutBuilder(
    builder: (_, box) => SingleChildScrollView(
      key: Key(name),
      scrollDirection: Axis.horizontal,
      child: SizedBox(
        width: box.maxWidth < minWidth ? minWidth : box.maxWidth,
        child: child,
      ),
    ),
  );

  @override
  Widget build(BuildContext context) {
    final room = model.rooms[index]!;
    final session = model.sessions[index];
    final controller = session.controller;
    final ready = controller?.value.isInitialized == true;
    final stream = session.stream;
    final surface =
        model.reduceTransparency || MediaQuery.highContrastOf(context)
        ? const Color(0xFF0C0D10)
        : const Color(0xC70C0D10);
    final buttonStyle = IconButton.styleFrom(
      backgroundColor: surface,
      foregroundColor: foreground,
      disabledForegroundColor: secondary.withValues(alpha: 0.45),
      minimumSize: const Size(44, 44),
      padding: EdgeInsets.zero,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(13)),
    );
    return Stack(
      key: const Key('playback-controls'),
      fit: StackFit.expand,
      children: [
        Positioned(
          left: 0,
          right: 0,
          top: 0,
          child: strip(
            'playback-top-bar',
            300,
            Row(
              children: [
                Expanded(
                  child: Tooltip(
                    message: room.title.isEmpty
                        ? room.name
                        : '${room.name} · ${room.title}',
                    child: DecoratedBox(
                      decoration: BoxDecoration(
                        color: surface,
                        borderRadius: BorderRadius.circular(13),
                      ),
                      child: Padding(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 10,
                          vertical: 8,
                        ),
                        child: Text(
                          room.name,
                          key: const Key('controlled-room'),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            fontSize: 13,
                            fontWeight: FontWeight.w600,
                            color: foreground,
                          ),
                        ),
                      ),
                    ),
                  ),
                ),
                const SizedBox(width: 6),
                Material(
                  color: surface,
                  borderRadius: BorderRadius.circular(13),
                  child: PopupMenuButton<int>(
                    key: const Key('control-quality'),
                    tooltip: stream == null ? '连接后显示可用清晰度' : '选择清晰度',
                    enabled:
                        !session.loading &&
                        stream != null &&
                        stream.qualities.length > 1,
                    onOpened: () => onMenuState(true),
                    onCanceled: () => onMenuState(false),
                    onSelected: (quality) {
                      onMenuState(false);
                      unawaited(session.changeQuality(quality));
                    },
                    itemBuilder: (_) => [
                      for (final quality in stream?.qualities ?? [])
                        CheckedPopupMenuItem<int>(
                          key: Key('quality-${quality.id}'),
                          value: quality.id,
                          checked: stream?.quality == quality.id,
                          child: Text(quality.label),
                        ),
                    ],
                    child: SizedBox(
                      width: 84,
                      height: 44,
                      child: Row(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          Flexible(
                            child: Text(
                              stream?.qualityLabel ?? '画质',
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: const TextStyle(
                                fontSize: 12,
                                color: foreground,
                              ),
                            ),
                          ),
                          const Icon(Icons.expand_more, size: 16),
                        ],
                      ),
                    ),
                  ),
                ),
                const SizedBox(width: 6),
                IconButton(
                  key: const Key('control-retry'),
                  tooltip: '重新连接此路',
                  style: buttonStyle,
                  onPressed: session.loading ? null : session.reconnect,
                  icon: const Icon(Icons.refresh, size: 20),
                ),
                const SizedBox(width: 6),
                IconButton(
                  key: const Key('control-remove'),
                  tooltip: '移除当前画面',
                  style: buttonStyle,
                  onPressed: () {
                    model.clear(index);
                    if (fullscreen) Navigator.pop(context);
                  },
                  icon: const Icon(Icons.close, size: 20),
                ),
              ],
            ),
          ),
        ),
        Positioned(
          left: 0,
          right: 0,
          bottom: 0,
          child: strip(
            'playback-bottom-bar',
            220,
            Material(
              color: surface,
              borderRadius: BorderRadius.circular(6),
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 2),
                child: Row(
                  children: [
                    IconButton(
                      key: const Key('control-pause'),
                      tooltip: controller?.value.isPlaying == true
                          ? '暂停'
                          : '播放',
                      style: buttonStyle.copyWith(
                        backgroundColor: const WidgetStatePropertyAll(
                          Colors.transparent,
                        ),
                      ),
                      onPressed: ready ? session.togglePlayback : null,
                      icon: Icon(
                        controller?.value.isPlaying == true
                            ? Icons.pause
                            : Icons.play_arrow,
                        size: 20,
                      ),
                    ),
                    IconButton(
                      key: const Key('control-audio'),
                      tooltip: session.volume == 0 ? '开启此路声音' : '静音',
                      style: buttonStyle.copyWith(
                        backgroundColor: const WidgetStatePropertyAll(
                          Colors.transparent,
                        ),
                      ),
                      onPressed: () => model.audio(index),
                      icon: Icon(
                        session.volume == 0
                            ? Icons.volume_off_outlined
                            : Icons.volume_up,
                        size: 20,
                      ),
                    ),
                    const Spacer(),
                    const IconButton(
                      key: Key('control-danmaku'),
                      tooltip: '画面弹幕尚未接入',
                      onPressed: null,
                      icon: Text(
                        '弹',
                        style: TextStyle(
                          fontSize: 16,
                          color: Color(0x73BDC1CA),
                        ),
                      ),
                    ),
                    IconButton(
                      key: const Key('control-fullscreen'),
                      tooltip: fullscreen ? '退出全屏' : '全屏',
                      style: buttonStyle.copyWith(
                        backgroundColor: const WidgetStatePropertyAll(
                          Colors.transparent,
                        ),
                      ),
                      onPressed: ready
                          ? () async {
                              if (fullscreen) {
                                Navigator.pop(context);
                                return;
                              }
                              onMenuState(true);
                              await Navigator.push(
                                context,
                                MaterialPageRoute<void>(
                                  builder: (_) => FullscreenPlayer(
                                    session: session,
                                    controls: ListenableBuilder(
                                      listenable: model,
                                      builder: (_, _) =>
                                          model.rooms[index] == null
                                          ? const SizedBox.shrink()
                                          : PlaybackControls(
                                              model: model,
                                              index: index,
                                              onMenuState: onMenuState,
                                              fullscreen: true,
                                            ),
                                    ),
                                  ),
                                ),
                              );
                              onMenuState(false);
                            }
                          : null,
                      icon: Icon(
                        fullscreen ? Icons.fullscreen_exit : Icons.fullscreen,
                        size: 20,
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ],
    );
  }
}
