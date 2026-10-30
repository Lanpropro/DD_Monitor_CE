import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:video_player/video_player.dart';

import 'design.dart';
import 'monitor_model.dart';
import 'platforms/bilibili.dart';
import 'watch_session.dart';

class SlotLayout extends StatelessWidget {
  const SlotLayout({super.key, required this.layout, required this.builder});
  final WallLayout layout;
  final Widget Function(int index) builder;
  static double aspect(WallLayout layout) =>
      layout == WallLayout.focus ? 32 / 27 : 16 / 9;
  @override
  Widget build(BuildContext context) => AspectRatio(
    aspectRatio: aspect(layout),
    child: LayoutBuilder(
      builder: (_, box) {
        final cells = layoutCells(layout);
        return Stack(
          children: [
            for (var i = 0; i < cells.length; i++)
              Positioned(
                left: cells[i].x * box.maxWidth,
                top: cells[i].y * box.maxHeight,
                width: cells[i].w * box.maxWidth,
                height: cells[i].h * box.maxHeight,
                child: Padding(
                  padding: const EdgeInsets.all(3),
                  child: builder(i),
                ),
              ),
          ],
        );
      },
    ),
  );
}

class WatchWall extends StatelessWidget {
  const WatchWall({super.key, required this.model, required this.onSelect});
  final MonitorModel model;
  final VoidCallback onSelect;
  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (_, box) {
      final wide = box.maxWidth >= 720;
      final layout = model.effectiveLayout(wide);
      // Reserve space for the floating Dock, including on short landscape phones.
      final height = math.max(
        80.0,
        box.maxHeight - MediaQuery.viewPaddingOf(context).bottom - 132,
      );
      final width = math.min(
        box.maxWidth - 24,
        height * SlotLayout.aspect(layout),
      );
      return Align(
        key: Key(wide ? 'regular-wall' : 'portrait-wall'),
        alignment: Alignment.topCenter,
        child: Padding(
          padding: const EdgeInsets.fromLTRB(12, 12, 12, 0),
          child: SizedBox(
            width: width,
            child: SlotLayout(
              key: const Key('wall-layout'),
              layout: layout,
              builder: (index) => LiveTile(
                index: index,
                session: model.sessions[index],
                room: model.rooms[index],
                onSelect: onSelect,
                onClear: () => model.clear(index),
                onAudio: () => model.audio(index),
              ),
            ),
          ),
        ),
      );
    },
  );
}

