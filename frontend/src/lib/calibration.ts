import type { States } from "./types";

/** A two-point calibration check of a room's feed-water pH or EC probe, as the integration keeps
 * it (custom_components/crop_steering/calibration.py, whose arithmetic `evaluate` repeats so the
 * form can show the result before it is saved). */
export type CalibrationProbe = "feed_ph" | "feed_ec";
export type CalibrationVerdict = "pass" | "drifting" | "fail";
export interface CalibrationPoint {
  reference: number;
  reading: number;
}
export interface CalibrationResult {
  points: CalibrationPoint[];
  slope_pct: number;
  offset: number;
  verdict: CalibrationVerdict;
}
export interface CalibrationRecord extends CalibrationResult {
  id: string;
  probe: CalibrationProbe;
  kind: "ph" | "ec";
  entity_id: string | null;
  at: string;
  note: string;
  /** 3.18: the calibration in force on the probe (a guided calibration); a check is never applied. */
  applied?: boolean;
  due_days?: number;
  superseded_by?: string | null;
}
export interface CalibrationDocument {
  schema_version: number;
  room_id: string;
  revision: number;
  records: CalibrationRecord[];
  sensors: Record<CalibrationProbe, string | null>;
  error: string | null;
  max_records: number;
}

/** What each probe is called, its unit, and the two reference solutions the form starts with. */
export const PROBES: Record<
  CalibrationProbe,
  { label: string; kind: "ph" | "ec"; unit: string; references: [number, number] }
> = {
  feed_ph: { label: "Feed-water pH", kind: "ph", unit: "pH", references: [7, 4] },
  feed_ec: { label: "Feed-water EC", kind: "ec", unit: "mS/cm", references: [1.413, 12.88] },
};
const KINDS = {
  ph: { range: [0, 14], spread: 1, anchor: 7, offset: [0.1, 0.3] },
  ec: { range: [0, 20], spread: 0.5, anchor: 0, offset: [0.1, 0.3] },
} as const;
export const VERDICT_TEXT: Record<CalibrationVerdict, string> = {
  pass: "Passes",
  drifting: "Drifting: clean and recalibrate",
  fail: "Fails: recalibrate or replace",
};
const round = (value: number, places: number) => {
  const factor = 10 ** places;
  return Math.round(value * factor) / factor;
};

/** The probe's slope (%), its offset at the anchor (pH 7, EC 0) and the verdict, or why the two
 * points cannot be used. */
export function evaluate(
  kind: "ph" | "ec",
  points: CalibrationPoint[],
): CalibrationResult | { error: string } {
  const spec = KINDS[kind];
  const [low, high] = spec.range;
  if (points.length !== 2) return { error: "A two-point calibration needs exactly two points" };
  for (const point of points)
    for (const [label, value] of [
      ["Reference", point.reference],
      ["Reading", point.reading],
    ] as const)
      if (!Number.isFinite(value) || value < low || value > high)
        return { error: `${label} must be a number from ${low} to ${high}` };
  const [{ reference: ref1, reading: read1 }, { reference: ref2, reading: read2 }] = points;
  if (Math.abs(ref2 - ref1) < spec.spread)
    return { error: `The two reference solutions must be at least ${spec.spread} apart` };
  const slope = (read2 - read1) / (ref2 - ref1);
  const slope_pct = round(slope * 100, 1);
  const offset = round(read1 + slope * (spec.anchor - ref1) - spec.anchor, 3);
  const [good, drifting] = spec.offset;
  const verdict: CalibrationVerdict =
    slope_pct >= 95 && slope_pct <= 105 && Math.abs(offset) <= good
      ? "pass"
      : slope_pct >= 90 && slope_pct <= 110 && Math.abs(offset) <= drifting
        ? "drifting"
        : "fail";
  return { points: points.map((p) => ({ ...p })), slope_pct, offset, verdict };
}

/** The demo's calibration store: the same answers as the integration, in memory. */
export class CalibrationDemo {
  private documents = new Map<string, CalibrationDocument>();
  constructor(
    private getStates: () => States,
    private now: () => number = Date.now,
  ) {}
  private document(roomId: string): CalibrationDocument {
    const prefix = roomId.startsWith("room:") ? roomId.slice(5) : "";
    const attributes =
      this.getStates()[`sensor.crop_steering_${prefix}engine_config`]?.attributes ?? {};
    const sensor = (key: string) => {
      const value = attributes[key];
      return typeof value === "string" && value ? value : null;
    };
    let document = this.documents.get(roomId);
    if (!document) {
      // Flower 2's pH probe was checked three weeks ago and was drifting. Due every 19 days, it went
      // due two days ago, as the demo's binary_sensor …calibration_due says (parity-demo/status.ts).
      const ph = sensor("feed_ph_sensor");
      const seeded = evaluate("ph", [
        { reference: 7, reading: 7.12 },
        { reference: 4, reading: 4.31 },
      ]) as CalibrationResult;
      document = {
        schema_version: 1,
        room_id: roomId,
        revision: ph ? 1 : 0,
        records: ph
          ? [
              {
                id: "demo-ph-check",
                probe: "feed_ph",
                kind: "ph",
                entity_id: ph,
                at: new Date(this.now() - 21 * 86_400_000).toISOString(),
                note: "",
                ...seeded,
                due_days: 19,
              },
            ]
          : [],
        sensors: { feed_ph: null, feed_ec: null },
        error: null,
        max_records: 100,
      };
      this.documents.set(roomId, document);
    }
    document.sensors = { feed_ph: sensor("feed_ph_sensor"), feed_ec: sensor("feed_ec_sensor") };
    return document;
  }
  /** The room's stored document itself, for the demo's guided calibration (parity-demo/feed-calibration.ts). */
  live(roomId: string): CalibrationDocument {
    return this.document(roomId);
  }
  call(action: string, data: Record<string, unknown>): CalibrationDocument {
    const roomId = String(data.room_id);
    const document = this.document(roomId);
    if (action === "calibration_record") {
      if (data.expected_revision !== document.revision)
        throw new Error("Calibration history changed elsewhere. Reload before saving.");
      const probe = data.probe as CalibrationProbe;
      if (!(probe in PROBES)) throw new Error("Calibrate the feed-water pH or EC probe");
      const result = evaluate(PROBES[probe].kind, data.points as CalibrationPoint[]);
      if ("error" in result) throw new Error(result.error);
      document.records = [
        {
          id: "demo-" + (document.revision + 1),
          probe,
          kind: PROBES[probe].kind,
          entity_id: document.sensors[probe],
          at: new Date(this.now()).toISOString(),
          note: String(data.note ?? "").trim(),
          ...result,
        },
        ...document.records,
      ].slice(0, document.max_records);
      document.revision += 1;
    } else if (action !== "calibration_get") throw new Error("Unsupported workspace action.");
    return structuredClone(document);
  }
}
