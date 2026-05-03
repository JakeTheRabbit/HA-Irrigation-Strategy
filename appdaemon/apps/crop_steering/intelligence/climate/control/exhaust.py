"""Exhaust controller — emergency + scheduled refresh only.

F1 is sealed under normal operation. The exhaust runs for:
- Emergency: temp > emergency_temp_c OR co2 > emergency_co2_ppm
- Scheduled: optional periodic refresh while lights are on
- Manual: operator override via service call (future)

Watchdog: max_runtime_min hard limit — if exhaust has been on longer
than that, force off and raise an anomaly.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from ..hardware import ExhaustCalibration
from .actions import Action, ActionKind


@dataclass
class ExhaustState:
    is_on: bool = False
    last_on_at: datetime | None = None
    last_off_at: datetime | None = None
    last_scheduled_at: datetime | None = None


def propose_exhaust(
    *,
    current_temp_c: float | None,
    current_co2_ppm: float | None,
    lights_on: bool,
    cal: ExhaustCalibration,
    state: ExhaustState,
    now: datetime | None = None,
) -> list[Action]:
    if not cal.entity:
        return []
    now = now or datetime.utcnow()

    # ── Emergency triggers ────────────────────────────────────────────
    if current_temp_c is not None and current_temp_c > cal.emergency_temp_c:
        if not state.is_on:
            return [Action(
                kind=ActionKind.SWITCH_ON,
                entity=cal.entity,
                reason=f"EMERGENCY: temp {current_temp_c:.1f}°C > {cal.emergency_temp_c:.1f}°C",
                actuator_class="exhaust",
                severity="emergency",
            )]
        return []  # already running for emergency

    if current_co2_ppm is not None and current_co2_ppm > cal.emergency_co2_ppm:
        if not state.is_on:
            return [Action(
                kind=ActionKind.SWITCH_ON,
                entity=cal.entity,
                reason=f"EMERGENCY: CO2 {current_co2_ppm:.0f} ppm > {cal.emergency_co2_ppm:.0f}",
                actuator_class="exhaust",
                severity="emergency",
            )]
        return []

    # ── Watchdog: force off if running too long ──────────────────────
    if state.is_on and state.last_on_at is not None:
        elapsed_min = (now - state.last_on_at).total_seconds() / 60.0
        if elapsed_min > cal.max_runtime_min:
            return [Action(
                kind=ActionKind.SWITCH_OFF,
                entity=cal.entity,
                reason=f"watchdog: exhaust on for {elapsed_min:.1f}min > {cal.max_runtime_min:.0f}",
                actuator_class="exhaust",
                severity="safety",
            )]

    # ── Scheduled refresh (only while lights on) ─────────────────────
    if cal.scheduled_enabled and lights_on:
        if state.is_on:
            # Currently in a scheduled refresh — turn off after duration
            assert state.last_on_at is not None
            elapsed_min = (now - state.last_on_at).total_seconds() / 60.0
            if elapsed_min >= cal.scheduled_duration_min:
                return [Action(
                    kind=ActionKind.SWITCH_OFF,
                    entity=cal.entity,
                    reason=f"scheduled refresh complete ({elapsed_min:.1f}min)",
                    actuator_class="exhaust",
                )]
        else:
            # Should we start a scheduled refresh?
            if state.last_scheduled_at is None:
                state.last_scheduled_at = now - timedelta(minutes=cal.scheduled_period_min)
            since = (now - state.last_scheduled_at).total_seconds() / 60.0
            if since >= cal.scheduled_period_min:
                state.last_scheduled_at = now
                return [Action(
                    kind=ActionKind.SWITCH_ON,
                    entity=cal.entity,
                    reason=f"scheduled refresh ({cal.scheduled_duration_min:.0f}min)",
                    actuator_class="exhaust",
                )]

    # ── Otherwise: ensure off ─────────────────────────────────────────
    if state.is_on and current_temp_c is not None and current_co2_ppm is not None:
        # No longer in emergency, no scheduled refresh → close
        if (current_temp_c <= cal.emergency_temp_c - 1.0 and
                current_co2_ppm <= cal.emergency_co2_ppm - 100):
            return [Action(
                kind=ActionKind.SWITCH_OFF,
                entity=cal.entity,
                reason="emergency cleared",
                actuator_class="exhaust",
            )]

    return []


def apply_action_to_state(state: ExhaustState, action: Action, now: datetime | None = None) -> None:
    now = now or datetime.utcnow()
    if action.kind == ActionKind.SWITCH_ON:
        state.is_on = True
        state.last_on_at = now
    elif action.kind == ActionKind.SWITCH_OFF:
        state.is_on = False
        state.last_off_at = now
