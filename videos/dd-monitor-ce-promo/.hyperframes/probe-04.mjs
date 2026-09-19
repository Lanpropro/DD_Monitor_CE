// Live-region map: pixels whose luma CHANGES across the 6s recording are real
// playing tiles; static black is the app's wall background / gaps.
import { readFileSync } from "node:fs";

const W = 1920;
const H = 1080;
const files = process.argv.slice(2);
const frames = files.map((f) => readFileSync(f));
const N = frames.length;
const lum = (buf, x, y) => {
  const i = (y * W + x) * 3;
  return 0.2126 * buf[i] + 0.7152 * buf[i + 1] + 0.0722 * buf[i + 2];
};
// per-pixel range of luma
const range = new Float32Array(W * H);
for (let y = 0; y < H; y += 2) {
  for (let x = 0; x < W; x += 2) {
    let lo = 255;
    let hi = 0;
    for (let f = 0; f < N; f++) {
      const l = lum(frames[f], x, y);
      if (l < lo) lo = l;
      if (l > hi) hi = l;
    }
    const r = hi - lo;
    range[y * W + x] = r;
    if (x + 1 < W) range[y * W + x + 1] = r;
    if (y + 1 < H) {
      range[(y + 1) * W + x] = r;
      if (x + 1 < W) range[(y + 1) * W + x + 1] = r;
    }
  }
}

const B = 32;
const cols = W / B;
const rows = H / B;
let header = "     ";
for (let c = 0; c < cols; c++) header += String(((c * B) / 32) % 10).padStart(3);
console.log("block 32x32; col index c => x=c*32 ; '#'=>=60% moving, '+'=25-60%, '.'=5-25%, ' '=<5%");
for (let by = 0; by < rows; by++) {
  let line = String(by * B).padStart(4) + " ";
  for (let bx = 0; bx < cols; bx++) {
    let live = 0;
    let n = 0;
    for (let y = by * B; y < (by + 1) * B; y++)
      for (let x = bx * B; x < (bx + 1) * B; x++) {
        if (range[y * W + x] > 12) live++;
        n++;
      }
    const f = live / n;
    line += (f >= 0.6 ? "#" : f >= 0.25 ? "+" : f >= 0.05 ? "." : " ").padStart(3);
  }
  console.log(line);
}

// exact separators: rows/cols where almost nothing moves
const colLive = new Float64Array(W);
const rowLive = new Float64Array(H);
for (let x = 0; x < W; x++) {
  let c = 0;
  for (let y = 0; y < H; y++) if (range[y * W + x] > 12) c++;
  colLive[x] = c / H;
}
for (let y = 0; y < H; y++) {
  let c = 0;
  for (let x = 0; x < W; x++) if (range[y * W + x] > 12) c++;
  rowLive[y] = c / W;
}
const runsOf = (arr, len, thr) => {
  const out = [];
  let s = -1;
  for (let i = 0; i < len; i++) {
    const on = arr[i] < thr;
    if (on && s < 0) s = i;
    if (!on && s >= 0) {
      out.push(`${s}-${i - 1}`);
      s = -1;
    }
  }
  if (s >= 0) out.push(`${s}-${len - 1}`);
  return out.filter((r) => {
    const [a, b] = r.split("-").map(Number);
    return b - a >= 2;
  });
};
console.log("\nstatic column runs (dead>97%):", runsOf(colLive, W, 0.03).join(" "));
console.log("static row runs (dead>97%):   ", runsOf(rowLive, H, 0.03).join(" "));
