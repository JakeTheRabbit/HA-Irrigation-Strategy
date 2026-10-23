import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { toast } from "sonner";
import { Heading } from "@/components/dashboard";
import { NeedsIntegration } from "@/components/needs-integration";
import { Sentence } from "@/components/primitives/sentence";
import { Button } from "@/components/ui/button";
import {
  deliveryLine,
  displayScale,
  newRule,
  notReporting,
  ruleBody,
  ruleStatus,
  ruleTokens,
  sameRule,
  sensorsPhones,
  sourceLabel,
  type RuleContext,
} from "@/lib/alert-rules";
import { parseNotifyDocument, type NotifyDocument } from "@/lib/notify";
import { callV2, type V2Outcome } from "@/lib/parity-api";
import type { AlertPreview, AlertRule, AlertRuleList, AlertRuleListItem } from "@/lib/parity-types";
import { roomProbeIds } from "@/lib/probes";
import type { StockDocument } from "@/lib/stock";
import { clock, hourTicks, lightsWindow, startOfDay } from "@/lib/time";
import type { Controller } from "@/lib/types";
import { offerUndo, revertEvents } from "@/lib/undo";
import { useNarrow } from "@/lib/use-narrow";
import type { PageProps } from "./placeholder";
import "./alert-rules.css";

const HOUR = 3_600_000;
const SENSORS_PREFIX = "binary_sensor.crop_steering_rule_";
type Listed = { state: "loading" | "ready" | "missing" | "error"; rules: AlertRuleListItem[]; revision: number | null; error: string | null };

/** `?rule=<id>|new` in the page's hash: the rule the builder holds. */
const ruleParam = () => new URLSearchParams(window.location.hash.split("?")[1] ?? "").get("rule");
function setRuleParam(value: string | null) {
  const [path, query = ""] = window.location.hash.split("?");
  const params = new URLSearchParams(query);
  if (value === null) params.delete("rule");
  else params.set("rule", value);
  const text = params.toString();
  window.history.replaceState(window.history.state, "", `${window.location.pathname}${window.location.search}${path}${text ? `?${text}` : ""}`);
  window.dispatchEvent(new Event("alert-rule-param"));
}
const hh = (hour: number) => `${String(Math.floor(hour)).padStart(2, "0")}:${String(Math.round((hour % 1) * 60)).padStart(2, "0")}`;
const message = (out: V2Outcome<unknown>) => (out.kind === "error" ? out.message : "This needs Crop Steering 3.18 or newer.");

/** Alert rules (T1, mockups 19 and 27): a sentence builder replayed over yesterday, a test push, and
 * the site's rules with an On switch. Saves, switches and deletes are read back from the rule list;
 * a switch and a delete apply at once with Undo. */
