"""Coordinator — Tier 3 supervisory logic.

Gathers proposals from per-actuator controllers, applies cross-actuator
rules, and produces the final ordered list of Actions to dispatch.

Cross-actuator rules:
1. Watchdog (Tier 4) safety actions ALWAYS take precedence.
2. Mutual exclusion between dehumidifier and humidifier — if both
   are proposed, dehu wins (over-dry is recoverable; over-wet kills
   buds).
3. AC↔dehu cooperation: if AC is actively cooling AND temp is also
   high, defer dehu staging — AC condensing already removes water.
4. Maintenance mode: if `input_boolean.gw_maintenance_mode` is on,
   filter out everything except watchdog actions.
5. Anomaly suppression: if `climate_emergency_temp` or
   `climate_emergency_co2` is in the active anomaly set, halt
   non-safety actions.
"""
from __future__ import annotations

from typing import Any

from .actions import Action, ActionKind


def resolve_proposals(
    *,
    proposals: dict[str, list[Action]],   # actuator_class → proposals
    safety_actions: list[Action],
    maintenance_mode: bool,
    active_anomalies: set[str] | None = None,
    ac_is_cooling: bool = False,
    temp_above_target: bool = False,
) -> list[Action]:
    """Return ordered list of actions to dispatch, with reasons annotated."""
    active_anomalies = active_anomalies or set()
    final: list[Action] = []

    # ── Tier 4 ALWAYS wins ────────────────────────────────────────────
    final.extend(safety_actions)

    if maintenance_mode:
        # Operator has full authority; we only enforce safety.
        return final

    in_emergency = bool(
        {"climate_emergency_temp", "climate_emergency_co2"} & active_anomalies
    )

    dehu_proposals = list(proposals.get("dehu", []))
    humid_proposals = list(proposals.get("humid", []))
    co2_proposals = list(proposals.get("co2", []))
    hvac_proposals = list(proposals.get("hvac", []))
    exhaust_proposals = list(proposals.get("exhaust", []))

    # ── Mutual exclusion: dehu wins over humid on conflict ────────────
    has_dehu_on = any(p.kind == ActionKind.SWITCH_ON for p in dehu_proposals)
    has_humid_on = any(p.kind == ActionKind.SWITCH_ON for p in humid_proposals)
    if has_dehu_on and has_humid_on:
        # Drop the humidifier ON — coordinator could also issue an
        # explicit OFF, but with min-off respected it'll just hold off.
        humid_proposals = [p for p in humid_proposals if p.kind != ActionKind.SWITCH_ON]

    # ── AC ↔ dehu cooperation ─────────────────────────────────────────
    # If the AC is already cooling AND the room is hot, the AC is doing
    # double duty (cooling + condensing). Defer staging more dehu so
    # we don't over-dry while temp hasn't even settled.
    if ac_is_cooling and temp_above_target:
        # Allow lead dehu ON, but suppress staging the lag.
        # Lag is identified via the `extras["role"] == "lag"` field.
        deferred = []
        kept = []
        for p in dehu_proposals:
            if p.kind == ActionKind.SWITCH_ON and p.extras.get("role") == "lag":
                deferred.append(p)
            else:
                kept.append(p)
        if deferred:
            kept.append(Action(
                kind=ActionKind.NOOP,
                entity="",
                reason=(
                    "deferring lag dehu — AC already cooling+condensing while "
                    "temp above target; revisit next tick"
                ),
                actuator_class="coordinator",
            ))
        dehu_proposals = kept

    # ── Emergency: suppress non-safety actions ────────────────────────
    if in_emergency:
        # Keep only safety/emergency severity proposals; drop normal control.
        def _keep(a: Action) -> bool:
            return a.severity in ("safety", "emergency")
        dehu_proposals = [a for a in dehu_proposals if _keep(a)]
        humid_proposals = [a for a in humid_proposals if _keep(a)]
        co2_proposals = [a for a in co2_proposals if _keep(a)]
        hvac_proposals = [a for a in hvac_proposals if _keep(a)]
        # Exhaust: emergency triggers add their own safety actions; keep all.

    # Order: HVAC mode first, HVAC setpoint, then exhaust, then dehu,
    # then humid, then co2. (Dehu before humid in case both somehow
    # made it through.)
    final.extend([a for a in hvac_proposals if a.kind == ActionKind.HVAC_MODE])
    final.extend([a for a in hvac_proposals if a.kind == ActionKind.HVAC_SETPOINT])
    final.extend(exhaust_proposals)
    final.extend(dehu_proposals)
    final.extend(humid_proposals)
    final.extend(co2_proposals)

    # Drop NOOPs for dispatch (they're informational only)
    return [a for a in final if a.kind != ActionKind.NOOP]
