/** Academy lesson stills (www/learn/assets/screens/demo-*-r4.png) and their capture manifest, from the
 * checked-out compiled demo only: build first, then run `node frontend/scripts/capture-academy.mjs`.
 * Genuine unmodified isolated-demo UI at 1280x720: navigation, scrolling and opening tabs/disclosures
 * only, no data edits or service calls. The clock is pinned like capture-readme.mjs. Fails on any
 * browser error or off-origin/API request. The r3 stills stay in place: the R3/R4 lesson videos were
 * rendered from them. */
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import { serveDashboard } from "./dashboard-server.mjs";

const EDITION = "r4";
const OUT = new URL("../../www/learn/assets/screens/", import.meta.url);
const WIDTH = 1280,
  HEIGHT = 720,
  CROP_W = 984,
  CROP_H = 500;
const REVIEWED =
  "Visually reviewed: genuine demo UI, visible labels legible at source resolution; no reconstructed controls or values.";

const heading = (page, name) =>
  page.locator("h1,h2,h3,h4").filter({ hasText: name }).first();
const card = (page, name) =>
  heading(page, name).locator("xpath=ancestor::section[1]");
const tab = (page, name) =>
  page.getByRole("button", { name, exact: true }).or(page.getByRole("tab", { name, exact: true })).first();

