// 静态服务器 + Chrome/CDP 真实探针。
//
// 为什么需要它：靠渲染 mp4 再反推像素太慢，而且 file:// 打开时相对路径的图片
// 加载不了（假象）。这个工具在项目根起一个静态服务器，让 Chrome 正常加载资源，
// 把时间轴 seek 到指定时刻，然后一次性读回：
//   · 每个选择器的真实几何（getBoundingClientRect）
//   · 图片是否加载成功（naturalWidth）
//   · 可选截图（用于逐像素核对）
//
// 用法：
//   node tools/probe-dom.mjs <composition相对路径> --at 3.5 [--shot out.png] [--sel .a .b]
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { writeFileSync } from "node:fs";
import { spawn } from "node:child_process";
import { extname, join, normalize, resolve } from "node:path";

const argv = process.argv.slice(2);
const comp = argv[0] || "compositions/v3/18-01-intro.html";
const flag = (name, def) => {
  const i = argv.indexOf(name);
  return i >= 0 && argv[i + 1] ? argv[i + 1] : def;
};
const AT = Number(flag("--at", "0"));
const SHOT = flag("--shot", "");
const SELS = (() => {
  const i = argv.indexOf("--sel");
  if (i < 0) return [".appstage", ".appwin", ".pt-sb", ".pt-main", ".pt-s20"];
  const out = [];
  for (let k = i + 1; k < argv.length && !argv[k].startsWith("--"); k++) out.push(argv[k]);
  return out.length ? out : [".appstage", ".appwin"];
})();

const ROOT = resolve(".");
const PORT = 8951;
const CHROME = process.env.CHROME_PATH || "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const TYPES = {
  ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8", ".png": "image/png", ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg", ".svg": "image/svg+xml", ".mp4": "video/mp4", ".webp": "image/webp",
};

const server = createServer(async (req, res) => {
  try {
    const url = new URL(req.url, "http://x");
    // ⚠ Windows 上 normalize() 会把 "/" 变成 "\"，后面按 "/" 写的回退正则就永远匹配不到，
    // 结果所有 assets/... 都 404（页面里 gsap 都没加载，几何全是未变换的假象）。
    // 所以先把路径统一成 "/" 分隔再处理。
    let p = decodeURIComponent(url.pathname).split(/[/\\]+/).filter(Boolean).join("/");
    if (p === "") p = "index.html";
    // composition 里的相对路径（assets/...）是相对**项目根**写的，
    // 而浏览器会相对当前文档目录解析。这里做一次回退：找不到就试项目根。
    const cands = [join(ROOT, p)];
    const m = p.match(/^(?:compositions|frames|lib)\/[^/]+\/(.+)$/);
    if (m) cands.push(join(ROOT, m[1]));
    let body = null;
    for (const c of cands) {
      try { body = await readFile(c); break; } catch { /* try next */ }
    }
    if (!body) { res.writeHead(404); res.end("404 " + p); return; }
    res.writeHead(200, { "content-type": TYPES[extname(p).toLowerCase()] || "application/octet-stream", "cache-control": "no-store" });
    res.end(body);
  } catch {
    res.writeHead(404); res.end("404");
  }
});
await new Promise((ok) => server.listen(PORT, "127.0.0.1", ok));
console.log(`静态服务 http://127.0.0.1:${PORT}  (root=${ROOT})`);

const child = spawn(CHROME, [
  "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
  "--disable-extensions", "--hide-scrollbars",
  "--window-size=1920,1080",
  `--remote-debugging-port=9351`,
  "--user-data-dir=" + (process.env.TEMP || ".") + "\\probe-dom-p2",
  "about:blank",
], { stdio: "ignore" });

