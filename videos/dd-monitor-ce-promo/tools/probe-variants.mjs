// 变体探针：同一个 composition、同一时刻，逐个注入一小段 CSS 后各截一张图。
// 用来二分定位「绘制被裁切」这类问题 —— DOM 的 getBoundingClientRect 只反映几何，
// 绘制裁剪只能靠像素看。
//
// 用法：node tools/probe-variants.mjs tools/variants.json
// 变体定义（JSON）：
//   { "comp": "compositions/v3/18-01-intro.html", "at": 3.9,
//     "variants": [ { "name": "baseline", "css": "" }, ... ] }
// 输出：raw/_var-<name>.png（用 tools/probe-shot.ps1 分析边界）
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { writeFileSync } from "node:fs";
import { spawn } from "node:child_process";
import { extname, join, resolve } from "node:path";

const cfgPath = process.argv[2] || "tools/variants.json";
const cfg = JSON.parse(await readFile(cfgPath, "utf8"));
const comp = cfg.comp || "compositions/v3/18-01-intro.html";
const AT = Number(cfg.at ?? 3.9);
const variants = cfg.variants || [{ name: "baseline", css: "" }];
const SELS = cfg.sels || [];

const ROOT = resolve(".");
const PORT = 8952;
const CHROME = process.env.CHROME_PATH || "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const TYPES = {
  ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8", ".png": "image/png", ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg", ".svg": "image/svg+xml", ".mp4": "video/mp4", ".webp": "image/webp",
};

const server = createServer(async (req, res) => {
  try {
    const url = new URL(req.url, "http://x");
    let p = decodeURIComponent(url.pathname).split(/[/\\]+/).filter(Boolean).join("/");
    if (p === "") p = "index.html";
    const cands = [join(ROOT, p)];
    const m = p.match(/^(?:compositions|frames|lib)\/[^/]+\/(.+)$/);
    if (m) cands.push(join(ROOT, m[1]));
    let body = null;
    for (const c of cands) { try { body = await readFile(c); break; } catch { /* next */ } }
    if (!body) { res.writeHead(404); res.end("404 " + p); return; }
    res.writeHead(200, { "content-type": TYPES[extname(p).toLowerCase()] || "application/octet-stream", "cache-control": "no-store" });
    res.end(body);
  } catch { res.writeHead(404); res.end("404"); }
});
await new Promise((ok) => server.listen(PORT, "127.0.0.1", ok));

const child = spawn(CHROME, [
  "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
  "--disable-extensions", "--hide-scrollbars", "--window-size=1920,1080",
  "--remote-debugging-port=9352",
  "--user-data-dir=" + (process.env.TEMP || ".") + "\\probe-var-p2",
  "about:blank",
], { stdio: "ignore" });

async function waitCdp() {
  for (let i = 0; i < 60; i++) {
    try {
      const j = await (await fetch("http://127.0.0.1:9352/json/list")).json();
      const p = j.find((t) => t.type === "page");
      if (p) return p;
    } catch { /* not ready */ }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error("CDP 未就绪");
}
async function connect(page) {
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  const pend = new Map(); let id = 0;
  ws.addEventListener("message", (ev) => {
    const m = JSON.parse(ev.data);
    if (m.id && pend.has(m.id)) { const p = pend.get(m.id); pend.delete(m.id); m.error ? p.bad(new Error(JSON.stringify(m.error))) : p.ok(m.result); }
  });
  const send = (method, params = {}) => new Promise((ok, bad) => { const i = ++id; pend.set(i, { ok, bad }); ws.send(JSON.stringify({ id: i, method, params })); });
  return new Promise((ok, bad) => { ws.addEventListener("open", () => ok(send), { once: true }); ws.addEventListener("error", bad, { once: true }); });
}

let code = 0;
try {
  const page = await waitCdp();
  const send = await connect(page);
  await send("Page.enable"); await send("Runtime.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 1920, height: 1080, deviceScaleFactor: 1, mobile: false });
  await send("Page.navigate", { url: `http://127.0.0.1:${PORT}/${comp}` });

  let ready = false;
  for (let i = 0; i < 40; i++) {
    await new Promise((r) => setTimeout(r, 400));
    const r = await send("Runtime.evaluate", { expression: "Object.keys(window.__timelines||{}).length", returnByValue: true }).catch(() => null);
    if (r?.result?.value > 0) { ready = true; break; }
  }
  console.log(`时间轴就绪: ${ready ? "是" : "否"}   at=${AT}s`);

  for (const v of variants) {
    const at = Number(v.at ?? AT);
    // 先清掉上一轮的注入，再 seek（seek 会重算所有补间，注入的 CSS 不参与补间）
    await send("Runtime.evaluate", {
      expression: `(() => {
        document.querySelectorAll('style[data-probe]').forEach(e => e.remove());
        const s = document.createElement('style'); s.setAttribute('data-probe','1');
        s.textContent = ${JSON.stringify(v.css || "")};
        document.head.appendChild(s);
        const k = Object.keys(window.__timelines||{})[0];
        if (k) { window.__timelines[k].pause(); window.__timelines[k].seek(${at}, false); }
        return true;
      })()`, returnByValue: true,
    });
    await new Promise((r) => setTimeout(r, 260));
    if (SELS.length) {
      const info = await send("Runtime.evaluate", {
        expression: `JSON.stringify(${JSON.stringify(SELS)}.map(s => {
          const e = document.querySelector(s);
          if (!e) return s + "=MISSING";
          const cs = getComputedStyle(e); const r = e.getBoundingClientRect();
          return s + " o=" + (+cs.opacity).toFixed(2) + " box=" + Math.round(r.x) + "," + Math.round(r.y) + " " + Math.round(r.width) + "x" + Math.round(r.height);
        }))`, returnByValue: true,
      });
      console.log(`    ${JSON.parse(info.result.value).join("  |  ")}`);
    }
    const shot = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
    const out = `raw/_var-${v.name}.png`;
    writeFileSync(out, Buffer.from(shot.data, "base64"));
    console.log(`  ${v.name.padEnd(24)} -> ${out}`);
  }
} catch (e) {
  console.error("✗ " + e.message); code = 1;
} finally {
  try { child.kill(); } catch { /* ignore */ }
  server.close();
}
process.exit(code);
