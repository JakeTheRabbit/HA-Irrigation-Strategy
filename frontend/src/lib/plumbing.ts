/** How a room is plumbed. Mirrors custom_components/crop_steering/plumbing.py: the operator
 * DECLARES the layout, the mapped switches have to match it, and the server checks again. */
export const PLUMBING_LAYOUTS = {
  valves_only: { pump: false, mainline: false },
  pump_valves: { pump: true, mainline: false },
  mainline_valves: { pump: false, mainline: true },
  pump_mainline_valves: { pump: true, mainline: true },
} as const;
export type PlumbingLayout = keyof typeof PLUMBING_LAYOUTS;

export const PLUMBING_LABELS: Record<PlumbingLayout, string> = {
  valves_only: "Zone valves only",
  pump_valves: "A pump, then zone valves",
  mainline_valves: "A main-line valve, then zone valves",
  pump_mainline_valves: "A pump, a main-line valve, then zone valves",
};
export const PLUMBING_HINTS: Record<PlumbingLayout, string> = {
  valves_only: "Each zone is one switch and nothing else, such as a tent on one smart plug.",
  pump_valves: "The pump has to run whenever a zone waters.",
  mainline_valves: "Mains or gravity pressure behind a shared valve; no pump to switch.",
  pump_mainline_valves: "The pump starts, the shared valve opens, then the zone valve.",
};

const STAGES = [
  ["pump_switch", "pump", "pump"],
  ["main_line_switch", "mainline", "main-line valve"],
] as const;

export function isPlumbingLayout(value: unknown): value is PlumbingLayout {
  return typeof value === "string" && Object.hasOwn(PLUMBING_LAYOUTS, value);
}

/** Which of the two shared switches this layout uses. Unknown or undeclared: both are offered. */
export function plumbingUses(layout: unknown, key: string): boolean {
  if (!isPlumbingLayout(layout)) return true;
  const stage = STAGES.find(([field]) => field === key);
  return stage ? PLUMBING_LAYOUTS[layout][stage[1]] : true;
}

/** The layout the mapped switches already imply: a PREFILL for a room that never declared one. */
export function inferPlumbing(hardware: Record<string, unknown>): PlumbingLayout {
  const pump = !!hardware.pump_switch,
    mainline = !!hardware.main_line_switch;
  return (Object.keys(PLUMBING_LAYOUTS) as PlumbingLayout[]).find(
    (name) => PLUMBING_LAYOUTS[name].pump === pump && PLUMBING_LAYOUTS[name].mainline === mainline,
  )!;
}

/** Choosing a layout drops the switches it does not have, so what is reviewed is what is saved. */
export function hardwareForLayout<T extends Record<string, unknown>>(layout: unknown, hardware: T) {
  const next: Record<string, unknown> = { ...hardware };
  for (const [field] of STAGES) if (!plumbingUses(layout, field)) next[field] = "";
  return next as T;
}

/** Every way the mapped switches contradict the declared layout. Empty when nothing is declared. */
export function plumbingErrors(layout: unknown, hardware: Record<string, unknown>): string[] {
  if (!layout) return [];
  if (!isPlumbingLayout(layout)) return ["Choose how this room is plumbed."];
  const found: string[] = [];
  for (const [field, stage, label] of STAGES) {
    const mapped = !!hardware[field],
      needed = PLUMBING_LAYOUTS[layout][stage];
    if (needed && !mapped)
      found.push(
        "This room is plumbed with a " +
          label +
          ": choose the " +
          label +
          " switch, or change the plumbing.",
      );
    else if (mapped && !needed)
      found.push(
        "This room is plumbed without a " +
          label +
          ": clear the " +
          label +
          " switch, or change the plumbing.",
      );
  }
  return found;
}
