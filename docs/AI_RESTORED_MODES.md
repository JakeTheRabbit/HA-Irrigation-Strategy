# Restored options in the AI prompt

The controller brief is generated from the engine and controller shipped together. Its default phase and gate descriptions stay intact. An additional section appears only for restoration capabilities that exist in that image, and labels their opt-in behavior explicitly.

The section distinguishes the minimum P0 wait from the low-moisture bypass, stalled dryback from suspect probes, plain timed P2 from guarded timed P2, and budgeted floor top-ups from cap-exempt safety shots. A configured timer end replaces predictive P3; an EC flush target continues only through the existing correction, drainage, feed and budget checks.

The rescue-only dead-feed-probe option does not bypass other interlocks or accept an out-of-band reading. Waste preclosing is off by default, verifies closure before priming, and a transient unreadable policy holds. Rescue-miss and estimated-tank alerts do not withhold water.

Sump water-balance output is explicitly modeled evidence at room or shared-sump scope. It is not a measured per-zone runoff catch or measured transpiration. Learning/unresolvable output remains unknown. Only the estimator's AI mode adds that hint to AI evidence; it grants no new action authority.

After restoring packs are integrated, regenerate with `PYTHONPATH=addons/f2_control/f2_control python -m brain.controller_brief --write`. The generated copy and prompt regression tests must then match the combined runtime. Regeneration changes the shared instruction hash once; it does not change any live setting or cached request policy.
