import { useEffect, useId, useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Pill, type PillTone } from "@/components/mini-visuals";
import {
  PROBES,
  VERDICT_TEXT,
  evaluate,
  type CalibrationDocument,
  type CalibrationProbe,
  type CalibrationVerdict,
} from "@/lib/calibration";
import type { Controller } from "@/lib/types";
import { errorText } from "@/lib/utils";
import "./probe-calibration.css";

const TONE: Record<CalibrationVerdict, PillTone> = { pass: "on", drifting: "warn", fail: "off" };
const day = (iso: string) =>
  new Date(iso).toLocaleDateString([], { day: "numeric", month: "short", year: "numeric" });
const signed = (value: number) => (value > 0 ? "+" : "") + value;

/** Equipment › Probes: a two-point check of the feed-water pH and EC probes, the ones the
 * source-water gate trusts, and every check before it. A check changes no reading. */
export function ProbeCalibration({ controller }: { controller: Controller }) {
  const [document, setDocument] = useState<CalibrationDocument | null>(null);
  const [error, setError] = useState("");
  const [checking, setChecking] = useState<CalibrationProbe | null>(null);
  useEffect(() => {
    setDocument(null);
    setError("");
    setChecking(null);
    let current = true;
    if (!controller.roomId || !["live", "demo"].includes(controller.connection)) return;
    controller
      .operator<CalibrationDocument>("calibration_get")
      .then((result) => current && setDocument(result))
      .catch((reason) => current && setError(errorText(reason)));
    return () => {
      current = false;
    };
  }, [controller.roomId, controller.connection]);
  if (!document && !error) return null;
  const mapped = document
    ? (Object.keys(PROBES) as CalibrationProbe[]).filter((probe) => document.sensors[probe])
    : [];
  return (
    <section className="panel probe-calibration" aria-labelledby="calibration-title">
      <div className="panel-heading">
        <div>
          <h2 id="calibration-title">Feed probe calibration</h2>
          <p>
            Two reference solutions, what the probe read in each. The feed-water probes guard every
            shot; a check here changes no reading.
          </p>
        </div>
      </div>
      {(error || document?.error) && (
        <p className="calibration-error" role="alert">
          {error || document?.error}
        </p>
      )}
      {document && !mapped.length && (
        <p className="muted">No feed-water probe is mapped. Map one in Setup to check it here.</p>
      )}
      {document && (
        <ul className="calibration-probes">
          {mapped.map((probe) => {
            const last = document.records.find((record) => record.probe === probe);
            return (
              <li key={probe} data-calibration-probe={probe}>
                <span>
                  <strong>{PROBES[probe].label}</strong>
                  <code>{document.sensors[probe]}</code>
                </span>
                {last ? (
                  <span className="calibration-last">
                    <Pill tone={TONE[last.verdict]}>{VERDICT_TEXT[last.verdict]}</Pill>
                    <span className="muted small">Checked {day(last.at)}</span>
                  </span>
                ) : (
                  <span className="muted small">Never checked</span>
                )}
                <Button
                  size="sm"
                  variant="outline"
                  disabled={checking !== null}
                  onClick={() => setChecking(probe)}
                >
                  Check {PROBES[probe].label.replace("Feed-water ", "")}
                </Button>
              </li>
            );
          })}
        </ul>
      )}
      {document && checking && (
        <CheckForm
          key={checking}
          controller={controller}
          probe={checking}
          entityId={document.sensors[checking]!}
          revision={document.revision}
          onDone={(saved) => {
            if (saved) setDocument(saved);
            setChecking(null);
          }}
        />
      )}
      {document && document.records.length > 0 && (
        <div className="table-scroll" tabIndex={0} role="region" aria-label="Calibration history">
          <table className="data-table calibration-history">
            <caption>Calibration history, newest first</caption>
            <thead>
              <tr>
                <th scope="col">Date</th>
                <th scope="col">Probe</th>
                <th scope="col">Slope</th>
                <th scope="col">Offset</th>
                <th scope="col">Result</th>
                <th scope="col">Note</th>
              </tr>
            </thead>
            <tbody>
              {document.records.map((record) => (
                <tr key={record.id} data-calibration-record={record.verdict}>
                  <td>{day(record.at)}</td>
                  <td>{PROBES[record.probe]?.label ?? record.probe}</td>
                  <td className="numeric">{record.slope_pct} %</td>
                  <td className="numeric">
                    {signed(record.offset)} {PROBES[record.probe]?.unit}
                  </td>
                  <td>
                    <Pill tone={TONE[record.verdict]}>{VERDICT_TEXT[record.verdict]}</Pill>
                  </td>
                  <td>{record.note}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function CheckForm({
  controller,
  probe,
  entityId,
  revision,
  onDone,
}: {
  controller: Controller;
  probe: CalibrationProbe;
  entityId: string;
  revision: number;
  onDone: (saved: CalibrationDocument | null) => void;
}) {
  const spec = PROBES[probe];
  const id = useId();
  const [values, setValues] = useState(
    spec.references.map((reference) => ({ reference: String(reference), reading: "" })),
  );
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const points = values.map((value) => ({
    reference: value.reference === "" ? NaN : Number(value.reference),
    reading: value.reading === "" ? NaN : Number(value.reading),
  }));
  const result = values.some((value) => value.reading === "") ? null : evaluate(spec.kind, points);
  const now = controller.states[entityId]?.state;
  const update = (index: number, key: "reference" | "reading", value: string) =>
    setValues(values.map((row, i) => (i === index ? { ...row, [key]: value } : row)));
  return (
    <form
      className="calibration-form"
      aria-label={`Check the ${spec.label} probe`}
      onSubmit={async (event) => {
        event.preventDefault();
        if (!result || "error" in result) return;
        setBusy(true);
        setError("");
        try {
          onDone(
            await controller.operator<CalibrationDocument>("calibration_record", {
              expected_revision: revision,
              probe,
              points,
              ...(note.trim() ? { note: note.trim() } : {}),
            }),
          );
        } catch (reason) {
          setError(errorText(reason));
          setBusy(false);
        }
      }}
    >
      {values.map((value, index) => (
        <fieldset key={index} className="calibration-point">
          <legend>Solution {index + 1}</legend>
          <div>
            <Label htmlFor={`${id}-ref-${index}`}>Reference ({spec.unit})</Label>
            <Input
              id={`${id}-ref-${index}`}
              type="number"
              step="any"
              value={value.reference}
              onChange={(event) => update(index, "reference", event.target.value)}
            />
          </div>
          <div>
            <Label htmlFor={`${id}-read-${index}`}>Probe read ({spec.unit})</Label>
            <Input
              id={`${id}-read-${index}`}
              type="number"
              step="any"
              value={value.reading}
              onChange={(event) => update(index, "reading", event.target.value)}
            />
          </div>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            disabled={!now || !Number.isFinite(Number(now))}
            onClick={() => update(index, "reading", String(now))}
          >
            Use the reading now
          </Button>
        </fieldset>
      ))}
      <div className="calibration-note">
        <Label htmlFor={`${id}-note`}>Note (optional)</Label>
        <Input
          id={`${id}-note`}
          maxLength={200}
          value={note}
          onChange={(event) => setNote(event.target.value)}
        />
      </div>
      <p className="calibration-result" role="status" data-calibration-result>
        {!result ? (
          "Rinse the probe, let it settle in each solution, then enter what it read."
        ) : "error" in result ? (
          result.error
        ) : (
          <>
            Slope {result.slope_pct} % · offset {signed(result.offset)} {spec.unit} ·{" "}
            <Pill tone={TONE[result.verdict]}>{VERDICT_TEXT[result.verdict]}</Pill>
          </>
        )}
      </p>
      {error && (
        <p className="calibration-error" role="alert">
          {error}
        </p>
      )}
      <div className="calibration-actions">
        <Button type="submit" size="sm" disabled={busy || !result || "error" in result}>
          Save the check
        </Button>
        <Button type="button" size="sm" variant="ghost" onClick={() => onDone(null)}>
          Cancel
        </Button>
      </div>
    </form>
  );
}
