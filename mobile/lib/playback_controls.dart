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

  @override
  Widget build(BuildContext context) {
    final room = model.rooms[index]!;
    final session = model.sessions[index];
    final controller = session.controller;
    final ready = controller?.value.isInitialized == true;
    final stream = session.stream;
    return GlassSurface(
      key: const Key('playback-controls'),
      reduced: model.reduceTransparency,
      radius: 16,
      child: Material(
        color: Colors.transparent,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(12, 8, 12, 4),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Text(
                      '位置 ${index + 1} · ${room.name}',
                      key: const Key('controlled-room'),
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        fontSize: 14,
                        fontWeight: FontWeight.w600,
                        color: foreground,
                      ),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Flexible(
                    child: Text(
                      session.status,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(fontSize: 12, color: secondary),
                    ),
                  ),
                ],
              ),
              Row(
                children: [
                  IconButton(
                    key: const Key('control-pause'),
                    tooltip: controller?.value.isPlaying == true ? '暂停' : '播放',
                    onPressed: ready ? session.togglePlayback : null,
                    icon: Icon(
                      controller?.value.isPlaying == true
                          ? Icons.pause
                          : Icons.play_arrow,
                    ),
                  ),
                  IconButton(
                    key: const Key('control-audio'),
                    tooltip: session.volume == 0 ? '开启此路声音' : '静音',
                    onPressed: () => model.audio(index),
                    icon: Icon(
                      session.volume == 0
                          ? Icons.volume_off_outlined
                          : Icons.volume_up,
                    ),
                  ),
                  Expanded(
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
                      child: Padding(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 8,
                          vertical: 12,
                        ),
                        child: Row(
                          mainAxisAlignment: MainAxisAlignment.center,
                          children: [
                            Flexible(
                              child: Text(
                                stream?.qualityLabel ?? '清晰度',
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                                style: const TextStyle(fontSize: 13),
                              ),
                            ),
                            if (stream != null && stream.qualities.length > 1)
                              const Icon(Icons.expand_more, size: 18),
                          ],
                        ),
                      ),
                    ),
                  ),
                  if (session.error != null)
                    IconButton(
                      key: const Key('control-retry'),
                      tooltip: '重新连接',
                      onPressed: session.reconnect,
                      icon: const Icon(Icons.refresh),
                    ),
                  IconButton(
                    key: const Key('control-fullscreen'),
                    tooltip: fullscreen ? '退出全屏' : '全屏',
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
                    ),
                  ),
                  IconButton(
                    key: const Key('control-remove'),
                    tooltip: '移除当前画面',
                    onPressed: () {
                      model.clear(index);
                      if (fullscreen) Navigator.pop(context);
                    },
                    icon: const Icon(Icons.close),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}
