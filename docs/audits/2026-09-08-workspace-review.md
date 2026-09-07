# Independent workspace review — 2026-09-08

Scope: parent-authored Grow plan and Rooms & setup workflows, operator response transport, isolated demo implementation, active strategy target overlay, and App draft guards. Browser checks use the compiled canonical dashboard at `http://127.0.0.1:5198/dashboard.html?demo=1`; response-bearing Home Assistant endpoints are intercepted fixtures. No production Home Assistant connection, writes, deployment, or commit occurred.

## Findings and corrections

1. **Live disarm rejected extra service field.** GrowPlanner sent `expected_revision` on `strategy_disarm`, but the strict schema in `custom_components/crop_steering/strategy_api.py` permits only `room_id`. Parent corrected the payload. The browser fixture rejects unknown fields and checks the exact canonical room identifier.
2. **Error plans offered actions the backend rejects.** Save and activate require draft status. Parent made error plans read-only with disarm recovery. The browser fixture verifies error-state editing and Arm are unavailable while Disarm remains reachable.
3. **Setup draft survived an accepted global room change.** Setup was not keyed to selected room, so its old local document could outlive the App discard prompt. Parent keyed Setup by controller room ID. Browser checks change Flower 2's draft name, accept switching to Flower 1, and assert both configuration select and room name now identify Flower 1.
4. **Mapping dialog list semantics were incomplete.** Direct button children inside `role=list` caused `aria-required-children`. Changed the labeled container to `role=group`. Mapping controls remain native buttons with pressed selection state.
5. **Missing light schedule silently became 00:00–12:00.** Added an adjacent explanation identifying each substituted light hour. These are illustration defaults, not a claim about discovered controller configuration.
6. **P3 graph incorrectly reused morning dryback as an overnight endpoint.** The authoritative engine computes relative drop from measured peak for P0. The graph now shows reference → P0 morning trigger → P1 target → P2 reference; the VWC line ends at P3. Only P3's emergency floor remains plotted. No overnight VWC trend or scheduled emergency shot is invented. The dryback drag handle is at the P0 boundary. Regression: peak 70, relative target 20 gives 56 VWC; no VWC points belong to P3.
7. **Timing parameters needed a visible relationship to the graph.** Added eligible P1 window ticks using supplied maximum count and interval, clipped before the P3 cutoff. They are explicitly conditional planning windows; P2 remains sensor-triggered rather than a fabricated periodic schedule. Missing/zero cadence yields no invented ticks.

8. **Existing plans did not gain newly configured zones.** Reproduction: load an existing three-zone plan, add Zone 4 in Setup, then return to Grow plan; only three rows were available. Added explicit **Update zones from setup**, which edits the local draft, retains existing active schedules and all profiles, removes archived assignments, and seeds new assignments using finite current catalog values at both endpoints. New blocks cover days 1–84 from today. The action is unavailable outside draft status and still requires review/save. Missing values are not invented. Parent refreshed demo catalogs without mutating saved plans. Three pure regressions cover preservation, stable-ID archive/restore collisions, and missing values. Browser regression now loads the plan before setup changes, then syncs and saves the fourth zone.

9. **Plan lifecycle status did not update after initial load.** Added a quiet 20-second `strategy_get` refresh. It preserves the selected day, zone and tab, pauses while drafts/reviews/writes are active, and rejects late results after edits, room/connection changes or a newer explicit document response. It does not turn on the page busy spinner. The strict browser fixture accelerates only this interval and proves armed → active without navigation, retained preview day, and a held response released after editing cannot replace the draft.

## Verification

`frontend/scripts/verify-workspace.mjs` exercises:

- Native steering slider changes both SVG VWC and EC paths.
- Exported plans prove day/week edits preserve neighboring days and other zones.
- Navigation, hash, back, and room draft guards preserve edits on Keep editing and discard only after confirmation.
- Endpoint profile duplication, rename and editing; keyboard curve handle edits; reviewed save, arm and disarm.
- Room mapping adds a zone, chooses an actual offered valve and VWC probe, saves delivery sizing, archives/restores the stable zone ID, and leaves other room mappings intact.
- Creates, archives and restores an isolated demo room without any equipment requests.
- Strict API fixtures enforce response wrappers, revision handling and canonical scope; failed saves preserve the draft. Setup response shapes are verified too.
- Background armed → active status changes without navigation; selected day is retained and a delayed response cannot replace a newly edited draft.
- Valid active strategy targets replace manual references. Expired snapshots withhold targets and manual setpoints remain locked while the plan is engaged.
- Desktop/mobile accessibility and 390px document width, including the mapping dialog.
- Same-origin HA parent CSS variables, dynamic dark/light change, persistent explicit override, automatic-follow restoration, loaded Roboto and embedded OFL license.

Focused pure planning and zone-sync tests: **10 passed**. TypeScript: **passed**. The new cadence and corrected morning/P3 semantics were each tested red before implementation, then green.

Final canonical compiled browser run (build 02:16:09): **9/9 groups passed**, including 4 WCAG 2 A/AA and 2.1 AA checks (planner desktop/mobile, setup mobile, mapping dialog mobile), with no JavaScript exceptions and no unexpected external/API requests. Same-origin iframe theme inheritance, parent palette changes, explicit override, and actual loaded bundled Roboto were verified. Machine-readable evidence is `output/playwright/workspace-verification.json`; screenshots include `workspace-grow-planner.png`, `workspace-grow-mobile.png`, `workspace-setup-mobile.png`, and `workspace-stale-plan.png`.

## Limits

The live-looking browser scenario is a deterministic intercepted API fixture. It validates the frontend's transport and rendering contracts against the repository's service schemas; it is not an installed Home Assistant integration/runtime test. Browser checks do not advance a real grow-day boundary or actuate equipment. The planning graphic is an explicitly labeled setpoint illustration, separate from recorded history.

Native-theme README screenshots were generated from the compiled local demo: `img/operator-dashboard.png` and `img/grow-plan.png`. The parent fixture supplies Home Assistant palette variables; it is not a production installation screenshot.

The strengthened existing-plan → new-zone → explicit sync → save regression passed against the final canonical rebuild, including the refreshed demo catalog.

Final lifecycle rerun against build 02:16:09: **9/9 browser groups passed**. The armed-to-active and delayed-read draft-preservation checks are included in the strict response-bearing API group; no extra production timers or fixture overrides ship in the application. Production polling is 20 seconds. TypeScript passed after the synchronization change.