async function waitCdp() {
  for (let i = 0; i < 60; i++) {
    try {
      const j = await (await fetch("http://127.0.0.1:9351/json/list")).json();
      const p = j.find((t) => t.type === "page");
      if (p) return p;
    } catch { /* not ready */ }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error("CDP 未就绪");
}
function connect(page, onEvent) {
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  const pend = new Map(); let id = 0;
  ws.addEventListener("message", (ev) => {
    const m = JSON.parse(ev.data);
    if (m.id && pend.has(m.id)) { const p = pend.get(m.id); pend.delete(m.id); m.error ? p.bad(new Error(JSON.stringify(m.error))) : p.ok(m.result); return; }
    if (onEvent && m.method) onEvent(m);
  });
  const send = (method, params = {}) => new Promise((ok, bad) => { const i = ++id; pend.set(i, { ok, bad }); ws.send(JSON.stringify({ id: i, method, params })); });
  return new Promise((ok, bad) => { ws.addEventListener("open", () => ok(send), { once: true }); ws.addEventListener("error", bad, { once: true }); });
}

let code = 0;
try {
  const page = await waitCdp();
  // 收集页面运行期错误：之前"timelines 空 / gsap undefined"只能说明脚本没执行，
  // 真正的原因（404、语法错误、图片没加载）必须从控制台里读出来。
  const pageErrors = [];
  const send = await connect(page, (m) => {
    if (m.method === "Log.entryAdded" && m.params.entry.level === "error") pageErrors.push(m.params.entry.text);
    if (m.method === "Runtime.exceptionThrown") pageErrors.push(m.params.exceptionDetails.text + " " + (m.params.exceptionDetails.exception?.description || ""));
  });
  await send("Page.enable"); await send("Runtime.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1920, height: 1080, deviceScaleFactor: 1, mobile: false });
  await send("Log.enable").catch(() => {});
  await send("Page.navigate", { url: `http://127.0.0.1:${PORT}/${comp}` });

  // 轮询等待时间轴注册完成，而不是死等固定毫秒
  let ready = false;
  for (let i = 0; i < 40; i++) {
    await new Promise((r) => setTimeout(r, 400));
    const r2 = await send("Runtime.evaluate", {
      expression: "Object.keys(window.__timelines || {}).length",
      returnByValue: true,
    }).catch(() => null);
    if (r2 && r2.result && r2.result.value > 0) { ready = true; break; }
  }
  console.log(`时间轴就绪: ${ready ? "是" : "否（超时）"}`);
  if (pageErrors.length) console.log("页面错误:\n  " + pageErrors.join("\n  "));

  const expr = `(() => {
    const sels = ${JSON.stringify(SELS)};
    const out = { timelines: Object.keys(window.__timelines || {}), gsap: typeof window.gsap, at: ${AT} };
    // 把时间轴 seek 到目标时刻
    const key = Object.keys(window.__timelines || {})[0];
    if (key) { window.__timelines[key].pause(); window.__timelines[key].seek(${AT}, false); }
    out.seeked = key || null;
    out.items = sels.map(s => {
      const el = document.querySelector(s);
      if (!el) return { sel: s, missing: true };
      const r = el.getBoundingClientRect();
      const cs = getComputedStyle(el);
      return { sel: s, x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height),
               transform: cs.transform === 'none' ? 'none' : cs.transform.slice(0, 60),
               opacity: cs.opacity };
    });
    out.imgs = Array.from(document.images).map(i => ({ src: i.getAttribute('src'), nat: i.naturalWidth + 'x' + i.naturalHeight, ok: i.complete && i.naturalWidth > 0 }));
    return JSON.stringify(out);
  })()`;
  const res = await send("Runtime.evaluate", { expression: expr, returnByValue: true });
  const d = JSON.parse(res.result.value);
  console.log(`timelines: ${d.timelines.join(",")}   gsap: ${d.gsap}   seek->${d.at}s (${d.seeked})`);
  console.log("\n几何:");
  for (const it of d.items) console.log("  " + JSON.stringify(it));
  console.log("\n图片:");
  for (const im of d.imgs) console.log(`  ${im.ok ? "OK  " : "FAIL"} ${String(im.nat).padEnd(10)} ${im.src}`);

  if (SHOT) {
    const shot = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
    writeFileSync(SHOT, Buffer.from(shot.data, "base64"));
    console.log(`\n截图 -> ${SHOT}`);
  }
} catch (e) {
  console.error("✗ " + e.message); code = 1;
} finally {
  try { child.kill(); } catch { /* ignore */ }
  server.close();
}
process.exit(code);
