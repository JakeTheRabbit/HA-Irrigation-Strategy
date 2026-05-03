"""ClimateSense — environmental control intelligence pillars.

Sister platform to RootSense. Same architecture (pillars + bus + store),
parallel package layout, same module-enable gating pattern.

Pillars (each opt-in, gated by its own switch):
- sensing.py        — climate sensor fusion + derived metrics
- timeline.py       — recipe loader, per-phase target resolution
- control.py        — temp/RH/CO2 closed loops with hardware calibration
- lights.py         — photoperiod manager + DLI tracker
- anomaly.py        — climate excursions and peer-sensor disagreement

Shared infra inherited from the parent intelligence/ package:
- bus.py            — RootSenseBus (in-process pub/sub)
- store.py          — RootSenseStore (SQLite analytics)
- base.py           — IntelligenceApp mixin

Hardware calibration:
- Each control loop reads its actuator config from
  hardware_<room>.yaml (e.g. hardware_f1.yaml). Calibration offsets
  account for the real-world gap between commanded and measured
  state — heat pumps that run hot, dehumidifiers that overshoot,
  CO2 solenoids with non-linear flow.
"""
from __future__ import annotations

CLIMATESENSE_VERSION = "0.1.0-dev"

__all__ = [
    "sensing",
    "timeline",
    "control",
    "lights",
    "anomaly",
    "hardware",
]
