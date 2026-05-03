"""ClimateSenseControl — AppDaemon adapter.

Replaces the original monolithic control.py with a thin layer that:
1. Reads sensor state.
2. Resolves the active leaf-VPD-derived RH target (or recipe-direct RH
   if leaf temp sensor not configured).
3. Calls each per-actuator propose() function.
4. Calls the watchdog.
5. Calls the coordinator to merge and prioritise.
6. Dispatches the final actions to HA.

Per-actuator state (HVACState, DehuState, HumidState, CO2State,
ExhaustState) is held on the app instance and mutated when actions
are successfully dispatched.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from ...base import IntelligenceApp
from ...bus import RootSenseBus
from ..hardware import HardwareCalibration, load_hardware_calibration
from ..leaf_vpd import leaf_vpd_kpa, solve_target_rh
from . import co2 as co2_mod
from . import coordinator as coord
from . import dehumidifier as dehu_mod
from . import exhaust as exhaust_mod
from . import hvac as hvac_mod
from . import humidifier as humid_mod
from . import watchdog as watchdog_mod
from .actions import Action, ActionKind


class ClimateSenseControl(IntelligenceApp):
    def initialize(self) -> None:  # noqa: D401
        self.bus = RootSenseBus.instance()
        cfg = self.args or {}
        hardware_path = Path(cfg.get(
            "hardware_file",
            str(Path(self.app_dir) / "crop_steering" / "intelligence" / "climate" / "hardware_f1.yaml"),
        ))
        try:
            self.hw: HardwareCalibration = load_hardware_calibration(hardware_path)
            self.log("Loaded hardware calibration for room %s", self.hw.room)
        except Exception as e:  # noqa: BLE001
            self.log("ClimateSenseControl: %s — DISABLED", e, level="ERROR")
            self.hw = None  # type: ignore[assignment]

        self.tick_seconds = int(cfg.get("tick_seconds", 30))
        self.maintenance_entity = cfg.get(
            "maintenance_entity", "input_boolean.gw_maintenance_mode"
        )
        self.environment_enabled_entity = cfg.get(
            "environment_enabled_entity", "input_boolean.gw_environment_enabled"
        )

        # Per-actuator state
        self.hvac_state = hvac_mod.HVACState()
        self.dehu_state = dehu_mod.DehuState()
        self.humid_state = humid_mod.HumidState()
        self.co2_state = co2_mod.CO2State()
        self.exhaust_state = exhaust_mod.ExhaustState()

        # Sensor freshness tracking — populated each tick
        self._sensor_state: dict[str, dict[str, Any]] = {}
        self._active_anomalies: set[str] = set()

        # Anomaly events from the bus update _active_anomalies
        self.bus.subscribe("anomaly.detected", self._on_anomaly)

        self.run_every(self._tick, "now+15", self.tick_seconds)
        self.log("ClimateSenseControl ready (tick=%ds)", self.tick_seconds)

    # ------------------------------------------------------------------ tick

    def _tick(self, _kwargs: Any) -> None:
        if not self._is_module_enabled() or self.hw is None:
            return
        if not self._is_environment_active():
            return  # operator master-disable; do nothing

        now = datetime.utcnow()

        # ── Read sensors ──────────────────────────────────────────────
        room = self._read_room_state(now)
        targets = self._resolve_targets(lights_on=room["lights_on"], room=room)
        if targets is None:
            return  # no recipe targets yet

        # ── Per-actuator propose ──────────────────────────────────────
        proposals: dict[str, list[Action]] = {}

        # HVAC: chase day_temp_c / night_temp_c
        target_temp = targets.get("day_temp_c" if room["lights_on"] else "night_temp_c")
        proposals["hvac"] = hvac_mod.propose_hvac(
            target_c=target_temp,
            current_c=room["temp_c"],
            cal=self.hw.hvac_primary,
            state=self.hvac_state,
            now=now,
        ) if self.hw.hvac_primary else []

        # Dehu / Humid: chase the leaf-VPD-derived RH target
        target_rh = targets.get("derived_rh_pct") or targets.get(
            "day_rh_pct" if room["lights_on"] else "night_rh_pct"
        )
        proposals["dehu"] = dehu_mod.propose_dehu(
            current_rh=room["rh_pct"],
            target_rh=target_rh,
            cal=self.hw.dehumidifier,
            state=self.dehu_state,
            now=now,
        )
        proposals["humid"] = humid_mod.propose_humid(
            current_rh=room["rh_pct"],
            target_rh=target_rh,
            cal=self.hw.humidifier,
            state=self.humid_state,
            now=now,
        )

        # CO2: pulse
        proposals["co2"] = co2_mod.propose_co2(
            current_ppm=room["co2_ppm"],
            target_ppm=targets.get("co2_ppm"),
            lights_on=room["lights_on"],
            cal=self.hw.co2,
            state=self.co2_state,
            now=now,
        )

        # Exhaust: emergency + scheduled
        proposals["exhaust"] = exhaust_mod.propose_exhaust(
            current_temp_c=room["temp_c"],
            current_co2_ppm=room["co2_ppm"],
            lights_on=room["lights_on"],
            cal=self.hw.exhaust,
            state=self.exhaust_state,
            now=now,
        )

        # ── Watchdog ──────────────────────────────────────────────────
        actuator_runtime = self._snapshot_actuator_runtime()
        safety_actions, anomaly_codes = watchdog_mod.watchdog_check(
            hw=self.hw,
            sensor_state=self._sensor_state,
            actuator_runtime=actuator_runtime,
            now=now,
        )
        for code in anomaly_codes:
            self._fire_anomaly(code)

        # ── Coordinate ────────────────────────────────────────────────
        ac_is_cooling = self.hvac_state.last_mode == "cool"
        temp_above_target = (
            target_temp is not None
            and room["temp_c"] is not None
            and room["temp_c"] > target_temp
        )

        actions = coord.resolve_proposals(
            proposals=proposals,
            safety_actions=safety_actions,
            maintenance_mode=False,   # we already early-returned if true
            active_anomalies=self._active_anomalies,
            ac_is_cooling=ac_is_cooling,
            temp_above_target=temp_above_target,
        )

        # ── Dispatch ──────────────────────────────────────────────────
        for action in actions:
            self._dispatch(action, now)

    # ------------------------------------------------------------------ dispatch

    def _dispatch(self, action: Action, now: datetime) -> None:
        try:
            if action.kind == ActionKind.SWITCH_ON:
                self.call_service("switch/turn_on", entity_id=action.entity)
            elif action.kind == ActionKind.SWITCH_OFF:
                domain = action.entity.split(".")[0]
                self.call_service(f"{domain}/turn_off", entity_id=action.entity)
            elif action.kind == ActionKind.HVAC_SETPOINT:
                self.call_service("climate/set_temperature",
                                  entity_id=action.entity,
                                  temperature=action.value)
            elif action.kind == ActionKind.HVAC_MODE:
                self.call_service("climate/set_hvac_mode",
                                  entity_id=action.entity,
                                  hvac_mode=action.value)
            elif action.kind == ActionKind.NUMBER_SET:
                self.call_service("number/set_value",
                                  entity_id=action.entity, value=action.value)
            else:
                return

            # Update per-actuator state
            cls = action.actuator_class
            if cls == "hvac":
                hvac_mod.apply_action_to_state(self.hvac_state, action, now)
            elif cls == "dehu":
                dehu_mod.apply_action_to_state(self.dehu_state, action, now)
            elif cls == "humid":
                humid_mod.apply_action_to_state(self.humid_state, action, now)
            elif cls == "co2":
                co2_mod.apply_action_to_state(self.co2_state, action, self.hw.co2, now)
            elif cls == "exhaust":
                exhaust_mod.apply_action_to_state(self.exhaust_state, action, now)

            self.log("DISPATCH [%s] %s on %s — %s",
                     action.severity, action.kind.value, action.entity, action.reason)
        except Exception as e:  # noqa: BLE001
            self.log("DISPATCH FAILED %s on %s: %s",
                     action.kind.value, action.entity, e, level="ERROR")

    # ------------------------------------------------------------------ helpers

    def _read_room_state(self, now: datetime) -> dict[str, Any]:
        s = self.hw.sensors
        result = {
            "temp_c": self._read_and_track(s.temp_primary, now),
            "rh_pct": self._read_and_track(s.rh_primary, now),
            "co2_ppm": self._read_and_track(s.co2, now),
            "vpd_kpa": self._read_and_track(s.vpd, now),
            "leaf_temp_c": self._read_and_track(s.leaf_temp, now) if s.leaf_temp else None,
            "lights_on": str(self.get_state(s.lights_on)).lower() == "on" if s.lights_on else False,
        }
        return result

    def _read_and_track(self, entity: str | None, now: datetime) -> float | None:
        if not entity:
            return None
        v = self._read_float(entity)
        if v is not None:
            self._sensor_state[entity] = {"value": v, "last_update": now}
        return v

    def _resolve_targets(self, lights_on: bool, room: dict[str, Any]) -> dict[str, float] | None:
        """Read the per-metric target sensors published by the timeline.

        If a leaf-VPD target is published AND we have leaf temp +
        air temp readings, derive an RH target via solve_target_rh
        and surface it as `derived_rh_pct`.
        """
        keys = [
            "day_temp_c", "night_temp_c",
            "day_rh_pct", "night_rh_pct",
            "vpd_kpa", "leaf_vpd_kpa", "co2_ppm",
        ]
        out: dict[str, float] = {}
        for k in keys:
            v = self._read_float(f"sensor.climate_target_{k}")
            if v is not None:
                out[k] = v
        if not out:
            return None

        # Leaf-VPD-derived RH if possible
        target_leaf_vpd = out.get("leaf_vpd_kpa")
        leaf_t = room.get("leaf_temp_c")
        air_t = room.get("temp_c")
        if (target_leaf_vpd is not None and leaf_t is not None and air_t is not None):
            sol = solve_target_rh(
                target_leaf_vpd, leaf_temp_c=leaf_t, air_temp_c=air_t,
            )
            out["derived_rh_pct"] = sol.target_rh_pct
            # Publish the derived target so dashboards / anomaly scanner
            # can compare and flag unattainable conditions.
            self.set_state(
                "sensor.climate_derived_rh_target_pct",
                state=round(sol.target_rh_pct, 1),
                attributes={
                    "attainable": sol.attainable,
                    "raw_target_rh_pct": round(sol.raw_target_rh_pct, 2),
                    "leaf_temp_c": leaf_t,
                    "air_temp_c": air_t,
                    "target_leaf_vpd_kpa": target_leaf_vpd,
                    "unit_of_measurement": "%",
                    "icon": "mdi:water-percent",
                    "friendly_name": "Derived RH target (from leaf VPD)",
                },
            )
            if not sol.attainable:
                self._fire_anomaly("climate_unattainable_rh_target")
        return out

    def _snapshot_actuator_runtime(self) -> dict[str, dict[str, Any]]:
        snap: dict[str, dict[str, Any]] = {}
        # Dehu units
        for name, u in self.dehu_state.units.items():
            for unit_cfg in self.hw.dehumidifier.units:
                if unit_cfg["name"] != name:
                    continue
                for relay in unit_cfg["relays"]:
                    snap[relay] = {
                        "is_on": u.is_on,
                        "last_on_at": u.last_on_at,
                        "actuator_class": "dehumidifier",
                    }
        # Humidifier
        if self.hw.humidifier.entity:
            snap[self.hw.humidifier.entity] = {
                "is_on": self.humid_state.is_on,
                "last_on_at": self.humid_state.last_on_at,
                "actuator_class": "humidifier",
            }
        # CO2
        if self.hw.co2.solenoid:
            snap[self.hw.co2.solenoid] = {
                "is_on": self.co2_state.phase == "on",
                "last_on_at": (
                    self.co2_state.phase_until - __import__("datetime").timedelta(seconds=self.hw.co2.pulse_on_seconds)
                    if self.co2_state.phase == "on" and self.co2_state.phase_until else None
                ),
                "actuator_class": "co2",
            }
        # Exhaust
        if self.hw.exhaust.entity:
            snap[self.hw.exhaust.entity] = {
                "is_on": self.exhaust_state.is_on,
                "last_on_at": self.exhaust_state.last_on_at,
                "actuator_class": "exhaust",
            }
        return snap

    def _on_anomaly(self, _topic: str, payload: dict[str, Any]) -> None:
        code = payload.get("code")
        if not code:
            return
        severity = payload.get("severity", "info")
        # Only critical/emergency anomalies suppress control
        if severity in ("critical", "emergency"):
            self._active_anomalies.add(code)
        elif code in self._active_anomalies and severity in ("info",):
            # info-only updates don't add or remove
            pass

    def _fire_anomaly(self, code: str) -> None:
        if code in self._active_anomalies:
            return
        self.fire_event("crop_steering_anomaly",
                        code=code, zone=None, severity="warning",
                        evidence="raised by control watchdog",
                        remediation="see docs/upgrade/SEQUENCE_OF_OPERATIONS.md",
                        ts=datetime.utcnow().isoformat())
        self._active_anomalies.add(code)

    def _is_environment_active(self) -> bool:
        env = str(self.get_state(self.environment_enabled_entity)).lower() == "on"
        maint = str(self.get_state(self.maintenance_entity)).lower() == "on"
        return env and not maint
