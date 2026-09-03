import { readFile, writeFile } from "node:fs/promises";

const targetList = await fetch("http://127.0.0.1:9222/json/list").then((response) => response.json());
const target = targetList.find((item) => item.type === "page");
if (!target) throw new Error("No Edge page target found");

const seed = JSON.parse(await readFile("backend/app/spots/data/spots_seed.json", "utf8"));
const meta = seed.region_meta ?? {};
const spotsByArea = new Map();
for (const spot of seed.spots ?? []) {
  const regionCode = String(spot.region_code ?? "");
  const areaCode = String(meta[regionCode]?.area_cd ?? regionCode.slice(0, 2));
  if (!spot.image_url || !Number.isFinite(spot.lat) || !Number.isFinite(spot.lng)) continue;
  const list = spotsByArea.get(areaCode) ?? [];
  list.push({
    id: Number(spot.id),
    name: String(spot.name),
    category: String(spot.category),
    region_name: String(meta[regionCode]?.label ?? ""),
    address: spot.address ?? null,
    location: { lat: Number(spot.lat), lng: Number(spot.lng) },
    congestion: null,
    is_hidden_gem: Boolean(spot.is_hidden_gem),
    image_url: spot.image_url,
    photo_credit: null,
  });
  spotsByArea.set(areaCode, list);
}

const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  ws.addEventListener("open", resolve, { once: true });
  ws.addEventListener("error", reject, { once: true });
});

let sequence = 0;
const pending = new Map();
const browserErrors = [];

function send(method, params = {}) {
  const id = ++sequence;
  ws.send(JSON.stringify({ id, method, params }));
  return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
}

ws.addEventListener("message", async (event) => {
  const message = JSON.parse(event.data.toString());
  if (message.id) {
    const waiter = pending.get(message.id);
    if (!waiter) return;
    pending.delete(message.id);
    if (message.error) waiter.reject(new Error(message.error.message));
    else waiter.resolve(message.result);
    return;
  }
  if (message.method === "Runtime.exceptionThrown") {
    browserErrors.push(message.params.exceptionDetails?.text ?? "Runtime exception");
  }
  if (message.method === "Log.entryAdded" && message.params.entry?.level === "error") {
    browserErrors.push(message.params.entry.text);
  }
  if (message.method === "Fetch.requestPaused") {
    const requestUrl = new URL(message.params.request.url);
    const areaCode = requestUrl.searchParams.get("area_cd") ?? "26";
    const candidates = spotsByArea.get(areaCode) ?? [];
    const hidden = candidates.filter((spot) => spot.is_hidden_gem).slice(0, 6);
    const hiddenIds = new Set(hidden.map((spot) => spot.id));
    const trending = candidates.filter((spot) => !hiddenIds.has(spot.id)).slice(0, 6);
    const body = Buffer.from(
      JSON.stringify({
        region: null,
        area: { area_cd: areaCode, label: areaCode },
        trending,
        hidden_picks: hidden,
        trending_total: trending.length,
        hidden_total: hidden.length,
      })
    ).toString("base64");
    await send("Fetch.fulfillRequest", {
      requestId: message.params.requestId,
      responseCode: 200,
      responseHeaders: [
        { name: "Content-Type", value: "application/json; charset=utf-8" },
        { name: "Access-Control-Allow-Origin", value: "*" },
      ],
      body,
    });
  }
});

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
async function evaluate(expression) {
  const result = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
  return result.result?.value;
}

await send("Runtime.enable");
await send("Log.enable");
await send("Page.enable");
await send("Emulation.setDeviceMetricsOverride", {
  width: 1440,
  height: 1000,
  deviceScaleFactor: 1,
  mobile: false,
});
await send("Fetch.enable", {
  patterns: [{ urlPattern: "*api/v1/places/featured*", requestStage: "Request" }],
});
await send("Page.navigate", { url: "http://localhost:3000/demo-home" });

async function waitForMap(city) {
  for (let attempt = 0; attempt < 60; attempt += 1) {
    const ready = await evaluate(`(() => {
      const figure = document.querySelector('figure[class*="routeStage"]');
      const heading = figure?.querySelector('[class*="mapHeading"]')?.textContent ?? '';
      const paths = figure?.querySelectorAll('g[class*="mapBoundaries"] path').length ?? 0;
      const pins = figure?.querySelectorAll('g[class*="mapPin"]').length ?? 0;
      return heading.includes(${JSON.stringify(city)}) && paths > 0 && pins > 0;
    })()`);
    if (ready) return;
    await sleep(250);
  }
  throw new Error(`${city} map did not become ready`);
}

async function inspect(city, slug) {
  await waitForMap(city);
  const details = await evaluate(`(() => {
    const figure = document.querySelector('figure[class*="routeStage"]');
    return {
      city: ${JSON.stringify(city)},
      heading: figure?.querySelector('[class*="mapHeading"]')?.textContent?.replace(/\\s+/g, ' ').trim(),
      districtPathCount: figure?.querySelectorAll('g[class*="mapBoundaries"] path').length ?? 0,
      routePinCount: figure?.querySelectorAll('g[class*="mapPin"]').length ?? 0,
      ariaLabel: figure?.getAttribute('aria-label'),
      errorOverlay: Boolean(document.querySelector('[data-nextjs-dialog], .vite-error-overlay, #webpack-dev-server-client-overlay')),
      hasContent: document.body.innerText.trim().length > 0,
      assetRequests: performance.getEntriesByType('resource').map((entry) => entry.name).filter((name) => name.includes('/data/region-maps/')),
    };
  })()`);
  const screenshot = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
  await writeFile(`artifacts/region-map-${slug}.png`, Buffer.from(screenshot.data, "base64"));
  return details;
}

async function selectCity(city) {
  const clicked = await evaluate(`(() => {
    const button = Array.from(document.querySelectorAll('button')).find((item) => item.textContent?.trim() === ${JSON.stringify(city)});
    if (!button) return false;
    button.click();
    return true;
  })()`);
  if (!clicked) throw new Error(`${city} button not found`);
}

const results = [];
results.push(await inspect("부산", "busan"));
await selectCity("서울");
results.push(await inspect("서울", "seoul"));
await selectCity("세종");
results.push(await inspect("세종", "sejong"));

await send("Emulation.setDeviceMetricsOverride", {
  width: 375,
  height: 812,
  deviceScaleFactor: 1,
  mobile: true,
});
await sleep(500);
await evaluate(`document.querySelector('figure[class*="routeStage"]')?.scrollIntoView({ block: 'start' })`);
await sleep(300);
const mobile = await evaluate(`(() => {
  const figure = document.querySelector('figure[class*="routeStage"]');
  const cityButtons = Array.from(figure?.querySelectorAll('button') ?? []);
  return {
    viewportWidth: window.innerWidth,
    documentWidth: document.documentElement.scrollWidth,
    horizontalOverflow: document.documentElement.scrollWidth > window.innerWidth,
    minCityButtonHeight: Math.min(...cityButtons.map((button) => button.getBoundingClientRect().height)),
    routePinCount: figure?.querySelectorAll('g[class*="mapPin"]').length ?? 0,
  };
})()`);
const mobileScreenshot = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
await writeFile("artifacts/region-map-sejong-mobile.png", Buffer.from(mobileScreenshot.data, "base64"));

console.log(JSON.stringify({ results, mobile, browserErrors }, null, 2));
try {
  await send("Browser.close");
} catch {
  // Browser.close may tear down the socket before its acknowledgement reaches Node.
}
