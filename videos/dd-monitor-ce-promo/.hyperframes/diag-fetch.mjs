import { spawn } from "node:child_process";
const CHROME = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const PORT = 9341;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const chrome = spawn(
  CHROME,
  ["--headless=new", "--disable-gpu", "--window-size=1920,1080", `--remote-debugging-port=${PORT}`,
   `--user-data-dir=${process.env.TEMP}\\hfdiag`, "about:blank"],
  { stdio: "ignore" },
);
async function attach() {
  for (let i = 0; i < 60; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
      const p = list.find((t) => t.type === "page" && t.webSocketDebuggerUrl);
      if (p) {
        const ws = new WebSocket(p.webSocketDebuggerUrl);
        await new Promise((ok, bad) => { ws.addEventListener("open", ok, { once: true }); ws.addEventListener("error", bad, { once: true }); });
        return ws;
      }
    } catch {}
    await sleep(250);
  }
  throw new Error("no chrome");
}
const ws = await attach();
let id = 0; const pending = new Map();
ws.addEventListener("message", (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) { const { ok, bad } = pending.get(m.id); pending.delete(m.id); m.error ? bad(new Error(JSON.stringify(m.error))) : ok(m.result); }
});
const send = (method, params = {}) => new Promise((ok, bad) => { const i = ++id; pending.set(i, { ok, bad }); ws.send(JSON.stringify({ id: i, method, params })); });
await send("Page.enable"); await send("Runtime.enable");
await send("Page.navigate", { url: "http://127.0.0.1:8931/.hyperframes/view-03.html?t=3.4" });
await sleep(2000);
const out = await send("Runtime.evaluate", {
  expression: `(async () => {
    const a = await fetch('compositions/frames/03-layout-1to4.html');
    const txt = await a.text();
    const b = await fetch('/compositions/frames/03-layout-1to4.html');
    return JSON.stringify({ href: location.href, rel: a.status, relLen: txt.length, abs: b.status, absLen: (await b.text()).length, ua: navigator.userAgent.slice(0,60) });
  })()`,
  awaitPromise: true, returnByValue: true,
});
console.log(out.result.value, out.exceptionDetails ? JSON.stringify(out.exceptionDetails) : "");
try { chrome.kill(); } catch {}
process.exit(0);
