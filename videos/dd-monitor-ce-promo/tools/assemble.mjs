// 唯一正确的组装入口 —— 把 restore 和 assemble 焊在一起。
//
// 为什么必须这样：
//   assemble-index.mjs 的 approved-video 提升是**破坏性**的：它把 <video> 从帧文件里
//   摘走、换成一行注释，再挂到 index.html 的宿主根。所以直接重复跑 assemble 时，
//   帧里已经没有被提升的视频了，会生成一个**没有视频的 index**（全片窗口黑屏）。
//   这个坑我踩过两次，所以不再手敲两步：只用这个脚本。
//
// 顺序：restore-videos（把视频注回帧） -> assemble-index（提升并挂载） -> 自检
//
// 用法：node tools/assemble.mjs <projectDir> <productLaunchVideoSkillDir>

import { execFileSync } from "node:child_process";
import { readFileSync, existsSync } from "node:fs";
import { join, resolve } from "node:path";

const proj = resolve(process.argv[2] ?? ".");
const skill = process.argv[3];
if (!skill || !existsSync(skill)) {
  console.error("用法：node tools/assemble.mjs <projectDir> <product-launch-video skill 目录>");
  process.exit(1);
}

const run = (label, file, args) => {
  console.log(`\n── ${label} ──`);
  const out = execFileSync(process.execPath, [file, ...args], { cwd: proj, encoding: "utf8" });
  console.log(out.trim());
  return out;
};

run("1/2 把 approved 视频注回帧文件", join(proj, "tools/restore-videos.mjs"), [proj]);

const assembly = run("2/2 组装 index.html（提升视频 + 挂音频）", join(skill, "scripts/assemble-index.mjs"), [
  "--storyboard", join(proj, "STORYBOARD.md"),
  "--hyperframes", proj,
  "--audio-meta", join(proj, "audio_meta.json"),
]);

// 自检：帧数和挂进 index 的视频数必须对得上，否则就是在黑屏
const framesDir = join(proj, "compositions/frames");
const expectedVideos = Number(
  readFileSync(join(proj, "tools/restore-videos.mjs"), "utf8").match(/const PLAN = \[([\s\S]*?)\n\];/)[1]
    .match(/\{ f: "/g).length,
);
const html = readFileSync(join(proj, "index.html"), "utf8");
const actualVideos = (html.match(/<video/g) || []).length;
const actualSfx = (html.match(/<audio/g) || []).length;

console.log(`\n── 自检 ──`);
console.log(`  帧目录：${existsSync(framesDir) ? "存在" : "缺失"}`);
console.log(`  index 里的 <video>：${actualVideos}（期望 ${expectedVideos}）`);
console.log(`  index 里的 <audio>：${actualSfx}`);

if (actualVideos !== expectedVideos) {
  console.error(`\n✗ 视频数量不对 —— 渲染出来会是黑屏。检查 restore-videos.mjs 的 PLAN 与帧文件是否匹配。`);
  process.exit(1);
}
console.log(`\n✓ 组装完成，视频与音频都已挂上。`);
