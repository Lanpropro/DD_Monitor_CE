import 'package:flutter/material.dart';
import 'package:video_player/video_player.dart';

import 'design.dart';
import 'monitor_model.dart';
import 'platforms/bilibili.dart';
import 'watch_session.dart';

class SlotLayout extends StatelessWidget {
  const SlotLayout({
    super.key,
    required this.layout,
    required this.builder,
    this.fill = false,
    this.cells,
    this.aspectRatio,
    this.overlays,
  });
  final bool fill;
  final List<WallCell>? cells;
  final double? aspectRatio;
  final List<Widget> Function(Size size)? overlays;
  final WallLayout layout;
  final Widget Function(int index) builder;
  @override
  Widget build(BuildContext context) {
    final content = LayoutBuilder(
      builder: (_, box) {
        final cells = this.cells ?? layoutCells(layout);
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
            ...?overlays?.call(box.biggest),
          ],
        );
      },
    );
    return fill
        ? content
        : AspectRatio(aspectRatio: aspectRatio ?? 16 / 9, child: content);
  }
}

class WatchWall extends StatelessWidget {
  const WatchWall({
    super.key,
    required this.model,
    required this.onSelect,
    this.onDragState,
  });
  final MonitorModel model;
  final VoidCallback onSelect;
  final ValueChanged<bool>? onDragState;
  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (_, box) {
      final wide = box.maxWidth >= 720;
      final layout = model.effectiveLayout(wide);
      return Align(
        key: Key(wide ? 'regular-wall' : 'portrait-wall'),
        alignment: Alignment.center,
        child: Padding(
          padding: const EdgeInsets.all(3),
          child: SizedBox(
            width: double.infinity,
            height: double.infinity,
            child: SlotLayout(
              key: const Key('wall-layout'),
              fill: true,
              layout: layout,
              cells: model.cells(layout),
              overlays: (size) => [
                for (final vertical in [true, false])
                  for (
                    var i = 1;
                    i < model.cuts(layout, vertical).length - 1;
                    i++
                  )
                    for (final segment in dividerSegments(
                      model.cells(layout),
                      model.cuts(layout, vertical)[i],
                      vertical,
                    ))
                      Positioned(
                        left: vertical
                            ? model.cuts(layout, true)[i] * size.width - 12
                            : segment.start * size.width,
                        top: vertical
                            ? segment.start * size.height
                            : model.cuts(layout, false)[i] * size.height - 12,
                        width: vertical
                            ? 24
                            : (segment.end - segment.start) * size.width,
                        height: vertical
                            ? (segment.end - segment.start) * size.height
                            : 24,
                        child: MouseRegion(
                          cursor: vertical
                              ? SystemMouseCursors.resizeLeftRight
                              : SystemMouseCursors.resizeUpDown,
                          child: Semantics(
                            label: '${vertical ? '竖向' : '横向'}分隔线 $i',
                            onIncrease: () {
                              model.moveDivider(
                                layout,
                                vertical,
                                i,
                                model.cuts(layout, vertical)[i] + 0.03,
                              );
                              model.saveRatios();
                            },
                            onDecrease: () {
                              model.moveDivider(
                                layout,
                                vertical,
                                i,
                                model.cuts(layout, vertical)[i] - 0.03,
                              );
                              model.saveRatios();
                            },
                            child: GestureDetector(
                              key: Key(
                                'divider-${vertical ? 'x' : 'y'}-$i-${segment.start}',
                              ),
                              behavior: HitTestBehavior.opaque,
                              onHorizontalDragUpdate: vertical
                                  ? (details) => model.moveDivider(
                                      layout,
                                      true,
                                      i,
                                      model.cuts(layout, true)[i] +
                                          details.delta.dx / size.width,
                                    )
                                  : null,
                              onVerticalDragUpdate: vertical
                                  ? null
                                  : (details) => model.moveDivider(
                                      layout,
                                      false,
                                      i,
                                      model.cuts(layout, false)[i] +
                                          details.delta.dy / size.height,
                                    ),
                              onHorizontalDragEnd: vertical
                                  ? (_) => model.saveRatios()
                                  : null,
                              onVerticalDragEnd: vertical
                                  ? null
                                  : (_) => model.saveRatios(),
                              onHorizontalDragCancel: vertical
                                  ? model.saveRatios
                                  : null,
                              onVerticalDragCancel: vertical
                                  ? null
                                  : model.saveRatios,
                              child: Center(
                                child: Container(
                                  width: vertical ? 3 : 32,
                                  height: vertical ? 32 : 3,
                                  decoration: BoxDecoration(
                                    color: Colors.white30,
                                    borderRadius: BorderRadius.circular(2),
                                  ),
                                ),
                              ),
                            ),
                          ),
                        ),
                      ),
              ],
              builder: (index) => DragTarget<int>(
                key: Key('drop-slot-$index'),
                onWillAcceptWithDetails: (details) =>
                    details.data != index && model.rooms[details.data] != null,
                onAcceptWithDetails: (details) =>
                    model.swapPositions(details.data, index),
                builder: (_, candidates, _) {
                  final room = model.rooms[index];
                  final tile = LiveTile(
                    index: index,
                    session: model.sessions[index],
                    room: room,
                    onSelect: onSelect,
                    onClear: () => model.clear(index),
                    onAudio: () => model.audio(index),
                  );
                  return DecoratedBox(
                    position: DecorationPosition.foreground,
                    decoration: BoxDecoration(
                      borderRadius: BorderRadius.circular(cardRadius),
                      border: candidates.isEmpty
                          ? null
                          : Border.all(color: accent, width: 3),
                    ),
                    child: room == null
                        ? tile
                        : Semantics(
                            hint: '长按拖到其他位置，交换或移动画面',
                            child: LongPressDraggable<int>(
                              key: Key('drag-slot-$index'),
                              data: index,
                              maxSimultaneousDrags: 1,
                              onDragStarted: () => onDragState?.call(true),
                              onDragEnd: (_) => onDragState?.call(false),
                              feedback: Material(
                                elevation: 8,
                                color: panel,
                                borderRadius: BorderRadius.circular(cardRadius),
                                clipBehavior: Clip.antiAlias,
                                child: SizedBox(
                                  width: 200,
                                  height: 112,
                                  child: RoomCover(
                                    url: room.cover,
                                    child: Align(
                                      alignment: Alignment.bottomLeft,
                                      child: Container(
                                        color: Colors.black54,
                                        padding: const EdgeInsets.all(8),
                                        child: Text(
                                          room.name,
                                          maxLines: 1,
                                          overflow: TextOverflow.ellipsis,
                                          style: const TextStyle(
                                            color: Colors.white,
                                            fontSize: 14,
                                          ),
                                        ),
                                      ),
                                    ),
                                  ),
                                ),
                              ),
                              child: tile,
                            ),
                          ),
                  );
                },
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
              borderRadius: BorderRadius.circular(cardRadius),
              border: Border.all(color: subtleBorder),
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
                      child: Semantics(
                        label: '从关注中选择主播，位置 ${index + 1}',
                        button: true,
                        child: const SizedBox.expand(),
                      ),
                    ),
                  ),
                if (room != null)
                  Positioned(
                    left: 8,
                    top: 8,
                    right: 40,
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
                            '${index + 1}  ${room!.name}',
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
