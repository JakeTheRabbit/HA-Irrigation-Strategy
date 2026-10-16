import { useMemo, useState } from "react";
import { Check, CircleSlash, Leaf, ListChecks, Table2 } from "lucide-react";
import { number, time as clock } from "@/components/dashboard";
import { Sparkline } from "@/components/mini-visuals";
import { Input } from "@/components/ui/input";
import { descriptor } from "@/lib/model";
import {
  deltaSeries,
  doubleCheck,
  RULES,
  ruleRows,
  shotCheck,
  shotLog,
  stressNow,
  stressSources,
  toC,
  VERDICT_WORDS,
  waterResponse,
  zoneGates,
  type LiveValue,
  type ShotCheck,
} from "@/lib/sensing";
import type { Controller, Zone } from "@/lib/types";
import { useRecentHistory } from "@/lib/use-recent-moisture";
import { errorText } from "@/lib/utils";
import "./sensing.css";

const pts = (v: number | null, digits = 1) => (v === null ? "—" : `${v >= 0 ? "+" : ""}${number(v, digits)}`);

/** Every gate the controller checks before this zone's next shot, pass or hold, in its order: open when one
 * holds. The gates themselves are the controller's and can never be switched off here. */
export function ZoneGates({ controller, zone }: { controller: Controller; zone: Zone }) {
  const gates = zoneGates(controller.states, controller.room.room.prefix, zone.id);
  if (!gates || !gates.length) return null;
  const held = gates.filter((g) => g.state === "hold");
  return (
    <details className="zone-more sensing-gates" open={held.length > 0} data-zone-gates>
      <summary>
        Before the next shot · {held.length ? `${held.length} holding` : "all clear"}
      </summary>
      <ul className="sensing-gate-list" aria-label="Gates before the next shot">
        {gates.map((g) => (
          <li key={g.key} data-state={g.state}>
            {g.state === "hold" ? <CircleSlash size={14} aria-hidden="true" /> : <Check size={14} aria-hidden="true" />}
            <span className="sensing-gate-label">{g.label}</span>
            {g.detail && <span className="muted small">{g.detail}</span>}
          </li>
        ))}
      </ul>
    </details>
  );
}

/** The zone's last shots from the controller's own shot check: the rise each one's litres should give, the
 * rise seen, pore EC, and a verdict (the AI judge's beside it when the AI is on). */
