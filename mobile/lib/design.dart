import 'dart:ui';

import 'package:flutter/material.dart';

const background = Color(0xFF202226);
const panel = Color(0xFF303237);
const elevated = Color(0xFF383A40);
const accent = Color(0xFF00A1D6);
const foreground = Color(0xFFF1F2F4);
const secondary = Color(0xFFBDC1CA);
const subtleBorder = Color(0x29838391);
const cardRadius = 12.0;
const controlRadius = 8.0;

ThemeData monitorTheme() => ThemeData(
  brightness: Brightness.dark,
  useMaterial3: true,
  colorScheme: const ColorScheme.dark(
    primary: accent,
    onPrimary: background,
    surface: panel,
    onSurface: foreground,
    secondary: accent,
    outline: subtleBorder,
  ),
  scaffoldBackgroundColor: background,
  hoverColor: Colors.white.withValues(alpha: 0.06),
  focusColor: accent.withValues(alpha: 0.20),
  appBarTheme: const AppBarTheme(
    backgroundColor: background,
    foregroundColor: foreground,
    scrolledUnderElevation: 0,
    elevation: 0,
    titleTextStyle: TextStyle(fontSize: 20, fontWeight: FontWeight.w600),
  ),
  textTheme: const TextTheme(
    bodyLarge: TextStyle(fontSize: 15, height: 1.6, color: foreground),
    bodyMedium: TextStyle(fontSize: 15, height: 1.6, color: secondary),
    titleMedium: TextStyle(
      fontSize: 15,
      height: 1.45,
      fontWeight: FontWeight.w600,
      color: foreground,
    ),
    labelLarge: TextStyle(fontSize: 13, fontWeight: FontWeight.w600),
  ),
  cardTheme: CardThemeData(
    color: panel,
    elevation: 0,
    margin: EdgeInsets.zero,
    shape: RoundedRectangleBorder(
      borderRadius: BorderRadius.circular(cardRadius),
    ),
  ),
  dividerTheme: const DividerThemeData(color: subtleBorder, thickness: 1),
  listTileTheme: const ListTileThemeData(selectedColor: foreground),
  filledButtonTheme: FilledButtonThemeData(
    style: FilledButton.styleFrom(
      minimumSize: const Size(44, 44),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(controlRadius),
      ),
    ),
  ),
  textButtonTheme: TextButtonThemeData(
    style: TextButton.styleFrom(
      minimumSize: const Size(44, 44),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(controlRadius),
      ),
    ),
  ),
  inputDecorationTheme: InputDecorationTheme(
    filled: true,
    fillColor: elevated,
    hintStyle: const TextStyle(color: secondary, fontSize: 14),
    contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
    border: OutlineInputBorder(
      borderRadius: BorderRadius.circular(controlRadius),
      borderSide: BorderSide.none,
    ),
    focusedBorder: OutlineInputBorder(
      borderRadius: BorderRadius.circular(controlRadius),
      borderSide: const BorderSide(color: accent, width: 2),
    ),
  ),
  chipTheme: ChipThemeData(
    backgroundColor: Colors.transparent,
    selectedColor: accent.withValues(alpha: 0.18),
    showCheckmark: false,
    side: BorderSide.none,
    shape: const StadiumBorder(),
    labelStyle: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600),
  ),
  popupMenuTheme: PopupMenuThemeData(
    color: elevated,
    surfaceTintColor: Colors.transparent,
    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
  ),
  dialogTheme: DialogThemeData(
    backgroundColor: elevated,
    surfaceTintColor: Colors.transparent,
    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(24)),
  ),
);

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
        color: opaque ? elevated : elevated.withValues(alpha: 0.88),
        borderRadius: BorderRadius.circular(radius),
        border: Border.all(
          color: Colors.white.withValues(alpha: opaque ? 0.3 : 0.10),
        ),
        gradient: opaque
            ? null
            : LinearGradient(
                begin: Alignment.topLeft,
                end: Alignment.bottomRight,
                colors: [
                  Colors.white.withValues(alpha: 0.04),
                  elevated.withValues(alpha: 0.04),
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
            color: Colors.black.withValues(alpha: 0.16),
            blurRadius: 16,
            offset: const Offset(0, 8),
          ),
        ],
      ),
      child: ClipRRect(
        borderRadius: BorderRadius.circular(radius),
        child: opaque
            ? surface
            : BackdropFilter(
                filter: ImageFilter.blur(sigmaX: 20, sigmaY: 20),
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
