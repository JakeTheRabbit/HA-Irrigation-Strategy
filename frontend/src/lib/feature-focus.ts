/**
 * `?feature=<id>` links (Settings › Capabilities, the room-off banner) open the page that owns a
 * feature at its control. Every page honours them through one reader in the app shell.
 */
import { controlsOf, entityIdOf, FEATURES } from "./features";

/** The feature an address names, or null. */
export function featureOf(hash: string): string | null {
  return new URLSearchParams(hash.split("?")[1] ?? "").get("feature");
}

/** Element ids a feature link lands on, best first: the feature's own card (`config-<id>`), then
 * each of its controls' editors in this room (`setting-<entity>`, `choice-<entity>`). */
export function featureTargets(id: string, prefix: string, zones: number[]): string[] {
  const feature = FEATURES.find((item) => item.id === id);
  const ids = [`config-${id}`];
  for (const control of feature ? controlsOf(feature) : [])
    for (const zone of [
      ...(control.scope === "zone" ? [] : [null]),
      ...(control.scope === "room" ? [] : zones),
    ]) {
      const entity = entityIdOf(prefix, control, zone);
      ids.push(`setting-${entity}`, `choice-${entity}`);
    }
  return ids;
}

/** True when every control of the feature belongs to the room, not a zone: a page with a zone or
 * room picker opens on the room for it. */
export function roomOnlyFeature(id: string | null): boolean {
  const feature = FEATURES.find((item) => item.id === id);
  return !!feature && controlsOf(feature).every((control) => control.scope === "room");
}
