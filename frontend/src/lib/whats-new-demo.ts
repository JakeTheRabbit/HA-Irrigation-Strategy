import type { WhatsNewDocument } from "./whats-new";

/** What the demo's integration answers to whats_new_get: a frozen copy of four real releases'
 * highlights from custom_components/crop_steering/WHATS_NEW.md. Frozen on purpose: the dashboard
 * bundle must not read that file, or every release pull request, which adds a section to it, would
 * have to rebuild the bundle, and a release pull request may not. */
export const DEMO_WHATS_NEW: Omit<WhatsNewDocument, "seen"> = {
  version: "2.24.0",
  releases: [
    {
      version: "2.24.0",
      date: "2026-09-26",
      items: [
        "Nothing is watered while the pump, main line or a zone's valve is offline: the zone waits, and says which switch is missing.",
        "A room switched back on within a day carries on where it left off.",
        "Move a zone to any phase by hand, from its details.",
        "Every irrigation setting has a plain name, and a ? that explains it.",
        "Bug fixes and improvements.",
      ],
    },
    {
      version: "2.23.0",
      date: "2026-09-25",
      items: [
        "The grow-day chart shows how today is tracking: each phase's target, yesterday or a typical day, and the rest of today.",
        "Repairs cards link straight to what their message means and what to do.",
        "Bug fixes and improvements.",
      ],
    },
    {
      version: "2.22.0",
      date: "2026-09-25",
      items: [
        "A Stock tanks page counts your nutrient concentrates down batch by batch, and warns before they run low.",
        "The Overview reads at a glance: how fast each zone is drying, water against its daily limit, and valves in colour.",
        "Water use for each zone: today, this week and the whole grow.",
        "The tank card graphs its EC and pH.",
      ],
    },
    {
      version: "2.21.0",
      date: "2026-09-25",
      items: [
        "The Overview opens on today's grow day: every zone's phases, shots and holds on one chart, with the next shot estimated.",
        "A calmer look, with bigger text, and colour only where it means something.",
      ],
    },
  ],
};
