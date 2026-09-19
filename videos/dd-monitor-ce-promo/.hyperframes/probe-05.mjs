// Connected components of the near-black mask => the wall's background/gap regions.
// The complement (within the wall's bounding box) is the tile rectangles.
import { readFileSync } from "node:fs";

const W = 1920;
const H = 1080;
const S = 4; // downsample factor
const w = W / S;
const h = H / S;
const buf = readFileSync(process.argv[2]);
const lum = (x, y) => {
  const i = (y * W + x) * 3;
  return 0.2126 * buf[i] + 0.7152 * buf[i + 1] + 0.0722 * buf[i + 2];
};
const black = new Uint8Array(w * h);
for (let y = 0; y < h; y++)
  for (let x = 0; x < w; x++) {
    let c = 0;
    for (let dy = 0; dy < S; dy++)
      for (let dx = 0; dx < S; dx++) if (lum(x * S + dx, y * S + dy) < 10) c++;
    black[y * w + x] = c >= S * S - 2 ? 1 : 0;
  }

const label = new Int32Array(w * h).fill(-1);
const comps = [];
const stack = [];
for (let i = 0; i < w * h; i++) {
  if (!black[i] || label[i] >= 0) continue;
  const id = comps.length;
  let minX = w;
  let maxX = -1;
  let minY = h;
  let maxY = -1;
  let area = 0;
  stack.push(i);
  label[i] = id;
  while (stack.length) {
    const p = stack.pop();
    const x = p % w;
    const y = (p - x) / w;
    area++;
    if (x < minX) minX = x;
    if (x > maxX) maxX = x;
    if (y < minY) minY = y;
    if (y > maxY) maxY = y;
    for (const [dx, dy] of [
      [1, 0],
      [-1, 0],
      [0, 1],
      [0, -1],
    ]) {
      const nx = x + dx;
      const ny = y + dy;
      if (nx < 0 || ny < 0 || nx >= w || ny >= h) continue;
      const q = ny * w + nx;
      if (black[q] && label[q] < 0) {
        label[q] = id;
        stack.push(q);
      }
    }
  }
  comps.push({ id, area, minX, maxX, minY, maxY });
}

comps.sort((a, b) => b.area - a.area);
console.log(`black components (area>${400 * S * S}px):`);
for (const c of comps) {
  const px = (v) => v * S;
  const areaPx = c.area * S * S;
  if (areaPx < 400) continue;
  console.log(
    `  area=${areaPx}  x ${px(c.minX)}..${px(c.maxX) + S - 1}  y ${px(c.minY)}..${px(c.maxY) + S - 1}  (w=${px(c.maxX - c.minX) + S}, h=${px(c.maxY - c.minY) + S})`,
  );
}

// Non-black coverage profile: for each column, fraction of y that is NOT black.
const colCov = [];
for (let x = 0; x < w; x++) {
  let c = 0;
  for (let y = 0; y < h; y++) if (!black[y * w + x]) c++;
  colCov.push(c / h);
}
const rowCov = [];
for (let y = 0; y < h; y++) {
  let c = 0;
  for (let x = 0; x < w; x++) if (!black[y * w + x]) c++;
  rowCov.push(c / w);
}
// report jumps in coverage (tile edges) as boundaries
const edges = (arr, scale, name) => {
  const out = [];
  for (let i = 1; i < arr.length; i++) {
    const d = arr[i] - arr[i - 1];
    if (Math.abs(d) > 0.12) out.push(`${i * scale}(${d > 0 ? "+" : ""}${d.toFixed(2)})`);
  }
  console.log(`${name} coverage jumps: ${out.join(" ")}`);
};
edges(colCov, S, "column");
edges(rowCov, S, "row");
