import { spawn } from "node:child_process";
const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const PORT = 9351;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const chrome = spawn(CHROME, ["--headless=new", "--disable-gpu", "--window-size=1920,1080",
  `--remote-debugging-port=${PORT}`, `--user-data-dir=${process.env.TEMP}\\hffont`, "about:blank"], { stdio: "ignore" });
async function attach() {
  for (let i = 0; i < 60; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
      const p = list.find((t) => t.type === "page" && t.webSocketDebuggerUrl);
      if (p) { const ws = new WebSocket(p.webSocketDebuggerUrl); await new Promise((ok, bad) => { ws.addEventListener("open", ok, { once: true }); ws.addEventListener("error", bad, { once: true }); }); return ws; }
    } catch {}
    await sleep(250);
  }
  throw new Error("no chrome");
}
const ws = await attach();
let id = 0; const pending = new Map();
ws.addEventListener("message", (ev) => { const m = JSON.parse(ev.data); if (m.id && pending.has(m.id)) { const { ok, bad } = pending.get(m.id); pending.delete(m.id); m.error ? bad(new Error(JSON.stringify(m.error))) : ok(m.result); } });
const send = (method, params = {}) => new Promise((ok, bad) => { const i = ++id; pending.set(i, { ok, bad }); ws.send(JSON.stringify({ id: i, method, params })); });
await send("DOM.enable"); await send("CSS.enable"); await send("Page.enable"); await send("Runtime.enable");
await send("Page.navigate", { url: "http://127.0.0.1:8931/.hyperframes/view-03.html?t=3.45" });
await sleep(2200);
const doc = await send("DOM.getDocument", { depth: -1 });
const find = async (sel) => {
  const r = await send("DOM.querySelector", { nodeId: doc.root.nodeId, selector: sel });
  return r.nodeId;
};
for (const sel of [".ddf03-head", ".ddf03-sub"]) {
  const nodeId = await find(sel);
  const fonts = await send("CSS.getPlatformFontsForNode", { nodeId });
  console.log(sel, JSON.stringify(fonts.fonts));
}
try { chrome.kill(); } catch {}
process.exit(0);
