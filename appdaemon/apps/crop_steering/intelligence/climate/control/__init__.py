"""Climate control package — per-actuator state machines + coordinator.

Layered architecture (matches commercial BMS pattern):

  Layer 1  Setpoint authority   → timeline.py + leaf_vpd.solve_target_rh
  Layer 2  Per-actuator law     → hvac.py / dehu.py / humidifier.py /
                                  co2.py / exhaust.py
  Layer 3  Coordinator          → coordinator.py (resolves AC↔dehu,
                                  applies cross-actuator rules)
  Layer 4  Safety watchdogs     → watchdog.py (max-runtime, sensor
                                  sanity, runaway detection)
  Layer 5  Observability        → SQLite store + bus events

Each per-actuator file exposes a `propose(target, current, hw, state)
→ Action` function. The coordinator gathers proposals, resolves
conflicts, applies safety overrides, and emits the final commands.
The actual AppDaemon app class (ClimateSenseControl) is a thin
adapter that owns the tick loop and wires Layer 5 logging.
"""
from .actions import Action, ActionKind  # noqa: F401
from .app import ClimateSenseControl  # noqa: F401
