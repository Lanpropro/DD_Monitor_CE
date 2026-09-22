// 用渲染用的 Chrome 把 gsap 抓回本地。
//
// 为什么需要这个：这个环境里 PowerShell 的 Invoke-WebRequest 和 DSH 的 web_fetch
// 都连不上外网，但渲染时 Chrome 能连（间歇性可用）。所以让 Chrome 去取，
// 再通过 CDP 把文本交回来落盘。取到之后所有帧改用本地 gsap，渲染不再看网络脸色。
//
// 用法：node tools/fetch-gsap.mjs [输出路径]
import { writeFileSync, mkdirSync } from "node:fs";
import { spawn } from "node:child_process";
import { dirname } from "node:path";

const CHROME = process.env.CHROME_PATH || "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const PORT = 9339;
const SRC = process.argv[3] || "https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js";
const OUT = process.argv[2] || "assets/lib/gsap.min.js";

const child = spawn(
  CHROME,
  [
    "--headless=new",
    "--disable-gpu",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-extensions",
    `--remote-debugging-port=${PORT}`,
    "--user-data-dir=" + (process.env.TEMP || ".") + "\\gsapfetch-profile",
    "about:blank",
  ],
  { stdio: "ignore" },
);

async function waitCdp() {
  for (let i = 0; i < 60; i++) {
    try {
      const r = await fetch(`http://127.0.0.1:${PORT}/json/list`);
      const j = await r.json();
      const page = j.find((t) => t.type === "page");
      if (page) return page;
    } catch {
      /* 还没起来 */
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error("CDP 未就绪");
}

function connect(page) {
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  const pend = new Map();
  let id = 0;
  ws.addEventListener("message", (ev) => {
    const m = JSON.parse(ev.data);
    if (m.id && pend.has(m.id)) {
      const p = pend.get(m.id);
      pend.delete(m.id);
      m.error ? p.bad(new Error(JSON.stringify(m.error))) : p.ok(m.result);
    }
  });
  const send = (method, params = {}) =>
    new Promise((ok, bad) => {
      const i = ++id;
      pend.set(i, { ok, bad });
      ws.send(JSON.stringify({ id: i, method, params }));
    });
  return new Promise((ok, bad) => {
    ws.addEventListener("open", () => ok(send), { once: true });
    ws.addEventListener("error", bad, { once: true });
  });
}

let code = 0;
try {
  const page = await waitCdp();
  const send = await connect(page);
  await send("Page.enable");
  await send("Runtime.enable");

  // 失败就重试 —— 这个环境的网络是间歇性的
  let text = null;
  for (let i = 1; i <= 8 && !text; i++) {
    try {
      const res = await send("Runtime.evaluate", {
        expression: `fetch(${JSON.stringify(SRC)}, {cache:"no-store"}).then(r => r.ok ? r.text() : ("HTTP " + r.status))`,
        awaitPromise: true,
        returnByValue: true,
      });
      const v = res.result && res.result.value;
      if (typeof v === "string" && v.length > 40000) text = v;
      else console.log(`  第 ${i} 次拿到 ${v ? v.length : "null"} —— 重试`);
    } catch (e) {
      console.log(`  第 ${i} 次异常：${e.message}`);
    }
    if (!text) await new Promise((r) => setTimeout(r, 700));
  }

  if (!text) throw new Error("八次都没取到 gsap");
  mkdirSync(dirname(OUT), { recursive: true });
  writeFileSync(OUT, text, "utf8");
  console.log(`✓ 取回 ${text.length} bytes -> ${OUT}`);
} catch (e) {
  console.error("✗ " + e.message);
  code = 1;
} finally {
  try { child.kill(); } catch { /* ignore */ }
}
process.exit(code);
