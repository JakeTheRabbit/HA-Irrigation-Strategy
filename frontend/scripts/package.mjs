/** Package one canonical, self-contained application for all supported delivery paths. */
import { readFile, writeFile, mkdir, copyFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import path from "node:path";
const root = fileURLToPath(new URL("../../", import.meta.url));
const www = path.join(root, "www"),
  addon = path.join(root, "addons/f2_control/www/public"),
  integration = path.join(root, "custom_components/crop_steering/www");
const html = (await readFile(new URL("../dist/index.html", import.meta.url), "utf8")).replace(
  /^[\t ]+$/gm,
  "",
);
if (/<script[^>]+src=/.test(html) || /<link[^>]+rel="stylesheet"/.test(html))
  throw new Error("Primary dashboard must inline scripts and styles.");
if (/url\(["']?https?:\/\//.test(html))
  throw new Error("Dashboard fonts/assets must not depend on external network requests.");
for (const folder of [www, addon, integration]) {
  await mkdir(folder, { recursive: true });
  await writeFile(path.join(folder, "dashboard.html"), html);
}
const routes = {
  "index.html": "overview",
  "f2.html": "overview",
  "f2-classic.html": "grow-plan",
  "home.html": "overview",
  "overview.html": "overview",
  "setpoints.html": "grow-plan",
  "crop_steering.html": "overview",
  "crop_steering_tune.html": "strategy",
  "crop_steering_rules.html": "help",
  "office.html": "sensors",
  "system-map.html": "insights",
  "irrigation-manual.html": "help",
  "install.html": "setup",
  "SYSTEM_GUIDE.html": "help",
};
function redirect(filename, route) {
  const classic = filename === "f2-classic.html" || filename === "crop_steering_tune.html";
  return (
    '<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Crop Steering</title></head><body><p>Opening Crop Steering…</p><noscript><a href="./dashboard.html">Open dashboard</a> · JavaScript is required.</noscript><script>\n' +
    'const query=new URLSearchParams(location.search);const legacyViews={dashboard:"overview",tune:"strategy",timeline:"grow-plan",recipes:"grow-plan",climate:"sensors",control:"settings",substrate:"insights",analyze:"insights",floor:"setup",floorplan:"setup",log:"activity",logs:"activity"};\n' +
    (classic
      ? 'const room=query.get("room");if(!room||!room.startsWith("room:"))query.set("room",room==="f1"?"room:f1_":"room:");\n'
      : "") +
    'const view=query.get("view");query.delete("view");const route=legacyViews[view]||' +
    JSON.stringify(route) +
    ';location.replace("./dashboard.html"+(query.size?"?"+query.toString():"")+(location.hash||"#/"+route));\n' +
    "</script></body></html>\n"
  );
}
for (const [filename, route] of Object.entries(routes)) {
  const stub = redirect(filename, route);
  await writeFile(path.join(www, filename), stub);
  await writeFile(path.join(addon, filename), stub);
}
await writeFile(path.join(integration, "index.html"), redirect("index.html", "overview"));
await copyFile(path.join(addon, "index.html"), path.join(root, "addons/f2_control/web-index.html"));
console.log(
  "Packaged " +
    Math.round(Buffer.byteLength(html) / 1024) +
    " KiB native dashboard in integration, add-on and web; " +
    Object.keys(routes).length +
    " compatibility routes.",
);
