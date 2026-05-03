"""ClimateSense Pillar 2 — Setpoints Timeline.

Loads a recipe YAML, resolves "what are my targets right now?" based
on day-in-grow + day/night state, and publishes target sensors that
the control loop subscribes to.

Recipe schema (see config/recipes/athena_f1_default.yaml for an example):

  recipe: <name>
  units: {temp: c, rh: pct, co2: ppm, vpd: kpa}
  phases:
    - name: <human-readable>
      days: <int — duration of this phase>
      photoperiod_hours: <int>
      crop_steering_intent: <-100..+100, optional>
      targets:
        day_temp_c:    {value, tolerance, optional ramp_minutes}
        night_temp_c:  {value, tolerance}
        day_rh_pct:    {value, tolerance}
        night_rh_pct:  {value, tolerance}
        vpd_kpa:       {value, tolerance}            # optional
        co2_ppm:       {value, tolerance}
        ppfd_target:   {value, tolerance}            # optional

The pillar publishes one sensor per metric:

  sensor.climate_target_day_temp_c
  sensor.climate_target_night_temp_c
  sensor.climate_target_co2_ppm
  ... etc

Plus diagnostic:

  sensor.climate_recipe_active_phase
    state = phase name
    attributes:
      day_in_grow:        n
      day_in_phase:       n
      photoperiod_hours:  n
      recipe:             <name>

The timeline pillar may also drive the cultivator-intent slider if
`switch.crop_steering_intelligence_climate_drives_intent_enabled` is on.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None  # type: ignore

from ..base import IntelligenceApp
from ..bus import RootSenseBus

_LOGGER = logging.getLogger(__name__)


@dataclass
class Target:
    value: float
    tolerance: float = 0.0
    ramp_minutes: float = 0.0


@dataclass
class Phase:
    name: str
    days: int
    photoperiod_hours: int = 12
    crop_steering_intent: float | None = None
    targets: dict[str, Target] = field(default_factory=dict)


@dataclass
class Recipe:
    name: str
    units: dict[str, str]
    phases: list[Phase]

    @property
    def total_days(self) -> int:
        return sum(p.days for p in self.phases)

    def phase_for_day(self, day_in_grow: int) -> tuple[Phase, int] | None:
        """Return (active phase, day_in_phase) or None if past the end."""
        cumulative = 0
        for phase in self.phases:
            if day_in_grow < cumulative + phase.days:
                return phase, day_in_grow - cumulative
            cumulative += phase.days
        return None  # past the recipe's end


def load_recipe(path: Path | str) -> Recipe:
    """Load and validate a recipe YAML."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Recipe file not found: {p}")
    if yaml is None:
        raise RuntimeError("PyYAML is not available")
    raw = yaml.safe_load(p.read_text())
    if not isinstance(raw, dict):
        raise ValueError(f"Recipe root must be a mapping in {p}")

    name = str(raw.get("recipe", p.stem))
    units = raw.get("units", {}) or {}

    phases_raw = raw.get("phases", []) or []
    phases: list[Phase] = []
    for i, ph in enumerate(phases_raw):
        if not isinstance(ph, dict):
            raise ValueError(f"Phase {i} in {p} must be a mapping")
        targets_raw = ph.get("targets", {}) or {}
        targets = {}
        for key, t in targets_raw.items():
            if isinstance(t, dict):
                targets[key] = Target(
                    value=float(t["value"]),
                    tolerance=float(t.get("tolerance", 0.0)),
                    ramp_minutes=float(t.get("ramp_minutes", 0.0)),
                )
            else:
                targets[key] = Target(value=float(t))
        phases.append(Phase(
            name=str(ph.get("name", f"phase_{i}")),
            days=int(ph.get("days", 7)),
            photoperiod_hours=int(ph.get("photoperiod_hours", 12)),
            crop_steering_intent=(
                float(ph["crop_steering_intent"])
                if "crop_steering_intent" in ph else None
            ),
            targets=targets,
        ))
    if not phases:
        raise ValueError(f"Recipe {p} has no phases")

    return Recipe(name=name, units=units, phases=phases)


