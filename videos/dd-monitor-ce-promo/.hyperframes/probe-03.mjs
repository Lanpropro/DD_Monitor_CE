// Black-region map: mark blocks that are (almost) pure black — the app's inter-tile gaps.
import { readFileSync } from "node:fs";

const W = 1920;
const H = 1080;
const buf = readFileSync(process.argv[2]);
const lum = (x, y) => {
  const i = (y * W + x) * 3;
  return 0.2126 * buf[i] + 0.7152 * buf[i + 1] + 0.0722 * buf[i + 2];
};

const B = 32;
const cols = W / B;
const rows = H / B;
let header = "    ";
for (let c = 0; c < cols; c++) header += String(Math.floor((c * B) / 100) % 10).padStart(3);
console.log("each cell = 32x32px; '#'=>=85% black, '+'=50-85%, '.'=15-50%, ' '=<15%");
console.log(header);
for (let by = 0; by < rows; by++) {
  let line = String(by * B).padStart(4);
  for (let bx = 0; bx < cols; bx++) {
    let black = 0;
    let n = 0;
    for (let y = by * B; y < (by + 1) * B; y += 2)
      for (let x = bx * B; x < (bx + 1) * B; x += 2) {
        if (lum(x, y) < 8) black++;
        n++;
      }
    const f = black / n;
    line += (f >= 0.85 ? "#" : f >= 0.5 ? "+" : f >= 0.15 ? "." : " ").padStart(3);
  }
  console.log(line);
}
