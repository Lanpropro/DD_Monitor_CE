import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:video_player/video_player.dart';

import 'platforms/bilibili.dart';
import 'watch_session.dart';

const background = Color(0xFF11151C);
const panel = Color(0xFF1C222C);
const accent = Color(0xFF8AB4FF);
const secondary = Color(0xFFA7B0BD);
const tabs = ['观看', '关注', '插件', '设置'];
const tabIcons = [
  Icons.live_tv_outlined,
  Icons.favorite_border,
  Icons.extension_outlined,
  Icons.settings_outlined,
];

class MonitorApp extends StatefulWidget {
  const MonitorApp({super.key, this.provider});
  final BilibiliProvider? provider;
  @override
  State<MonitorApp> createState() => _MonitorAppState();
}

class _MonitorAppState extends State<MonitorApp> with WidgetsBindingObserver {
  late final session = WatchSession(
    widget.provider ??
        BilibiliProvider(allowFlv: defaultTargetPlatform != TargetPlatform.iOS),
  );
  int selected = 0;
  String lastInput = '';

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.paused) unawaited(session.suspend());
    if (state == AppLifecycleState.resumed) unawaited(session.resume());
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    session.dispose();
    super.dispose();
  }

  Future<void> addRoom(BuildContext context) async {
    final room = await showModalBottomSheet<String>(
      context: context,
      isScrollControlled: true,
      useSafeArea: true,
      showDragHandle: true,
      builder: (_) => AddRoomSheet(initial: lastInput),
    );
    if (room == null || !mounted) return;
    setState(() {
      lastInput = room;
      selected = 0;
    });
    unawaited(session.watch(room));
  }

  @override
  Widget build(BuildContext context) => MaterialApp(
    debugShowCheckedModeBanner: false,
    title: 'DD监控室',
    theme: ThemeData(
      brightness: Brightness.dark,
      useMaterial3: true,
      colorScheme: ColorScheme.fromSeed(
        seedColor: accent,
        brightness: Brightness.dark,
        surface: panel,
        primary: accent,
      ),
      scaffoldBackgroundColor: background,
      appBarTheme: const AppBarTheme(backgroundColor: background),
      textTheme: const TextTheme(
        bodyLarge: TextStyle(fontSize: 17),
        bodyMedium: TextStyle(fontSize: 15, color: secondary),
      ),
    ),
    home: Builder(
      builder: (context) => Scaffold(
        appBar: AppBar(
          toolbarHeight: 80,
          title: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'DD监控室',
                style: TextStyle(fontSize: 13, color: secondary),
              ),
              Text(
                tabs[selected],
                style: const TextStyle(
                  fontSize: 28,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ],
          ),
          actions: [
            if (selected == 0)
              IconButton(
                key: const Key('add-room'),
                tooltip: '添加直播间',
                onPressed: () => addRoom(context),
                icon: const Icon(Icons.add_circle_outline),
              ),
            const SizedBox(width: 12),
          ],
        ),
        body: SafeArea(
          top: false,
          bottom: false,
          child: IndexedStack(
            index: selected,
            children: [
              ListenableBuilder(
                listenable: session,
                builder: (_, _) =>
                    WatchWall(session: session, onAdd: () => addRoom(context)),
              ),
              const EmptySection(
                icon: Icons.favorite_border,
                title: '关注的直播间',
                detail: '关注管理尚未接入此预览版',
              ),
              const Padding(
                padding: EdgeInsets.all(20),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Card(
                      child: ListTile(
                        leading: Icon(Icons.live_tv),
                        title: Text('B 站直播'),
                        subtitle: Text('匿名观看 · 已内置'),
                      ),
                    ),
                    Padding(
                      padding: EdgeInsets.all(16),
                      child: Text('插件商店尚未接入此预览版'),
                    ),
                  ],
                ),
              ),
              const Padding(
                padding: EdgeInsets.all(20),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('DD监控室 0.2.0', style: TextStyle(fontSize: 20)),
                    SizedBox(height: 16),
                    Text('Flutter 移动端预览 · 单路 B 站直播'),
                    SizedBox(height: 12),
                    Text('进入后台时释放播放器；返回后恢复正在观看的直播。'),
                  ],
                ),
              ),
            ],
          ),
        ),
        bottomNavigationBar: SafeArea(
          top: false,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 12),
            child: Center(
              heightFactor: 1,
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 520),
                child: Material(
                  color: panel,
                  borderRadius: BorderRadius.circular(26),
                  clipBehavior: Clip.antiAlias,
                  child: Row(
                    children: [
                      for (var i = 0; i < tabs.length; i++)
                        Expanded(
                          child: Semantics(
                            selected: selected == i,
                            child: InkWell(
                              key: Key('dock-$i'),
                              onTap: () => setState(() => selected = i),
                              child: Padding(
                                padding: const EdgeInsets.symmetric(
                                  vertical: 12,
                                ),
                                child: Column(
                                  mainAxisSize: MainAxisSize.min,
                                  children: [
                                    Icon(
                                      tabIcons[i],
                                      color: selected == i ? accent : secondary,
                                    ),
                                    const SizedBox(height: 4),
                                    Text(
                                      tabs[i],
                                      style: TextStyle(
                                        fontSize: 12,
                                        color: selected == i
                                            ? accent
                                            : secondary,
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                            ),
                          ),
                        ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    ),
  );
}

class WatchWall extends StatelessWidget {
  const WatchWall({super.key, required this.session, required this.onAdd});
  final WatchSession session;
  final VoidCallback onAdd;

  @override
  Widget build(BuildContext context) {
    final content = ListView(
      padding: const EdgeInsets.all(20),
      children: [
        VideoTile(session: session, onAdd: onAdd),
        const SizedBox(height: 18),
        Row(
          children: [
            Expanded(
              child: Text(
                session.stream == null
                    ? '我的画面墙'
                    : 'B 站 · ${session.stream!.roomId}',
                style: const TextStyle(fontSize: 20),
              ),
            ),
            if (session.stream != null ||
                session.loading ||
                session.error != null)
              IconButton(
                tooltip: '停止观看',
                onPressed: session.stop,
                icon: const Icon(Icons.stop_circle_outlined),
              ),
          ],
        ),
        Text(
          session.status,
          style: TextStyle(
            color: session.error == null
                ? secondary
                : Theme.of(context).colorScheme.error,
          ),
        ),
        if (session.error != null)
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton(onPressed: onAdd, child: const Text('重新连接')),
          ),
      ],
    );
    return LayoutBuilder(
      builder: (_, constraints) {
        if (constraints.maxWidth < 720) {
          return KeyedSubtree(key: const Key('portrait-wall'), child: content);
        }
        return Row(
          key: const Key('regular-wall'),
          children: [
            SizedBox(
              width: 230,
              child: Padding(
                padding: const EdgeInsets.all(20),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text('直播间', style: TextStyle(fontSize: 20)),
                    const SizedBox(height: 20),
                    Text(
                      session.stream == null
                          ? '尚未添加直播间'
                          : 'B 站 · ${session.stream!.roomId}',
                    ),
                    const SizedBox(height: 16),
                    OutlinedButton.icon(
                      onPressed: onAdd,
                      icon: const Icon(Icons.add),
                      label: const Text('添加直播间'),
                    ),
                  ],
                ),
              ),
            ),
            const VerticalDivider(width: 1),
            Expanded(child: content),
          ],
        );
      },
    );
  }
}

class VideoTile extends StatelessWidget {
  const VideoTile({super.key, required this.session, required this.onAdd});
  final WatchSession session;
  final VoidCallback onAdd;

  @override
  Widget build(BuildContext context) {
    final controller = session.controller;
    return ClipRRect(
      borderRadius: BorderRadius.circular(18),
      child: AspectRatio(
        key: const Key('video-slot'),
        aspectRatio: 16 / 9,
        child: ColoredBox(
          color: Colors.black,
          child: Stack(
            alignment: Alignment.center,
            children: [
              if (controller != null && controller.value.isInitialized)
                AspectRatio(
                  aspectRatio: controller.value.aspectRatio,
                  child: VideoPlayer(controller),
                )
              else if (!session.loading)
                Column(
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    const Icon(
                      Icons.live_tv_outlined,
                      size: 36,
                      color: secondary,
                    ),
                    const SizedBox(height: 10),
                    const Text('还没有直播画面'),
                    TextButton(onPressed: onAdd, child: const Text('添加直播间')),
                  ],
                ),
              if (session.loading) const CircularProgressIndicator(),
              if (controller != null)
                Positioned(
                  bottom: 4,
                  right: 4,
                  child: DecoratedBox(
                    decoration: BoxDecoration(
                      color: Colors.black54,
                      borderRadius: BorderRadius.circular(24),
                    ),
                    child: Row(
                      children: [
                        IconButton(
                          tooltip: controller.value.isPlaying ? '暂停' : '播放',
                          onPressed: session.togglePlayback,
                          icon: Icon(
                            controller.value.isPlaying
                                ? Icons.pause
                                : Icons.play_arrow,
                          ),
                        ),
                        IconButton(
                          tooltip: controller.value.volume == 0 ? '开启声音' : '静音',
                          onPressed: () => controller.setVolume(
                            controller.value.volume == 0 ? 1 : 0,
                          ),
                          icon: Icon(
                            controller.value.volume == 0
                                ? Icons.volume_off
                                : Icons.volume_up,
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}

class EmptySection extends StatelessWidget {
  const EmptySection({
    super.key,
    required this.icon,
    required this.title,
    required this.detail,
  });
  final IconData icon;
  final String title;
  final String detail;
  @override
  Widget build(BuildContext context) => Center(
    child: Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 40, color: secondary),
          const SizedBox(height: 18),
          Text(title, style: const TextStyle(fontSize: 22)),
          const SizedBox(height: 8),
          Text(detail, textAlign: TextAlign.center),
        ],
      ),
    ),
  );
}

class AddRoomSheet extends StatefulWidget {
  const AddRoomSheet({super.key, required this.initial});
  final String initial;
  @override
  State<AddRoomSheet> createState() => _AddRoomSheetState();
}

class _AddRoomSheetState extends State<AddRoomSheet> {
  final form = GlobalKey<FormState>();
  late final input = TextEditingController(text: widget.initial);
  void submit() {
    if (form.currentState!.validate()) {
      Navigator.pop(context, validateRoomId(input.text));
    }
  }

  @override
  void dispose() {
    input.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => SingleChildScrollView(
    child: Padding(
      padding: EdgeInsets.fromLTRB(
        24,
        8,
        24,
        MediaQuery.viewInsetsOf(context).bottom + 24,
      ),
      child: Form(
        key: form,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Text('添加 B 站直播间', style: TextStyle(fontSize: 22)),
            const SizedBox(height: 20),
            TextFormField(
              key: const Key('room-input'),
              controller: input,
              autofocus: true,
              keyboardType: TextInputType.number,
              textInputAction: TextInputAction.go,
              decoration: const InputDecoration(
                labelText: '房间号',
                hintText: '输入数字房间号',
                border: OutlineInputBorder(),
              ),
              validator: (value) {
                try {
                  validateRoomId(value ?? '');
                  return null;
                } on LiveLookupException catch (error) {
                  return error.message;
                }
              },
              onFieldSubmitted: (_) => submit(),
            ),
            const SizedBox(height: 20),
            FilledButton(
              key: const Key('start-watch'),
              onPressed: submit,
              child: const Padding(
                padding: EdgeInsets.all(12),
                child: Text('开始观看'),
              ),
            ),
          ],
        ),
      ),
    ),
  );
}
