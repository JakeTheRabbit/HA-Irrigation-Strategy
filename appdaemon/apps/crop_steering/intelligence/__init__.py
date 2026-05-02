"""RootSense intelligence pillars.

Each submodule is an opt-in AppDaemon app or library:

- bus.py                  — in-process pub/sub used by all pillars
- store.py                — SQLite analytics store (rootsense.db)
- root_zone.py            — Pillar 1: substrate analytics, field capacity, dryback episodes
- adaptive_irrigation.py  — Pillar 2: cultivator intent, dynamic shot planning, optimisation loop
- agronomic.py            — Pillar 3: transpiration, climate-substrate, run analytics
- orchestration.py        — Pillar 4: coordinator + custom shots + emergency
- anomaly.py              — cross-cutting anomaly scanner

See docs/upgrade/ROOTSENSE_v3_PLAN.md for the full design.
"""

__all__ = [
    "bus",
    "store",
    "root_zone",
    "adaptive_irrigation",
    "agronomic",
    "orchestration",
    "anomaly",
]

ROOTSENSE_VERSION = "3.0.0-dev"
