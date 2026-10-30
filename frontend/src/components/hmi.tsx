/** The parts every operator card is built from (high-performance HMI): one status line, up to four
 * gauges that show a value against its target, and at most one advisory "Check" chip. Colour is used
 * only for a value that is not normal; everything else is grey. */
import type { HTMLAttributes, ReactNode } from "react";
import { CircleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { gaugeSpeech, type GaugeModel } from "@/lib/hmi";
import { trimNumber as fix } from "@/lib/utils";
import "./hmi.css";


/** "Zone 1 · P2 · Maintenance [on plan]": what the reader must see first. */
export function StatusLine({
  name,
  phase,
  state,
  children,
  ...rest
}: {
  name?: ReactNode;
  phase?: string | null;
  state: { text: string; abnormal: boolean } | null;
  children?: ReactNode;
} & HTMLAttributes<HTMLParagraphElement>) {
  const parts = [name, phase].filter(Boolean);
  return (
    <p className="hmi-status" data-hmi-status {...rest}>
      {parts.map((part, index) => (
        <span key={index} className={index ? "hmi-status-part" : "hmi-status-name"}>
          {part}
        </span>
      ))}
      {state && (
        <span className="hmi-chip" data-abnormal={state.abnormal ? "" : undefined}>
          {state.text}
        </span>
      )}
      {children}
    </p>
  );
}

/** A data-quality note beside the status: muted, never an alarm colour. */
export function QualityChip({ children, ...rest }: HTMLAttributes<HTMLSpanElement>) {
  return (
    <span className="hmi-chip hmi-quality" {...rest}>
      {children}
    </span>
  );
}

/** One analog indicator: the value, a bar with its target or band, and the deviation. */
export function Gauge({
  model,
  id,
  marksKey = true,
}: {
  model: GaugeModel;
  id?: string;
  /** Show the key of the marked levels under the bar (else the row shows it). */
  marksKey?: boolean;
}) {
  const span = model.max - model.min || 1;
  const at = (value: number) =>
    `${Math.min(100, Math.max(0, ((value - model.min) / span) * 100))}%`;
  const unit = (value: number) => `${fix(value, model.digits)}${model.unit}`;
  return (
    <div
      className="hmi-gauge"
      data-gauge={id}
      data-state={model.state}
      role="img"
      aria-label={gaugeSpeech(model)}
    >
      <div className="hmi-gauge-head">
        <span className="hmi-gauge-label">{model.label}</span>
        <strong className="hmi-gauge-value">
          {model.value === null ? "—" : fix(model.value, model.digits)}
          {model.value !== null && model.unit && <span className="unit">{model.unit}</span>}
        </strong>
      </div>
      <div className="hmi-gauge-track">
        {model.band && (
          <span
            className="hmi-gauge-band"
            style={{
              left: at(model.band[0]),
              width: `calc(${at(model.band[1])} - ${at(model.band[0])})`,
            }}
          />
        )}
        {model.value !== null && (
          <span className="hmi-gauge-fill" style={{ width: at(model.value) }} />
        )}
        {model.reference && (
          <span
            className="hmi-gauge-reference"
            style={{
              left: at(model.reference[0]),
              width: `calc(${at(model.reference[1])} - ${at(model.reference[0])})`,
            }}
          />
        )}
        {model.marks.map((mark) => (
          <span
            key={mark.key}
            className="hmi-gauge-mark"
            data-mark={mark.key}
            style={{ left: at(mark.value) }}
          />
        ))}
        {model.target !== null && !model.band && (
          <span className="hmi-gauge-target" style={{ left: at(model.target) }} />
        )}
      </div>
      <div className="hmi-gauge-foot">
        <span>
          {model.band
            ? `${fix(model.band[0], model.digits)}–${unit(model.band[1])}`
            : model.target !== null
              ? `target ${unit(model.target)}`
              : ""}
          {model.reference &&
            ` · ref ${fix(model.reference[0], 0)}–${fix(model.reference[1], 0)}${model.unit}`}
        </span>
        <span className="hmi-gauge-words">{model.words}</span>
      </div>
      {marksKey && <MarksKey model={model} />}
    </div>
  );
}

function MarksKey({ model }: { model: GaugeModel }) {
  if (!model.marks.length) return null;
  return (
    <p className="hmi-gauge-marks">
      {model.marks.map((mark) => (
        <span key={mark.key} data-mark={mark.key}>
          {mark.label} {fix(mark.value, model.digits)}
        </span>
      ))}
    </p>
  );
}

/** Up to four gauges in a row; two by two on a phone. With `marksBelow`, the key of the marked
 * levels is one line under the whole row instead of under a narrow gauge. */
export function GaugeRow({
  gauges,
  label,
  className = "",
  marksBelow = false,
}: {
  gauges: { id: string; model: GaugeModel }[];
  label: string;
  className?: string;
  marksBelow?: boolean;
}) {
  const marked = gauges.find((item) => item.model.marks.length);
  return (
    <div className={`hmi-gauges-box ${className}`} role="group" aria-label={label}>
      <div className="hmi-gauges">
        {gauges.slice(0, 4).map((item) => (
          <Gauge key={item.id} id={item.id} model={item.model} marksKey={!marksBelow} />
        ))}
      </div>
      {marksBelow && marked && <MarksKey model={marked.model} />}
    </div>
  );
}

/** The one advisory under a chart: a sentence and, when there is one, the change that fixes it.
 * The action changes the draft only. Alerts keep their own system; this is not an alarm. */
export function CheckChip({
  text,
  action,
  ...rest
}: {
  text: string;
  action?: { label: string; run: () => void } | null;
} & HTMLAttributes<HTMLDivElement>) {
  return (
    <div className="hmi-check" role="note" {...rest}>
      <CircleAlert size={16} aria-hidden="true" />
      <span className="hmi-check-label">Check</span>
      <span className="hmi-check-text">{text}</span>
      {action && (
        <Button type="button" variant="outline" size="sm" onClick={action.run}>
          {action.label}
        </Button>
      )}
    </div>
  );
}
