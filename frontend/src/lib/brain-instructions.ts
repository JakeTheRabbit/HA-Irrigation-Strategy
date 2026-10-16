/** Room instructions are administrator-supplied context. Published blocks are controller snapshots. */
export const PROFILE_FIELDS = [
  "substrate",
  "environment",
  "genetics",
  "stage",
  "feed",
  "goals",
  "constraints",
  "calibration",
] as const;
export type ProfileField = (typeof PROFILE_FIELDS)[number];
export interface PromptConfig {
  notes: string;
  profile: Partial<Record<ProfileField, string>>;
  cache: { ttl: "5m" | "1h"; A: boolean; B: boolean; C: boolean; evidence: boolean };
}
export interface PromptBlock {
  id: "A" | "B" | "C";
  text: string;
  hash: string;
  sources: string[];
  tokens_estimate: number;
  cache_control: { type: string; ttl?: string } | null;
}
export interface InstructionsDocument {
  room_id: string;
  revision: number;
  rebuild: number;
  config: PromptConfig;
  history: { revision: number; config: PromptConfig; at: string }[];
  live: {
    blocks: PromptBlock[];
    revision: number;
    published_at: string;
    stage_arc: string | null;
    substrates: string[];
    rebuild: number;
  } | null;
  telemetry: {
    cache_hit_ratio?: number | null;
    tokens_today?: { cache_read: number; cache_write: number; uncached: number } | null;
    spent_usd?: number | null;
    model?: string | null;
    cache_savings_estimate_usd?: number | null;
  };
}
export const defaultPromptConfig = (): PromptConfig => ({
  notes: "",
  profile: {},
  cache: { ttl: "1h", A: true, B: true, C: true, evidence: true },
});
export function normalizeConfig(config: PromptConfig): PromptConfig {
  const profile: PromptConfig["profile"] = {};
  for (const key of PROFILE_FIELDS)
    if (config.profile[key]?.trim()) profile[key] = config.profile[key]!.trim();
  return { notes: config.notes.trim(), profile, cache: { ...config.cache } };
}
export function configDiff(before: PromptConfig, after: PromptConfig) {
  const a = normalizeConfig(before),
    b = normalizeConfig(after);
  return [
    ...(a.notes !== b.notes
      ? [
          {
            key: "notes",
            label: "House notes",
            before: a.notes || "Empty",
            after: b.notes || "Empty",
          },
        ]
      : []),
    ...PROFILE_FIELDS.filter((key) => a.profile[key] !== b.profile[key]).map((key) => ({
      key,
      label: `Grow context: ${key}`,
      before: a.profile[key] || "Unspecified",
      after: b.profile[key] || "Unspecified",
    })),
    ...Object.keys(a.cache)
      .filter(
        (key) =>
          a.cache[key as keyof PromptConfig["cache"]] !==
          b.cache[key as keyof PromptConfig["cache"]],
      )
      .map((key) => ({
        key: `cache_${key}`,
        label: `Cache ${key}`,
        before: String(a.cache[key as keyof PromptConfig["cache"]]),
        after: String(b.cache[key as keyof PromptConfig["cache"]]),
      })),
  ];
}
export function contextTokenEstimate(config: PromptConfig) {
  const normalized = normalizeConfig(config);
  return Math.ceil(
    (normalized.notes.length + Object.values(normalized.profile).join(" ").length) / 4,
  );
}
export function validateConfig(config: PromptConfig): string | null {
  if (config.notes.length > 12000) return "House notes are limited to 12,000 characters.";
  if (Object.values(config.profile).some((text) => (text?.length ?? 0) > 1000))
    return "Each context field is limited to 1,000 characters.";
  if (
    /(?:ignore|bypass|disable|override|skip)\s+(?:all\s+|the\s+|code[- ]enforced\s+)*(?:previous instructions|safety|interlocks?|kill switch|daily cap|holds?)/i.test(
      config.notes + " " + Object.values(config.profile).join(" "),
    )
  )
    return "Context must not ask the AI to bypass safety rules or interlocks.";
  return null;
}
export class InstructionsDemo {
  private rooms = new Map<string, InstructionsDocument>();
  call(action: string, data: Record<string, unknown>) {
    const id = String(data.room_id);
    const doc = this.rooms.get(id) ?? {
      room_id: id,
      revision: 0,
      rebuild: 0,
      config: defaultPromptConfig(),
      history: [],
      live: null,
      telemetry: {},
    };
    if (action !== "brain_prompt_get") {
      if (data.expected_revision !== doc.revision)
        throw new Error("Instructions changed elsewhere. Reload before saving.");
      if (action === "brain_prompt_rebuild") doc.rebuild++;
      else {
        const config =
          action === "brain_prompt_rollback"
            ? doc.history.find((h) => h.revision === data.revision)?.config
            : (data.config as PromptConfig);
        if (!config) throw new Error("That revision is no longer available.");
        const error = validateConfig(config);
        if (error) throw new Error(error);
        doc.history = [
          ...doc.history,
          { revision: doc.revision, config: doc.config, at: new Date().toISOString() },
        ].slice(-10);
        doc.config = normalizeConfig(structuredClone(config));
        doc.revision++;
      }
    }
    this.rooms.set(id, doc);
    return structuredClone(doc);
  }
}
