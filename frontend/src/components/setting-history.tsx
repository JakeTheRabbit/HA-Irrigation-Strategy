import { useState } from "react";
import { Clock3 } from "lucide-react";
import { Popover } from "radix-ui";
import { changeWords, changesHash, fromSetpointLog, toEntries, type ChangeEntry, type SetpointLogRow } from "@/lib/changes";
import { pickKey } from "@/lib/facility";
import { callV2 } from "@/lib/parity-api";
import type { HistoryChange } from "@/lib/parity-types";
import { clock, dayLabel } from "@/lib/time";
import type { Controller } from "@/lib/types";
import "./setting-history.css";

const DAYS = 30;
const SHOWN = 5;

/** The setting's key and zone in the selected room, from its entity id. */
function settingOf(entityId: string, prefix: string): { key: string; zone: number | null } | null {
  const root = `number.crop_steering_${prefix}`;
  if (!entityId.startsWith(root)) return null;
  const rest = entityId.slice(root.length);
  const zoned = /^zone_(\d+)_(.+)$/.exec(rest);
  return zoned ? { key: zoned[2], zone: Number(zoned[1]) } : { key: rest, zone: null };
}

type Loaded = { state: "loading" } | { state: "ready"; entries: ChangeEntry[] } | { state: "error"; message: string };

/** The clock beside a setting: its last changes (who, from what to what, why) in a popover, read
 * when it opens, and the way to all of them on History › Changes. */
export function SettingHistory({ controller, entityId }: { controller: Controller; entityId: string }) {
  const [loaded, setLoaded] = useState<Loaded>({ state: "loading" });
  const prefix = controller.room.room.prefix;
  const setting = settingOf(entityId, prefix);
  const words = changeWords(controller.states, controller.rooms);
  const label = setting ? words.label(setting.key) : entityId;
  if (!setting) return null;
  async function load() {
    setLoaded({ state: "loading" });
    const since = new Date(Date.now() - DAYS * 86_400_000).toISOString();
    const outcome = await callV2<{ changes: HistoryChange[] }>(controller, "history_changes", {
      room_id: controller.roomId,
      since,
      key: setting!.key,
      ...(setting!.zone !== null ? { zone: setting!.zone } : {}),
    });
    if (outcome.kind === "ok") {
      const own = (outcome.data?.changes ?? []).filter((c) => c.scope === (setting!.zone === null ? "room" : `zone:${setting!.zone}`));
      setLoaded({ state: "ready", entries: toEntries(own, words).slice(0, SHOWN) });
      return;
    }
    if (outcome.kind === "error") {
      setLoaded({ state: "error", message: outcome.message });
      return;
    }
    try {
      const log = await controller.operator<{ changes?: SetpointLogRow[] }>("setpoint_log_get", {});
      const rows = (log.changes ?? []).filter((row) => row.entity_id === entityId && Date.parse(row.at) >= Date.parse(since));
      setLoaded({ state: "ready", entries: fromSetpointLog(rows, controller.roomId, words).slice(0, SHOWN) });
    } catch (error) {
      setLoaded({ state: "error", message: error instanceof Error ? error.message : "The setting log could not be read." });
    }
  }
  const room = setting.zone === null ? controller.roomId : pickKey(controller.roomId, setting.zone);
  return (
    <Popover.Root onOpenChange={(open) => open && void load()}>
      <Popover.Trigger asChild>
        <button type="button" className="setting-help-trigger setting-history-trigger" aria-label={`Changes to ${label}`} data-setting-history>
          <Clock3 size={15} aria-hidden="true" />
        </button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content className="setting-help setting-history" aria-label={`Changes to ${label}`} side="bottom" align="start" sideOffset={6} collisionPadding={12}>
          <div className="setting-help-head">
            <strong>{label}</strong>
            <span className="muted small">last {DAYS} days</span>
          </div>
          {loaded.state === "loading" ? (
            <p className="muted">Reading…</p>
          ) : loaded.state === "error" ? (
            <p role="alert">{loaded.message}</p>
          ) : loaded.entries.length ? (
            <ol className="setting-history-list">
              {loaded.entries.map((entry) => (
                <li key={entry.id}>
                  <span className="setting-history-when">
                    <time dateTime={new Date(entry.at).toISOString()}>
                      {dayLabel(entry.at, controller.timeZone)} {clock(entry.at, controller.timeZone)}
                    </time>{" "}
                    · {entry.chip}
                  </span>
                  <span>
                    {entry.before && <s>{entry.before}</s>} → <b>{entry.after}</b>
                  </span>
                  {entry.reason && <span className="muted">{entry.reason}</span>}
                </li>
              ))}
            </ol>
          ) : (
            <p className="muted">No changes to this setting in the last {DAYS} days.</p>
          )}
          <a href={changesHash({ since: "", room, kind: "setpoint" })}>All changes on History › Changes</a>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}
