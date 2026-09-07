# Branch consolidation review — 8 September 2026

This review compared every local branch and origin branch against the unified workspace at `b61d7a6999ecbc5029b9b2eca92272c02ba2bedc`, including the working release corrections. Git ancestry and patch equivalence were checked alongside source and complete-tree comparisons.

**No unique controller feature or safety fix requires recovery from a non-main branch.** Retired tips are preserved through archive tags and private Git bundles. Cleanup is complete: the main project and dedicated controller repository each have only `main`, locally and on GitHub. Eight remote and eleven local non-main branches were removed from this repository after verification; the controller repository's superseded two-room branch was also archived and removed.

## Remote branches

| Branch | Reviewed tip | Result |
| --- | --- | --- |
| `claude/issue-fix-d01ahv` | `702464e` | Overview/control layout fix is patch-equivalent to `f07dde9`; the modern workspace supersedes the old page. |
| `claude/row-height-distribution-t6h3sd` | `a0bf642` | Orphan-zone daily-volume fallback is patch-equivalent to `8c41f36` and retained in the controller. |
| `claude/vwc-ec-graph-html-yj6pzm` | `371e263` | One unique teaching HTML file, preserved under `archive/2026-09-08/branches/`; its useful planning controls are superseded. |
| `feat/adaptive-steering-vmax-predictive-p3` | `a9d8e15` | Ancestor of the unified workspace. |
| `feat/f2-two-room` | `b61d7a6` | Consolidation baseline containing the unified workspace, setup and grow-plan implementation. |
| `feat/monorepo-consolidation` | `97b0b90` | Ancestor of the unified workspace. |
| `feature/dial-ppfd-rehydration` | `d6aa512` | Historical global dial patch is already represented in history. Per-zone/day endpoint interpolation and canonical runtime targets replace its retired AppDaemon implementation. |
| `fix/production-ready-audit` | `bdba26f` | Squashed as `0495abb`; comparing the two tips changes only README, with identical controller/integration/CI/test source. |
| `main` | `aaf8850` | Ancestor of the baseline. |

## Local history

Six apparently divergent local tips are complete-tree matches to existing ancestors of the baseline:

| Local tip | Equivalent ancestor |
| --- | --- |
| `design/multiroom-crop-steering` / `1b38e26` | `1d1bdd4` |
| `feat/dashboard-ux-redesign` / `9ffb74b` | `9dd0772` |
| `feat/signal-discipline` / `1d65d65` | `4d1d122` |
| `feat/visual-editor-merge` / `fc4fbd5` | `1b4480b` |
| `fix/p2-ec-logic-divergence` / `74a62fc` | `efa6fea` |
| previous local `main` / `8e7c585` | `e697a3c` |

The earlier lights/watchdog fix at `a938954` and independent pH-gate fix at `1347f84` are patch-equivalent to changes already retained. Local tracking branches share the reviewed remote tips. The local rescue snapshot adds old standalone dashboards, not controller code; preserve those privately rather than publishing them wholesale.

## Feature decisions

- Keep the current combined VWC/EC recorder chart and reactive planning curve. The old trainer invents plant response and overnight behavior, uses different dryback arithmetic, and lacks current timing/guardrail contracts.
- Keep continuous steering in the grow planner: reviewed endpoint profiles interpolate per zone and day, and canonical runtime overrides cover both historical mode families.
- Keep dual fused-sensor naming and room-scoped resolution, blind-zone time transitions/budgets, source-water gates, interruptible duration accounting and shared-hardware fault holds.
- Preserve optional longer-history providers, recorded shot overlays and measured dryback analysis as future ideas. Reimplement them with source timestamps, coverage and correct units.
- Do not restore old run-summary code that labels current readings and today's counters as a 56-day run, or peak/trough labels that confuse VWC percentage points with relative dryback percent.

Sensor validation gaps found during this source review were reported for release correction. The audit itself does not establish that a fix was deployed or that physical irrigation was verified. Final release tests and live commissioning remain separate evidence.

## Publication boundary

`scripts/prepare_addon_release.py` prepares a tracked-files-only add-on payload and review manifest. Preparation leaves the dedicated repository unchanged. The payload uses tracked canonical `www/` content with the add-on landing-page overlay, excludes tests/caches/untracked files, and verifies that the vendored engine matches its tested source. Applying or publishing is explicit and limited to the dedicated repository's `f2_control/` directory; root repository metadata is preserved.
