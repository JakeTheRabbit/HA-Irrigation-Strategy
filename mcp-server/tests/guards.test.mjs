import test from "node:test";
import assert from "node:assert/strict";
import { HaClient, configFromEnv } from "../dist/ha.js";
import { Workspace } from "../dist/workspace.js";
import { mockHa, TOKEN } from "./mock-ha.mjs";

const base = { HA_URL: "http://127.0.0.1:8123", HA_TOKEN: TOKEN };
test("configuration accepts only a fixed origin and explicit write opt-in", () => {
  assert.equal(configFromEnv(base).writes, false);
  for (const CROP_STEERING_ALLOW_WRITES of ["1", "yes", "TRUE", "false", ""])
    assert.equal(
      configFromEnv({ ...base, CROP_STEERING_ALLOW_WRITES }).writes,
      false,
    );
  assert.equal(
    configFromEnv({ ...base, CROP_STEERING_ALLOW_WRITES: "true" }).writes,
    true,
  );
  for (const HA_URL of [
    "",
    "file:///etc/passwd",
    "https://user:pass@ha.invalid",
    "https://ha.invalid/api",
    "https://ha.invalid?token=x",
    "https://ha.invalid#fragment",
  ])
    assert.throws(() => configFromEnv({ ...base, HA_URL }), /HA_URL/);
  for (const HA_TIMEOUT_MS of ["0", "NaN", "60001", "1.5"])
    assert.throws(
      () => configFromEnv({ ...base, HA_TIMEOUT_MS }),
      /HA_TIMEOUT_MS/,
    );
  assert.throws(() => configFromEnv({ ...base, HA_TOKEN: "" }), /HA_TOKEN/);
  assert.throws(() => configFromEnv({ ...base, HA_TOKEN: "a\nb" }), /HA_TOKEN/);
});

test("proposal expiry and process-local memory prevent later replay", async (t) => {
  const ha = await mockHa(t);
  let now = 1000;
  const client = new HaClient({
    url: ha.url,
    token: TOKEN,
    timeoutMs: 1000,
    writes: true,
  });
  const workspace = new Workspace(client, () => now, 1000);
  const p = await workspace.previewSetup("room:veg_", { room_name: "Renamed" });
  now = 2000;
  await assert.rejects(
    workspace.apply(p.proposal_token, p.room_id, p.expected_revision),
    /expired/,
  );
  const q = await workspace.previewSetup("room:veg_", { room_name: "Renamed" });
  await assert.rejects(
    new Workspace(client).apply(
      q.proposal_token,
      q.room_id,
      q.expected_revision,
    ),
    /missing/,
  );
  assert.equal(ha.saveCount, 0);
});

test("proposal retention is bounded and expired entries free capacity", async (t) => {
  const ha = await mockHa(t);
  let now = 1000;
  const workspace = new Workspace(
    new HaClient({ url: ha.url, token: TOKEN, timeoutMs: 1000, writes: false }),
    () => now,
    1000,
  );
  for (let n = 0; n < 20; n++)
    await workspace.previewSetup("room:veg_", { room_name: "Name " + n });
  await assert.rejects(
    workspace.previewSetup("room:veg_", { room_name: "Name 21" }),
    /Twenty proposals/,
  );
  now = 2000;
  assert.ok(
    (await workspace.previewSetup("room:veg_", { room_name: "Fresh" }))
      .proposal_token,
  );
});

test("HTTP client rejects unsupported services and oversized response without exposing body", async (t) => {
  const ha = await mockHa(t),
    client = new HaClient({
      url: ha.url,
      token: TOKEN,
      timeoutMs: 1000,
      writes: true,
    });
  await assert.rejects(client.service("strategy_activate", {}), /Unsupported/);
  assert.equal(ha.calls.length, 0);
  ha.intercept = (req, res) => {
    res.writeHead(200);
    res.end('"' + "x".repeat(8 * 1024 * 1024) + '"');
    return true;
  };
  await assert.rejects(client.service("setup_read"), /exceeds 8 MiB/);
});
