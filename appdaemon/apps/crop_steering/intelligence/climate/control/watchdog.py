"""Watchdog — Tier 4 safety.

Runs every tick. Checks for:
- Sensor staleness (any critical sensor older than `sensor_stale_seconds`).
- Actuator runaway (any actuator on longer than its `max_runtime_min`).
- Emergency conditions (temp > emergency_temp_c, CO2 > emergency_co2_ppm)
  even if other layers somehow missed them.

Returns a list of safety/emergency Actions the coordinator MUST issue
unconditionally (overriding normal control proposals).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from ..hardware import HardwareCalibration
from .actions import Action, ActionKind


def watchdog_check(
    *,
    hw: HardwareCalibration,
    sensor_state: dict[str, dict[str, Any]],   # entity → {value, last_update}
    actuator_runtime: dict[str, dict[str, Any]],  # entity → {is_on, last_on_at}
    hvac_mode: str | None = None,              # last commanded mode; None if unknown
    now: datetime | None = None,
) -> tuple[list[Action], list[str]]:
    """Return (safety_actions, anomaly_codes)."""
    now = now or datetime.utcnow()
    actions: list[Action] = []
    anomaly_codes: list[str] = []

    # ── Sensor staleness ──────────────────────────────────────────────
    critical_sensors = [
        ("temp", hw.sensors.temp_primary),
        ("rh", hw.sensors.rh_primary),
        ("co2", hw.sensors.co2),
    ]
    for label, entity in critical_sensors:
        if not entity:
            continue
        s = sensor_state.get(entity)
        if s is None:
            anomaly_codes.append(f"climate_sensor_unavailable:{label}")
            continue
        last_update = s.get("last_update")
        if last_update is None:
            continue
        if (now - last_update).total_seconds() > hw.safety.sensor_stale_seconds:
            anomaly_codes.append(f"climate_sensor_stale:{label}")

    # ── Emergency conditions (re-flagged at watchdog level) ──────────
    temp_state = sensor_state.get(hw.sensors.temp_primary, {})
    temp_value = temp_state.get("value") if temp_state else None
    if temp_value is not None and temp_value > hw.safety.emergency_temp_c:
        anomaly_codes.append("climate_emergency_temp")
        # Force-on exhaust
        if hw.exhaust.entity:
            actions.append(Action(
                kind=ActionKind.SWITCH_ON,
                entity=hw.exhaust.entity,
                reason=f"WATCHDOG: temp {temp_value:.1f}°C > emergency {hw.safety.emergency_temp_c:.1f}",
                actuator_class="exhaust",
                severity="emergency",
            ))
        # If HVAC is in heat mode during a high-temp emergency it is
        # ACTIVELY making things worse — force OFF.
        if hvac_mode == "heat" and hw.hvac_primary:
            actions.append(Action(
                kind=ActionKind.HVAC_MODE,
                entity=hw.hvac_primary.entity,
                value="off",
                reason=(
                    f"WATCHDOG: HVAC heating during temp emergency "
                    f"({temp_value:.1f}°C > {hw.safety.emergency_temp_c:.1f}) — force off"
                ),
                actuator_class="hvac",
                severity="emergency",
            ))

    co2_state = sensor_state.get(hw.sensors.co2, {})
    co2_value = co2_state.get("value") if co2_state else None
    if co2_value is not None and co2_value > hw.safety.emergency_co2_ppm:
        anomaly_codes.append("climate_emergency_co2")
        # Force-close CO2 solenoid
        if hw.co2.solenoid:
            actions.append(Action(
                kind=ActionKind.SWITCH_OFF,
                entity=hw.co2.solenoid,
                reason=f"WATCHDOG: CO2 {co2_value:.0f} > emergency {hw.safety.emergency_co2_ppm:.0f}",
                actuator_class="co2",
                severity="emergency",
            ))

    # ── Actuator runaway ──────────────────────────────────────────────
    runtime_caps = hw.safety.actuator_max_runtime_min
    for entity, info in actuator_runtime.items():
        if not info.get("is_on"):
            continue
        last_on = info.get("last_on_at")
        if last_on is None:
            continue
        actuator_class = info.get("actuator_class", "unknown")
        cap = runtime_caps.get(actuator_class)
        if cap is None:
            continue
        elapsed_min = (now - last_on).total_seconds() / 60.0
        if elapsed_min > cap:
            anomaly_codes.append(f"climate_actuator_runaway:{actuator_class}:{entity}")
            actions.append(Action(
                kind=ActionKind.SWITCH_OFF,
                entity=entity,
                reason=f"WATCHDOG: {actuator_class} {entity} on for {elapsed_min:.0f}min > {cap:.0f}",
                actuator_class=actuator_class,
                severity="safety",
            ))

    return actions, anomaly_codes
