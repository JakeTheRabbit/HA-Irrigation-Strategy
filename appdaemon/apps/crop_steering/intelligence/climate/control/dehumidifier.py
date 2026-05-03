"""Dehumidifier controller — staged with lead-lag rotation.

F1 hardware reality:
- 2 dehu units, each driven by wet-tip contactors with built-in 2-min
  hardware cooldown. Software does not enforce min_off — the contactor
  hardware does.
- 4 relays total = 2 dehus × 2 relays each (run + fan). We treat the
  pair as a single logical "dehu" actuator.

Best practice for staged dehumidification:
- Lead unit fires when RH > target + on_threshold for `demand_persistence`.
- Lag unit fires only if RH still high after `stage_persistence_min`.
- Both turn off when RH < target - off_threshold (with the lag turning
  off slightly before the lead, to keep load on the lead unit until
  it's clear demand is gone).
- Lead-lag rotation: at the start of every `rotation_period_days`,
  swap which unit is "lead" so wear evens across the units.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ..hardware import DehumidifierCalibration
from .actions import Action, ActionKind


@dataclass
class DehuUnitState:
    name: str
    is_on: bool = False
    last_on_at: datetime | None = None
    last_off_at: datetime | None = None
    cumulative_runtime_s: float = 0.0


@dataclass
class DehuState:
    units: dict[str, DehuUnitState] = field(default_factory=dict)
    lead_unit_name: str | None = None
    last_rotation_at: datetime | None = None
    demand_started_at: datetime | None = None
    last_lag_engaged_at: datetime | None = None


def propose_dehu(
    *,
    current_rh: float | None,
    target_rh: float | None,
    cal: DehumidifierCalibration,
    state: DehuState,
    now: datetime | None = None,
    on_threshold_pct: float = 5.0,
    off_threshold_pct: float = 2.0,
    demand_persistence_min: float = 3.0,
) -> list[Action]:
    """Propose stage on/off actions.

    Returns a list of Action — typically empty (no change), or one
    SWITCH_ON/SWITCH_OFF per relay of the unit being staged.
    """
    if not cal.units:
        return []
    now = now or datetime.utcnow()

    # ── Initialise state on first call ────────────────────────────────
    for unit in cal.units:
        state.units.setdefault(unit["name"], DehuUnitState(name=unit["name"]))
    if state.lead_unit_name is None:
        state.lead_unit_name = cal.units[0]["name"]
        state.last_rotation_at = now

    # ── Lead-lag rotation ─────────────────────────────────────────────
    if state.last_rotation_at is not None:
        elapsed = (now - state.last_rotation_at).total_seconds() / 86400.0
        if elapsed >= cal.rotation_period_days and len(cal.units) >= 2:
            current_idx = next(
                (i for i, u in enumerate(cal.units) if u["name"] == state.lead_unit_name),
                0,
            )
            new_idx = (current_idx + 1) % len(cal.units)
            state.lead_unit_name = cal.units[new_idx]["name"]
            state.last_rotation_at = now

    # ── No data → no action ──────────────────────────────────────────
    if current_rh is None or target_rh is None:
        return []

    delta_high = current_rh - (target_rh + on_threshold_pct)
    delta_low = (target_rh - off_threshold_pct) - current_rh

    actions: list[Action] = []

    if delta_high > 0:
        # Demand: turn on lead first, then lag if persistent
        if state.demand_started_at is None:
            state.demand_started_at = now
        demand_age_min = (now - state.demand_started_at).total_seconds() / 60.0

        lead_unit = _unit_by_name(cal, state.lead_unit_name)
        lag_unit = _other_unit(cal, state.lead_unit_name)

        # Stage 1: lead unit
        if demand_age_min >= demand_persistence_min:
            lead_state = state.units[state.lead_unit_name]
            if not lead_state.is_on:
                actions.extend(_turn_unit_on(lead_unit, "lead", reason=(
                    f"RH {current_rh:.1f}% > target {target_rh:.1f}+{on_threshold_pct} "
                    f"for {demand_age_min:.1f}min — staging lead"
                )))

        # Stage 2: lag unit, only after stage_persistence_min more
        if demand_age_min >= (demand_persistence_min + cal.stage_persistence_min):
            lag_state = state.units[lag_unit["name"]]
            if not lag_state.is_on:
                actions.extend(_turn_unit_on(lag_unit, "lag", reason=(
                    f"RH still {current_rh:.1f}% after {demand_age_min:.1f}min — staging lag"
                )))
                state.last_lag_engaged_at = now

    elif delta_low > 0:
        # Demand satisfied: clear timer + stage off lag first, then lead
        state.demand_started_at = None
        lag_unit = _other_unit(cal, state.lead_unit_name)
        lead_unit = _unit_by_name(cal, state.lead_unit_name)

        lag_state = state.units[lag_unit["name"]]
        if lag_state.is_on:
            actions.extend(_turn_unit_off(lag_unit, "lag", reason=(
                f"RH {current_rh:.1f}% < target {target_rh:.1f}-{off_threshold_pct} — releasing lag"
            )))
        else:
            lead_state = state.units[state.lead_unit_name]
            if lead_state.is_on:
                actions.extend(_turn_unit_off(lead_unit, "lead", reason=(
                    f"RH {current_rh:.1f}% < target {target_rh:.1f}-{off_threshold_pct} — releasing lead"
                )))

    else:
        # In hysteresis band: hold whatever we're doing, but reset
        # demand timer so we don't immediately stage on a one-tick spike.
        state.demand_started_at = None

    return actions


def _turn_unit_on(unit: dict, role: str, reason: str) -> list[Action]:
    return [Action(
        kind=ActionKind.SWITCH_ON,
        entity=relay,
        reason=f"{unit['name']} ({role}): {reason}",
        actuator_class="dehu",
        extras={"unit": unit["name"], "role": role, "relay_index": i},
    ) for i, relay in enumerate(unit["relays"])]


def _turn_unit_off(unit: dict, role: str, reason: str) -> list[Action]:
    return [Action(
        kind=ActionKind.SWITCH_OFF,
        entity=relay,
        reason=f"{unit['name']} ({role}): {reason}",
        actuator_class="dehu",
        extras={"unit": unit["name"], "role": role, "relay_index": i},
    ) for i, relay in enumerate(unit["relays"])]


def _unit_by_name(cal: DehumidifierCalibration, name: str | None) -> dict:
    if name is None:
        return cal.units[0]
    return next((u for u in cal.units if u["name"] == name), cal.units[0])


def _other_unit(cal: DehumidifierCalibration, lead_name: str | None) -> dict:
    if len(cal.units) < 2:
        return cal.units[0]
    return next((u for u in cal.units if u["name"] != lead_name), cal.units[0])


def apply_action_to_state(state: DehuState, action: Action, now: datetime | None = None) -> None:
    """Mutate state to reflect a successfully-issued action."""
    now = now or datetime.utcnow()
    unit_name = action.extras.get("unit")
    if unit_name is None:
        return
    unit_state = state.units.get(unit_name)
    if unit_state is None:
        return
    if action.kind == ActionKind.SWITCH_ON:
        unit_state.is_on = True
        unit_state.last_on_at = now
    elif action.kind == ActionKind.SWITCH_OFF:
        # Track runtime for wear-leveling diagnostics.
        if unit_state.last_on_at is not None:
            unit_state.cumulative_runtime_s += (now - unit_state.last_on_at).total_seconds()
        unit_state.is_on = False
        unit_state.last_off_at = now
