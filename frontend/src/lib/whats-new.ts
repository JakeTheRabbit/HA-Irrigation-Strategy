/** What's new: the release highlights the dashboard shows once after an update.
 *
 * The highlights come from the integration (crop_steering.whats_new_get), which ships them as
 * WHATS_NEW.md, not from this bundle: a release adds its section in its release pull request,
 * which may not rebuild the dashboard. The integration also keeps, for the whole installation, the
 * last release the window showed: null when it cannot know (an installation that was running
 * before this existed). */
export interface WhatsNewRelease {
  version: string;
  /** The release date, YYYY-MM-DD. */
  date: string;
  items: string[];
}
export interface WhatsNewDocument {
  /** The installed integration's version. */
  version: string;
  seen: string | null;
  releases: WhatsNewRelease[];
}
export interface WhatsNewSelection {
  releases: WhatsNewRelease[];
  /** Releases it would also show, left out to keep the window short. */
  more: number;
}

/** Where it cannot know what was shown, it shows this many days of releases. */
export const WINDOW_DAYS = 30;
/** The most releases the window shows at once. */
export const MOST = 5;
export const RELEASES_URL = "https://github.com/JakeTheRabbit/HA-Irrigation-Strategy/releases";
export const releaseUrl = (version: string) => `${RELEASES_URL}/tag/v${version}`;

const VERSION = /^\d+\.\d+\.\d+$/;
const DATE = /^\d{4}-\d{2}-\d{2}$/;

/** Negative when `a` is the older version. */
export function compareVersions(a: string, b: string): number {
  const x = a.split(".").map(Number),
    y = b.split(".").map(Number);
  for (let i = 0; i < 3; i++) if (x[i] !== y[i]) return x[i] - y[i];
  return 0;
}

/** The integration's answer, or null when it is not one: a missing service, an older integration. */
export function readWhatsNew(response: unknown): WhatsNewDocument | null {
  if (!response || typeof response !== "object") return null;
  const { version, seen, releases } = response as Record<string, unknown>;
  if (typeof version !== "string" || !VERSION.test(version) || !Array.isArray(releases))
    return null;
  const valid = releases.filter(
    (release): release is WhatsNewRelease =>
      !!release &&
      typeof release === "object" &&
      VERSION.test(String((release as WhatsNewRelease).version)) &&
      DATE.test(String((release as WhatsNewRelease).date)) &&
      Array.isArray((release as WhatsNewRelease).items) &&
      (release as WhatsNewRelease).items.every((item) => typeof item === "string") &&
      (release as WhatsNewRelease).items.length > 0,
  );
  return {
    version,
    seen: typeof seen === "string" && VERSION.test(seen) ? seen : null,
    releases: valid
      .filter((release) => compareVersions(release.version, version) <= 0)
      .sort((a, b) => compareVersions(b.version, a.version)),
  };
}

const capped = (releases: WhatsNewRelease[]): WhatsNewSelection => ({
  releases: releases.slice(0, MOST),
  more: Math.max(0, releases.length - MOST),
});

/** What the window shows after an update: every release since the last one it showed on this
 * installation, however long ago. Where it cannot know (`seen` null), the releases of the 30 days
 * up to the installed one. Newest first, at most five. */
export function unseen(doc: WhatsNewDocument): WhatsNewSelection {
  if (doc.seen !== null)
    return capped(
      doc.releases.filter((release) => compareVersions(release.version, doc.seen!) > 0),
    );
  const newest = doc.releases[0];
  if (!newest) return capped([]);
  const from = Date.parse(newest.date) - WINDOW_DAYS * 86_400_000;
  return capped(doc.releases.filter((release) => Date.parse(release.date) >= from));
}

/** Help & tools: the latest releases, whatever the window has shown. */
export const recent = (doc: WhatsNewDocument): WhatsNewSelection => capped(doc.releases);
