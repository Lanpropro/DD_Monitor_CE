// Throwaway frame verifier: drives headless Chrome over CDP (no npm deps).
import { writeFileSync } from "node:fs";

const PORT = Number(process.argv[2] || 9223);
const URL_BASE = process.argv[3] || "http://127.0.0.1:8931/.hyperframes/view-03.html";
const OUT_DIR = process.argv[4] || ".hyperframes/probe";
const TIMES = (process.argv[5] || "0.4,1.6,2.3,3.4").split(",").map(Number);

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function targets() {
  const r = await fetch(`http://127.0.0.1:${PORT}/json/list`);
  return r.json();
}

class Cdp {
  constructor(ws) {
    this.ws = ws;
    this.id = 0;
    this.pending = new Map();
    ws.addEventListener("message", (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id && this.pending.has(msg.id)) {
        const { ok, bad } = this.pending.get(msg.id);
        this.pending.delete(msg.id);
        msg.error ? bad(new Error(JSON.stringify(msg.error))) : ok(msg.result);
      }
    });
  }
  send(method, params = {}) {
    const id = ++this.id;
    return new Promise((ok, bad) => {
      this.pending.set(id, { ok, bad });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }
}

async function connect() {
  for (let i = 0; i < 40; i++) {
    try {
      const list = await targets();
      const page = list.find((t) => t.type === "page" && t.webSocketDebuggerUrl);
      if (page) {
        const ws = new WebSocket(page.webSocketDebuggerUrl);
        await new Promise((ok, bad) => {
          ws.addEventListener("open", ok, { once: true });
          ws.addEventListener("error", bad, { once: true });
        });
        return new Cdp(ws);
      }
    } catch {}
    await sleep(250);
  }
  throw new Error("could not attach to Chrome");
}

const cdp = await connect();
await cdp.send("Page.enable");
await cdp.send("Runtime.enable");
await cdp.send("Log.enable");

const logs = [];
cdp.ws.addEventListener("message", (ev) => {
  const m = JSON.parse(ev.data);
  if (m.method === "Runtime.consoleAPICalled") {
    logs.push("console: " + m.params.args.map((a) => a.value ?? a.description ?? a.type).join(" "));
  }
  if (m.method === "Runtime.exceptionThrown") {
    logs.push("exception: " + (m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text));
  }
  if (m.method === "Log.entryAdded") logs.push(`log[${m.params.entry.level}]: ${m.params.entry.text}`);
});

for (const t of TIMES) {
  const url = `${URL_BASE}?t=${t}`;
  await cdp.send("Page.navigate", { url });
  await sleep(1200);
  const probe = await cdp.send("Runtime.evaluate", {
    expression: `(function(){
      const tl = window.__timelines && window.__timelines["03-layout-1to4"];
      const root = document.getElementById("root");
      const field = document.querySelector(".ddf03-field");
      const win = document.querySelector(".ddf03-window");
      const vid = document.querySelector(".ddf03-plate");
      const cs = (el) => el ? getComputedStyle(el) : null;
      return JSON.stringify({
        title: document.title,
        hasTl: !!tl,
        tlDur: tl ? tl.duration() : null,
        tlPaused: tl ? tl.paused() : null,
        rootW: root ? root.getBoundingClientRect().width : null,
        cqw: field ? getComputedStyle(field).width : null,
        fieldBg: cs(field) ? cs(field).backgroundColor : null,
        winRect: win ? [Math.round(win.getBoundingClientRect().x), Math.round(win.getBoundingClientRect().y), Math.round(win.getBoundingClientRect().width), Math.round(win.getBoundingClientRect().height)] : null,
        chipRect: (function(){ const c = document.querySelector(".ddf03-chip"); return c ? [Math.round(c.getBoundingClientRect().x), Math.round(c.getBoundingClientRect().y), Math.round(c.getBoundingClientRect().width), Math.round(c.getBoundingClientRect().height)] : null; })(),
        headRect: (function(){ const c = document.querySelector(".ddf03-head"); return c ? [Math.round(c.getBoundingClientRect().x), Math.round(c.getBoundingClientRect().y), Math.round(c.getBoundingClientRect().width), Math.round(c.getBoundingClientRect().height)] : null; })(),
        subRect: (function(){ const c = document.querySelector(".ddf03-sub"); return c ? [Math.round(c.getBoundingClientRect().x), Math.round(c.getBoundingClientRect().y), Math.round(c.getBoundingClientRect().width), Math.round(c.getBoundingClientRect().height)] : null; })(),
        videoReady: vid ? vid.readyState : null,
        videoSize: vid ? [vid.videoWidth, vid.videoHeight] : null
      });
    })()`,
    returnByValue: true,
  });
  console.log(`--- t=${t} ---`);
  console.log(probe.result.value);
  const shot = await cdp.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
  writeFileSync(`${OUT_DIR}/cdp-${t}.png`, Buffer.from(shot.data, "base64"));
}

if (logs.length) console.log("LOGS:\n" + logs.join("\n"));
process.exit(0);
