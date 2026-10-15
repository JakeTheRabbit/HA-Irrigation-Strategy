## Substrate table for this install
Selected by the install's substrate option. 'generic' is the default for a fresh install: relative-only, no absolute moisture bands. Numbers are starting ranges (SUB-01), never limits; the engine's own bounds and the envelope still apply.

### Substrate `generic`: Unknown or other substrate (GL-LAW, USU, ENGINE, CTRL)


Rules:
- Use only relative figures: the zone's own peak, its own drybacks, its own EC history. No absolute VWC band applies to an unknown medium or an uncalibrated probe, so an arc's point bands do not apply either: compare only its relative (vendor) column with the zone's observed overnight dryback.
- Learn field capacity from the zone's repeated ramp plateaus (detected Vmax) before trusting any P1 target. With Auto Setpoints on, code sets both from the zone's own highest readings instead (CT-12), so they are only as sound as the probe.
- Treat the rescue floor as a safety limit and never propose lowering it. With Auto Setpoints off it is the grower's value; with it on, code shifts it with field capacity, down as well as up, so a floor falling with the zone's peaks may be following a drifting probe: raise that for a person (PRB-14).
- Advise measuring the medium's water release and air capacity in its container before tuning thresholds.

