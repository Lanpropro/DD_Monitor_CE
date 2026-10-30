import 'package:flutter/material.dart';

import 'design.dart';
import 'monitor_model.dart';
import 'platforms/bilibili.dart';
import 'wall_view.dart';

class FollowPage extends StatefulWidget {
  const FollowPage({
    super.key,
    required this.model,
    required this.onSelect,
    required this.onAdd,
  });
  final MonitorModel model;
  final ValueChanged<RoomInfo> onSelect;
  final VoidCallback onAdd;
  @override
  State<FollowPage> createState() => _FollowPageState();
}

class _FollowPageState extends State<FollowPage> {
  String search = '';
  int filter = 0;
  @override
  Widget build(BuildContext context) {
    final rooms =
        widget.model.follows
            .where(
              (room) =>
                  '${room.name} ${room.title} ${room.roomId}'
                      .toLowerCase()
                      .contains(search.toLowerCase()) &&
                  (filter == 0 ||
                      (filter == 1 ? room.live == true : room.live == false)),
            )
            .toList()
          ..sort(
            (a, b) =>
                (b.live == true ? 1 : 0).compareTo(a.live == true ? 1 : 0),
          );
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(20, 8, 20, 12),
          child: TextField(
            key: const Key('follow-search'),
            onChanged: (value) => setState(() => search = value),
            decoration: InputDecoration(
              hintText: '搜索主播、标题或房间号',
              prefixIcon: const Icon(Icons.search),
              filled: true,
              fillColor: panel,
              contentPadding: const EdgeInsets.all(12),
              border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(18),
                borderSide: BorderSide.none,
              ),
            ),
          ),
        ),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 20),
          child: Row(
            children: [
              for (var i = 0; i < 3; i++)
                Padding(
                  padding: const EdgeInsets.only(right: 8),
                  child: ChoiceChip(
                    key: Key('follow-filter-$i'),
                    label: Text(['全部', '直播中', '未开播'][i]),
                    selected: filter == i,
                    onSelected: (_) => setState(() => filter = i),
                  ),
                ),
              if (widget.model.refreshing)
                const Padding(
                  padding: EdgeInsets.only(left: 8),
                  child: SizedBox.square(
                    dimension: 16,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  ),
                ),
            ],
          ),
        ),
        if (widget.model.followError != null)
          Padding(
            padding: const EdgeInsets.all(12),
            child: Text(widget.model.followError!),
          ),
        Expanded(
          child: rooms.isEmpty
              ? SingleChildScrollView(
                  child: Padding(
                    padding: const EdgeInsets.all(24),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        const Icon(
                          Icons.favorite_border,
                          size: 40,
                          color: secondary,
                        ),
                        const SizedBox(height: 16),
                        Text(
                          widget.model.follows.isEmpty
                              ? '把喜欢的主播放在这里'
                              : '没有匹配的主播',
                          style: const TextStyle(fontSize: 20),
                        ),
                        const SizedBox(height: 8),
                        const Text('查看直播状态，点选封面放入直播墙'),
                        const SizedBox(height: 14),
                        if (widget.model.follows.isEmpty)
                          FilledButton.icon(
                            onPressed: widget.onAdd,
                            icon: const Icon(Icons.add),
                            label: const Text('添加关注'),
                          ),
                        const SizedBox(height: 90),
                      ],
                    ),
                  ),
                )
              : LayoutBuilder(
                  builder: (_, box) {
                    final columns = box.maxWidth < 600
                        ? 1
                        : box.maxWidth < 1100
                        ? 2
                        : 3;
                    return RefreshIndicator(
                      onRefresh: widget.model.refreshFollows,
                      child: GridView.builder(
                        key: const Key('follow-cards'),
                        padding: const EdgeInsets.fromLTRB(20, 16, 20, 130),
                        physics: const AlwaysScrollableScrollPhysics(),
                        itemCount: rooms.length,
                        gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
                          crossAxisCount: columns,
                          crossAxisSpacing: 16,
                          mainAxisSpacing: 16,
                          mainAxisExtent:
                              (box.maxWidth - 40 - 16 * (columns - 1)) /
                              columns *
                              9 /
                              16,
                        ),
                        itemBuilder: (_, index) {
                          final room = rooms[index];
                          final placed = widget.model.rooms.indexWhere(
                            (item) => item?.roomId == room.roomId,
                          );
                          return FollowCard(
                            room: room,
                            slot: placed >= 0 ? placed + 1 : null,
                            onSelect: () => widget.onSelect(room),
                            onRemove: () => widget.model.removeFollow(room),
                          );
                        },
                      ),
                    );
                  },
                ),
        ),
      ],
    );
  }
}

