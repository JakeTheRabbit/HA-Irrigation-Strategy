import { evaluate, type CalibrationDemo, type CalibrationRecord } from "../calibration";
import { looksSteady, spanOver, steadyFor, type FeedKind, type FeedProbe, type Reading } from "../feed-calibration";
import type { States } from "../types";
import { demoId } from "./journal";

/** The demo's guided feed pH/EC calibration on 3.18 (calibration.py calibration_start, _capture,
 * _status, _commit, _revert), answered as v2 envelopes. While a session is open the demo probe reports
 * every second: it settles from where it read toward what it reads in the buffer (pH 7.04 then 4.09;
 * EC 1.40 then 2.74), and starts toward the second buffer once the first point is captured. Like the
 * integration: a capture stores a point only when the last 30 s held still (or `force`), a session ends
 * 30 min after its last capture, a commit applies a pass or drifting result (a fail is kept, never
 * applied) and writes sensor.crop_steering_<prefix><probe>_corrected, and its Journal event puts the
 * calibration it replaced back (refused once the calibration in force is another). */

const PROBES: Record<FeedProbe, { kind: FeedKind; key: string }> = {
  feed_ph: { kind: "ph", key: "feed_ph_sensor" },
  feed_ec: { kind: "ec", key: "feed_ec_sensor" },
};
const SOLUTIONS: Record<FeedKind, [number, number]> = { ph: [7, 4], ec: [1.413, 2.77] };
/** What the demo probe reads in each buffer. */
const READS: Record<FeedKind, [number, number]> = { ph: [7.04, 4.09], ec: [1.4, 2.74] };
const ANCHOR: Record<FeedKind, number> = { ph: 7, ec: 0 };
const NAME: Record<FeedKind, string> = { ph: "pH", ec: "EC" };
const SETTLE_MS = 6_000;
const IDLE_MS = 30 * 60_000;
const EXPIRED = "Calibration session expired. Start again.";

interface Point {
  reference: number;
  reading: number;
  stable_s: number;
  forced: boolean;
}
interface Session {
  id: string;
  roomId: string;
  prefix: string;
  probe: FeedProbe;
  kind: FeedKind;
  entity: string;
  temperature: string | null;
  solutions: [number, number];
  points: (Point | null)[];
  active: number;
  samples: Reading[];
  sim: { from: number; to: number; since: number };
}

const iso = (ms: number) => new Date(ms).toISOString();
const round = (value: number, places: number) => Math.round(value * 10 ** places) / 10 ** places;
const ok = (data: unknown, now: number, roomId: string | null, eventIds: string[] = [], readback = "none") => ({
  api: 2,
  ok: true,
  room_id: roomId,
  revision: null,
  readback: { status: readback, at: iso(now) },
  event_ids: eventIds,
  data,
});
const refuse = (code: string, message: string, data?: unknown) => ({
  api: 2,
  ok: false,
  error: { code, message },
  ...(data !== undefined ? { data } : {}),
});
const correct = (raw: number, slopePct: number, offset: number, anchor: number) => anchor + (raw - anchor - offset) / (slopePct / 100);

export class FeedCalibrationDemo {
  private sessions = new Map<string, Session>();
  /** Each commit's Journal event: what Undo puts back. */
  private events = new Map<string, { roomId: string; probe: FeedProbe; recordId: string }>();
  private timer: ReturnType<typeof setInterval> | undefined;
  constructor(
    private getStates: () => States,
    private updateStates: (states: States) => void,
    private store: () => CalibrationDemo,
    private now: () => number = Date.now,
  ) {}

  /** Every session this demo opened, ended ones included: a step on one that ended is EXPIRED. */
  private opened = new Set<string>();
  /** Whether this Journal event is one of the demo's calibration commits. */
  owns(eventId: string) {
    return this.events.has(eventId);
  }
  /** Whether the call is this demo's: a start or revert naming a feed probe, a step on a session it
   * opened. Anything else falls through to Task 3's plain answers. */
  handles(action: string, data: Record<string, unknown>) {
    if (action === "calibration_start" || action === "calibration_revert") return typeof data.probe === "string" && data.probe in PROBES;
    return this.opened.has(String(data.session_id));
  }

  call(action: string, data: Record<string, unknown>): unknown {
    const now = this.now();
    this.expire(now);
    try {
      if (action === "calibration_start") return this.start(data, now);
      if (action === "calibration_revert") return this.revert(String(data.room_id), data.probe as FeedProbe, now, null);
      if (action === "history_revert") {
        const event = this.events.get(String(data.event_id))!;
        return this.revert(event.roomId, event.probe, now, event.recordId);
      }
      const session = this.sessions.get(String(data.session_id));
      if (!session) return refuse("invalid", EXPIRED);
      if (action === "calibration_status")
        return ok(
          { ...this.measure(session, now), points_captured: session.points.filter(Boolean).length, expires_at: iso(session.active + IDLE_MS) },
          now,
          session.roomId,
        );
      if (action === "calibration_capture") return this.capture(session, data, now);
      if (action === "calibration_commit") return this.commit(session, now);
    } catch (error) {
      return refuse("invalid", error instanceof Error ? error.message : String(error));
    }
    return refuse("invalid", `Unsupported demo action ${action}`);
  }

