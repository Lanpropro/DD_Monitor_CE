// Grid cells use (row, column, row span, column span), matching desktop layouts.
typedef GridCell = (int, int, int, int);
typedef WallCell = ({double x, double y, double w, double h});

enum WallLayout {
  adaptive('自动布局', 2, 2),
  single('单画面', 1, 1),
  vertical('上下两分', 2, 1),
  horizontal('左右两分', 1, 2),
  quad('四分', 2, 2),
  six('六分', 2, 3),
  nine('九分', 3, 3),
  main2('主画面 + 2 小', 2, 3, [(0, 0, 2, 2), (0, 2, 1, 1), (1, 2, 1, 1)]),
  mirrored('2 小 + 主画面（镜像）', 2, 2, [(0, 0, 1, 1), (1, 0, 1, 1), (0, 1, 2, 1)]),
  main3('主画面 + 3 小', 3, 3, [
    (0, 0, 3, 2),
    (0, 2, 1, 1),
    (1, 2, 1, 1),
    (2, 2, 1, 1),
  ]),
  focus('上主画面 + 下 2 小', 2, 2, [(0, 0, 1, 2), (1, 0, 1, 1), (1, 1, 1, 1)]),
  corner('主画面 + 5 小环绕', 3, 3, [
    (0, 0, 2, 2),
    (0, 2, 1, 1),
    (1, 2, 1, 1),
    (2, 0, 1, 1),
    (2, 1, 1, 1),
    (2, 2, 1, 1),
  ]);

  const WallLayout(this.label, this.rows, this.columns, [this.spec = const []]);
  final String label;
  final int rows, columns;
  final List<GridCell> spec;
  int get slots => spec.isEmpty ? rows * columns : spec.length;
  List<GridCell> get cells => spec.isNotEmpty
      ? spec
      : [
          for (var row = 0; row < rows; row++)
            for (var col = 0; col < columns; col++) (row, col, 1, 1),
        ];
}

List<int> _tracks(WallLayout layout, bool vertical) => {
  for (final cell in layout.cells) ...[
    vertical ? cell.$2 : cell.$1,
    vertical ? cell.$2 + cell.$4 : cell.$1 + cell.$3,
  ],
}.toList()..sort();

List<double> layoutCuts(WallLayout layout, bool vertical) => _tracks(
  layout,
  vertical,
).map((v) => v / (vertical ? layout.columns : layout.rows)).toList();

// One geometry drives the wall, preset thumbnails and placement miniatures.
List<WallCell> layoutCells(
  WallLayout layout, {
  List<double>? x,
  List<double>? y,
}) {
  final columns = _tracks(layout, true), rows = _tracks(layout, false);
  x ??= layoutCuts(layout, true);
  y ??= layoutCuts(layout, false);
  return [
    for (final cell in layout.cells)
      (
        x: x[columns.indexOf(cell.$2)],
        y: y[rows.indexOf(cell.$1)],
        w: x[columns.indexOf(cell.$2 + cell.$4)] - x[columns.indexOf(cell.$2)],
        h: y[rows.indexOf(cell.$1 + cell.$3)] - y[rows.indexOf(cell.$1)],
      ),
  ];
}

// A handle only covers shared edges, never the interior of a spanning video.
List<({double start, double end})> dividerSegments(
  List<WallCell> cells,
  double cut,
  bool vertical,
) {
  final segments = <({double start, double end})>[];
  for (final a in cells) {
    final edge = vertical ? a.x + a.w : a.y + a.h;
    if ((edge - cut).abs() > 0.000001) continue;
    for (final b in cells) {
      if (((vertical ? b.x : b.y) - cut).abs() > 0.000001) continue;
      final startA = vertical ? a.y : a.x, startB = vertical ? b.y : b.x;
      final endA = startA + (vertical ? a.h : a.w),
          endB = startB + (vertical ? b.h : b.w);
      final start = startA > startB ? startA : startB,
          end = endA < endB ? endA : endB;
      if (end - start > 0.000001) segments.add((start: start, end: end));
    }
  }
  segments.sort((a, b) => a.start.compareTo(b.start));
  return segments;
}
