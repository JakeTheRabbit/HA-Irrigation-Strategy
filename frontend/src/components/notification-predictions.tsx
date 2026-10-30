import { useState } from "react";
import { Check, Telescope, EyeOff } from "lucide-react";
import { UiTip } from "@/components/info-tip";
import { errorText } from "@/lib/utils";
import type { Controller } from "@/lib/types";
export function NotificationPredictions({ controller }: { controller: Controller }) {
  const predictions = controller.room.notifyPredictions;
  const [predictBusy, setPredictBusy] = useState(false);
  const [predictError, setPredictError] = useState("");
  async function choosePredictions(include: boolean) {
    if (!predictions.entityId || predictions.enabled === include) return;
    setPredictBusy(true);
    setPredictError("");
    try {
      const result = await controller.write([{ entityId: predictions.entityId, value: include }]);
      if (result.failed.length) setPredictError(result.failed.map((f) => f.reason).join(" "));
    } catch (error) {
      setPredictError(errorText(error));
    } finally {
      setPredictBusy(false);
    }
  }
  return (
    <section className="panel settings-section">
      <div className="settings-label">
        <h2>Notifications</h2>
        <p>The controller&rsquo;s vitals report, for {controller.room.room.name}.</p>
      </div>
      <div id="config-notify_predictions">
        <div className="label-with-tip">
          <h3 id="predictions-label">Next action of each zone</h3>
          <UiTip copyKey="include what each zone does next" />
        </div>
        <div
          className="theme-options water-view-options"
          role="group"
          aria-labelledby="predictions-label"
        >
          {(
            [
              { value: true, label: "Included", icon: Telescope },
              { value: false, label: "Not included", icon: EyeOff },
            ] as const
          ).map((option) => (
            <button
              key={option.label}
              className={predictions.enabled === option.value ? "chosen" : ""}
              aria-pressed={predictions.enabled === option.value}
              disabled={
                !predictions.entityId ||
                predictions.enabled === null ||
                predictBusy ||
                !["live", "demo"].includes(controller.connection)
              }
              onClick={() => void choosePredictions(option.value)}
            >
              <option.icon size={20} />
              <span>{option.label}</span>
              {predictions.enabled === option.value && <Check size={16} />}
            </button>
          ))}
        </div>
        {predictError && (
          <p className="small error-text" role="alert">
            {predictError}
          </p>
        )}
        <p className="small muted mt-3">
          {predictions.entityId
            ? "Under each zone, what the controller will do next, as the zone’s Next: line says it: for example “shot when VWC < 61% (now 58%) · P3 by 22:00”. Which phones get the report is ticked under Notifications (Vitals)."
            : "This needs the updated Crop Steering integration. Until then the controller includes them."}
        </p>
      </div>
    </section>
  );
}
