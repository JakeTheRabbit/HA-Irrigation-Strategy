import { describe, expect, it } from "vitest";
import { buildRoom, discoverRooms, ROOM_PARAMETERS, ZONE_PARAMETERS } from "./model";
import { createDemo } from "./demo";
import { parameterHelp, parameterLabels } from "./grow-plan";
import { GROUP_HELP, PHASE_GROUPS, settingWords } from "./setting-words";

/** Every parameter the Irrigation plan can show (model.ts `setting()` accepts exactly these). */
const shown = [
  ...new Set([...ZONE_PARAMETERS, ...ROOM_PARAMETERS]),
  ...["veg", "gen"].flatMap((mode) => [0, 1, 2].map((phase) => `ec_target_${mode}_p${phase}`)),
];

describe("setting words", () => {
  it("names every setting the Irrigation plan can show, with a one-line help", () => {
    for (const param of shown) {
      const words = settingWords(param);
      expect(words, param).toBeDefined();
      expect(words!.label, param).not.toBe("");
      expect(words!.short, param).not.toBe("");
      expect(words!.help, param).toMatch(/^[A-Z0-9].*\.$/);
    }
  });
  it("never gives two settings one name; the legacy shot cap is the same setting", () => {
    const names = new Map<string, string>();
    for (const param of shown) {
      const label = settingWords(param)!.label;
      const owner = param === "maximum_shot_duration" ? "max_shot_duration" : param;
      expect(names.get(label) ?? owner, `${label}: ${names.get(label)} and ${param}`).toBe(owner);
      names.set(label, owner);
    }
  });
  it("names the steering modes' targets apart and the Schedule's resolved ones plainly", () => {
    expect(settingWords("vegetative_dryback_target")!.label).toBe("P3 dryback target (vegetative)");
    expect(settingWords("generative_dryback_target")!.label).toBe("P3 dryback target (generative)");
    expect(settingWords("dryback_target")!.label).toBe("P3 dryback target");
    expect(settingWords("ec_target_gen_p2")!.label).toBe("Substrate EC target, P2 (generative)");
    expect(settingWords("ec_target_p1")!.label).toBe("Substrate EC target, P1");
    expect(settingWords("no_such_setting")).toBeUndefined();
  });
  it("gives the Schedule the Irrigation plan's words", () => {
    for (const [key, label] of Object.entries(parameterLabels))
      expect(label, key).toBe(settingWords(key)!.label);
    for (const [key, help] of Object.entries(parameterHelp))
      expect(help, key).toBe(settingWords(key)!.help);
  });
  it("files the dryback targets under P3 and full saturation under Substrate", () => {
    const states = createDemo(Date.UTC(2026, 8, 25, 12));
    const room = buildRoom(states, discoverRooms(states)[0]);
    const group = (suffix: string) =>
      room.settings.find((s) => s.entityId.endsWith(`zone_1_${suffix}`))?.group;
    expect(group("vegetative_dryback_target")).toBe(PHASE_GROUPS[3]);
    expect(group("p3_emergency_vwc_threshold")).toBe(PHASE_GROUPS[3]);
    expect(group("p0_maximum_wait_time")).toBe(PHASE_GROUPS[0]);
    expect(group("field_capacity")).toBe("Substrate");
    expect(room.settings.find((s) => s.entityId.endsWith("zone_1_p2_vwc_threshold"))).toMatchObject(
      {
        label: "Maintenance shot when below",
        description: settingWords("p2_vwc_threshold")!.help,
      },
    );
    for (const name of [...PHASE_GROUPS, "Substrate", "Safety"])
      expect(GROUP_HELP[name]).toBeTruthy();
  });
});
