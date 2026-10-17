import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { ReviewDialog } from "@/components/dashboard";
import {
  PROFILE_FIELDS,
  configDiff,
  contextTokenEstimate,
  defaultPromptConfig,
  normalizeConfig,
  validateConfig,
  type InstructionsDocument,
  type PromptConfig,
} from "@/lib/brain-instructions";
import type { Controller } from "@/lib/types";
import "./brain-instructions.css";

const labels: Record<string, string> = {
  substrate: "Substrate product and layout",
  environment: "Environment and climate",
  genetics: "Cultivar and genetics",
  stage: "Stage and dates",
  feed: "Feed and recipe",
  goals: "Yield and quality goals",
  constraints: "Constraints",
  calibration: "Probe calibration",
};
const hints: Record<string, string> = {
  substrate: "Brand, slab or pot layout, plants per slab and drippers",
  environment: "Sealed or vented, CO₂, PPFD/DLI, AC, dehumidifiers and targets",
  genetics: "Cultivar per zone and expected flower length",
  stage: "Flower start and weekly steering intent",
  feed: "Nutrient line, source water and measured runoff",
  goals: "Yield priority, quality goals and observations",
  constraints: "Water, labour, equipment and operating limits",
  calibration: "Probe calibration date, units and reference method",
};

export function BrainInstructions({
  controller,
  onDirtyChange,
}: {
  controller: Controller;
  onDirtyChange?: (dirty: boolean) => void;
}) {
  const [doc, setDoc] = useState<InstructionsDocument | null>(null);
  const [draft, setDraft] = useState<PromptConfig>(defaultPromptConfig);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [review, setReview] = useState(false);
  const generation = useRef(0);
  const room = controller.roomId;
  const writable = controller.admin !== false && ["demo", "live"].includes(controller.connection);
  const changes = doc ? configDiff(doc.config, draft) : [];
  const invalid = validateConfig(draft);
  useEffect(() => {
    onDirtyChange?.(changes.length > 0);
    return () => onDirtyChange?.(false);
  }, [changes.length, onDirtyChange]);
  useEffect(() => {
    const current = ++generation.current;
    setDoc(null);
    setError("");
    setDraft(defaultPromptConfig());
    controller
      .operator<InstructionsDocument>("brain_prompt_get", { room_id: room })
      .then((data) => {
        if (current !== generation.current) return;
        setDoc(data);
        setDraft(data.config);
      })
      .catch((err) => {
        if (current === generation.current) setError(String(err.message ?? err));
      });
    return () => {
      generation.current++;
    };
  }, [room, controller.operator]);
  async function reload() {
    const current = generation.current;
    setBusy(true);
    setError("");
    try {
      const data = await controller.operator<InstructionsDocument>("brain_prompt_get", {
        room_id: room,
      });
      if (current === generation.current) setDoc(data);
    } catch (err) {
      if (current === generation.current) setError(String(err));
    } finally {
      if (current === generation.current) setBusy(false);
    }
  }
  async function save() {
    if (!doc || invalid) throw new Error(invalid ?? "Instructions have not loaded.");
    const current = generation.current;
    const sent = normalizeConfig(draft);
    const saved = await controller.operator<InstructionsDocument>("brain_prompt_save", {
      room_id: room,
      expected_revision: doc.revision,
      config: sent,
    });
    const read = await controller.operator<InstructionsDocument>("brain_prompt_get", {
      room_id: room,
    });
    if (read.revision !== saved.revision || configDiff(sent, read.config).length)
      throw new Error("Instructions changed before readback. Reload and review again.");
    if (current === generation.current) {
      setDoc(read);
      setDraft(read.config);
    }
  }
  async function rebuild() {
    if (!doc) return;
    setBusy(true);
    setError("");
    const current = generation.current;
    try {
      const data = await controller.operator<InstructionsDocument>("brain_prompt_rebuild", {
        room_id: room,
        expected_revision: doc.revision,
      });
      if (current === generation.current) setDoc(data);
    } catch (err) {
      if (current === generation.current) setError(String(err));
    } finally {
      if (current === generation.current) setBusy(false);
    }
  }
  const prefix = controller.room.room.prefix;
  const value = (domain: string, key: string) =>
    controller.states[`${domain}.crop_steering_${prefix}${key}`]?.state ?? "Not reported";
  return (
    <section className="panel settings-section" data-brain-instructions>
      <div className="settings-label">
        <h2>Instructions</h2>
        <p>Read the controller's prompt. Add room context, house notes and cache preferences.</p>
      </div>
      <div className="brain-instructions">
        {error && (
          <p role="alert" className="form-error">
            {error}
          </p>
        )}
        {!doc ? (
          <p>
            {error
              ? "The updated integration must be installed to edit instructions."
              : "Loading instructions…"}
          </p>
        ) : (
          <>
            <div className="split-row">
              <span>Saved revision {doc.revision}</span>
              <Button variant="outline" disabled={busy} onClick={reload}>
                Refresh controller snapshot
              </Button>
            </div>
            {doc.live ? (
              <>
                <p role="status">
                  {doc.live.revision === doc.revision && doc.live.rebuild === doc.rebuild
                    ? "Controller has built this saved revision."
                    : "Waiting for the controller to build the saved settings."}{" "}
                  Snapshot: {doc.live.published_at}. Stage arc: {doc.live.stage_arc ?? "none"}.
                </p>
                {doc.live.blocks.map((block) => (
                  <details key={block.id} className="prompt-block">
                    <summary>
                      Block {block.id} · {block.tokens_estimate.toLocaleString()} tokens estimated ·{" "}
                      {block.hash.slice(0, 12)}
                    </summary>
                    <p>Sources: {block.sources.join(", ")}</p>
                    <p>
                      SHA-256: <code>{block.hash}</code>
                    </p>
                    <p>
                      {block.cache_control
                        ? `Cache breakpoint: ${block.cache_control.ttl ?? "5m"}`
                        : "No cache breakpoint on this block"}
                    </p>
                    <pre>{block.text}</pre>
                  </details>
                ))}
              </>
            ) : (
              <p>
                No controller-built prompt has been published.{" "}
                {controller.demo
                  ? "The demo never calls an AI provider."
                  : "The Claude provider must be configured in the controller app. This page does not generate a substitute prompt."}
              </p>
            )}
            <p>
              Cache reads today: {(doc.telemetry.tokens_today?.cache_read ?? 0).toLocaleString()}{" "}
              tokens. Hit ratio:{" "}
              {doc.telemetry.cache_hit_ratio == null
                ? "not reported"
                : `${Math.round(doc.telemetry.cache_hit_ratio * 100)}%`}
              . AI spend reported:{" "}
              {doc.telemetry.spent_usd == null
                ? "not reported"
                : `US$${doc.telemetry.spent_usd.toFixed(4)}`}
              .
            </p>
            <p>
              Estimated net cache savings this usage window:{" "}
              {doc.telemetry.cache_savings_estimate_usd == null
                ? "not reported (older usage data becomes known at the next reset)"
                : `US$${doc.telemetry.cache_savings_estimate_usd.toFixed(4)}`}
              . Compared with the same input billed without caching, using the controller's
              configured model tariff. Includes cache-write charges and conservative timeout
              estimates; a negative value means caching cost more.
            </p>
            <details open>
              <summary>Grow context</summary>
              <p>
                Substrate selected: <strong>{value("select", "substrate")}</strong>. Growth stage:{" "}
                <strong>{value("select", "growth_stage")}</strong>. Change substrate in Equipment
                and growth stage in Irrigation; notes below provide context and never change those
                settings.
              </p>
              {PROFILE_FIELDS.map((key) => (
                <div key={key}>
                  <Label htmlFor={`prompt-profile-${key}`}>{labels[key]}</Label>
                  <textarea
                    id={`prompt-profile-${key}`}
                    maxLength={1000}
                    disabled={!writable}
                    value={draft.profile[key] ?? ""}
                    placeholder={hints[key]}
                    onChange={(event) =>
                      setDraft({
                        ...draft,
                        profile: { ...draft.profile, [key]: event.target.value },
                      })
                    }
                  />
                </div>
              ))}
            </details>
            <Label htmlFor="prompt-notes">House rules and site notes</Label>
            <textarea
              id="prompt-notes"
              maxLength={12000}
              rows={8}
              disabled={!writable}
              value={draft.notes}
              onChange={(event) => setDraft({ ...draft, notes: event.target.value })}
              placeholder="Operating preferences and observations. Use headings to organise notes."
            />
            <p>
              Block C appears only when notes or context are set. The shipped rules remain
              unchanged. Never put credentials or personal information here; this context is sent to
              the AI provider.
            </p>
            <details>
              <summary>Caching</summary>
              <Label htmlFor="prompt-ttl">System block cache TTL</Label>
              <select
                id="prompt-ttl"
                disabled={!writable}
                value={draft.cache.ttl}
                onChange={(event) =>
                  setDraft({
                    ...draft,
                    cache: { ...draft.cache, ttl: event.target.value as "5m" | "1h" },
                  })
                }
              >
                <option value="5m">5 minutes</option>
                <option value="1h">1 hour</option>
              </select>
              {(["A", "B", "C", "evidence"] as const).map((key) => (
                <label className="prompt-cache-option" key={key}>
                  <input
                    type="checkbox"
                    disabled={!writable}
                    checked={draft.cache[key]}
                    onChange={(event) =>
                      setDraft({ ...draft, cache: { ...draft.cache, [key]: event.target.checked } })
                    }
                  />
                  {key === "evidence"
                    ? "Evidence breakpoint (5 minutes)"
                    : `Block ${key} breakpoint`}
                </label>
              ))}
              <p>
                Each breakpoint caches the cumulative prefix. Caching B or C can also cache A, even
                with A's breakpoint off. TTL changes affect future requests; 1-hour writes cost more
                than 5-minute writes.
              </p>
              <Button variant="outline" disabled={!writable || busy} onClick={rebuild}>
                Rebuild local prompt
              </Button>
              <p>
                This asks the controller to rebuild on its next pass. It does not purge the
                provider's cache or make a paid call.
              </p>
            </details>
            {invalid && <p role="alert">{invalid}</p>}
            <div className="split-row">
              <Button
                disabled={!writable || !changes.length || !!invalid}
                onClick={() => setReview(true)}
              >
                Review instructions
              </Button>
              <Button
                variant="outline"
                disabled={!writable}
                onClick={() => setDraft(defaultPromptConfig())}
              >
                Restore defaults to draft
              </Button>
            </div>
            {doc.history.length > 0 && (
              <details>
                <summary>Saved versions</summary>
                {[...doc.history].reverse().map((entry) => (
                  <div className="split-row" key={entry.revision}>
                    <span>
                      Revision {entry.revision} · {entry.at}
                    </span>
                    <Button
                      variant="outline"
                      disabled={!writable}
                      onClick={() => setDraft(structuredClone(entry.config))}
                    >
                      Load into draft
                    </Button>
                  </div>
                ))}
              </details>
            )}
            {changes.length > 0 && (
              <details open>
                <summary>Draft difference</summary>
                {changes.map((change) => (
                  <div className="prompt-diff" key={change.key}>
                    <strong>{change.label}</strong>
                    <pre className="before">{change.before}</pre>
                    <pre className="after">{change.after}</pre>
                  </div>
                ))}
              </details>
            )}
            <ReviewDialog
              controller={controller}
              open={review}
              onOpenChange={setReview}
              title="Review AI instructions"
              items={changes.map((change) => ({
                change: { entityId: `prompt.${change.key}`, value: "context" },
                label: change.label,
                before: change.before.slice(0, 100),
                after: change.after.slice(0, 100),
              }))}
              run={save}
              note={`Context text: about ${contextTokenEstimate(draft)} tokens, estimated from character count. Cache writes and reads affect billed input cost; savings are not guaranteed. The controller applies these notes on its next pass.`}
              caution="Code-enforced safety, holds, budgets and permitted powers continue to apply."
            />
          </>
        )}
      </div>
    </section>
  );
}
