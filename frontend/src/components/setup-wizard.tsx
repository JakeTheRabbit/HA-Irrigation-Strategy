import { useState } from "react";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { MARK_SYMBOL, WIZARD_STEPS, stepMark, switchOn, warnings } from "@/lib/commissioning";
import type { Controller } from "@/lib/types";
import type { Commissioning, SetupDocument, SetupRoom } from "@/lib/operator-types";
import { startTour } from "@/lib/tour";
import { errorText } from "@/lib/utils";

/** The setup wizard for a room still being set up: each step's live check, the test shot a person
 * watches, and Switch on, which waits for every safety check. Mapping, probes and sizing are edited in
 * the room's setup below; this only checks them. Switch on marks the room set up; watering itself is
 * switched on with the room's Watering switch, through its usual review. */
export function SetupWizard({
  controller,
  room,
  onStatus,
}: {
  controller: Controller;
  room: SetupRoom;
  onStatus: (status: Commissioning) => void;
}) {
  const status = room.commissioning!;
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [asked, setAsked] = useState<Record<number, string>>({}),
    [notSeen, setNotSeen] = useState<number | null>(null);
  const gate = switchOn(status);
  const next = WIZARD_STEPS.findIndex(
    (s) => !s.check || stepMark(status.checks.find((c) => c.id === s.check)) !== "done",
  );
  const zones = room.zones.filter((z) => z.active);

  async function act(run: () => Promise<Commissioning | void>) {
    setBusy(true);
    setError("");
    try {
      const result = await run();
      if (result) onStatus(result);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }
  const commission = async (data: Record<string, unknown>) =>
    (
      await controller.operator<SetupRoom>("setup_commission", {
        entry_id: room.entry_id,
        expected_revision: room.revision,
        ...data,
      })
    ).commissioning;
  const save = (data: Record<string, unknown>) => act(() => commission(data));
  const checkAgain = () =>
    act(async () => {
      const doc = await controller.operator<SetupDocument>("setup_read");
      return doc.rooms.find((r) => r.entry_id === room.entry_id)?.commissioning;
    });
  const pressed = (zone: number) =>
    asked[zone] ||
    controller.states["button.crop_steering_" + room.prefix + "zone_" + zone + "_test_shot"]
      ?.state ||
    "";

  return (
    <section className="panel workspace-card setup-wizard" aria-label="Setup wizard">
      <div className="workspace-section-heading">
        <div>
          <h2>Set up this room</h2>
          <p className="muted">
            Step {Math.min(next < 0 ? WIZARD_STEPS.length : next + 1, WIZARD_STEPS.length)} of{" "}
            {WIZARD_STEPS.length} · {WIZARD_STEPS[next < 0 ? WIZARD_STEPS.length - 1 : next].label}.
            Each step checks itself; you can stop and come back on another device.
          </p>
        </div>
        <Button variant="outline" disabled={busy} onClick={checkAgain}>
          <RefreshCw size={15} />
          Check again
        </Button>
      </div>
      <ol className="wizard-steps">
        {WIZARD_STEPS.map((s) => {
          const check = status.checks.find((c) => c.id === s.check);
          const mark = s.check ? stepMark(check) : gate.enabled ? "done" : "todo";
          return (
            <li key={s.label} data-mark={mark}>
              <span className="wizard-mark" aria-label={mark}>
                {MARK_SYMBOL[mark]}
              </span>
              <span>
                <strong>{s.label}</strong>
                {check?.problems.map((p) => (
                  <span key={p} className="muted wizard-problem">
                    {p}
                  </span>
                ))}
              </span>
            </li>
          );
        })}
      </ol>
      {!status.checks.find((c) => c.id === "sizing")?.ok && (
        <div className="workspace-message">
          <p>
            Sizing is still on the generic starting values. Check plants, pot size and drippers
            below (or run the catch test), save, then confirm. This never holds Switch on.
          </p>
          <Button
            variant="outline"
            disabled={busy}
            onClick={() => save({ sizing_confirmed: true })}
          >
            Sizing is right
          </Button>
        </div>
      )}
      <div className="wizard-test-shots">
        <h3>Test shot</h3>
        <p className="muted">
          A 10-second shot through the controller's safety checks. Watering must be on for it to
          run. Watch a dripper while it runs.
        </p>
        {zones.map((zone) => {
          const shot = pressed(zone.id);
          const seen = !!shot && status.draft.water_seen[String(zone.id)] === shot;
          return (
            <div key={zone.id} className="wizard-test-shot">
              <Button
                variant="outline"
                disabled={busy}
                onClick={() =>
                  act(async () => {
                    const result = await controller.operator<{ requested: string }>("test_shot", {
                      room_id: "room:" + room.prefix,
                      zone: zone.id,
                    });
                    setAsked({ ...asked, [zone.id]: result.requested });
                    setNotSeen(null);
                  })
                }
              >
                Test shot · {zone.name}
              </Button>
              {shot && !seen && (
                <span>
                  Watch a dripper on {zone.name}. Did water come out?{" "}
                  <Button
                    size="sm"
                    disabled={busy}
                    onClick={() => save({ water_seen: { [zone.id]: shot } })}
                  >
                    Yes
                  </Button>{" "}
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={busy}
                    onClick={() => setNotSeen(zone.id)}
                  >
                    No
                  </Button>
                </span>
              )}
              {seen && <span>Water seen.</span>}
              {notSeen === zone.id && (
                <p className="muted">
                  Check that Watering is on, that this zone's valve is the one mapped, and that the
                  pump is primed and the controller app is running. Then run it again.
                </p>
              )}
            </div>
          );
        })}
      </div>
      {warnings(status).length > 0 && (
        <p className="muted">Worth a look, never blocking: {warnings(status).join(" · ")}</p>
      )}
      <div className="wizard-switch-on">
        <Button
          disabled={busy || !gate.enabled}
          onClick={() =>
            act(async () => {
              const result = await commission({ done: true });
              // The tour runs once, here: a room set up before the wizard never passes this way.
              if (result?.commissioned) startTour();
              return result;
            })
          }
        >
          Switch on
        </Button>
        <span className="muted">
          {gate.enabled
            ? "Rules only to start is the right choice. The controller waters from your probes and targets; you can add the AI assistant any time."
            : "Waiting for " + gate.reason}
        </span>
      </div>
      {error && <div className="workspace-message error">{error}</div>}
    </section>
  );
}
