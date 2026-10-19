/* Full-page screenshot capture for the prototype.

   Usage:
     node website-prototype/capture.mjs
     node website-prototype/capture.mjs --browser "C:\\path\\to\\chrome.exe"

   Requires a local Chrome/Edge. The prototype itself has no build step. */

import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.join(HERE, "shots");
const PORT = 9333;

const candidates = [
  process.env.CHROME_PATH,
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
].filter(Boolean);

const argBrowser = process.argv.indexOf("--browser");
const browser = argBrowser !== -1 ? process.argv[argBrowser + 1] : candidates.find(existsSync);

if (!browser) {
  throw new Error("Chrome or Edge was not found. Pass --browser <path>.");
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function waitForDebugger() {
  for (let attempt = 0; attempt < 80; attempt += 1) {
    try {
      const response = await fetch(`http://127.0.0.1:${PORT}/json/list`);
      const targets = await response.json();
      const page = targets.find((target) => target.type === "page");
      if (page?.webSocketDebuggerUrl) return page;
    } catch {
      // Chrome is still starting.
    }
    await sleep(150);
  }
  throw new Error("Timed out waiting for the browser debugger.");
}

function connect(url) {
  const socket = new WebSocket(url);
  let id = 0;
  const pending = new Map();

  socket.addEventListener("message", (event) => {
    const message = JSON.parse(event.data);
    if (!message.id) return;
    const entry = pending.get(message.id);
    if (!entry) return;
    pending.delete(message.id);
    if (message.error) entry.reject(new Error(message.error.message));
    else entry.resolve(message.result);
  });

  const ready = new Promise((resolve, reject) => {
    socket.addEventListener("open", resolve, { once: true });
    socket.addEventListener("error", reject, { once: true });
  });

  const send = (method, params = {}) =>
    new Promise((resolve, reject) => {
      const messageId = ++id;
      pending.set(messageId, { resolve, reject });
      socket.send(JSON.stringify({ id: messageId, method, params }));
    });

  const onMessage = (handler) => {
    socket.addEventListener("message", (event) => handler(JSON.parse(event.data)));
  };

  return { ready, send, onMessage, close: () => socket.close() };
}

async function main() {
  await mkdir(OUT, { recursive: true });
  const profile = path.join(tmpdir(), `ddm-prototype-${Date.now()}`);
  const pageUrl = `${new URL(`file:///${path.join(HERE, "index.html").replaceAll("\\", "/")}`)}?capture=1`;

  const processHandle = spawn(
    browser,
    [
      "--headless=new",
      "--no-sandbox",
      "--disable-gpu",
      "--disable-crashpad",
      "--disable-extensions",
      "--no-first-run",
      "--hide-scrollbars",
      "--force-device-scale-factor=1",
      `--remote-debugging-port=${PORT}`,
      `--user-data-dir=${profile}`,
      "--window-size=1440,900",
      pageUrl,
    ],
    { stdio: "ignore" },
  );

  try {
    const target = await waitForDebugger();
    const cdp = connect(target.webSocketDebuggerUrl);
    await cdp.ready;
    await cdp.send("Page.enable");
    await cdp.send("Runtime.enable");
    await cdp.send("Log.enable");

    const browserErrors = [];
    const onRuntimeError = (message) => {
      if (message.method === "Runtime.exceptionThrown") {
        browserErrors.push(message.params.exceptionDetails.text);
      }
      if (message.method === "Log.entryAdded" && message.params.entry.level === "error") {
        browserErrors.push(message.params.entry.text);
      }
    };
    cdp.onMessage(onRuntimeError);

    await cdp.send("Emulation.setDeviceMetricsOverride", {
      width: 1440,
      height: 900,
      deviceScaleFactor: 1,
      mobile: false,
    });

    for (let attempt = 0; attempt < 80; attempt += 1) {
      const { result } = await cdp.send("Runtime.evaluate", {
        expression: "document.readyState",
        returnByValue: true,
      });
      if (result.value === "complete") break;
      await sleep(150);
    }

    await cdp.send("Runtime.evaluate", {
      expression: `Promise.all([
        document.fonts.ready,
        ...Array.from(document.images)
          .filter((image) => !image.complete)
          .map((image) => new Promise((resolve) => {
            image.addEventListener("load", resolve, { once: true });
            image.addEventListener("error", resolve, { once: true });
          })),
      ])`,
      awaitPromise: true,
    });
    await sleep(500);

    const capture = async (width, height, name) => {
      await cdp.send("Emulation.setDeviceMetricsOverride", {
        width,
        height,
        deviceScaleFactor: 1,
        mobile: width < 600,
      });
      await sleep(500);
      const { result } = await cdp.send("Runtime.evaluate", {
        expression: "document.documentElement.scrollHeight",
        returnByValue: true,
      });
      const pageHeight = result.value;
      const shot = await cdp.send("Page.captureScreenshot", {
        format: "png",
        captureBeyondViewport: true,
        clip: { x: 0, y: 0, width, height: pageHeight, scale: 1 },
      });
      const file = path.join(OUT, name);
      await writeFile(file, Buffer.from(shot.data, "base64"));
      console.log(`${name}: ${width}x${pageHeight}, ${Math.round(shot.data.length * 0.75 / 1024)} KB`);
    };

    for (const width of [320, 375, 414, 768, 1024, 1440]) {
      await cdp.send("Emulation.setDeviceMetricsOverride", {
        width,
        height: 900,
        deviceScaleFactor: 1,
        mobile: width < 600,
      });
      await sleep(180);
      const { result } = await cdp.send("Runtime.evaluate", {
        expression: `({
          width: window.innerWidth,
          scrollWidth: document.documentElement.scrollWidth,
          brokenImages: Array.from(document.images)
            .filter((image) => !image.complete || image.naturalWidth === 0)
            .map((image) => image.getAttribute("src")),
        })`,
        returnByValue: true,
      });
      const audit = result.value;
      if (audit.scrollWidth > audit.width + 1) {
        throw new Error(`Horizontal overflow at ${width}px: ${audit.scrollWidth}px`);
      }
      if (audit.brokenImages.length) {
        throw new Error(`Broken images at ${width}px: ${audit.brokenImages.join(", ")}`);
      }
      console.log(`audit ${width}px: no horizontal overflow, images loaded`);
    }

    if (browserErrors.length) {
      throw new Error(`Browser errors:\n${browserErrors.join("\n")}`);
    }

    await capture(1440, 900, "desktop.png");
    await capture(390, 844, "mobile.png");

    cdp.close();
  } finally {
    processHandle.kill();
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
