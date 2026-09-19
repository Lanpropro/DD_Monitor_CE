// ASCII luma map of the raw frame so tile boundaries can be read off with coordinates.
import { readFileSync } from "node:fs";

const W = 1920;
const H = 1080;
const buf = readFileSync(process.argv[2]);
const luma = (x, y) => {
  const i = (y * W + x) * 3;
  return 0.2126 * buf[i] + 0.7152 * buf[i + 1] + 0.0722 * buf[i + 2];
};

const BW = 32; // block width
const BH = 40; // block height
const cols = W / BW;
const rows = H / BH;
const map = [];
for (let by = 0; by < rows; by++) {
  const line = [];
  for (let bx = 0; bx < cols; bx++) {
    let sum = 0;
    let n = 0;
    for (let y = by * BH; y < (by + 1) * BH; y += 4)
      for (let x = bx * BW; x < (bx + 1) * BW; x += 4) {
        sum += luma(x, y);
        n++;
      }
    line.push(Math.round(sum / n));
  }
  map.push(line);
}
const chars = " .:-=+*#%@";
console.log("block = 32px wide x 40px tall; col index = x/32, row index = y/40");
console.log("     " + Array.from({ length: cols }, (_, i) => String(i % 10).padStart(3)).join(""));
map.forEach((line, i) => {
  console.log(
    String(i).padStart(3) + "  " +
      line.map((v) => chars[Math.min(9, Math.floor(v / 25.6))].padStart(3)).join(""),
  );
});

// precise separator detection: a separator is a run of columns whose mean luma is
// very low AND whose variance across the column is low (flat app background).
const stat = [];
for (let x = 0; x < W; x++) {
  let sum = 0;
  let sum2 = 0;
  let n = 0;
  for (let y = 200; y < 1040; y += 2) {
    const l = luma(x, y);
    sum += l;
    sum2 += l * l;
    n++;
  }
  const mean = sum / n;
  stat.push({ mean, sd: Math.sqrt(Math.max(0, sum2 / n - mean * mean)) });
}
const flat = [];
let s = -1;
for (let x = 0; x < W; x++) {
  const on = stat[x].mean < 22 && stat[x].sd < 12;
  if (on && s < 0) s = x;
  if (!on && s >= 0) {
    flat.push(`${s}-${x - 1}`);
    s = -1;
  }
}
console.log(`\nflat dark column runs (y200-1040): ${flat.join(" ")}`);
