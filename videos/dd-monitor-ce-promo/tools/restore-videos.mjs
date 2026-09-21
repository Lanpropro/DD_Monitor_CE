// 把 approved 视频块注回帧文件。
//
// 背景：assemble-index.mjs 的"视频提升"是**破坏性**的 —— 它把 <video> 从帧文件里
// 摘走、换成一行注释，再挂到 index.html 的宿主根。所以第二次组装时帧里已经没有视频
// 可提了，会生成一个没有视频的 index。踩过一次，15 帧的窗口全黑。
//
// 因此组装必须走这个顺序：先 restore，再 assemble。
//
// 几何全部按 cqw = 画布宽度的 1%（1920 -> 19.2px）从各帧窗口的 CSS 反算，
// 保证视频和帧自己画的窗口框对齐（视频绘制在帧 DOM 之上，错位会盖住窗口装饰）。
//
// v2（16 拍）映射见 PLAN；每项可选 `fit`（默认 cover）与 `mediaStart`（源内偏移）。
//
// 用法：node restore-videos.mjs <projectDir>
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { join } from "node:path";

const proj = process.argv[2] ?? ".";
const framesDir = join(proj, "compositions/frames");
const CQW = 1920 / 100; // 19.2px

// 每帧：输出文件、视频源、窗口 CSS 意图（left/right/width/top/bottom，单位 cqw）、时长
// 注意 bottom 是负值：窗口下沿跑出画布。
const PLAN = [
  { f: "01-wall-build",      src: "assets/rec-wall-build.mp4",      id: "ddf01-plate", cls: "",                 dur: 3.5, top: 16, l: 7,  r: 7,  b: -6 },
  { f: "02-title",           src: "assets/rec-wall-build.mp4",      id: "ddf02-plate", cls: "ddf02-plate",      dur: 5.5, top: 16, l: 7,  r: 7,  b: -6, bottom: true },
  { f: "03-layout-1to2",     src: "assets/rec-layout-1to2.mp4",     id: "ddf03-plate", cls: "ddf03-plate",      dur: 4,   top: 31, r: 5,  w: 52, b: -7, mediaStart: 4 },
  { f: "04-layout-1to4",     src: "assets/rec-layout-1to4.mp4",     id: "ddf04-plate", cls: "ddf04-plate",      dur: 3,   top: 31, r: 5,  w: 52, b: -7 },
  { f: "05-layout-9grid",    src: "assets/rec-layout-9grid.mp4",    id: "ddf05-plate", cls: "ddf05-plate",      dur: 3,   top: 31, r: 5,  w: 52, b: -7 },
  { f: "06-layout-bigplus",  src: "assets/rec-layout-bigplus.mp4",  id: "ddf06-plate", cls: "ddf06-plate",      dur: 3.5, top: 31, r: 5,  w: 52, b: -7 },
  { f: "07-layout-danmaku",  src: "assets/rec-layout-danmaku.mp4",  id: "ddf07-plate", cls: "ddf07-plate",      dur: 5.5, top: 29, r: 3,  w: 56, b: -9, mediaStart: 2 },
  { f: "08-portrait-flip",   src: "assets/rec-portrait-flip.mp4",   id: "ddf08-plate", cls: "ddf08-plate",      dur: 5.5, top: 3,  r: 7,  w: 31, b: -3 },
  { f: "09-portrait-slideout", src: "assets/rec-portrait-slideout.mp4", id: "ddf09-plate", cls: "ddf09-plate", dur: 2,   top: 0,  l: 0,  r: 0,  b: 0 },
  { f: "10-layout-cutback",  src: "assets/rec-layout-bigplus.mp4",  id: "ddf10-plate", cls: "ddf10-plate",      dur: 1,   top: 31, r: 5,  w: 52, b: -7 },
  { f: "11-follow-list",     src: "assets/rec-follow-list.mp4",     id: "ddf11-plate", cls: "ddf11-plate",      dur: 3.5, top: 10, l: 6,  w: 40, b: -2, fit: "fill" },
  { f: "12-channel-route",   src: "assets/rec-channel-route.mp4",   id: "ddf12-plate", cls: "ddf12-plate",      dur: 6,   top: 18, l: 12, r: 12, b: -8, mediaStart: 31 },
  { f: "13-reconnect",       src: "assets/rec-channel-route.mp4",   id: "ddf13-plate", cls: "ddf13-plate",      dur: 3,   top: 18, l: 12, r: 12, b: -8, mediaStart: 37 },
  { f: "15-wall-scroll",     src: "assets/rec-wall-scroll-pan.mp4", id: "ddf15-plate", cls: "ddf15-plate",      dur: 5,   top: 0,  l: 0,  r: 0,  b: 0 },
];

