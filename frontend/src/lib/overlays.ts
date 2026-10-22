import { settingWords } from "./setting-words";
import { dayWord } from "./utils";
import { formatClock } from "./clock";

/** The room's AI overlays (crop_steering.overlay_get): settings the AI brain moved that go back to
 * the grower's own value (`old`) by themselves at `expires`, the lights-on that ends the grow-day the
 * change was for. Keep makes the AI's value the grower's own; Undo puts the grower's back now. */
export interface Overlay {
  entity_id: string;
  zone: number | null;
  field: string;
  old: number;
  new: number;
  by: string;
  at: string;
  expires: string;
}
export interface OverlayDocument {
  schema_version: number;
  room_id: string;
  overlays: Overlay[];
  error: string | null;
}

const clock = (at: number) => formatClock(at);
/** "22:48", or "Yesterday 22:48" / "tomorrow 06:00" when it is not today. */
function when(at: number, now: number) {
  const days = Math.round(
    (new Date(at).setHours(0, 0, 0, 0) - new Date(now).setHours(0, 0, 0, 0)) / 86_400_000,
  );
  const word = days === 1 ? "tomorrow" : dayWord(at, now);
  return word ? `${word} ${clock(at)}` : clock(at);
}

/** The setting in grower words: "Maintenance shot size". */
export const overlayLabel = (overlay: Overlay) =>
  settingWords(overlay.field)?.label ?? overlay.field.replaceAll("_", " ");

/** "Set by AI 22:48 · goes back at lights-on tomorrow 06:00". */
export function overlayText(overlay: Overlay, now: number) {
  return `Set by AI ${when(Date.parse(overlay.at), now)} · goes back at lights-on ${when(
    Date.parse(overlay.expires),
    now,
  )}`;
}

/** This zone's open overlays, oldest first; none for another room's document or no document. */
export function zoneOverlays(doc: OverlayDocument | null, roomId: string, zone: number) {
  return doc?.room_id === roomId ? doc.overlays.filter((overlay) => overlay.zone === zone) : [];
}
