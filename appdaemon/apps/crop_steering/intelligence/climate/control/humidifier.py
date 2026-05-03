"""Humidifier controller — bang-bang with min-off + mutex with dehu.

Single ultrasonic on F1; can cycle quickly. Mutual exclusion against
the dehumidifiers is enforced by the coordinator (proposes humid_off
when dehu is engaged).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..hardware import HumidifierCalibration
from .actions import Action, ActionKind


@dataclass
class HumidState:
    is_on: bool = False
    last_off_at: datetime | None = None
    last_on_at: datetime | None = None


def propose_humid(
    *,
    current_rh: float | None,
    target_rh: float | None,
    cal: HumidifierCalibration,
    state: HumidState,
    now: datetime | None = None,
    on_threshold_pct: float = 5.0,
    off_threshold_pct: float = 2.0,
) -> list[Action]:
    if not cal.entity or current_rh is None or target_rh is None:
        return []
    now = now or datetime.utcnow()

    if current_rh < (target_rh - on_threshold_pct):
        if state.is_on:
            return []
        # Respect min-off only on transition to on
        if state.last_off_at is not None:
            elapsed = (now - state.last_off_at).total_seconds()
            if elapsed < cal.min_off_seconds:
                return []
        return [Action(
            kind=ActionKind.SWITCH_ON,
            entity=cal.entity,
            reason=f"RH {current_rh:.1f}% < target {target_rh:.1f}-{on_threshold_pct}",
            actuator_class="humid",
        )]
    elif current_rh > (target_rh + off_threshold_pct):
        if not state.is_on:
            return []
        return [Action(
            kind=ActionKind.SWITCH_OFF,
            entity=cal.entity,
            reason=f"RH {current_rh:.1f}% > target {target_rh:.1f}+{off_threshold_pct}",
            actuator_class="humid",
        )]
    return []


def apply_action_to_state(state: HumidState, action: Action, now: datetime | None = None) -> None:
    now = now or datetime.utcnow()
    if action.kind == ActionKind.SWITCH_ON:
        state.is_on = True
        state.last_on_at = now
    elif action.kind == ActionKind.SWITCH_OFF:
        state.is_on = False
        state.last_off_at = now
