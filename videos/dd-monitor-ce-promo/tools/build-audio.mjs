// 把内置音效铺到分镜上，生成 audio_meta.json。
//
// 为什么要自己写这一步：本片没有口播，走的是"BGM + 字幕卡"路线，
// 而 audio.mjs 在无 HeyGen 凭证时会把 BGM 整个禁用掉（它只试检索、没有回退），
// SFX 也不会自动铺。所以这里显式做两件事：
//   1) 把内置 SFX 拷进 assets/sfx/
//   2) 按分镜 Scene 的时间码生成 sfx 线索表，并把自带的 BGM 写进 bgm 字段
//
// 时间码来源：STORYBOARD.md 各拍 Scene 行（帧内偏移秒）。
//
// 用法：node build-audio.mjs <projectDir> <bundledSfxDir>
import { copyFileSync, existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { join } from "node:path";

const proj = process.argv[2] ?? ".";
const bundled = process.argv[3];
if (!bundled || !existsSync(bundled)) {
  console.error("用法：node build-audio.mjs <projectDir> <bundledSfxDir>");
  process.exit(1);
}

// 帧号 -> 帧起点（STORYBOARD.md 的时长核算）
const FRAME_START = {
  1: 0, 2: 6.0, 3: 10.5, 4: 14.0, 5: 17.5, 6: 21.0, 7: 24.5, 8: 30.0,
  9: 33.5, 10: 37.0, 11: 40.5, 12: 44.0, 13: 47.5, 14: 51.0, 15: 55.5,
};

// [帧号, 帧内偏移秒, 音效名, 音量]
const CUES = [
  // 01 墙面逐格亮起：pop 密度递增，最后整墙亮完一声 whoosh
  [1, 0.45, "pop", 0.30], [1, 0.87, "pop", 0.30], [1, 1.25, "pop", 0.32],
  [1, 1.62, "pop", 0.32], [1, 1.95, "pop", 0.34], [1, 2.25, "pop", 0.34],
  [1, 2.53, "pop", 0.36], [1, 2.79, "pop", 0.36], [1, 3.03, "pop", 0.38],
  [1, 3.25, "pop", 0.38], [1, 3.45, "pop", 0.40], [1, 3.63, "pop", 0.40],
  [1, 3.79, "pop", 0.42], [1, 3.93, "pop", 0.42], [1, 4.06, "pop", 0.44],
  [1, 4.18, "pop", 0.44], [1, 4.63, "whoosh-cinematic", 0.50],
  // 02 标题：字替 + 落定
  [2, 1.40, "whoosh-short", 0.55], [2, 2.60, "impact-bass-1", 0.48],
  // 03–06 蓝色布局整段
  [3, 0.80, "whoosh-short", 0.45], [3, 1.10, "click-soft", 0.40],
  [4, 0.80, "click-soft", 0.34], [4, 1.10, "click-soft", 0.34],
  [4, 1.40, "click-soft", 0.34], [4, 1.80, "whoosh-short", 0.42],
  [5, 0.80, "click-soft", 0.38], [5, 1.00, "pop", 0.30], [5, 1.25, "pop", 0.30],
  [5, 1.50, "pop", 0.30], [5, 1.75, "pop", 0.30], [5, 2.00, "pop", 0.30],
  [6, 0.80, "click-soft", 0.38], [6, 1.50, "whoosh-short", 0.44],
  // 07 竖屏（全片最长的一拍）
  [7, 1.70, "whoosh-cinematic", 0.50], [7, 2.60, "riser", 0.42], [7, 4.10, "impact-bass-1", 0.52],
  // 08–11 近白场细节段
  [8, 0.90, "whoosh-short", 0.42], [8, 1.20, "click-soft", 0.36],
  [8, 1.70, "click-soft", 0.36], [8, 2.10, "click-soft", 0.36],
  [9, 0.90, "click-soft", 0.36], [9, 1.50, "pop", 0.34], [9, 2.40, "whoosh-short", 0.40],
  [10, 0.86, "click-soft", 0.38], [10, 1.28, "ping", 0.34],
  [10, 1.56, "click-soft", 0.34], [10, 1.84, "pop", 0.34],
  [11, 0.50, "whoosh-short", 0.40], [11, 0.85, "ping", 0.38], [11, 1.35, "ping", 0.38],
  // 12 断流重连
  [12, 0.90, "error", 0.42], [12, 0.95, "riser", 0.36], [12, 2.10, "chime", 0.46],
  // 13 插件
  [13, 0.90, "typing", 0.30], [13, 1.86, "click-soft", 0.36], [13, 2.38, "click-soft", 0.36],
  // 14 宣言（held frame）
  [14, 1.50, "chime", 0.44], [14, 2.04, "impact-bass-2", 0.42],
  // 15 片尾 logo 拼装
  [15, 0.35, "whoosh-short", 0.38], [15, 0.55, "whoosh-short", 0.38],
  [15, 0.75, "whoosh-short", 0.38], [15, 1.20, "riser", 0.44],
  [15, 1.60, "chime", 0.48], [15, 2.60, "whoosh-cinematic", 0.46],
];

// 音效时长（秒），用于写 duration_s；取实际文件时长
function sfxDuration(path) {
  try {
    const out = execFileSync("ffprobe", [
      "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path,
    ], { encoding: "utf8" });
    return Math.round(parseFloat(out.trim()) * 1000) / 1000;
  } catch {
    return 0.6;
  }
}

const sfxDir = join(proj, "assets/sfx");
mkdirSync(sfxDir, { recursive: true });

const needed = [...new Set(CUES.map((c) => c[2]))];
const durations = {};
const missing = [];
for (const name of needed) {
  const from = join(bundled, `${name}.mp3`);
  if (!existsSync(from)) {
    missing.push(name);
    continue;
  }
  const to = join(sfxDir, `${name}.mp3`);
  if (!existsSync(to)) copyFileSync(from, to);
  durations[name] = sfxDuration(to);
}
if (missing.length) {
  console.error(`!! 内置音效里找不到：${missing.join(", ")}`);
  process.exit(1);
}

const sfx = CUES.map(([frame, offset, name, volume]) => ({
  frame,
  file: `assets/sfx/${name}.mp3`,
  offset_s: offset,
  duration_s: durations[name],
  volume,
}));

// BGM：用自己生成的曲子。响度 -17 LUFS，比参考片低约 1.7dB，用音量补一点。
const bgmPath = "assets/bgm/track.wav";
const meta = {
  bgm: existsSync(join(proj, bgmPath))
    ? { path: bgmPath, volume: 1.2, mode: "local", query: "driving electronic, 129 BPM" }
    : null,
  bgm_pending: false,
  voices: [],
  sfx,
};

writeFileSync(join(proj, "audio_meta.json"), JSON.stringify(meta, null, 2) + "\n", "utf8");

console.log(`音效文件 ${needed.length} 个 -> assets/sfx/`);
console.log(`SFX 线索 ${sfx.length} 条，覆盖 ${new Set(CUES.map((c) => c[0])).size} 帧`);
console.log(`BGM: ${meta.bgm ? meta.bgm.path + " (volume " + meta.bgm.volume + ")" : "无"}`);
console.log(`写出 audio_meta.json`);