export function ZoneShots({ controller, zone }: { controller: Controller; zone: Zone }) {
  const rows = shotLog(controller.states, controller.room.room.prefix, zone.id);
  if (rows === null) return null;
  const ai = rows.some((r) => r.aiVerdict);
  return (
    <details className="zone-more" data-zone-shots>
      <summary>Last shots · did the water land?</summary>
      {rows.length === 0 ? (
        <p className="muted small sensing-pad">
          No shots since the controller started: the table is kept in memory and fills again with the next shots.
        </p>
      ) : (
        <div className="sensing-scroll">
          <table className="sensing-table">
            <thead>
              <tr>
                <th>Time</th>
                <th>Shot</th>
                <th>Litres</th>
                <th title="VWC points the litres should give the zone's substrate">Expected</th>
                <th title="Highest VWC within 10 min, in points">Spike</th>
                <th title="VWC 20 min after, in points">Kept</th>
                <th title="Pore EC change 20 min after, mS/cm">EC</th>
                <th>Check</th>
                {ai && <th>AI</th>}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.start} data-verdict={r.verdict}>
                  <td>{clock(Date.parse(r.start))}</td>
                  <td>{r.kind.replace(/_/g, " ")}</td>
                  <td>{r.litres === null ? "—" : number(r.litres, 2)}</td>
                  <td>{pts(r.expected)}</td>
                  <td>{pts(r.peak)}</td>
                  <td>{pts(r.retained)}</td>
                  <td>{pts(r.ecMove, 2)}</td>
                  <td>{VERDICT_WORDS[r.verdict] ?? r.verdict}</td>
                  {ai && <td>{r.aiVerdict ? r.aiVerdict.replace(/_/g, " ") : "—"}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </details>
  );
}

function useStress(controller: Controller, zone: number | null) {
  const { states, room } = controller;
  const prefix = room.room.prefix;
  const attrs = descriptor(states, room.room)?.attributes ?? {};
  const sources = stressSources(states, attrs, prefix, zone);
  const lightsOn = useMemo(() => {
    const on = Number(states[`number.crop_steering_${prefix}lights_on_hour`]?.state);
    const off = Number(states[`number.crop_steering_${prefix}lights_off_hour`]?.state);
    if (!Number.isFinite(on) || !Number.isFinite(off) || on === off) return true;
    const h = new Date().getHours();
    return on < off ? h >= on && h < off : h >= on || h < off;
  }, [states, prefix]);
  return { sources, now: sources ? stressNow(states, prefix, sources) : null, lightsOn };
}

/** The plant-stress card: leaf minus air temperature, leaf VPD and, with the grower's own baselines, CWSI.
 * Shown only when the room's Plant stress card switch is on and a leaf sensor is mapped; hidden with the lights
 * off. A reading, never an alarm. */
export function PlantStressCard({ controller, zone }: { controller: Controller; zone: Zone }) {
  const { sources, now, lightsOn } = useStress(controller, zone.id);
  const ids = sources && sources.air ? [sources.leaf, sources.air] : [];
  const series = useRecentHistory(controller, ids, 24);
  if (!sources || !lightsOn) return null;
  const unit = (id: string) => controller.states[id]?.attributes.unit_of_measurement;
  const toPoints = (id: string) =>
    (series?.find((s) => s.entityId === id)?.points ?? []).map((p) => ({
      time: Date.parse(p.time),
      value: toC(p.value, unit(id)),
    }));
  const line = sources.air && series ? deltaSeries(toPoints(sources.leaf), toPoints(sources.air)) : [];
  return (
    <section className="panel sensing-stress" aria-labelledby={`stress-${zone.id}`} data-plant-stress>
      <div className="panel-heading">
        <div>
          <h2 id={`stress-${zone.id}`}>
            <Leaf size={16} aria-hidden="true" /> Plant stress
          </h2>
          <p>Leaf against air, from the mapped leaf sensor. A reading, not an alarm.</p>
        </div>
      </div>
      <div className="zone-panel-body">
        {now === null ? (
          <p className="muted small">The leaf or the air temperature has no reading now.</p>
        ) : (
          <dl className="sensing-facts">
            <div>
              <dt>Leaf − air</dt>
              <dd>
                {pts(now.delta)} °C <Sparkline points={line} label="Leaf minus air over 24 hours" />
              </dd>
            </div>
            <div>
              <dt>Leaf VPD</dt>
              <dd>{now.leafVpd === null ? "needs a humidity sensor" : `${number(now.leafVpd, 2)} kPa`}</dd>
            </div>
            {now.cwsi !== null && (
              <div>
                <dt title="0 transpiring freely, 1 stopped, against your own baselines">CWSI</dt>
                <dd>{number(now.cwsi, 2)}</dd>
              </div>
            )}
          </dl>
        )}
      </div>
    </section>
  );
}

/** Today's one-line plant-stress reading, under the same conditions as the card. */
export function PlantStressStrip({ controller }: { controller: Controller }) {
  const { sources, now, lightsOn } = useStress(controller, null);
  if (!sources || !lightsOn || now === null) return null;
  return (
    <p className="today-line sensing-strip" data-plant-stress-strip>
      <span className="today-fact">
        <Leaf size={14} aria-hidden="true" /> Leaf − air {pts(now.delta)} °C
      </span>
      {now.leafVpd !== null && <span className="today-fact">Leaf VPD {number(now.leafVpd, 2)} kPa</span>}
      {now.cwsi !== null && <span className="today-fact">CWSI {number(now.cwsi, 2)}</span>}
    </p>
  );
}

/** History › Water use: how each zone's quiet lights-on drying answers VPD over its recorded grow-days, when
 * the room's Water vs VPD switch is on. An observation, not a cause. */
export function WaterVpdCard({ controller }: { controller: Controller }) {
  const { states, room } = controller;
  const rows = room.zones.map((zone) => ({ zone, answer: waterResponse(states, room.room.prefix, zone.id) }));
  if (!rows.some((r) => r.answer)) return null;
  return (
    <section className="panel" aria-labelledby="water-vpd-title" data-water-vpd>
      <div className="panel-heading">
        <div>
          <h2 id="water-vpd-title">Drying against VPD</h2>
          <p>
            Each zone’s median quiet dryback rate per grow-day against the day’s mean VPD with the lights on. Plant
            size and light change over the same days, so read it as an observation.
          </p>
        </div>
      </div>
      <ul className="sensing-vpd-list">
        {rows.map(({ zone, answer }) => (
          <li key={zone.id}>
            <strong>{zone.name}</strong>{" "}
            {answer?.slope !== null && answer?.slope !== undefined ? (
              <>
                {number(answer.slope, 2)} points/h per kPa · r {answer.r === null ? "—" : number(answer.r, 2)} ·{" "}
                {answer.days} grow-days
              </>
            ) : null}
            <span className="muted small"> {answer?.words || "Nothing recorded yet."}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function valueText(v: LiveValue, zones: Zone[]) {
  const where = v.zone === null ? "room" : (zones.find((z) => z.id === v.zone)?.name ?? `Zone ${v.zone}`);
  const value = typeof v.value === "boolean" ? (v.value ? "on" : "off") : number(v.value, 2);
  return `${where} ${value}`;
}

/** Help › Rules: the doctrine's rules, searchable and by topic, each with the settings it names and the room's
 * live values; then the settings outside the engine's bounds. Generated from doctrine/doctrine.rules.json. */
export function RulesPanel({ controller }: { controller: Controller }) {
  const [query, setQuery] = useState("");
  const { states, room } = controller;
  const ids = room.zones.map((z) => z.id);
  const rows = ruleRows(states, room.room.prefix, ids, query);
  const flagged = doubleCheck(states, room.room.prefix, ids);
  const topics = [...new Set(rows.map((r) => r.rule.topic))];
  return (
    <section className="panel" aria-labelledby="rules-title" id="rules" data-rules>
      <div className="panel-heading">
        <div>
          <h2 id="rules-title">
            <ListChecks size={16} aria-hidden="true" /> Rules
          </h2>
          <p>
            The {RULES.rules.length} rules the controller and the AI assistant follow (doctrine{" "}
            {RULES.doctrine_version}), with this room’s settings beside the rules that name one.
          </p>
        </div>
      </div>
      <div className="zone-panel-body">
        {flagged.length > 0 && (
          <div className="sensing-flagged" role="note">
            <strong>Double-check these:</strong> outside the engine’s bounds:{" "}
            {flagged.map((v) => `${v.setting.replace(/_/g, " ")} (${valueText(v, room.zones)})`).join(", ")}.
          </div>
        )}
        <Input
          type="search"
          placeholder="Search rules: an id, a topic or words"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Search rules"
        />
        {topics.map((topic) => (
          <details key={topic} className="sensing-topic" open={!!query}>
            <summary>
              {topic.replace(/_/g, " ")} · {rows.filter((r) => r.rule.topic === topic).length}
            </summary>
            <ul className="sensing-rules">
              {rows
                .filter((r) => r.rule.topic === topic)
                .map(({ rule, values }) => (
                  <li key={rule.id}>
                    <span className="sensing-rule-id">{rule.id}</span> {rule.text}{" "}
                    <span className="muted small">({rule.evidence})</span>
                    {values.length > 0 && (
                      <span className="sensing-values">
                        {values.map((v) => (
                          <span key={`${v.setting}-${v.zone}`} data-outside={v.outside || undefined}>
                            {v.setting.replace(/_/g, " ")}: {valueText(v, room.zones)}
                          </span>
                        ))}
                      </span>
                    )}
                  </li>
                ))}
            </ul>
          </details>
        ))}
      </div>
    </section>
  );
}

/** Settings: the room's read-only sensing choices. Each starts off; none changes watering. */
export function SensingSettings({ controller }: { controller: Controller }) {
  const { states, room } = controller;
  const prefix = room.room.prefix;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const live = ["live", "demo"].includes(controller.connection);
  async function write(entityId: string, value: boolean | string | number) {
    setBusy(true);
    setError("");
    try {
      const result = await controller.write([{ entityId, value }]);
      if (result.failed.length) setError(result.failed.map((f) => f.reason).join(" "));
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  const switches: [string, string, string][] = [
    [
      "water_vpd_insight",
      "Water vs VPD",
      "Keep each zone’s grow-day records and relate its quiet drying to the room’s VPD (History › Water use). Needs a VPD sensor, or temperature and humidity.",
    ],
    [
      "plant_stress_card",
      "Plant stress card",
      "Leaf minus air temperature and leaf VPD on Today and the zone page. Needs a leaf temperature sensor in Equipment › Setup.",
    ],
  ];
  const check = shotCheck(states, prefix);
  const checkId = `select.crop_steering_${prefix}shot_check`;
  const modes: [ShotCheck, string][] = [
    ["off", "Off"],
    ["table", "Table"],
    ["table_and_alert", "Table and alert"],
  ];
  const baselines = ["cwsi_lower_baseline", "cwsi_upper_baseline"] as const;
  return (
    <section className="panel settings-section" data-sensing-settings>
      <div className="settings-label">
        <h2>Sensing</h2>
        <p>Read-only readouts for {room.room.name}. None of them changes how the room is watered.</p>
      </div>
      <div className="sensing-settings">
        {switches.map(([key, label, help]) => {
          const id = `switch.crop_steering_${prefix}${key}`;
          const state = states[id]?.state;
          return (
            <label key={key} className="sensing-toggle">
              <input
                type="checkbox"
                checked={state === "on"}
                disabled={!states[id] || busy || !live}
                onChange={(e) => void write(id, e.target.checked)}
              />
              <span>
                <strong>{label}</strong>
                <span className="muted small">{states[id] ? help : "Needs the updated Crop Steering integration."}</span>
              </span>
            </label>
          );
        })}
        <div>
          <h3 id="shot-check-label">
            <Table2 size={16} aria-hidden="true" /> Shot check
          </h3>
          <div className="theme-options" role="group" aria-labelledby="shot-check-label">
            {modes.map(([value, label]) => (
              <button
                key={value}
                className={check === value ? "chosen" : ""}
                aria-pressed={check === value}
                disabled={!states[checkId] || busy || !live}
                onClick={() => void write(checkId, value)}
              >
                <span>{label}</span>
                {check === value && <Check size={16} />}
              </button>
            ))}
          </div>
          <p className="small muted mt-3">
            Table: each zone page lists its last shots and whether the water landed, from the controller’s own
            check. Table and alert: also CS-701 after two shots in a row with no sign of water, only while the AI
            assistant is off (with it on, its shot judge raises CS-701).
          </p>
        </div>
        <div className="sensing-baselines">
          <h3>CWSI baselines (leaf − air, °C)</h3>
          {baselines.map((key) => {
            const id = `number.crop_steering_${prefix}${key}`;
            return (
              <label key={key}>
                {key === "cwsi_lower_baseline" ? "Well watered" : "Not transpiring"}
                <Input
                  type="number"
                  step="0.1"
                  defaultValue={states[id]?.state ?? ""}
                  disabled={!states[id] || busy || !live}
                  onBlur={(e) => {
                    const v = Number(e.target.value);
                    if (e.target.value !== "" && Number.isFinite(v) && String(v) !== states[id]?.state)
                      void write(id, v);
                  }}
                />
              </label>
            );
          })}
          <p className="small muted">Your own canopy’s numbers; CWSI shows only when the second is above the first.</p>
        </div>
        {error && (
          <p className="small error-text" role="alert">
            {error}
          </p>
        )}
      </div>
    </section>
  );
}
