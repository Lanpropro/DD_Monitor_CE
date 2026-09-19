// Throwaway frame verifier — spawns its own headless Chrome and drives it over CDP.
import { writeFileSync } from "node:fs";
import { spawn } from "node:child_process";

const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const PORT = 9333;
const BASE = "http://127.0.0.1:8931/.hyperframes/view-03.html";
const OUT = ".hyperframes/probe";
const TIMES = (process.argv[2] || "0.4,1.6,2.3,3.4").split(",").map(Number);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const chrome = spawn(
  CHROME,
  [
    "--headless=new",
    "--disable-gpu",
    "--hide-scrollbars",
    "--autoplay-policy=no-user-gesture-required",
    "--window-size=1920,1080",
    `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${process.env.TEMP}\\hfverify`,
    "about:blank",
  ],
  { stdio: "ignore", detached: false },
);

async function connect() {
  for (let i = 0; i < 60; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
      const page = list.find((t) => t.type === "page" && t.webSocketDebuggerUrl);
      if (page) {
        const ws = new WebSocket(page.webSocketDebuggerUrl);
        await new Promise((ok, bad) => {
          ws.addEventListener("open", ok, { once: true });
          ws.addEventListener("error", bad, { once: true });
        });
        return ws;
      }
    } catch {}
    await sleep(250);
  }
  throw new Error("could not attach to Chrome");
}

const ws = await connect();
let id = 0;
const pending = new Map();
const logs = [];
ws.addEventListener("message", (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) {
    const { ok, bad } = pending.get(m.id);
    pending.delete(m.id);
    m.error ? bad(new Error(JSON.stringify(m.error))) : ok(m.result);
  }
  if (m.method === "Runtime.exceptionThrown")
    logs.push("EXC " + (m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text));
  if (m.method === "Runtime.consoleAPICalled")
    logs.push("CON " + m.params.args.map((a) => a.value ?? a.description).join(" "));
  if (m.method === "Network.loadingFailed") logs.push("NETFAIL " + m.params.errorText);
});
const send = (method, params = {}) =>
  new Promise((ok, bad) => {
    const i = ++id;
    pending.set(i, { ok, bad });
    ws.send(JSON.stringify({ id: i, method, params }));
  });

await send("Page.enable");
await send("Runtime.enable");

const PROBE = `(function(){
  const tl = window.__timelines && window.__timelines["03-layout-1to4"];
  const box = (sel) => { const e = document.querySelector(sel); if (!e) return null; const r = e.getBoundingClientRect(); return [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)]; };
  const vid = document.querySelector(".ddf03-plate");
  return JSON.stringify({
    title: document.title,
    hasTl: !!tl, dur: tl ? +tl.duration().toFixed(3) : null,
    field: box(".ddf03-field"), chip: box(".ddf03-chip"), win: box(".ddf03-window"),
    head: box(".ddf03-head"), sub: box(".ddf03-sub"),
    headText: (document.querySelector(".ddf03-head")||{}).textContent,
    fieldBg: (function(){const e=document.querySelector(".ddf03-field");return e?getComputedStyle(e).backgroundColor:null;})(),
    vReady: vid ? vid.readyState : null, vSize: vid ? [vid.videoWidth, vid.videoHeight] : null,
    vRect: vid ? (function(){const r=vid.getBoundingClientRect();return [Math.round(r.x),Math.round(r.y),Math.round(r.width),Math.round(r.height)];})() : null
  });
})()`;

for (const t of TIMES) {
  await send("Page.navigate", { url: `${BASE}?t=${t}` });
  await sleep(1500);
  const r = await send("Runtime.evaluate", { expression: PROBE, returnByValue: true });
  console.log(`--- t=${t} ---`);
  console.log(r.result.value);
  const shot = await send("Page.captureScreenshot", { format: "png" });
  writeFileSync(`${OUT}/cdp-${t}.png`, Buffer.from(shot.data, "base64"));
}
if (logs.length) console.log("LOGS:\n" + logs.slice(0, 20).join("\n"));
try { chrome.kill(); } catch {}
process.exit(0);
