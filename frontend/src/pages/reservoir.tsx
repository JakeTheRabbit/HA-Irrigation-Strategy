import { Settings2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Pill } from "@/components/mini-visuals";
import { TankLevel } from "@/components/tank-level";
import { TankStatus } from "@/components/tank-status";
import { dosingStatusId, readStatus } from "@/lib/dosing";
import { batchLine, reservoirView, RELEASE_PCT } from "@/lib/reservoir";
import type { Page } from "@/lib/routes";
import type { Controller } from "@/lib/types";
import "./reservoir.css";

/** The tank on Equipment › Feed & dosing: the tank and pump, what the reservoir minimum is doing,
 * the batch on the tank, and the level charted with the shots, pump runs and fills. Shown also while
 * dosing itself is unavailable (an older integration, or offline), with the last readings. */
export function TankPanels({
  controller,
  navigate,
}: {
  controller: Controller;
  navigate: (page: Page) => void;
}) {
  const prefix = controller.room.room.prefix;
  const guard = reservoirView(controller.states, prefix);
  const batch = batchLine(readStatus(controller.states[dosingStatusId(prefix)]));
  const configure = () => navigate("equipment/setup");
  const litres = (value: number) => value.toLocaleString(undefined, { maximumFractionDigits: 1 });
  return (
    <>
      <TankStatus controller={controller} onConfigure={configure} />
      <section
        className="panel reservoir-guard"
        aria-labelledby="reservoir-guard-title"
        data-reservoir-guard={guard.state}
      >
        <div className="panel-heading">
          <h2 id="reservoir-guard-title">Tank minimum</h2>
          {guard.state === "unmapped" && (
            <Button variant="ghost" onClick={configure}>
              <Settings2 size={16} /> Map the tank level
            </Button>
          )}
        </div>
        <div className="reservoir-guard-body">
          <p className="reservoir-guard-state">
            <Pill dot tone={guard.tone}>
              {guard.label}
            </Pill>
            {guard.code && <a href={`#/help?code=${guard.code}`}>{guard.code}</a>}
          </p>
          <p>{guard.detail}</p>
          {guard.state !== "unmapped" && (
            <dl className="reservoir-guard-facts">
              <div>
                <dt>Minimum</dt>
                <dd>
                  {guard.minimum} % · starts again at {RELEASE_PCT} %
                </dd>
              </div>
              <div>
                <dt>Above the minimum</dt>
                <dd>
                  {guard.aboveMinimumL === null
                    ? "Not learned yet"
                    : `About ${litres(guard.aboveMinimumL)} L`}
                </dd>
              </div>
              <div>
                <dt>Litres per 1 %</dt>
                <dd>
                  {guard.litresPerPct === null
                    ? "Learned from the shots"
                    : `${litres(guard.litresPerPct)} L`}
                </dd>
              </div>
            </dl>
          )}
          {batch && (
            <p className="reservoir-guard-batch">
              <Pill tone={batch.tone}>{batch.label}</Pill>
              <Button variant="link" onClick={() => navigate("equipment/dosing")}>
                Open Dosing
              </Button>
            </p>
          )}
        </div>
      </section>
      <TankLevel controller={controller} onConfigure={configure} />
    </>
  );
}