  private reading(entity: string): number | null {
    const value = Number(this.getStates()[entity]?.state);
    return Number.isFinite(value) && this.getStates()[entity]?.state !== "" ? value : null;
  }
  private measure(session: Session, now: number) {
    const raw = this.reading(session.entity);
    if (raw === null) return { reading: null, raw: null, stable: false, drift: null, stable_s: 0 };
    const samples = [...session.samples, { at: now, value: raw }];
    const r = spanOver(samples);
    return {
      reading: raw,
      raw,
      stable: looksSteady(r, session.kind),
      drift: Number.isNaN(r.span) ? round(Math.max(...samples.map((s) => s.value)) - Math.min(...samples.map((s) => s.value)), 4) : round(r.span, 4),
      stable_s: Math.floor(steadyFor(samples, session.kind) / 1000),
    };
  }

  private start(data: Record<string, unknown>, now: number) {
    const roomId = String(data.room_id);
    const probe = data.probe as FeedProbe;
    if (!(probe in PROBES)) throw new Error("Calibrate the feed-water pH or EC probe");
    const { kind, key } = PROBES[probe];
    const prefix = roomId.replace(/^room:/, "");
    const attributes = this.getStates()[`sensor.crop_steering_${prefix}engine_config`]?.attributes ?? {};
    const entity = typeof attributes[key] === "string" && attributes[key] ? String(attributes[key]) : null;
    if (!entity) throw new Error(`The room has no feed ${NAME[kind]} probe set up`);
    const raw = this.reading(entity);
    if (raw === null) throw new Error(`No reading from the feed ${NAME[kind]} probe for 2 min. Check it's plugged in.`);
    // One session per room: a new start replaces the last.
    for (const [id, s] of this.sessions) if (s.roomId === roomId) this.sessions.delete(id);
    const temperature = typeof attributes.tank_temperature_sensor === "string" ? attributes.tank_temperature_sensor : null;
    const session: Session = {
      id: demoId(now, `feed-cal:${roomId}:${probe}:${this.sessions.size}:${Math.random()}`),
      roomId,
      prefix,
      probe,
      kind,
      entity,
      temperature,
      solutions: SOLUTIONS[kind],
      points: [null, null],
      active: now,
      // Not steady until the probe has reported for a whole window in the buffer.
      samples: [{ at: now, value: raw }],
      sim: { from: raw, to: READS[kind][0], since: now },
    };
    this.sessions.set(session.id, session);
    this.opened.add(session.id);
    this.tick();
    return ok(
      {
        session_id: session.id,
        room_id: roomId,
        probe,
        kind,
        solutions: session.solutions,
        raw_entity_id: entity,
        temperature_entity_id: temperature,
        dosing_paused: true,
        expires_at: iso(now + IDLE_MS),
      },
      now,
      roomId,
    );
  }

  private capture(session: Session, data: Record<string, unknown>, now: number) {
    const point = Number(data.point);
    if (point !== 0 && point !== 1) throw new Error("point must be 0 or 1");
    const measured = this.measure(session, now);
    if (measured.raw === null) throw new Error(`No reading from the feed ${NAME[session.kind]} probe for 2 min. Check it's plugged in.`);
    session.active = now;
    if (!measured.stable && data.force !== true)
      return refuse("guard_refused", "The reading is not steady yet: nothing was captured. Wait, or capture it anyway.", measured);
    session.points[point] = { reference: session.solutions[point], reading: measured.raw, stable_s: measured.stable_s, forced: !measured.stable };
    // The grower rinses the probe and stands it in the second buffer next.
    if (point === 0) session.sim = { from: measured.raw, to: READS[session.kind][1], since: now };
    return ok(measured, now, session.roomId, [demoId(now, `feed-cal-capture:${session.id}:${point}`)]);
  }

  private commit(session: Session, now: number) {
    if (session.points.some((p) => !p)) throw new Error("Capture both points before applying the calibration");
    const points = session.points as Point[];
    const result = evaluate(
      session.kind,
      points.map((p) => ({ reference: p.reference, reading: p.reading })),
    );
    if ("error" in result) throw new Error(result.error);
    const applied = result.verdict !== "fail";
    const doc = this.store().live(session.roomId);
    const record: CalibrationRecord = {
      id: demoId(now, `feed-cal-record:${session.id}`).toLowerCase(),
      probe: session.probe,
      kind: session.kind,
      entity_id: session.entity,
      at: iso(now),
      note: "",
      ...result,
      applied,
      due_days: 30,
      superseded_by: null,
    };
    if (applied)
      for (const old of doc.records)
        if (old.probe === record.probe && old.applied) {
          old.applied = false;
          old.superseded_by = record.id;
        }
    doc.records = [record, ...doc.records];
    doc.revision += 1;
    this.sessions.delete(session.id);
    const eventId = demoId(now, `feed-cal-commit:${record.id}`);
    this.events.set(eventId, { roomId: session.roomId, probe: session.probe, recordId: record.id });
    if (!applied)
      return refuse(
        "invalid",
        `The probe failed calibration (response ${record.slope_pct} %, offset ${record.offset}). It is recorded but not applied: clean or replace the probe and calibrate it again.`,
      );
    this.publishCorrected(session.roomId, session.probe);
    return ok(
      { record_id: record.id, revision: doc.revision, slope_pct: record.slope_pct, offset: record.offset, verdict: record.verdict, applied: true },
      now,
      session.roomId,
      [eventId],
    );
  }