const SHOTS = [
  {
    name: "overview",
    route: "all-zones",
    description: "Status › All rooms. Actual Room A/Room B grouped zone cards (r3 name: Overview, All zones).",
  },
  {
    name: "selected-room",
    route: "today",
    description: "Status › Room for actual Room A: zone cards, sensors and AI assistant summary.",
  },
  {
    name: "zone-detail",
    route: "zone/2",
    description: "Actual Room A Zone 2 page, including phase, observations and decision context.",
  },
  {
    name: "currentday",
    route: "plan/targets",
    description: "Irrigation › Current day for actual Room A Zone 1: target source, plan graph and setpoints; unchanged demo values.",
    review: "Navigation, target-source and draft/review context. Plot continues below viewport; the graph crop shows it whole.",
  },
  {
    name: "currentday-graph",
    route: "plan/targets",
    kind: "actual plot and complete native legend crop",
    region: async (page) => {
      const panel = page.locator(".planning-curve").first();
      await panel.scrollIntoViewIfNeeded();
      await page.evaluate(() => document.querySelector(".planning-legend").scrollIntoView({ block: "start" }));
      return page.evaluate(() => {
        const panel = document.querySelector(".planning-curve");
        const legend = panel.querySelector(".planning-legend").getBoundingClientRect();
        const box = panel.getBoundingClientRect();
        const bottom = Math.max(
          ...[...panel.querySelectorAll("svg")]
            .map((s) => s.getBoundingClientRect())
            .filter((r) => r.top >= legend.top && r.height > 40)
            .map((r) => r.bottom),
        );
        return { x: box.x, y: legend.top, width: box.width, height: bottom - legend.top + 2 };
      });
    },
    description: "Unmodified Current day plot with its native legend and both axes. Tight crop from the legend to the bottom of the plot; no inputs or CSS changed.",
    review: "Visually reviewed native legend and complete axes; crop taken by the browser, no image editing.",
  },
  {
    name: "calendar",
    route: "plan/schedule",
    description: "Irrigation › Grow plan & presets (r3 name: Calendar) for actual Room A Zone 1: stored demo schedule reference and plan graph.",
  },
  {
    name: "calendar-profile-grid",
    route: "plan/schedule",
    kind: "actual DOM region",
    region: (page) => card(page, "Grow overview"),
    description: "Actual Grow overview balance grid and selected week from the native Grow plan & presets DOM.",
    review: "Actual native crop; later weeks continue in horizontal overflow and below, outside this capture.",
  },
  {
    name: "endpoint-profiles",
    route: "plan/schedule",
    kind: "actual DOM region",
    region: async (page) => {
      await tab(page, "Endpoint profiles").click();
      return page.locator("details.plan-advanced .workspace-tabs").first();
    },
    fromRegionTop: true,
    description: "Grow plan & presets › Endpoint profiles tab: actual operator-defined endpoint profile fields; tab opened, no values changed.",
    review: "Actual native endpoint editor crop starting at the tab strip; no values changed.",
  },
  {
    name: "history-compare",
    route: "history/compare",
    description: "History › Compare runs. Actual available demo comparison; coverage and present reference remain as displayed.",
  },
  {
    name: "probes",
    route: "equipment/probes",
    description: "Equipment › Probes & offsets (r3 name: Probes). Actual probe view with its real demo readings and health.",
  },
  {
    name: "equipment-setup",
    route: "equipment/setup",
    prepare: async (page) => {
      await tab(page, "Rooms & mappings").click();
      await heading(page, "Room name and status").waitFor();
      await page.evaluate(() => {
        const el = [...document.querySelectorAll("button,[role=tab]")].find((e) => e.textContent.trim() === "Rooms & mappings");
        // The page header scrolls away; leave only the gap above the tab strip.
        window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - 40);
      });
    },
    description: "Equipment › Setup: pumps & valves, Rooms & mappings tab, scrolled to the tab: stored revision and acknowledgement state. Tab opened; no configuration edits.",
  },
  {
    name: "probe-mapping",
    route: "equipment/setup",
    kind: "actual DOM region",
    prepare: async (page) => {
      await tab(page, "Rooms & mappings").click();
    },
    region: (page) => card(page, "Zones and probe mapping"),
    description: "Rooms & mappings › Zones and probe mapping: actual Zone 1 valve/probe mapping and delivery sizing; no edits.",
    review: "Actual native crop of the top of the mapping card; later zones continue below, outside this capture.",
  },
  {
    name: "tank-and-feed",
    route: "equipment/dosing",
    prepare: async (page) => {
      await page.evaluate(() => {
        const el = [...document.querySelectorAll("h2")].find((e) => e.textContent.trim().startsWith("Tank and pump"));
        window.scrollTo(0, el.closest("section").getBoundingClientRect().top + window.scrollY - 40);
      });
    },
    description: "Equipment › Feed & dosing (r3 name: Tank and feed), scrolled to Tank and pump for actual Room A. Values are demo observations, not the lesson tank-conflict scenario.",
  },
  {
    name: "settings-defaultview",
    route: "settings",
    kind: "actual DOM region",
    region: async (page) => {
      await page.locator("section.where-opens").first().scrollIntoViewIfNeeded();
      // The card stretches to its row; crop it just below its last line of content.
      return page.evaluate(() => {
        const card = document.querySelector("section.where-opens");
        const box = card.getBoundingClientRect();
        const bottom = Math.max(...[...card.children].map((e) => e.getBoundingClientRect().bottom));
        return { x: box.x, y: box.y, width: box.width, height: bottom - box.y + 24 };
      });
    },
    description: "Settings › Dashboards & display › Where the app opens (r3 name: Settings › Display › Default view): actual landing-page preference; not changed.",
  },
  {
    name: "ai-assistant",
    route: "today/ai",
    description: "Actual visible AI assistant state and explanation panels for Room A. No prompt submitted.",
    review: "Actual AI status and budget view. Details continue below viewport; this image does not establish advice accuracy.",
  },
];

const html = await readFile(new URL("../../www/dashboard.html", import.meta.url));
const revision = execFileSync("git", ["rev-parse", "HEAD"], { encoding: "utf8" }).trim();
const server = await serveDashboard();
const browser = await chromium.launch({
  headless: true,
  ...(process.platform === "win32" ? { channel: "chrome" } : {}),
});
const forbidden = [],
  errors = [],
  captures = [];