class LiveTile extends StatelessWidget {
  const LiveTile({
    super.key,
    required this.index,
    required this.session,
    required this.room,
    required this.onSelect,
    required this.onClear,
    required this.onAudio,
  });
  final int index;
  final WatchSession session;
  final RoomInfo? room;
  final VoidCallback onSelect;
  final VoidCallback onClear;
  final VoidCallback onAudio;
  @override
  Widget build(BuildContext context) => ListenableBuilder(
    listenable: session,
    builder: (_, _) {
      final controller = session.controller;
      return LayoutBuilder(
        builder: (_, box) {
          final compact = box.maxWidth < 160;
          return Container(
            key: Key('video-slot-$index'),
            decoration: BoxDecoration(
              color: Colors.black,
              borderRadius: BorderRadius.circular(16),
              border: Border.all(color: Colors.white24),
            ),
            clipBehavior: Clip.antiAlias,
            child: Stack(
              fit: StackFit.expand,
              children: [
                if (controller != null && controller.value.isInitialized)
                  Center(
                    child: AspectRatio(
                      aspectRatio: controller.value.aspectRatio,
                      child: VideoPlayer(controller),
                    ),
                  )
                else if (room != null && room!.cover.isNotEmpty)
                  RoomCover(
                    url: room!.cover,
                    child: const ColoredBox(color: Colors.black54),
                  ),
                if (room == null)
                  Material(
                    color: panel.withValues(alpha: 0.6),
                    child: InkWell(
                      key: Key('empty-slot-$index'),
                      onTap: onSelect,
                      child: Center(
                        child: Semantics(
                          label: '从关注中选择主播，位置 ${index + 1}',
                          button: true,
                          child: const Icon(
                            Icons.add_circle_outline,
                            size: 32,
                            color: secondary,
                          ),
                        ),
                      ),
                    ),
                  ),
                Positioned(
                  left: 8,
                  top: 8,
                  right: room == null ? null : 40,
                  child: IgnorePointer(
                    child: DecoratedBox(
                      decoration: BoxDecoration(
                        color: Colors.black54,
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: Padding(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 6,
                          vertical: 3,
                        ),
                        child: Text(
                          '${index + 1}${room == null ? ' 空位' : '  ${room!.name}'}',
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            fontSize: 12,
                            color: Colors.white,
                          ),
                        ),
                      ),
                    ),
                  ),
                ),
                if (room != null)
                  Positioned(
                    top: 0,
                    right: 0,
                    child: IconButton(
                      tooltip: '移除位置 ${index + 1}',
                      onPressed: onClear,
                      icon: const Icon(Icons.close, size: 18),
                      style: IconButton.styleFrom(
                        backgroundColor: Colors.black45,
                        minimumSize: const Size(40, 40),
                      ),
                    ),
                  ),
                if (session.loading)
                  const Center(
                    child: SizedBox.square(
                      dimension: 24,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    ),
                  ),
                if (session.error != null)
                  Center(
                    child: InkWell(
                      onTap: () => session.watch(room!.roomId),
                      child: Padding(
                        padding: const EdgeInsets.all(8),
                        child: Text(
                          '${session.error!}\n点击重试',
                          maxLines: 3,
                          overflow: TextOverflow.ellipsis,
                          textAlign: TextAlign.center,
                          style: const TextStyle(
                            fontSize: 12,
                            color: Colors.white,
                          ),
                        ),
                      ),
                    ),
                  ),
                if (controller != null && compact)
                  Positioned(
                    bottom: 0,
                    right: 0,
                    child: PopupMenuButton<String>(
                      key: Key('tile-menu-$index'),
                      tooltip: '画面控制',
                      onSelected: (value) {
                        if (value == 'audio') onAudio();
                        if (value == 'pause') session.togglePlayback();
                        if (value == 'full') {
                          Navigator.push(
                            context,
                            MaterialPageRoute<void>(
                              builder: (_) =>
                                  FullscreenPlayer(session: session),
                            ),
                          );
                        }
                      },
                      itemBuilder: (_) => [
                        PopupMenuItem(
                          value: 'pause',
                          child: Text(controller.value.isPlaying ? '暂停' : '播放'),
                        ),
                        PopupMenuItem(
                          value: 'audio',
                          child: Text(session.volume == 0 ? '开启此路声音' : '静音'),
                        ),
                        const PopupMenuItem(value: 'full', child: Text('全屏')),
                      ],
                      icon: const Icon(Icons.more_horiz),
                    ),
                  ),
                if (controller != null && !compact)
                  Positioned(
                    bottom: 0,
                    right: 0,
                    child: DecoratedBox(
                      decoration: BoxDecoration(
                        color: Colors.black54,
                        borderRadius: BorderRadius.circular(20),
                      ),
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          IconButton(
                            key: Key('pause-$index'),
                            tooltip: controller.value.isPlaying ? '暂停' : '播放',
                            onPressed: session.togglePlayback,
                            icon: Icon(
                              controller.value.isPlaying
                                  ? Icons.pause
                                  : Icons.play_arrow,
                              size: 20,
                            ),
                          ),
                          IconButton(
                            key: Key('audio-$index'),
                            tooltip: session.volume == 0 ? '开启此路声音' : '静音',
                            onPressed: onAudio,
                            icon: Icon(
                              session.volume == 0
                                  ? Icons.volume_off_outlined
                                  : Icons.volume_up,
                              size: 20,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ),
                if (controller != null && !compact)
                  Positioned(
                    bottom: 0,
                    left: 0,
                    child: IconButton(
                      key: Key('fullscreen-$index'),
                      tooltip: '全屏',
                      style: IconButton.styleFrom(
                        backgroundColor: Colors.black54,
                      ),
                      onPressed: () => Navigator.push(
                        context,
                        MaterialPageRoute<void>(
                          builder: (_) => FullscreenPlayer(session: session),
                        ),
                      ),
                      icon: const Icon(Icons.fullscreen, size: 20),
                    ),
                  ),
              ],
            ),
          );
        },
      );
    },
  );
}

class FullscreenPlayer extends StatelessWidget {
  const FullscreenPlayer({super.key, required this.session});
  final WatchSession session;
  @override
  Widget build(BuildContext context) => Scaffold(
    backgroundColor: Colors.black,
    appBar: AppBar(backgroundColor: Colors.black, title: const Text('直播画面')),
    body: ListenableBuilder(
      listenable: session,
      builder: (_, _) {
        final controller = session.controller;
        return controller == null
            ? const Center(child: Text('播放已停止'))
            : Center(
                child: AspectRatio(
                  aspectRatio: controller.value.aspectRatio,
                  child: VideoPlayer(controller),
                ),
              );
      },
    ),
  );
}
