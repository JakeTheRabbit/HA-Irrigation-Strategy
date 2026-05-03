"""HVAC controller — bang-bang with hysteresis + calibration + mode switching.

Best practice for compressor-driven HVAC (heat pumps, mini-splits):
- Bang-bang with deadband (NOT PID — kills compressors).
- Settle window: don't issue another setpoint within N min of the last.
- Mode-change cooldown: don't flip cool↔heat more often than M min.
- Calibration offset: command `target + offset` so the room actually
  reaches target despite return-air sensor bias / radiant load.
- IR-blaster insurance: re-issue last-known-good setpoint every refresh
  interval to recover from lost-IR-packet failures.

Pure function: propose(target_c, current_c, hvac_cal, state) → list[Action].
The state object tracks last-command time + last-mode for cooldown logic
and is owned by the coordinator (passed in mutably).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ..hardware import HVACCalibration
from .actions import Action, ActionKind


@dataclass
class HVACState:
    last_command_at: datetime | None = None
    last_setpoint_c: float | None = None
    last_mode: str | None = None        # "cool" | "heat" | "off" | None
    last_mode_change_at: datetime | None = None


def propose_hvac_off(*, cal: HVACCalibration, state: HVACState,
                      reason: str = "force off") -> list[Action]:
    """Emit an explicit OFF mode action. Used by:
    - The coordinator when maintenance mode is engaged.
    - The watchdog when the unit is in heat mode during a high-temp
      emergency (running heat is making things worse).
    - The operator-facing service `crop_steering.hvac_force_off`.
    """
    if state.last_mode == "off":
        return []
    return [Action(
        kind=ActionKind.HVAC_MODE,
        entity=cal.entity,
        value="off",
        reason=reason,
        actuator_class="hvac",
        severity="safety",
    )]


def propose_hvac(
    *,
    target_c: float | None,
    current_c: float | None,
    cal: HVACCalibration,
    state: HVACState,
    now: datetime | None = None,
) -> list[Action]:
    """Return a list of Action(s) the coordinator should consider.

    Returns an empty list (no action) when in deadband, in settle
    window, or in mode-change cooldown — the actuator should keep
    doing what it's doing.
    """
    if target_c is None or current_c is None:
        return []
    now = now or datetime.utcnow()

    # Decide mode based on which side of target we're on.
    desired_mode = "cool" if current_c > target_c else "heat"

    actions: list[Action] = []

    # Mode-change handling: if we want to flip direction, check the
    # cooldown. If cooldown not satisfied, we don't change mode AND
    # we don't issue a setpoint either — the system keeps doing what
    # it was doing until cooldown elapses.
    needs_mode_change = (state.last_mode is not None
                         and state.last_mode != desired_mode)
    if needs_mode_change:
        if state.last_mode_change_at is not None:
            elapsed = (now - state.last_mode_change_at).total_seconds() / 60.0
            if elapsed < cal.mode_change_cooldown_min:
                return []  # too soon to flip; hold current mode
        actions.append(Action(
            kind=ActionKind.HVAC_MODE,
            entity=cal.entity,
            value=desired_mode,
            reason=f"mode flip {state.last_mode} → {desired_mode}",
            actuator_class="hvac",
        ))

    # Compute the calibration-adjusted setpoint to send.
    commanded = cal.commanded_setpoint(target_c=target_c, current_c=current_c)

    # Deadband bypass: if commanded matches target (we're inside
    # deadband per HVACCalibration.commanded_setpoint), no setpoint
    # change unless we're refreshing for IR-insurance.
    in_deadband = abs(current_c - target_c) < cal.deadband_c

    # Settle window: skip new setpoint if recent.
    settle_blocked = (
        state.last_command_at is not None
        and (now - state.last_command_at).total_seconds() / 60.0 < cal.settle_minutes
    )

    # IR-blaster refresh: re-issue last setpoint at refresh_interval_min
    # to recover from any lost IR commands. This is independent of the
    # settle window — the refresh is "insurance", not a control change.
    refresh_due = (
        state.last_command_at is not None
        and state.last_setpoint_c is not None
        and (now - state.last_command_at).total_seconds() / 60.0 >= cal.refresh_interval_min
    )

    if in_deadband and not refresh_due:
        return actions  # may still include the mode flip above

    if settle_blocked and not refresh_due:
        return actions

    # Avoid emitting an identical-value setpoint repeatedly — but always
    # emit on a mode change or when refresh is due.
    same_as_last = (
        state.last_setpoint_c is not None
        and abs(commanded - state.last_setpoint_c) < 0.01
    )
    if same_as_last and not (needs_mode_change or refresh_due):
        return actions

    actions.append(Action(
        kind=ActionKind.HVAC_SETPOINT,
        entity=cal.entity,
        value=round(commanded, 1),
        reason=(
            f"target={target_c:.1f}°C current={current_c:.1f}°C → "
            f"commanded={commanded:.1f}°C (offset applied)"
            + (" [IR refresh]" if refresh_due else "")
        ),
        actuator_class="hvac",
    ))
    return actions


def apply_action_to_state(state: HVACState, action: Action, now: datetime | None = None) -> None:
    """Mutate `state` to reflect that `action` was successfully issued.

    Coordinator calls this after a successful HA service call.
    """
    now = now or datetime.utcnow()
    if action.kind == ActionKind.HVAC_SETPOINT:
        state.last_command_at = now
        state.last_setpoint_c = float(action.value)
    elif action.kind == ActionKind.HVAC_MODE:
        state.last_mode = str(action.value)
        state.last_mode_change_at = now
        # Setting a new mode clears the settle window so the controller
        # can immediately follow up with a setpoint.
        state.last_command_at = None
