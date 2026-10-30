import 'dart:ui';

import 'package:flutter/material.dart';

const background = Color(0xFF11151C);
const panel = Color(0xFF1C222C);
const accent = Color(0xFF8AB4FF);
const secondary = Color(0xFFA7B0BD);

// Flutter approximation of the approved material; content cards stay opaque.
class GlassSurface extends StatelessWidget {
  const GlassSurface({
    super.key,
    required this.child,
    this.radius = 24,
    this.reduced = false,
  });
  final Widget child;
  final double radius;
  final bool reduced;
  @override
  Widget build(BuildContext context) {
    final opaque = reduced || MediaQuery.highContrastOf(context);
    final surface = DecoratedBox(
      decoration: BoxDecoration(
        color: opaque ? panel : panel.withValues(alpha: 0.72),
        borderRadius: BorderRadius.circular(radius),
        border: Border.all(
          color: Colors.white.withValues(alpha: opaque ? 0.3 : 0.18),
        ),
        gradient: opaque
            ? null
            : LinearGradient(
                begin: Alignment.topLeft,
                end: Alignment.bottomRight,
                colors: [
                  Colors.white.withValues(alpha: 0.16),
                  panel.withValues(alpha: 0.76),
                  panel.withValues(alpha: 0.9),
                ],
              ),
      ),
      child: child,
    );
    return Container(
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(radius),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.25),
            blurRadius: 20,
            offset: const Offset(0, 6),
          ),
        ],
      ),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(radius),
        child: opaque
            ? surface
            : BackdropFilter(
                filter: ImageFilter.blur(sigmaX: 24, sigmaY: 24),
                child: surface,
              ),
      ),
    );
  }
}

class RoomCover extends StatelessWidget {
  const RoomCover({super.key, required this.url, this.child});
  final String url;
  final Widget? child;
  @override
  Widget build(BuildContext context) => Stack(
    fit: StackFit.expand,
    children: [
      const ColoredBox(
        color: panel,
        child: Center(
          child: Icon(Icons.live_tv_outlined, color: secondary, size: 36),
        ),
      ),
      if (url.isNotEmpty)
        Image.network(
          url,
          fit: BoxFit.cover,
          errorBuilder: (_, _, _) => const SizedBox.shrink(),
        ),
      ?child,
    ],
  );
}

class StatusLabel extends StatelessWidget {
  const StatusLabel({super.key, required this.live});
  final bool? live;
  @override
  Widget build(BuildContext context) => Row(
    mainAxisSize: MainAxisSize.min,
    children: [
      Icon(
        Icons.circle,
        size: 7,
        color: live == true ? const Color(0xFFFF6B80) : secondary,
      ),
      const SizedBox(width: 5),
      Text(
        live == null
            ? '状态待更新'
            : live!
            ? '直播中'
            : '未开播',
        style: const TextStyle(fontSize: 12, color: Colors.white),
      ),
    ],
  );
}
