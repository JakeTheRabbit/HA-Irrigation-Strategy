"""ClimateSense Pillar 4 — Photoperiod & Lights Manager.

Reads photoperiod from the active recipe phase and drives the master
lights switch on the schedule. Optionally ramps PPFD via a dimmer
entity over `ramp_minutes` at sunrise/sunset.

Fires `climate_lights_on` and `climate_lights_off` events that
RootSense's existing photoperiod logic already listens for.

For the F1 install, the lights schedule is currently held in the GW
pack via the `Grow Room Light Timer` template sensor (8:00 → 20:00 in
the live config). This pillar is a drop-in upgrade: when enabled, the
recipe phase's `photoperiod_hours` overrides the static 12-h default.

Defaults assume:
- master switch entity: `light.grow_room_all_lights` (or
  `switch.grow_room_lights_master` if you prefer a switch)
- dimmer entity (optional): `number.grow_room_light_intensity_pct`

Configurable via `apps.yaml`:
  lights_master_entity: switch.your_lights
  dimmer_entity: number.your_dimmer
  lights_on_hour: 8
  ramp_minutes: 30
"""
from __future__ import annotations

import logging
from datetime import datetime, time, timedelta
from typing import Any

from ..base import IntelligenceApp
from ..bus import RootSenseBus

_LOGGER = logging.getLogger(__name__)


class ClimateSenseLights(IntelligenceApp):
    def initialize(self) -> None:  # noqa: D401
        self.bus = RootSenseBus.instance()
        cfg = self.args or {}

        self.master_entity = cfg.get("lights_master_entity", "light.grow_room_all_lights")
        self.dimmer_entity = cfg.get("dimmer_entity")
        self.lights_on_hour = int(cfg.get("lights_on_hour", 8))
        self.ramp_minutes = float(cfg.get("ramp_minutes", 30))
        self.lights_state_sensor = cfg.get(
            "lights_state_sensor", "binary_sensor.gw_lights_on"
        )

        # Schedule sunrise/sunset every minute — the heavy logic only runs
        # near the boundary times.
        self.run_every(self._tick, "now+15", 60)

        self.log(
            "ClimateSenseLights ready (master=%s dimmer=%s on_hr=%d ramp=%.0fmin)",
            self.master_entity, self.dimmer_entity,
            self.lights_on_hour, self.ramp_minutes,
        )

    def _tick(self, _kwargs: Any) -> None:
        if not self._is_module_enabled():
            return

        photoperiod = self._read_active_photoperiod()
        if photoperiod is None:
            return

        on_t = time(self.lights_on_hour, 0)
        off_hour = (self.lights_on_hour + photoperiod) % 24
        off_t = time(off_hour, 0)

        now = datetime.now().time()
        is_day = self._is_within(on_t, off_t, now)
        currently_on = str(self.get_state(self.lights_state_sensor)).lower() == "on"

        if is_day and not currently_on:
            self._lights_on()
            self.bus.publish("climate.lights_on", {"ts": datetime.utcnow().isoformat()})
            self.fire_event("climate_lights_on")
        elif not is_day and currently_on:
            self._lights_off()
            self.bus.publish("climate.lights_off", {"ts": datetime.utcnow().isoformat()})
            self.fire_event("climate_lights_off")

        # Sunrise / sunset ramp via dimmer (if configured)
        self._maybe_apply_ramp(now, on_t, off_t, is_day)

    def _read_active_photoperiod(self) -> int | None:
        """Read photoperiod from the timeline pillar's diagnostic sensor."""
        attrs = None
        try:
            attrs = self.get_state("sensor.climate_recipe_active_phase", attribute="all")
        except Exception:  # noqa: BLE001
            pass
        if attrs and isinstance(attrs, dict):
            a = attrs.get("attributes", {})
            ph = a.get("photoperiod_hours")
            if ph:
                return int(ph)
        # fallback
        return 12

    def _is_within(self, on_t: time, off_t: time, now: time) -> bool:
        """Return True if `now` is in the [on_t, off_t) window, handling
        midnight wrap (e.g. on=18:00, off=06:00)."""
        if on_t == off_t:
            return False
        if on_t < off_t:
            return on_t <= now < off_t
        return now >= on_t or now < off_t  # wraps midnight

    def _lights_on(self) -> None:
        domain = self.master_entity.split(".")[0]
        self.call_service(f"{domain}/turn_on", entity_id=self.master_entity)

    def _lights_off(self) -> None:
        domain = self.master_entity.split(".")[0]
        self.call_service(f"{domain}/turn_off", entity_id=self.master_entity)

    def _maybe_apply_ramp(self, now: time, on_t: time, off_t: time, is_day: bool) -> None:
        if not self.dimmer_entity:
            return
        target_ppfd = self._read_float("sensor.climate_target_ppfd_target")
        if target_ppfd is None:
            return

        # Compute fraction of the way through the ramp window.
        # We treat ramp_minutes as the fade-in (sunrise) and fade-out
        # (sunset) duration. Outside the ramp windows the dimmer holds
        # at full target (during photoperiod) or 0 (off).
        ramp_s = int(self.ramp_minutes * 60)
        nowdt = datetime.now()
        on_dt = nowdt.replace(hour=on_t.hour, minute=on_t.minute, second=0, microsecond=0)
        off_dt = nowdt.replace(hour=off_t.hour, minute=off_t.minute, second=0, microsecond=0)

        if is_day:
            since_on = (nowdt - on_dt).total_seconds()
            until_off = (off_dt - nowdt).total_seconds()
            if 0 <= since_on < ramp_s:
                fraction = since_on / ramp_s
            elif 0 <= until_off < ramp_s:
                fraction = until_off / ramp_s
            else:
                fraction = 1.0
            value = target_ppfd * fraction
        else:
            value = 0.0

        # Convert PPFD target → dimmer % heuristically: assume the dimmer
        # is linear and 100% = `ppfd_max` (override via config if needed).
        ppfd_max = self._read_float(f"number.{self.dimmer_entity.split('.')[1]}_max", default=1100) or 1100
        pct = max(0.0, min(100.0, (value / ppfd_max) * 100))
        self.call_service("number/set_value",
                          entity_id=self.dimmer_entity, value=round(pct, 1))
