# AI instructions and room context

Settings > AI assistant > Instructions shows the exact text the Claude controller built at the displayed publication time. Every system block includes its source paths, full SHA-256 and an estimated token count. No prompt is invented in the dashboard: a rules-only controller or an older app shows that no snapshot is available.

Administrator notes and structured context are revisioned per room in Home Assistant storage. The last ten saved versions can be loaded into a draft, reviewed and saved as a new revision. Writes require an authenticated administrator and the current revision; stale edits are refused. A save is verified by readback before the editor reports success. The dashboard also shows whether the controller has built that revision yet.

House notes and the optional substrate, environment, genetics, stage, feed, goals, constraints and calibration fields appear in a separate block C. They are operator-supplied context, not verified agronomy or authorization to bypass code-enforced safety. Explicit requests to bypass safety are refused; the controller's safety and power checks remain authoritative. Do not put credentials or personal information in notes, since they are sent to the AI provider. The shipped block A is never edited. An install with no notes/context gets the same A/B prompt and request as before.

The existing room Substrate and Growth stage settings remain authoritative and visible beside the context editor. Change those in Equipment > Setup. Context does not change room sizing, substrate selection, the controller's configured stage arc or any live target. Calibration and environment notes do not imply measured evidence. The selected global stage arc is shown with the published snapshot; per-room arc selection and additional sourced agronomy are separate work.

Cache preferences control breakpoints, not isolated provider entries. Each breakpoint caches the cumulative preceding prefix: B or C can cache A even when A's breakpoint is off. The system-block TTL can be 5 minutes or 1 hour; evidence keeps the existing 5-minute TTL. There are at most four breakpoints (A/B/C/evidence). Defaults preserve today's behavior: A/B at 1 hour, evidence at 5 minutes, C absent until context is supplied.

Rebuild local prompt requests regeneration on the next controller pass. It makes no paid AI request and does not purge the provider cache. Cache hit ratio, read tokens and AI spend come from the controller's reported usage. Estimated net cache savings compare the same input without caching against charged input, including cache writes, at the controller's model tariff; conservative timeout charges also count, so the figure is explicitly an estimate. Negative savings mean caching cost more. Old usage files show no estimate until the next window reset. Token counts in the editor are character-based estimates; the page does not claim guaranteed monetary savings.

The prompt snapshot is persisted separately from Recorder. The configuration sensor excludes its text attribute from Recorder to avoid duplicating notes in every state record. The controller publishes changed text/settings once and retries a refused publication. Saved configuration can be newer than the controller snapshot; this discrepancy is shown explicitly.

## Restored options in the AI prompt

The controller brief is generated from the engine and controller shipped together. Its default phase and gate descriptions stay intact. An additional section appears only for restoration capabilities that exist in that image, and labels their opt-in behavior explicitly.

The section distinguishes the minimum P0 wait from the low-moisture bypass, stalled dryback from suspect probes, plain timed P2 from guarded timed P2, and budgeted floor top-ups from cap-exempt safety shots. A configured timer end replaces predictive P3; an EC flush target continues only through the existing correction, drainage, feed and budget checks.

The rescue-only dead-feed-probe option does not bypass other interlocks or accept an out-of-band reading. Waste preclosing is off by default, verifies closure before priming, and a transient unreadable policy holds. Rescue-miss and estimated-tank alerts do not withhold water.

Sump water-balance output is explicitly modeled evidence at room or shared-sump scope. It is not a measured per-zone runoff catch or measured transpiration. Learning/unresolvable output remains unknown. Only the estimator's AI mode adds that hint to AI evidence; it grants no new action authority.

After restoring packs are integrated, regenerate with `PYTHONPATH=addons/f2_control/f2_control python -m brain.controller_brief --write`. The generated copy and prompt regression tests must then match the combined runtime. Regeneration changes the shared instruction hash once; it does not change any live setting or cached request policy.