  /** Takes the applied calibration off and puts back the one it replaced. With `recordId` (an Undo of
   * that commit) only while that calibration is still the one in force. */
  private revert(roomId: string, probe: FeedProbe, now: number, recordId: string | null) {
    const doc = this.store().live(roomId);
    const current = doc.records.find((r) => r.probe === probe && r.applied);
    if (recordId !== null && current?.id !== recordId)
      return refuse("stale_revision", "The probe's calibration changed since this change. Reload before putting it back.");
    if (!current) throw new Error(`No applied calibration of the feed ${NAME[PROBES[probe].kind]} probe to put back`);
    current.applied = false;
    const previous = doc.records.find((r) => r.superseded_by === current.id);
    if (previous) {
      previous.applied = true;
      previous.superseded_by = null;
    }
    doc.revision += 1;
    for (const [id, s] of this.sessions) if (s.roomId === roomId) this.sessions.delete(id);
    this.publishCorrected(roomId, probe);
    const data = { probe, revision: doc.revision, reverted_record_id: current.id, record_id: previous?.id ?? null, applied: !!previous };
    return recordId === null
      ? ok(data, now, roomId, [demoId(now, `feed-cal-revert:${current.id}`)])
      : ok(
          { reverted_event_id: null, new_event_id: demoId(now, `feed-cal-revert:${current.id}`), readback: "verified" },
          now,
          roomId,
          [],
          "verified",
        );
  }

  /** sensor.crop_steering_<prefix><probe>_corrected: the raw reading under the calibration in force. */
  private publishCorrected(roomId: string, probe: FeedProbe) {
    const prefix = roomId.replace(/^room:/, "");
    const { kind, key } = PROBES[probe];
    const states = this.getStates();
    const source = String(states[`sensor.crop_steering_${prefix}engine_config`]?.attributes[key] ?? "");
    const record = this.store()
      .live(roomId)
      .records.find((r) => r.probe === probe && r.applied);
    const raw = this.reading(source);
    const id = `sensor.crop_steering_${prefix}${probe}_corrected`;
    const stamp = iso(this.now());
    this.updateStates({
      ...states,
      [id]: {
        entity_id: id,
        state: record && raw !== null ? String(round(correct(raw, record.slope_pct, record.offset, ANCHOR[kind]), 3)) : "unknown",
        attributes: {
          friendly_name: `Feed ${NAME[kind]} corrected`,
          unit_of_measurement: kind === "ph" ? "pH" : "mS/cm",
          source,
          applied: !!record,
          slope_pct: record?.slope_pct ?? null,
          offset: record?.offset ?? null,
        },
        last_changed: stamp,
        last_updated: stamp,
      },
    });
  }

  private expire(now: number) {
    for (const [id, s] of this.sessions) if (now - s.active >= IDLE_MS) this.sessions.delete(id);
    if (!this.sessions.size && this.timer !== undefined) {
      clearInterval(this.timer);
      this.timer = undefined;
    }
  }
  /** Every second while a session is open: each session's probe reports where it has settled to. */
  private tick() {
    if (this.timer !== undefined) return;
    this.timer = setInterval(() => {
      const now = this.now();
      this.expire(now);
      if (!this.sessions.size) return;
      let states = this.getStates();
      const stamp = iso(now);
      for (const s of this.sessions.values()) {
        const digits = 2;
        const value = round(s.sim.to + (s.sim.from - s.sim.to) * Math.exp(-(now - s.sim.since) / SETTLE_MS), digits);
        const old = states[s.entity];
        if (!old) continue;
        const changed = Number(old.state) !== value;
        if (changed) {
          // As the integration keeps them: the last 5 min, and the reading before that.
          const keep = now - 10 * 30_000;
          s.samples = [...s.samples.filter((r) => r.at <= keep).slice(-1), ...s.samples.filter((r) => r.at > keep), { at: now, value }];
        }
        states = {
          ...states,
          [s.entity]: { ...old, state: String(value), last_updated: stamp, last_changed: changed ? stamp : old.last_changed },
        };
      }
      this.updateStates(states);
    }, 1_000);
  }
}
