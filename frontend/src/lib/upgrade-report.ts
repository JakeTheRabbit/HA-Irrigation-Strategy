import { REPOSITORY_URL } from "./whats-new";

/** The Upgrade report of a room (Settings › System status): what the 3.18 update carried across
 * and what needs a person, as `crop_steering.migration_report {room_id}` answers it (migration.py).
 * The Repairs card CS-616 sends the grower here. */

export interface UpgradeRow {
  id: string;
  title: string;
  detail: string;
  /** A dashboard address (`#/...`) to open, or null. */
  page: string | null;
  /** The section of docs/UPGRADING.md on GitHub, or null. */
  doc: string | null;
}
export interface UpgradeReportView {
  release: string;
  acknowledged: string | null;
  carried: UpgradeRow[];
  needsYou: UpgradeRow[];
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === "object" && !Array.isArray(value);
const text = (value: unknown) => (typeof value === "string" && value.trim() ? value.trim() : null);

/** A dashboard address the report names: a hash route only, never another site. */
export const pageHref = (page: unknown): string | null =>
  typeof page === "string" && /^#\/[a-z0-9/_-]*(\?[\w=&.-]*)?$/i.test(page) ? page : null;

/** The upgrade guide's section on GitHub, as Help links documents: a path under docs/ only. */
export const docHref = (doc: unknown): string | null =>
  typeof doc === "string" && /^docs\/[A-Za-z0-9_./-]+\.md(#[a-z0-9_-]+)?$/i.test(doc) && !doc.includes("..")
    ? `${REPOSITORY_URL}/blob/main/${doc}`
    : null;

function rows(value: unknown): UpgradeRow[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    if (!isRecord(item)) return [];
    const id = text(item.id),
      title = text(item.title);
    if (!id || !title) return [];
    return [{ id, title, detail: text(item.detail) ?? "", page: pageHref(item.page), doc: docHref(item.doc) }];
  });
}

/** The report to show, or null when there is nothing to show (a fresh room answers two empty
 * lists) or the answer is not one. */
export function reportView(data: unknown): UpgradeReportView | null {
  if (!isRecord(data)) return null;
  const carried = rows(data.carried),
    needsYou = rows(data.needs_you);
  if (!carried.length && !needsYou.length) return null;
  return { release: text(data.release) ?? "", acknowledged: text(data.acknowledged), carried, needsYou };
}
