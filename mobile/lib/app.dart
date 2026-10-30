import 'dart:async';

import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'design.dart';
import 'follow_view.dart';
import 'monitor_model.dart';
import 'platforms/bilibili.dart';
import 'wall_view.dart';

const tabs = ['直播墙', '关注', '插件', '设置'];
const tabIcons = [
  Icons.live_tv_outlined,
  Icons.favorite_border,
  Icons.extension_outlined,
  Icons.settings_outlined,
];

class MonitorApp extends StatefulWidget {
  const MonitorApp({super.key, this.model, this.preferences});
  final MonitorModel? model;
  final SharedPreferences? preferences;
  @override
  State<MonitorApp> createState() => _MonitorAppState();
}

class _MonitorAppState extends State<MonitorApp> with WidgetsBindingObserver {
  late final model =
      widget.model ?? MonitorModel(preferences: widget.preferences);
  int selected = 0;
  Timer? refreshTimer;
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    unawaited(model.refreshFollows());
    refreshTimer = Timer.periodic(
      const Duration(seconds: 60),
      (_) => unawaited(model.refreshFollows()),
    );
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.paused) {
      refreshTimer?.cancel();
      unawaited(model.suspend());
    }
    if (state == AppLifecycleState.resumed) {
      unawaited(model.resume());
      refreshTimer?.cancel();
      refreshTimer = Timer.periodic(
        const Duration(seconds: 60),
        (_) => unawaited(model.refreshFollows()),
      );
    }
  }

  @override
  void dispose() {
    refreshTimer?.cancel();
    WidgetsBinding.instance.removeObserver(this);
    if (widget.model == null) model.dispose();
    super.dispose();
  }

  Future<void> addFollow(BuildContext context) async {
    await showAdaptivePanel<void>(context, AddFollowSheet(model: model), model);
  }

  Future<void> place(BuildContext context, RoomInfo room) async {
    if (room.live != true) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text(room.live == false ? '该主播尚未开播' : '请先刷新主播状态')),
      );
      return;
    }
    final wide = MediaQuery.sizeOf(context).width >= 720;
    final layout = model.effectiveLayout(wide);
    final index = await showAdaptivePanel<int>(
      context,
      PlacementPanel(model: model, room: room, layout: layout),
      model,
    );
    if (index == null || !mounted || !context.mounted) return;
    if (model.rooms[index] != null &&
        model.rooms[index]!.roomId != room.roomId) {
      final replace = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('替换当前画面？'),
          content: Text(
            '位置 ${index + 1} 的 ${model.rooms[index]!.name} 将替换为 ${room.name}。',
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('取消'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('替换'),
            ),
          ],
        ),
      );
      if (replace != true || !mounted) return;
    }
    setState(() => selected = 0);
    unawaited(model.place(room, index));
  }

  Future<void> chooseLayout(BuildContext context) async {
    final chosen = await showAdaptivePanel<WallLayout>(
      context,
      Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              '选择布局',
              style: TextStyle(fontSize: 22, fontWeight: FontWeight.w600),
            ),
            const SizedBox(height: 12),
            for (final layout in WallLayout.values)
              ListTile(
                key: Key('layout-${layout.name}'),
                leading: const Icon(Icons.grid_view_rounded),
                title: Text(layout.label),
                trailing: model.layout == layout
                    ? const Icon(Icons.check, color: accent)
                    : null,
                onTap: () => Navigator.pop(context, layout),
              ),
          ],
        ),
      ),
      model,
    );
    if (chosen == null || !context.mounted) return;
    if (model.rooms.skip(chosen.slots).any((room) => room != null)) {
      final confirmed = await showDialog<bool>(
        context: context,
        builder: (context) => AlertDialog(
          title: const Text('移除超出布局的画面？'),
          content: const Text('关注会保留，超出新布局的位置将停止播放。'),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('取消'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('切换'),
            ),
          ],
        ),
      );
      if (confirmed != true) return;
    }
    await model.changeLayout(chosen);
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
      appBarTheme: const AppBarTheme(
        backgroundColor: background,
        scrolledUnderElevation: 0,
      ),
      textTheme: const TextTheme(
        bodyLarge: TextStyle(fontSize: 17),
        bodyMedium: TextStyle(fontSize: 15, color: secondary),
      ),
    ),
    home: Builder(
      builder: (context) => ListenableBuilder(
        listenable: model,
        builder: (_, _) => MediaQuery.sizeOf(context).isEmpty
            ? const ColoredBox(color: background)
            : Scaffold(
                extendBody: true,
                appBar: AppBar(
                  toolbarHeight:
                      70 *
                      MediaQuery.textScalerOf(context).scale(1).clamp(1.0, 1.5),
                  title: Row(
                    children: [
                      const Icon(
                        Icons.live_tv_rounded,
                        size: 21,
                        color: accent,
                      ),
                      const SizedBox(width: 9),
                      Flexible(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Text(
                              'DD监控室',
                              style: TextStyle(fontSize: 12, color: secondary),
                            ),
                            Text(
                              tabs[selected],
                              style: const TextStyle(
                                fontSize: 25,
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                  actions: [
                    if (selected == 0)
                      Padding(
                        padding: const EdgeInsets.only(right: 16),
                        child: GlassSurface(
                          radius: 23,
                          reduced: model.reduceTransparency,
                          child: TextButton.icon(
                            key: const Key('choose-layout'),
                            onPressed: () => chooseLayout(context),
                            icon: const Icon(Icons.grid_view_rounded, size: 18),
                            label: Text(
                              model
                                  .effectiveLayout(
                                    MediaQuery.sizeOf(context).width >= 720,
                                  )
                                  .label,
                              style: const TextStyle(
                                fontSize: 13,
                                color: Colors.white,
                              ),
                            ),
                          ),
                        ),
                      ),
                    if (selected == 1) ...[
                      IconButton(
                        tooltip: '刷新主播状态',
                        onPressed: model.refreshing
                            ? null
                            : model.refreshFollows,
                        icon: const Icon(Icons.refresh),
                      ),
                      IconButton(
                        key: const Key('add-follow'),
                        tooltip: '添加关注',
                        onPressed: () => addFollow(context),
                        icon: const Icon(Icons.add_circle_outline),
                      ),
                      const SizedBox(width: 12),
                    ],
                  ],
                ),
                body: SafeArea(
                  top: false,
                  bottom: false,
                  child: IndexedStack(
                    index: selected,
                    children: [
                      WatchWall(
                        model: model,
                        onSelect: () => setState(() => selected = 1),
                      ),
                      FollowPage(
                        model: model,
                        onSelect: (room) => place(context, room),
                        onAdd: () => addFollow(context),
                      ),
                      const PluginPage(),
                      SettingsPage(
                        model: model,
                        onLayout: () => chooseLayout(context),
                      ),
                    ],
                  ),
                ),
                bottomNavigationBar: SafeArea(
                  top: false,
                  child: Padding(
                    padding: const EdgeInsets.fromLTRB(18, 8, 18, 12),
                    child: Center(
                      heightFactor: 1,
                      child: ConstrainedBox(
                        constraints: const BoxConstraints(maxWidth: 500),
                        child: GlassSurface(
                          radius: 32,
                          reduced: model.reduceTransparency,
                          child: Padding(
                            padding: const EdgeInsets.all(5),
                            child: Row(
                              children: [
                                for (var i = 0; i < tabs.length; i++)
                                  Expanded(
                                    child: Semantics(
                                      selected: selected == i,
                                      button: true,
                                      child: Material(
                                        color: Colors.transparent,
                                        child: InkWell(
                                          key: Key('dock-$i'),
                                          borderRadius: BorderRadius.circular(
                                            27,
                                          ),
                                          onTap: () =>
                                              setState(() => selected = i),
                                          child: DecoratedBox(
                                            decoration: BoxDecoration(
                                              color: selected == i
                                                  ? Colors.white.withValues(
                                                      alpha: 0.13,
                                                    )
                                                  : Colors.transparent,
                                              borderRadius:
                                                  BorderRadius.circular(27),
                                              border: Border.all(
                                                color: selected == i
                                                    ? Colors.white24
                                                    : Colors.transparent,
                                              ),
                                            ),
                                            child: Padding(
                                              padding:
                                                  const EdgeInsets.symmetric(
                                                    vertical: 9,
                                                  ),
                                              child: Column(
                                                mainAxisSize: MainAxisSize.min,
                                                children: [
                                                  Icon(
                                                    tabIcons[i],
                                                    size: 23,
                                                    color: selected == i
                                                        ? accent
                                                        : secondary,
                                                  ),
                                                  const SizedBox(height: 3),
                                                  Text(
                                                    tabs[i],
                                                    style: TextStyle(
                                                      fontSize: 11,
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
      ),
    ),
  );
}

Future<T?> showAdaptivePanel<T>(
  BuildContext context,
  Widget child,
  MonitorModel model,
) {
  if (MediaQuery.sizeOf(context).width >= 720) {
    return showDialog<T>(
      context: context,
      builder: (_) => Dialog(
        backgroundColor: Colors.transparent,
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 540),
          child: GlassSurface(
            reduced: model.reduceTransparency,
            child: SingleChildScrollView(child: child),
          ),
        ),
      ),
    );
  }
  return showModalBottomSheet<T>(
    context: context,
    isScrollControlled: true,
    useSafeArea: true,
    backgroundColor: Colors.transparent,
    builder: (_) => GlassSurface(
      reduced: model.reduceTransparency,
      radius: 28,
      child: SingleChildScrollView(
        child: Padding(
          padding: EdgeInsets.only(
            bottom: MediaQuery.viewInsetsOf(context).bottom,
          ),
          child: child,
        ),
      ),
    ),
  );
}

class PluginPage extends StatelessWidget {
  const PluginPage({super.key});
  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (_, box) => Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (box.maxWidth >= 720)
          const SizedBox(
            width: 220,
            child: Padding(
              padding: EdgeInsets.all(24),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('已安装', style: TextStyle(fontSize: 20)),
                  SizedBox(height: 22),
                  ListTile(leading: Icon(Icons.live_tv), title: Text('平台源')),
                ],
              ),
            ),
          ),
        Expanded(
          child: ListView(
            padding: const EdgeInsets.fromLTRB(20, 16, 20, 120),
            children: [
              Card(
                color: panel,
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: ListTile(
                    leading: Container(
                      width: 52,
                      height: 52,
                      decoration: BoxDecoration(
                        color: const Color(0xFFDE6A9B),
                        borderRadius: BorderRadius.circular(15),
                      ),
                      child: const Icon(
                        Icons.live_tv_rounded,
                        color: Colors.white,
                      ),
                    ),
                    title: const Text('B站直播'),
                    subtitle: const Text('平台源 · 匿名观看'),
                    trailing: const Text(
                      '已内置',
                      style: TextStyle(color: accent),
                    ),
                  ),
                ),
              ),
              const Padding(
                padding: EdgeInsets.all(16),
                child: Text('插件商店尚未接入此预览版。'),
              ),
            ],
          ),
        ),
      ],
    ),
  );
}

class SettingsPage extends StatefulWidget {
  const SettingsPage({super.key, required this.model, required this.onLayout});
  final MonitorModel model;
  final VoidCallback onLayout;
  @override
  State<SettingsPage> createState() => _SettingsPageState();
}

class _SettingsPageState extends State<SettingsPage> {
  int section = 0;
  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (_, box) {
      final wide = box.maxWidth >= 720;
      final sections = [
        Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('观看', style: TextStyle(color: secondary)),
            const SizedBox(height: 10),
            Card(
              color: panel,
              child: Column(
                children: [
                  ListTile(
                    leading: const Icon(Icons.grid_view_rounded),
                    title: const Text('默认布局'),
                    subtitle: Text(widget.model.layout.label),
                    trailing: const Icon(Icons.chevron_right),
                    onTap: widget.onLayout,
                  ),
                  const Divider(height: 1, indent: 56),
                  const ListTile(
                    leading: Icon(Icons.volume_up_outlined),
                    title: Text('声音'),
                    subtitle: Text('默认仅位置 1 出声，点击其他画面的声音按钮切换'),
                  ),
                  const Divider(height: 1, indent: 56),
                  const ListTile(
                    leading: Icon(Icons.aspect_ratio),
                    title: Text('画面适配'),
                    subtitle: Text('保持原始比例'),
                  ),
                ],
              ),
            ),
          ],
        ),
        Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('外观', style: TextStyle(color: secondary)),
            const SizedBox(height: 10),
            Card(
              color: panel,
              child: Column(
                children: [
                  const ListTile(
                    leading: Icon(Icons.dark_mode_outlined),
                    title: Text('主题'),
                    trailing: Text('深色'),
                  ),
                  const Divider(height: 1, indent: 56),
                  SwitchListTile(
                    key: const Key('reduce-transparency'),
                    secondary: const Icon(Icons.blur_off_outlined),
                    title: const Text('减少透明效果'),
                    value: widget.model.reduceTransparency,
                    onChanged: widget.model.setTransparency,
                  ),
                ],
              ),
            ),
          ],
        ),
        Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text('应用', style: TextStyle(color: secondary)),
            const SizedBox(height: 10),
            const Card(
              color: panel,
              child: ListTile(
                leading: Icon(Icons.info_outline),
                title: Text('关于 DD监控室'),
                subtitle: Text('0.3.0 · Flutter 移动端预览'),
              ),
            ),
          ],
        ),
      ];
      return Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (wide)
            SizedBox(
              width: 220,
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  children: [
                    for (var i = 0; i < 3; i++)
                      ListTile(
                        selected: section == i,
                        selectedTileColor: accent.withValues(alpha: 0.12),
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(14),
                        ),
                        title: Text(['观看', '外观', '应用'][i]),
                        onTap: () => setState(() => section = i),
                      ),
                  ],
                ),
              ),
            ),
          Expanded(
            child: Align(
              alignment: Alignment.topCenter,
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 800),
                child: ListView(
                  padding: const EdgeInsets.fromLTRB(20, 16, 20, 120),
                  children: [
                    if (wide)
                      sections[section]
                    else
                      for (final section in sections)
                        Padding(
                          padding: const EdgeInsets.only(bottom: 22),
                          child: section,
                        ),
                  ],
                ),
              ),
            ),
          ),
        ],
      );
    },
  );
}