const px = (v) => Math.round(v * CQW * 10) / 10;

function rect(p) {
  if (p.ov) return p.ov;
  const w = p.w != null ? p.w : 100 - (p.l ?? 0) - (p.r ?? 0);
  const x = p.l != null ? p.l : 100 - w - p.r;
  const y = p.top;
  // bottom 是相对画布底的偏移（负值表示下沿超出画布）
  const bottomPx = p.b * CQW;
  const h = 1080 - y * CQW - bottomPx;
  return { x: px(x), y: px(y), w: px(w), h: Math.round(h * 10) / 10 }; // h 已是像素，不要再乘
}

let restored = 0;
const report = [];

for (const p of PLAN) {
  const path = join(framesDir, `${p.f}.html`);
  if (!existsSync(path)) {
    report.push(`!! ${p.f}: 文件不存在`);
    continue;
  }
  let src = readFileSync(path, "utf8");

  const hasComment = /<!--\s*approved frame video hoisted by assemble-index\s*-->/.test(src);
  const videoRe = new RegExp(`<video\\b[^>]*id="${p.id}"[\\s\\S]*?</video>`);
  const hasVideo = videoRe.test(src);
  if (!hasComment && !hasVideo) {
    report.push(`-- ${p.f}: 既没有提升注释也没有该视频，跳过`);
    continue;
  }

  const r = rect(p);
  const cls = p.cls ? `\n      class="${p.cls}"` : "";
  const fit = p.fit ?? "cover";
  const mediaStart = p.mediaStart != null ? `\n      data-media-start="${p.mediaStart}"` : "";
  const block =
    `<video\n` +
    `      id="${p.id}"${cls}\n` +
    `      data-frame-video="approved"\n` +
    `      data-frame-video-x="${r.x}"\n` +
    `      data-frame-video-y="${r.y}"\n` +
    `      data-frame-video-width="${r.w}"\n` +
    `      data-frame-video-height="${r.h}"\n` +
    `      data-frame-video-fit="${fit}"\n` +
    `      data-start="0"\n` +
    `      data-duration="${p.dur}"\n` +
    `      data-track-index="2"\n` +
    `      src="${p.src}"${mediaStart}\n` +
    `      muted\n` +
    `      playsinline\n` +
    `      preload="auto"\n` +
    `    ></video>`;

  // 注释存在就替换注释；否则替换已有的同名视频块（这样脚本可以重复跑）
  const next = hasComment
    ? src.replace(/<!--\s*approved frame video hoisted by assemble-index\s*-->/, block)
    : src.replace(videoRe, block);
  if (next === src) {
    report.push(`!! ${p.f}: 替换失败`);
    continue;
  }
  writeFileSync(path, next, "utf8");
  restored++;
  report.push(`OK ${p.f}: x=${r.x} y=${r.y} w=${r.w} h=${r.h} fit=${fit}  ${p.src.split("/").pop()}`);
}

console.log(report.join("\n"));
console.log(`\n注回 ${restored} 帧的视频块`);
if (restored === 0) console.log("（若已经注回过，这是正常的：直接跑 assemble 即可）");