class ClimateSenseTimeline(IntelligenceApp):
    """AppDaemon entry point for the timeline pillar."""

    def initialize(self) -> None:  # noqa: D401
        self.bus = RootSenseBus.instance()
        cfg = self.args or {}
        self.recipe_dir = Path(cfg.get("recipe_dir", "/config/recipes"))
        self.default_recipe = cfg.get("default_recipe", "athena_f1_default")
        self.day_offset_entity = cfg.get(
            "day_offset_entity", "number.climate_grow_day_offset"
        )
        self.lights_on_entity = cfg.get(
            "lights_on_entity", "binary_sensor.gw_lights_on"
        )
        self.drives_intent_switch = (
            "switch.crop_steering_intelligence_climate_drives_intent_enabled"
        )

        self._recipe: Recipe | None = None
        self._reload_recipe()

        # Republish targets every minute (cheap; covers day/night
        # transitions promptly and lets recipe edits take effect).
        self.run_every(self._tick, "now+5", 60)

        self.log(
            "ClimateSenseTimeline ready (recipe_dir=%s default=%s)",
            self.recipe_dir, self.default_recipe,
        )

    def _tick(self, _kwargs: Any) -> None:
        if not self._is_module_enabled():
            return
        if self._recipe is None:
            return

        day = self._read_int(self.day_offset_entity, default=0) or 0
        active = self._recipe.phase_for_day(day)
        if active is None:
            self.set_state(
                "sensor.climate_recipe_active_phase",
                state="completed",
                attributes={
                    "recipe": self._recipe.name,
                    "day_in_grow": day,
                    "total_days": self._recipe.total_days,
                    "icon": "mdi:check-circle-outline",
                    "friendly_name": "Recipe phase",
                },
            )
            return

        phase, day_in_phase = active
        is_day = self._is_lights_on()

        # Diagnostic sensor
        self.set_state(
            "sensor.climate_recipe_active_phase",
            state=phase.name,
            attributes={
                "recipe": self._recipe.name,
                "day_in_grow": day,
                "day_in_phase": day_in_phase,
                "phase_days": phase.days,
                "photoperiod_hours": phase.photoperiod_hours,
                "is_day": is_day,
                "icon": "mdi:calendar-clock",
                "friendly_name": "Recipe phase",
            },
        )

        # Per-target sensors
        for key, t in phase.targets.items():
            self.set_state(
                f"sensor.climate_target_{key}",
                state=round(t.value, 3),
                attributes={
                    "tolerance": t.tolerance,
                    "ramp_minutes": t.ramp_minutes,
                    "phase": phase.name,
                    "day_in_phase": day_in_phase,
                    "is_day_target": "day_" in key,
                    "is_night_target": "night_" in key,
                    "friendly_name": f"Target — {key}",
                },
            )

        # Optionally drive the cultivator intent slider
        if (
            phase.crop_steering_intent is not None
            and self._is_intent_drive_enabled()
        ):
            self.call_service(
                "number/set_value",
                entity_id="number.crop_steering_steering_intent",
                value=phase.crop_steering_intent,
            )

        # Bus event so other pillars (control loop, anomaly scanner)
        # can react without polling the per-target sensors.
        self.bus.publish("climate.targets_updated", {
            "phase": phase.name,
            "day_in_grow": day,
            "day_in_phase": day_in_phase,
            "is_day": is_day,
            "targets": {k: {"value": t.value, "tolerance": t.tolerance}
                        for k, t in phase.targets.items()},
        })

    def _reload_recipe(self) -> None:
        try:
            path = self.recipe_dir / f"{self.default_recipe}.yaml"
            self._recipe = load_recipe(path)
            self.log("Loaded recipe %s with %d phases (%d days)",
                     self._recipe.name, len(self._recipe.phases),
                     self._recipe.total_days)
        except Exception as e:  # noqa: BLE001
            self.log("Failed to load recipe: %s", e, level="ERROR")
            self._recipe = None

    def _is_lights_on(self) -> bool:
        return str(self.get_state(self.lights_on_entity)).lower() == "on"

    def _is_intent_drive_enabled(self) -> bool:
        return str(self.get_state(self.drives_intent_switch)).lower() == "on"
