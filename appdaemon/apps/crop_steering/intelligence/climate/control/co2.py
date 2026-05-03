"""CO2 controller — pulse-injection with adaptive cadence + safety gating.

Best practice:
- Only inject during photoperiod (lights on).
- Wait `lights_on_lead_min` after lights-on (stomata need time to open).
- Hard cap at `hard_max_ppm` regardless of any other condition.
- Pulse: open solenoid for `pulse_on_seconds`, close for
  `pulse_off_seconds`, repeat until target − deadband reached.
- Adaptive: if room responds well (stays above target_minus_deadband
  through the pulse_off period), extend pulse_off — slows injection.
  If room sluggish (drops back below target during pulse_off), shorten.
  Clamped to [pulse_off_min_seconds, pulse_off_max_seconds].
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from ..hardware import CO2Calibration
from .actions import Action, ActionKind


@dataclass
class CO2State:
    phase: str = "off"                       # "on" | "off" | "blocked"
    phase_until: datetime | None = None
    last_lights_on_at: datetime | None = None
    current_pulse_off_seconds: int = 240     # adapts within bounds
    last_ppm_at_pulse_start: float | None = None


def propose_co2(
    *,
    current_ppm: float | None,
    target_ppm: float | None,
    lights_on: bool,
    cal: CO2Calibration,
    state: CO2State,
    now: datetime | None = None,
    deadband_ppm: float = 50.0,
) -> list[Action]:
    if not cal.solenoid:
        return []
    now = now or datetime.utcnow()

    # ── Hard safety cap (highest priority) ────────────────────────────
    if current_ppm is not None and current_ppm > cal.hard_max_ppm:
        return [Action(
            kind=ActionKind.SWITCH_OFF,
            entity=cal.solenoid,
            reason=f"CO2 {current_ppm:.0f} > hard cap {cal.hard_max_ppm:.0f}",
            actuator_class="co2",
            severity="emergency",
        )]

    # ── Lights-off safety: solenoid must be off ───────────────────────
    if not lights_on and cal.off_at_lights_off:
        if state.phase == "on":
            return [Action(
                kind=ActionKind.SWITCH_OFF,
                entity=cal.solenoid,
                reason="lights off — closing solenoid",
                actuator_class="co2",
                severity="safety",
            )]
        return []

    # ── Lights-on lead time ──────────────────────────────────────────
    if state.last_lights_on_at is None:
        state.last_lights_on_at = now if lights_on else None
        return []
    lights_on_for_min = (now - state.last_lights_on_at).total_seconds() / 60.0
    if lights_on_for_min < cal.lights_on_lead_min:
        return []  # stomata still opening

    if current_ppm is None or target_ppm is None:
        return []

    # ── Already near target → close ──────────────────────────────────
    if current_ppm >= target_ppm - deadband_ppm:
        if state.phase == "on":
            return [Action(
                kind=ActionKind.SWITCH_OFF,
                entity=cal.solenoid,
                reason=f"CO2 {current_ppm:.0f} reached target {target_ppm:.0f} − {deadband_ppm:.0f}",
                actuator_class="co2",
            )]
        return []

    # ── Pulse cadence ────────────────────────────────────────────────
    if state.phase_until is not None and now < state.phase_until:
        return []  # still in current phase window

    if state.phase in ("off", "blocked"):
        # Adapt pulse_off based on previous response
        if state.last_ppm_at_pulse_start is not None and current_ppm > 0:
            recovery_ppm = current_ppm - state.last_ppm_at_pulse_start
            if recovery_ppm > 100:
                state.current_pulse_off_seconds = min(
                    int(state.current_pulse_off_seconds * 1.2),
                    cal.pulse_off_max_seconds,
                )
            elif recovery_ppm < 30:
                state.current_pulse_off_seconds = max(
                    int(state.current_pulse_off_seconds * 0.8),
                    cal.pulse_off_min_seconds,
                )
        state.last_ppm_at_pulse_start = current_ppm
        return [Action(
            kind=ActionKind.SWITCH_ON,
            entity=cal.solenoid,
            reason=(
                f"CO2 pulse: current {current_ppm:.0f} < target {target_ppm:.0f} "
                f"(off-period was {state.current_pulse_off_seconds}s)"
            ),
            actuator_class="co2",
        )]
    else:
        # Was on → close
        return [Action(
            kind=ActionKind.SWITCH_OFF,
            entity=cal.solenoid,
            reason=f"end of {cal.pulse_on_seconds}s injection pulse",
            actuator_class="co2",
        )]


def apply_action_to_state(state: CO2State, action: Action, cal: CO2Calibration,
                           now: datetime | None = None) -> None:
    now = now or datetime.utcnow()
    if action.kind == ActionKind.SWITCH_ON:
        state.phase = "on"
        state.phase_until = now + timedelta(seconds=cal.pulse_on_seconds)
    elif action.kind == ActionKind.SWITCH_OFF:
        state.phase = "off"
        state.phase_until = now + timedelta(seconds=state.current_pulse_off_seconds)


def reset_lights_off(state: CO2State) -> None:
    """Coordinator calls this on the lights-off edge."""
    state.last_lights_on_at = None
    state.phase = "blocked"
