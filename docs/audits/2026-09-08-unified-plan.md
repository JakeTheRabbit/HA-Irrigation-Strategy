# Unified irrigation plan release verification

Recorded 8 September 2026, Pacific/Auckland.

## Published software

- Integration release **2.16.1**, source `693151cd7a74130e50661af5a0182e6f97af1a66`.
- Controller **0.13.3**, dedicated repository commit `918fefb`.
- One Irrigation plan navigation entry with Today and Schedule views. Existing route bookmarks are preserved.
- When a schedule owns the room, Today displays effective scheduled targets and its read-only graph instead of disabled manual fallback inputs.
- VWC and dashed EC reference curves connect across lights-off and overnight. Missing EC anchors retain gaps; EC interpolation is explicitly not a physical prediction. Inconsistent relative dryback endpoints produce an explanation rather than an invented overnight rise.
- Controller decision code is unchanged by this release.

## Automated and browser evidence

- 221 frontend tests passed.
- 56 browser workflow groups passed: dashboard 19, mock-live 10, workspace 9, steering 5, recipes/demo 4, tank/zone 4, HA shell 5.
- Desktop and mobile checks assert Today/Schedule remain side by side, including keyboard/history navigation and unsaved changes.
- Active-target tests verify effective values, absence of fallback inputs, no unintended mutation and unavailable/stale snapshot behavior.
- GitHub Validate, Installation Workflow, Release packaging and Pages workflows passed for the release source.
- Documentation screenshots were regenerated with isolated demo data.

## Live installation and preservation

- Backed up the integration, controller image, persistent state and both room configuration entries before upgrading in place.
- Installed through the existing controller repository and HACS, then restarted HA. Both integration entries loaded.
- Integration manifest reports **2.16.1**; the installed controller reports **0.13.3**, started, with unchanged app options.
- Persistent counters and retained runtime fields matched the stopped pre-upgrade state. Room configuration data/options were unchanged, including the previously verified tank mappings.
- All **398** existing control values matched the snapshot, allowing equivalent numeric formatting such as `42` and `42.0`.
- Original engine states restored and read back: **F1 on, F2 off**.
- Both final heartbeats reported healthy, setup revision **1**, no pending setup and no hardware fault. F2's temporary startup hold cleared on the normal five-minute discovery refresh after its hardware reported off.
- Controller source, strategy runtime, core, run API and both installed dashboard copies matched published source. The public demo matched that same dashboard build.
- In the native HA panel, the single Irrigation plan entry opened Today; its Schedule button opened Scheduled targets with stored revision 0. No target or plan writes were performed during this browser verification.
- The graphical tank readings and timezone-aware last-irrigation events remained visible. The native HA menu recovery button was verified during the preceding 2.16.0 deployment.

Private backup and test output remain outside Git under `output/live-upgrade/unified-plan` and `output/playwright`. No credentials or private operational scratch dashboards were published.

These checks establish software installation, configuration retention and interface behavior. They do not measure physical water delivery, predict plant response or commission an entire scheduled run.
