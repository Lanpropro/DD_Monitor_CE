// Numeric boundary readout: mean luma along short probes that cross tile seams.
import { readFileSync } from "node:fs";

const W = 1920;
const H = 1080;
const buf = readFileSync(process.argv[2]);
const lum = (x, y) => {
  const i = (y * W + x) * 3;
  return 0.2126 * buf[i] + 0.7152 * buf[i + 1] + 0.0722 * buf[i + 2];
};
const colMean = (x, y0, y1) => {
  let s = 0;
  let n = 0;
  for (let y = y0; y < y1; y++) {
    s += lum(x, y);
    n++;
  }
  return Math.round(s / n);
};
const rowMean = (y, x0, x1) => {
  let s = 0;
  let n = 0;
  for (let x = x0; x < x1; x++) {
    s += lum(x, y);
    n++;
  }
  return Math.round(s / n);
};

function scanCols(label, y0, y1, from, to, step = 1) {
  const out = [];
  for (let x = from; x <= to; x += step) out.push(`${x}:${colMean(x, y0, y1)}`);
  console.log(`${label} (y ${y0}-${y1})\n  ${out.join(" ")}`);
}
function scanRows(label, x0, x1, from, to, step = 1) {
  const out = [];
  for (let y = from; y <= to; y += step) out.push(`${y}:${rowMean(y, x0, x1)}`);
  console.log(`${label} (x ${x0}-${x1})\n  ${out.join(" ")}`);
}

// left rail / big-tile left edge
scanCols("rail-big seam", 100, 350, 0, 60, 2);
// big tile right edge -> right column tiles
scanCols("big|right seam", 60, 350, 860, 920);
// right tile right edge -> right rail
scanCols("right|far seam", 60, 250, 1740, 1920, 2);
// big tile bottom edge -> bottom row
scanRows("big-bottom seam", 100, 800, 390, 440);
// top-right tile 1 bottom / tile 2 top
scanRows("right tiles seam", 1350, 1750, 240, 300);
// bottom row tile seams (vertical) at y 900-1000
scanCols("bottom row seams", 900, 1000, 800, 1000);
scanCols("bottom row seams b", 900, 1000, 1150, 1350);