export function AlertRules({ controller, onDirtyChange }: PageProps) {
  const { timeZone: tz, roomId, room, rooms, states } = controller;
  const phone = useNarrow(720);
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(timer);
  }, []);

  // The site's rules.
  const [list, setList] = useState<Listed>({ state: "loading", rules: [], revision: null, error: null });
  const load = useCallback(async () => {
    const out = await callV2<AlertRuleList>(controller, "alert_rule_list", {});
    if (out.kind === "ok") setList({ state: "ready", rules: out.data.rules, revision: out.data.revision, error: null });
    else if (out.kind === "missing") setList({ state: "missing", rules: [], revision: null, error: null });
    else setList((p) => ({ ...p, state: p.state === "ready" ? "ready" : "error", error: out.message }));
    return out;
  }, [controller.operator]);
  useEffect(() => {
    void load();
  }, [load]);

  // Who rule pushes reach (the Sensors kind), and the room's stock tanks and probes.
  const [notify, setNotify] = useState<NotifyDocument | null>(null);
  useEffect(() => {
    controller
      .operator<unknown>("notify_get")
      .then((raw) => setNotify(parseNotifyDocument(raw)))
      .catch(() => setNotify(null));
  }, [controller.operator]);
  const [stocks, setStocks] = useState<{ id: string; name: string }[]>([]);
  useEffect(() => {
    let current = true;
    controller
      .operator<StockDocument>("stock_get", { room_id: roomId })
      .then((doc) => current && setStocks((doc.tanks ?? []).map((t) => ({ id: t.id, name: t.name }))))
      .catch(() => current && setStocks([]));
    return () => {
      current = false;
    };
  }, [controller.operator, roomId]);
  const nameOf = (entity: string) => {
    const name = states[entity]?.attributes.friendly_name;
    return typeof name === "string" && name ? name : entity;
  };
  const probes = useMemo(
    () => roomProbeIds(room.zones, states).map((id) => ({ id, name: nameOf(id) })),
    [room.zones, states],
  );
  const roomName = (id: string) => rooms.find((r) => r.id === id)?.name ?? (id === roomId ? room.room.name : id.replace(/^room:/, "") || "Room");
  const prefixOf = (id: string) => id.replace(/^room:/, "");
  const phonesFor = (id: string) => sensorsPhones(notify?.config.recipients ?? [], prefixOf(id));
  const ctxFor = (rule: Pick<AlertRule, "room_id">): RuleContext => ({
    room: roomName(rule.room_id),
    zones: rule.room_id === roomId ? room.zones.map((z) => z.id) : [],
    phones: phonesFor(rule.room_id).map((p) => p.name),
    stocks: rule.room_id === roomId ? stocks : [],
    probes: rule.room_id === roomId ? probes : [],
  });

  // The rule the builder holds: `?rule=<id>`, else a new one for the room the tree picked.
  const [param, setParam] = useState<string | null>(() => ruleParam());
  useEffect(() => {
    const read = () => setParam(ruleParam());
    window.addEventListener("hashchange", read);
    window.addEventListener("alert-rule-param", read);
    return () => {
      window.removeEventListener("hashchange", read);
      window.removeEventListener("alert-rule-param", read);
    };
  }, []);
  const editing = param && param !== "new" ? (list.rules.find((r) => r.id === param) ?? null) : null;
  const fresh = useMemo(() => newRule(roomId, room.zones[0]?.id ?? 1), [roomId, room.zones[0]?.id]);
  const original: AlertRule = editing ?? fresh;
  const [draft, setDraft] = useState<AlertRule>(original);
  const originalKey = JSON.stringify(ruleBody(original));
  useEffect(() => {
    setDraft(original);
    setDelivery(null);
  }, [originalKey, editing?.id]);
  const dirty = !sameRule(draft, original);
  useEffect(() => onDirtyChange(dirty), [dirty]);
  const [note, setNote] = useState<{ text: string; tone: "ok" | "bad" } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  // Yesterday as the draft would have seen it, 250 ms after the last edit.
  const [preview, setPreview] = useState<{ data: AlertPreview | null; error: string | null } | null>(null);
  const body = JSON.stringify(ruleBody(draft));
  useEffect(() => {
    if (list.state !== "ready") return;
    let current = true;
    const timer = setTimeout(() => {
      void callV2<AlertPreview>(controller, "alert_rule_preview", { rule: JSON.parse(body), hours: 24 }).then((out) => {
        if (!current) return;
        if (out.kind === "ok") setPreview({ data: out.data, error: null });
        else setPreview((p) => ({ data: p?.data ?? null, error: message(out) }));
      });
    }, 250);
    return () => {
      current = false;
      clearTimeout(timer);
    };
  }, [body, list.state, controller.operator]);

  // The test push and its delivery, phone by phone.
  const [delivery, setDelivery] = useState<string | null>(null);
  const phones = phonesFor(draft.room_id);
  const names = Object.fromEntries((notify?.config.recipients ?? []).map((r) => [r.service, r.name]));
  const sendTest = async () => {
    setBusy("test");
    setDelivery(null);
    const out = await callV2<AlertPreview & { delivery?: AlertPreview["delivery"] }>(controller, "alert_rule_test", { rule: JSON.parse(body), send: true });
    setBusy(null);
    // A phone that did not get it is an `unavailable` answer that still carries every row.
    const rows = out.kind === "ok" ? out.data.delivery : out.kind === "error" ? (out.data as { delivery?: AlertPreview["delivery"] } | undefined)?.delivery : undefined;
    setDelivery(rows ? deliveryLine(rows, names) : `Not sent: ${message(out)}`);
  };

  /** The list read again, and the rule `id` in it (null when gone), or the read's failure. */
  const readBack = async (id: string) => {
    const out = await load();
    if (out.kind !== "ok") return { ok: false as const, error: message(out) };
    return { ok: true as const, rule: out.data.rules.find((r) => r.id === id) ?? null };
  };
  const undoEvents = (eventIds: string[], what: string) => async () => {
    try {
      await revertEvents(controller, eventIds);
      await load();
      toast.success(`${what} put back. Written and read back ${clock(Date.now(), tz)}.`);
    } catch (error) {
      // An undo that stopped part way says how many were put back (UndoError); the list shows the rest.
      await load();
      throw error;
    }
  };
  const after = (eventIds: string[], text: string, what: string) => {
    if (eventIds.length) offerUndo({ message: text, undo: undoEvents(eventIds, what) });
    else toast(`${text} Undo not available here: put back from History.`);
  };

  const save = async () => {
    if (list.revision === null) return;
    setBusy("save");
    setNote(null);
    const out = await callV2<{ rule: AlertRule; revision: number }>(controller, "alert_rule_set", {
      expected_revision: list.revision,
      rule: JSON.parse(body),
    });
    if (out.kind !== "ok") {
      setBusy(null);
      if (out.kind === "error" && out.code === "stale_revision") void load();
      setNote({ text: message(out), tone: "bad" });
      return;
    }
    const back = await readBack(out.data.rule.id);
    setBusy(null);
    if (back.ok && back.rule && sameRule(back.rule, draft)) {
      setNote({ text: `Saved and watching. Written and read back ${clock(Date.now(), tz)}.`, tone: "ok" });
      setRuleParam(out.data.rule.id);
    } else
      setNote({
        text: back.ok ? "Saved, but the rule list does not show it yet. Reload and check it before saving again." : `Saved, but the rule list could not be read: ${back.error}`,
        tone: "bad",
      });
  };

  const toggle = async (item: AlertRuleListItem) => {
    if (list.revision === null) return;
    setBusy(item.id);
    const next = { ...item, active: !item.active };
    const out = await callV2(controller, "alert_rule_set", { expected_revision: list.revision, rule: ruleBody(next) });
    if (out.kind !== "ok") {
      setBusy(null);
      if (out.kind === "error" && out.code === "stale_revision") void load();
      toast.error(message(out));
      return;
    }
    const back = await readBack(item.id);
    setBusy(null);
    if (!back.ok || !back.rule || back.rule.active !== next.active) {
      toast.error("The controller did not confirm the switch. Reload and check it before trying again.");
      return;
    }
    after(out.eventIds, `Rule ${next.active ? "on" : "off"}: ${item.summary_sentence} Written and read back ${clock(Date.now(), tz)}.`, "Switch");
  };

  const remove = async (item: AlertRuleListItem) => {
    if (list.revision === null) return;
    setBusy("delete");
    const out = await callV2(controller, "alert_rule_delete", { id: item.id, expected_revision: list.revision });
    if (out.kind !== "ok") {
      setBusy(null);
      if (out.kind === "error" && out.code === "stale_revision") void load();
      setNote({ text: message(out), tone: "bad" });
      return;
    }
    const back = await readBack(item.id);
    setBusy(null);
    if (!back.ok || back.rule) {
      setNote({ text: "The controller did not confirm the delete. Reload and check it before trying again.", tone: "bad" });
      return;
    }
    setRuleParam(phone ? null : "new");
    after(out.eventIds, `Deleted: ${item.summary_sentence}`, "Rule");
  };

  const edit = (item: AlertRuleListItem) => {
    if (item.room_id !== roomId && rooms.some((r) => r.id === item.room_id)) controller.changeRoom(item.room_id);
    setNote(null);
    setRuleParam(item.id);
  };

  // The room's lights, for the shaded nights on the replay.
  const lights = (id: string) => {
    const p = prefixOf(id);
    const on = Number(states[`number.crop_steering_${p}lights_on_hour`]?.state);
    const off = Number(states[`number.crop_steering_${p}lights_off_hour`]?.state);
    return Number.isFinite(on) && Number.isFinite(off) ? { on, off } : null;
  };

  const ctx = ctxFor(draft);
  const showBuilder = !phone || param !== null;
  const showList = !phone || param === null;
  const isNew = !editing;
  const title = phone && param !== null ? (isNew ? "New alert rule" : "Edit alert rule") : "Alert rules";

  return (
    <div className="alert-rules">
      <Heading
        title={title}
        action={
          phone && param !== null ? (
            <Button variant="link" onClick={() => setRuleParam(null)}>
              All rules
            </Button>
          ) : undefined
        }
      />
      {showBuilder &&
        (list.state === "missing" ? (
          <section className="panel ar-builder" aria-labelledby="ar-builder-title">
            <div className="ar-head">
              <h2 id="ar-builder-title">New rule</h2>
            </div>
            <NeedsIntegration feature="Your own alert rules" />
          </section>
        ) : (
          <section className="panel ar-builder" aria-labelledby="ar-builder-title">
            {!phone && (
              <div className="ar-head">
                <h2 id="ar-builder-title">{isNew ? "New rule" : "Edit rule"}</h2>
                <p>Your own lines on irrigation, dosing, sensors and offline devices. Coded CS alerts keep running whatever you set here.</p>
              </div>
            )}
            {phone && <h2 id="ar-builder-title" className="sr-only">{isNew ? "New rule" : "Edit rule"}</h2>}
            <Sentence parts={ruleTokens(draft, setDraft, ctx)} phone={phone} ariaLabel="Rule" />
            <RuleReplay
              draft={draft}
              preview={preview?.data ?? null}
              error={preview?.error ?? null}
              label={sourceLabel(draft, ctx)}
              lights={lights(draft.room_id)}
              tz={tz}
              now={now}
              phone={phone}
              onThreshold={(threshold) => setDraft((d) => ({ ...d, threshold }))}
            />
            <div className="ar-actions">
              <Button variant="outline" onClick={sendTest} disabled={busy !== null || !phones.length || controller.admin === false}>
                {phone ? "Send test" : `Send a test push to ${phones.length ? phones.map((p) => p.name).join(" and ") : "your phone"}`}
              </Button>
              {!isNew && (
                <Button variant="ghost" onClick={() => editing && void remove(editing)} disabled={busy !== null || controller.admin === false}>
                  Delete rule
                </Button>
              )}
              <Button className="ar-save" onClick={save} disabled={busy !== null || (!dirty && !isNew) || list.revision === null || controller.admin === false}>
                {busy === "save" ? "Saving…" : !dirty && !isNew ? "Saved" : phone ? "Save rule" : isNew ? "Save rule and start watching" : "Save changes"}
              </Button>
            </div>
            {!phones.length && notify && (
              <p className="ar-muted">
                No phone gets Sensors alerts in this room yet: tick it on <a href="#/settings/notifications">Notifications</a>.
              </p>
            )}
            {controller.admin === false && <p className="ar-muted">Only a Home Assistant administrator can save rules or send a test push.</p>}
            {delivery && (
              <p className="ar-delivery" role="status" data-delivery>
                {delivery}
              </p>
            )}
            {note && (
              <p className={`ar-note is-${note.tone}`} role="status" data-save-note>
                {note.text}
              </p>
            )}
          </section>
        ))}
      {showList && (
        <section className="panel ar-list" aria-labelledby="ar-list-title">
          <div className="ar-list-head">
            <h2 id="ar-list-title">Your rules</h2>
            {list.state === "ready" && (
              <small>
                {list.rules.length} {list.rules.length === 1 ? "rule" : "rules"} · {list.rules.filter((r) => r.active).length} on
              </small>
            )}
            {!phone && <span className="ar-muted ar-ha">Each rule is also binary_sensor.crop_steering_rule_… in Home Assistant</span>}
            {phone && list.state === "ready" && (
              <Button size="sm" onClick={() => setRuleParam("new")}>
                New rule
              </Button>
            )}
          </div>
          {list.state === "missing" ? (
            <LegacyRules controller={controller} />
          ) : list.state === "loading" ? (
            <p className="ar-muted">Reading the rules…</p>
          ) : list.state === "error" ? (
            <p className="ar-note is-bad">{list.error}</p>
          ) : !list.rules.length ? (
            <p className="ar-muted">No rules yet. Build one above and save it.</p>
          ) : (
            <ul className="ar-rows">
              {list.rules.map((item) => {
                const status = ruleStatus(item, now, tz);
                const silent = notReporting(item, ctxFor(item));
                return (
                  <li key={item.id} className="ar-row" data-rule={item.id} data-active={item.active ? "" : undefined} aria-current={editing?.id === item.id ? "true" : undefined}>
                    <div className="ar-row-text">
                      <span className="ar-sentence">{item.summary_sentence}</span>
                      {silent && <span className="ar-silent">{silent}</span>}
                    </div>
                    <span className={`ar-status is-${status.tone}`} data-status>
                      {status.text}
                    </span>
                    <Button variant="outline" size="sm" onClick={() => edit(item)} aria-label={`Edit: ${item.summary_sentence}`}>
                      Edit
                    </Button>
                    <button
                      type="button"
                      role="switch"
                      className="ar-switch"
                      aria-checked={item.active}
                      aria-label={`On: ${item.summary_sentence}`}
                      disabled={busy !== null || controller.admin === false}
                      onClick={() => void toggle(item)}
                    >
                      <span aria-hidden="true" />
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </section>
      )}
    </div>
  );
}

/** On an integration before 3.18: the rule binary sensors Home Assistant has, read-only. */
function LegacyRules({ controller }: { controller: Controller }) {
  const rules = Object.values(controller.states)
    .filter((s) => s.entity_id.startsWith(SENSORS_PREFIX))
    .sort((a, b) => a.entity_id.localeCompare(b.entity_id));
  if (!rules.length) return <p className="ar-muted">No alert rules in Home Assistant yet.</p>;
  return (
    <ul className="ar-rows">
      {rules.map((s) => (
        <li key={s.entity_id} className="ar-row" data-rule={s.entity_id}>
          <div className="ar-row-text">
            <span className="ar-sentence">{typeof s.attributes.friendly_name === "string" ? s.attributes.friendly_name : s.entity_id}</span>
          </div>
          <span className={`ar-status is-${s.state === "on" ? "bad" : "muted"}`}>{s.state === "on" ? "Firing now" : "Quiet"}</span>
        </li>
      ))}
    </ul>
  );
}

/** Yesterday's readings as the rule would have seen them: would-alert spans, dips too short to
 * alert, the nights, and the threshold as a dashed line that drags (or steps with the arrows). */
function RuleReplay({
  draft,
  preview,
  error,
  label,
  lights,
  tz,
  now,
  phone,
  onThreshold,
}: {
  draft: AlertRule;
  preview: AlertPreview | null;
  error: string | null;
  label: string;
  lights: { on: number; off: number } | null;
  tz: string;
  now: number;
  phone: boolean;
  onThreshold(threshold: number): void;
}) {
  const scale = displayScale(draft.source);
  const points = (preview?.series ?? []).map(([t, v]) => [Date.parse(t), v === null ? null : scale.toDisplay(v)] as const);
  const start = points[0]?.[0] ?? now - 24 * HOUR;
  const end = Math.max(points.at(-1)?.[0] ?? now, start + HOUR);
  const threshold = scale.toDisplay(draft.threshold);
  const values = points.flatMap(([, v]) => (v === null ? [] : [v]));
  let [lo, hi] = scale.unit === "%" ? [0, Math.max(100, ...values, threshold)] : [Math.min(...values, threshold), Math.max(...values, threshold)];
  if (scale.unit !== "%") {
    const pad = Math.max((hi - lo) * 0.15, scale.step * 5);
    [lo, hi] = [Math.max(scale.min, lo - pad), hi + pad];
  }
  const x = (t: number) => ((t - start) / (end - start)) * 100;
  const y = (v: number) => (1 - (v - lo) / (hi - lo)) * 100;
  const paths: string[] = [];
  let run: string[] = [];
  for (const [t, v] of points) {
    if (v === null) {
      if (run.length) paths.push(run.join(" "));
      run = [];
    } else run.push(`${run.length ? "L" : "M"}${(x(t) * 10).toFixed(1)},${y(v).toFixed(2)}`);
  }
  if (run.length) paths.push(run.join(" "));
  const span = (a: number, b: number) => ({ left: `${x(Math.max(a, start))}%`, width: `${Math.max(0.3, x(Math.min(b, end)) - x(Math.max(a, start)))}%` });
  const nights = useMemo(() => {
    if (!lights) return [];
    const days = [-2, -1, 0].map((d) => startOfDay(now + d * 24 * HOUR, tz));
    const on = days.map((day) => lightsWindow(day + 12 * HOUR, hh(lights.on), hh(lights.off), tz));
    const out: [number, number][] = [];
    for (let i = 0; i + 1 < on.length; i++) out.push([on[i].off, on[i + 1].on]);
    out.push([on.at(-1)!.off, Number.POSITIVE_INFINITY]);
    out.unshift([Number.NEGATIVE_INFINITY, on[0].on]);
    return out.filter(([a, b]) => b > start && a < end);
  }, [lights?.on, lights?.off, now, tz, start, end]);
  const valueAt = (t: number) => {
    let found: number | null = null;
    for (const [pt, v] of points) if (pt <= t && v !== null) found = v;
    return found;
  };
  const fires = (preview?.fires ?? []).map((f) => ({ start: Date.parse(f.start), at: Date.parse(f.fired_at), end: f.end ? Date.parse(f.end) : end }));
  const short = (preview?.ignored ?? []).filter((s) => s.reason === "shorter than min_duration");
  const ticks = hourTicks(start, end + 1, phone ? 6 : 3, tz);

  // The threshold line: drag, or ArrowUp/ArrowDown by a step (Shift: ten).
  const plot = useRef<HTMLDivElement>(null);
  const round = (v: number) => Number((Math.round(v / scale.step) * scale.step).toFixed(6));
  const move = (display: number) => onThreshold(scale.fromDisplay(round(Math.min(scale.max, Math.max(scale.min, display)))));
  const drag = (e: PointerEvent<HTMLDivElement>) => {
    const box = plot.current?.getBoundingClientRect();
    if (!box || !e.currentTarget.hasPointerCapture(e.pointerId)) return;
    move(hi - ((e.clientY - box.top) / box.height) * (hi - lo));
  };
  const keys = (e: KeyboardEvent<HTMLDivElement>) => {
    const step = scale.step * (e.shiftKey ? 10 : 1);
    const delta = { ArrowUp: step, ArrowRight: step, ArrowDown: -step, ArrowLeft: -step, PageUp: step * 10, PageDown: -step * 10 }[e.key];
    if (delta === undefined) return;
    e.preventDefault();
    move(threshold + delta);
  };
  const shown = (v: number) => `${Number(v.toFixed(2))} ${scale.unit}`;
  const lightsText = lights ? ` · lights ${hh(lights.on)}–${hh(lights.off)}` : "";

  return (
    <figure className="ar-replay" aria-labelledby="ar-replay-title">
      <figcaption className="ar-replay-head">
        <strong id="ar-replay-title">Yesterday, as this rule would have seen it</strong>
        {!phone && <span className="ar-muted">{label}{lightsText}</span>}
        {!phone && (
          <span className="ar-legend" aria-hidden="true">
            <i className="is-fire" /> would alert <i className="is-short" /> too short to alert <i className="is-line" /> your threshold
          </span>
        )}
      </figcaption>
      <div className="ar-chart">
        <div className="ar-yaxis" aria-hidden="true">
          <span>{shown(hi)}</span>
          <span>{shown(lo)}</span>
        </div>
        <div className="ar-plot" ref={plot}>
          {nights.map(([a, b], i) => (
            <div key={`n${i}`} className="ar-night" style={span(a, b)}>
              <span>Lights off</span>
            </div>
          ))}
          {short.map((s) => (
            <div key={s.start} className="ar-short" style={span(Date.parse(s.start), Date.parse(s.end))} title="Too short to alert" />
          ))}
          {fires.map((f) => (
            <div key={f.at} className="ar-fire" style={span(f.start, f.end)} title="Would alert">
              <span>{clock(f.at, tz)}</span>
            </div>
          ))}
          <svg viewBox="0 0 1000 100" preserveAspectRatio="none" aria-hidden="true">
            {paths.map((d, i) => (
              <path key={i} d={d} vectorEffect="non-scaling-stroke" />
            ))}
          </svg>
          {fires.map((f) => {
            const v = valueAt(f.at);
            return v === null ? null : <i key={`d${f.at}`} className="ar-dot" style={{ left: `${x(f.at)}%`, top: `${y(v)}%` }} />;
          })}
          <div
            className="ar-threshold"
            role="slider"
            tabIndex={0}
            aria-label="Threshold"
            aria-valuemin={scale.min}
            aria-valuemax={scale.max}
            aria-valuenow={threshold}
            aria-valuetext={shown(threshold)}
            style={{ top: `${y(threshold)}%` }}
            onKeyDown={keys}
            onPointerDown={(e) => {
              e.currentTarget.setPointerCapture(e.pointerId);
              e.currentTarget.focus();
            }}
            onPointerMove={drag}
            onPointerUp={(e) => e.currentTarget.releasePointerCapture(e.pointerId)}
          >
            <span>{shown(threshold)}</span>
          </div>
          {!points.length && <p className="ar-empty">{error ?? (preview ? "No readings yesterday." : "Reading yesterday…")}</p>}
        </div>
        <div className="ar-xaxis" aria-hidden="true">
          {ticks.map((t) => (
            <span key={t} style={{ left: `${x(t)}%` }}>
              {clock(t, tz)}
            </span>
          ))}
        </div>
      </div>
      <p className="ar-result" role="status" data-replay-sentence data-count={preview?.count ?? undefined}>
        {error && preview ? error : (preview?.sentence ?? "")}
      </p>
    </figure>
  );
}
