import { writeFileSync } from "node:fs";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const PORT = Number(process.argv[2] || 9224);

async function connect() {
  for (let i = 0; i < 40; i++) {
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
  throw new Error("no chrome");
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
  if (m.method === "Network.responseReceived") logs.push(`RES ${m.params.response.status} ${m.params.response.url}`);
  if (m.method === "Network.loadingFailed") logs.push(`FAIL ${m.params.errorText} ${m.params.requestId}`);
});
const send = (method, params = {}) =>
  new Promise((ok, bad) => {
    const i = ++id;
    pending.set(i, { ok, bad });
    ws.send(JSON.stringify({ id: i, method, params }));
  });

await send("Page.enable");
await send("Runtime.enable");
await send("Network.enable");
await send("Page.navigate", { url: "http://127.0.0.1:8931/.hyperframes/view-03.html?t=3.4" });
await sleep(2500);
const r = await send("Runtime.evaluate", {
  expression: `(async function(){
    const a = await fetch('/compositions/frames/03-layout-1to4.html');
    const txt = await a.text();
    const b = await fetch('/assets/rec-layout-1to4.mp4', { headers: { Range: 'bytes=0-1023' } });
    return JSON.stringify({ frameStatus: a.status, frameLen: txt.length, first: txt.slice(0,40), videoStatus: b.status, videoLen: (await b.arrayBuffer()).byteLength, href: location.href });
  })()`,
  awaitPromise: true,
  returnByValue: true,
});
console.log("PROBE:", r.result.value);
const shot = await send("Page.captureScreenshot", { format: "png" });
writeFileSync(".hyperframes/probe/diag2.png", Buffer.from(shot.data, "base64"));
console.log(logs.slice(0, 30).join("\n"));
process.exit(0);