class FollowCard extends StatelessWidget {
  const FollowCard({
    super.key,
    required this.room,
    required this.onSelect,
    required this.onRemove,
    this.slot,
  });
  final RoomInfo room;
  final VoidCallback onSelect;
  final VoidCallback onRemove;
  final int? slot;
  @override
  Widget build(BuildContext context) => Material(
    color: panel,
    borderRadius: BorderRadius.circular(20),
    clipBehavior: Clip.antiAlias,
    child: InkWell(
      key: Key('follow-${room.roomId}'),
      onTap: onSelect,
      child: AspectRatio(
        key: Key('cover-${room.roomId}'),
        aspectRatio: 16 / 9,
        child: RoomCover(
          url: room.cover,
          child: Stack(
            children: [
              const Positioned.fill(
                child: DecoratedBox(
                  decoration: BoxDecoration(
                    gradient: LinearGradient(
                      begin: Alignment.topCenter,
                      end: Alignment.bottomCenter,
                      colors: [
                        Colors.black54,
                        Colors.transparent,
                        Colors.black87,
                      ],
                      stops: [0, 0.4, 1],
                    ),
                  ),
                ),
              ),
              Positioned(
                top: 12,
                left: 14,
                child: StatusLabel(live: room.live),
              ),
              Positioned(
                top: 0,
                right: 0,
                child: PopupMenuButton<String>(
                  tooltip: '关注选项',
                  onSelected: (_) => onRemove(),
                  itemBuilder: (_) => [
                    const PopupMenuItem(value: 'remove', child: Text('取消关注')),
                  ],
                ),
              ),
              Positioned(
                left: 14,
                right: 14,
                bottom: 13,
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.end,
                  children: [
                    CircleAvatar(
                      radius: 18,
                      backgroundColor: panel,
                      foregroundColor: Colors.white,
                      child: Text(
                        room.name.isEmpty ? 'B' : room.name.characters.first,
                      ),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Text(
                            room.name,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: const TextStyle(
                              fontSize: 17,
                              color: Colors.white,
                              fontWeight: FontWeight.w600,
                            ),
                          ),
                          const SizedBox(height: 3),
                          Text(
                            room.title.isEmpty
                                ? 'B站 · ${room.roomId}'
                                : room.title,
                            maxLines: 1,
                            overflow: TextOverflow.ellipsis,
                            style: const TextStyle(
                              fontSize: 12,
                              color: Colors.white70,
                            ),
                          ),
                        ],
                      ),
                    ),
                    if (slot != null)
                      Padding(
                        padding: const EdgeInsets.only(left: 8),
                        child: DecoratedBox(
                          decoration: BoxDecoration(
                            color: Colors.black54,
                            borderRadius: BorderRadius.circular(8),
                          ),
                          child: Padding(
                            padding: const EdgeInsets.symmetric(
                              horizontal: 8,
                              vertical: 4,
                            ),
                            child: Text(
                              '画面 $slot',
                              style: const TextStyle(
                                color: accent,
                                fontSize: 12,
                              ),
                            ),
                          ),
                        ),
                      ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    ),
  );
}

class AddFollowSheet extends StatefulWidget {
  const AddFollowSheet({super.key, required this.model});
  final MonitorModel model;
  @override
  State<AddFollowSheet> createState() => _AddFollowSheetState();
}

class _AddFollowSheetState extends State<AddFollowSheet> {
  final input = TextEditingController();
  final form = GlobalKey<FormState>();
  bool loading = false;
  String? error;
  Future<void> submit() async {
    if (loading || !form.currentState!.validate()) return;
    setState(() {
      loading = true;
      error = null;
    });
    try {
      await widget.model.addFollow(input.text);
      if (mounted) Navigator.pop(context);
    } catch (exception) {
      if (mounted) {
        setState(() {
          loading = false;
          error = exception is LiveLookupException
              ? exception.message
              : '获取主播失败，请检查网络后重试';
        });
      }
    }
  }

  @override
  void dispose() {
    input.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.all(24),
    child: Form(
      key: form,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        mainAxisSize: MainAxisSize.min,
        children: [
          Row(
            children: [
              const Expanded(
                child: Text(
                  '添加关注',
                  style: TextStyle(fontSize: 22, fontWeight: FontWeight.w600),
                ),
              ),
              IconButton(
                tooltip: '关闭',
                onPressed: () => Navigator.pop(context),
                icon: const Icon(Icons.close),
              ),
            ],
          ),
          const Text('输入 B站数字房间号，保存到本机关注列表'),
          const SizedBox(height: 20),
          TextFormField(
            key: const Key('room-input'),
            controller: input,
            autofocus: true,
            enabled: !loading,
            keyboardType: TextInputType.number,
            textInputAction: TextInputAction.done,
            decoration: const InputDecoration(
              labelText: '房间号',
              border: OutlineInputBorder(),
            ),
            validator: (value) {
              try {
                validateRoomId(value ?? '');
                return null;
              } on LiveLookupException catch (e) {
                return e.message;
              }
            },
            onFieldSubmitted: (_) => submit(),
          ),
          if (error != null)
            Padding(
              padding: const EdgeInsets.only(top: 12),
              child: Text(
                error!,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
            ),
          const SizedBox(height: 20),
          FilledButton(
            key: const Key('save-follow'),
            onPressed: loading ? null : submit,
            child: Padding(
              padding: const EdgeInsets.all(12),
              child: loading
                  ? const SizedBox.square(
                      dimension: 20,
                      child: CircularProgressIndicator(strokeWidth: 2),
                    )
                  : const Text('保存关注'),
            ),
          ),
        ],
      ),
    ),
  );
}

class PlacementPanel extends StatelessWidget {
  const PlacementPanel({
    super.key,
    required this.model,
    required this.room,
    required this.layout,
  });
  final MonitorModel model;
  final RoomInfo room;
  final WallLayout layout;
  @override
  Widget build(BuildContext context) => Padding(
    padding: const EdgeInsets.all(24),
    child: Column(
      mainAxisSize: MainAxisSize.min,
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          children: [
            const Expanded(
              child: Text(
                '放到哪个位置',
                style: TextStyle(fontSize: 22, fontWeight: FontWeight.w600),
              ),
            ),
            IconButton(
              tooltip: '关闭',
              onPressed: () => Navigator.pop(context),
              icon: const Icon(Icons.close),
            ),
          ],
        ),
        const SizedBox(height: 8),
        Text(room.name, style: const TextStyle(fontSize: 17)),
        const SizedBox(height: 6),
        StatusLabel(live: room.live),
        const SizedBox(height: 20),
        SlotLayout(
          key: const Key('placement-layout'),
          layout: layout,
          builder: (index) {
            final current = model.rooms[index];
            return Semantics(
              label: '位置 ${index + 1}，${current?.name ?? '空位'}',
              button: true,
              child: Material(
                color: panel,
                borderRadius: BorderRadius.circular(12),
                clipBehavior: Clip.antiAlias,
                child: InkWell(
                  key: Key('place-$index'),
                  onTap: () => Navigator.pop(context, index),
                  child: Stack(
                    fit: StackFit.expand,
                    children: [
                      if (current != null)
                        RoomCover(
                          url: current.cover,
                          child: const ColoredBox(color: Colors.black38),
                        ),
                      if (current == null)
                        const Center(
                          child: Icon(
                            Icons.add_circle_outline,
                            color: accent,
                            size: 30,
                          ),
                        ),
                      Positioned(
                        top: 6,
                        left: 7,
                        right: 7,
                        child: Text(
                          '${index + 1} ${current?.name ?? '空位'}',
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                            color: Colors.white,
                            fontSize: 12,
                          ),
                        ),
                      ),
                      if (current != null && model.sessions[index].volume > 0)
                        const Positioned(
                          bottom: 6,
                          right: 6,
                          child: Icon(Icons.volume_up, size: 16, color: accent),
                        ),
                    ],
                  ),
                ),
              ),
            );
          },
        ),
        const SizedBox(height: 16),
        const Text(
          '点击空位即可播放',
          textAlign: TextAlign.center,
          style: TextStyle(color: Colors.white),
        ),
        const SizedBox(height: 6),
        const Text('已有画面的位置可替换', textAlign: TextAlign.center),
        const SizedBox(height: 8),
      ],
    ),
  );
}