try {
  const context = await browser.newContext({
    viewport: { width: WIDTH, height: HEIGHT },
    deviceScaleFactor: 1,
    colorScheme: "light",
    reducedMotion: "reduce",
  });
  await context.route("**/*", (route) => {
    const u = new URL(route.request().url());
    if (u.origin !== server.origin || u.pathname.startsWith("/api/")) {
      forbidden.push(u.origin + u.pathname);
      return route.abort();
    }
    return route.continue();
  });
  const page = await context.newPage();
  page.setDefaultTimeout(15000);
  page.on("pageerror", (e) => errors.push(e.message));
  await page.clock.setFixedTime(new Date(2026, 9, 18, 15, 50));
  for (const shot of SHOTS) {
    const route = `dashboard.html?demo=1#/${shot.route}`;
    await page.goto(`${server.origin}/${route}`, { waitUntil: "networkidle" });
    await page.locator("main").waitFor();
    await page.evaluate(() => document.fonts.ready);
    await page.evaluate(() => {
      document.activeElement?.blur();
      window.scrollTo(0, 0);
    });
    if (shot.prepare) await shot.prepare(page);
    const file = `demo-${shot.name}-${EDITION}.png`;
    const path = fileURLToPath(new URL(file, OUT));
    let clip = null;
    if (shot.region) {
      const region = await shot.region(page);
      if (typeof region.boundingBox === "function") {
        await region.waitFor({ state: "visible" });
        await region.evaluate((el) => el.scrollIntoView({ block: "start" }));
        await page.evaluate(() => window.scrollBy(0, -72));
        const box = await region.boundingBox();
        clip = { x: box.x, y: box.y, width: box.width, height: shot.fromRegionTop ? CROP_H : box.height };
      } else clip = region;
      clip = {
        x: Math.round(clip.x),
        y: Math.max(0, Math.round(clip.y)),
        width: Math.round(Math.min(clip.width, CROP_W, WIDTH - clip.x)),
        height: Math.round(Math.min(clip.height, CROP_H, HEIGHT - Math.max(0, clip.y))),
      };
    }
    await page.waitForTimeout(300);
    await page.screenshot({ path, ...(clip ? { clip } : {}) });
    const state = await page.evaluate((clip) => {
      const inView = (el) => {
        const r = el.getBoundingClientRect();
        const c = clip ?? { x: 0, y: 0, width: innerWidth, height: innerHeight };
        return el.offsetParent && r.bottom > c.y && r.top < c.y + c.height && r.right > c.x && r.left < c.x + c.width;
      };
      return {
        headings: [...document.querySelectorAll("h1,h2,h3")].filter(inView).map((e) => e.textContent.trim().replace(/\s+/g, " ")),
        demo: [...document.querySelectorAll("body *")].some((e) => (e.innerText || "").trim() === "Demo data" && inView(e)),
        room: document.querySelector(".room-chip.active, [aria-current] .room-name, nav [aria-current='true']")?.textContent.trim() ?? null,
      };
    }, clip);
    const png = await readFile(path);
    captures.push({
      file: `assets/screens/${file}`,
      route,
      visible_headings: state.headings,
      width: clip ? clip.width : WIDTH,
      height: clip ? clip.height : HEIGHT,
      ...(clip ? { clip } : {}),
      sha256: createHash("sha256").update(png).digest("hex"),
      selectedRoom: "Room A",
      demo_label_visible: state.demo,
      capture_kind: shot.kind ?? "full viewport",
      description: shot.description,
      review: shot.review ?? REVIEWED,
      review_status: "reviewed",
    });
    console.log(`${file} ${clip ? `${clip.width}x${clip.height}` : `${WIDTH}x${HEIGHT}`}`);
  }
  assert.deepEqual(forbidden, [], "academy capture must not request external or HA API resources");
  assert.deepEqual(errors, [], "no browser runtime errors");
  const manifest = {
    schema: 1,
    captured_at: new Date().toISOString(),
    origin: "http://127.0.0.1:<loopback port>/dashboard.html?demo=1 (frontend/scripts/capture-academy.mjs)",
    source_revision: revision,
    frontend_source_sha256: createHash("sha256").update(html).digest("hex"),
    frontend_source: "www/dashboard.html",
    fixed_local_time: "2026-10-18T15:50:00",
    supersedes: "demo-capture-manifest-r3.json for lesson stills; the r3 files remain the lesson-video scene sources",
    rule: "Genuine unmodified isolated demo UI. Actual Room A/Room B data. Fictional Training East lesson cases are separate. Only navigation, scrolling and tab/disclosure opening; no data edits or service calls.",
    captures,
  };
  await writeFile(new URL(`demo-capture-manifest-${EDITION}.json`, OUT), JSON.stringify(manifest, null, 2) + "\n");
  console.log(`Captured ${captures.length} academy stills from the isolated compiled demo; no external/API requests or runtime errors.`);
} finally {
  await browser.close();
  await server.close();
}
