"""History › Changes (G8): who changed what, folded from the journal. Pure: no Home Assistant.

fold_changes() turns journal events into change rows, newest first:
`target.changed` (a setting), `config.changed` (a saved store section), `plan.*`, and the
calibrations (`calibration.committed`/`reverted`, `pump.calibrated`). `ai.outcome` events are read
only to say how a learner or AI change worked out. Every other kind is left out.
"""

from __future__ import annotations

from datetime import UTC, datetime

from .const import SETPOINT_STEP_SCOPES
from .strategy_model import ENGINE_BOUNDS

PLAN_KINDS = (
    "plan.saved",
    "plan.armed",
    "plan.activated",
    "plan.disarmed",
    "plan.expired",
)
CALIBRATION_KINDS = ("calibration.committed", "calibration.reverted", "pump.calibrated")
# The journal kinds a fold reads (journal_query `kinds`).
KINDS = (
    "target.changed",
    "config.changed",
    *PLAN_KINDS,
    *CALIBRATION_KINDS,
    "ai.outcome",
)
CHANGE_KINDS = ("setpoint", "plan", "recipe", "setup", "calibration", "alerts")
# The store sections history_revert can save again (journal_api.history_revert).
REVERTIBLE_SECTIONS = {
    ("setup", "room"),
    ("site", "supply"),
    ("site", "presets"),
    ("timers", "programs"),
    ("calibration", "probe_user_offsets"),
}
# A learner or AI change is judged after the next lights-on.
TOO_SOON = "Too soon to judge — check after the next lights-on."
GOOD = "Dryback came back to target."
NOT_YET = "No change in dryback yet."
# The writers whose changes carry an outcome and their limits -> limits.writer.
WRITERS = {"learner": "learner", "ai": "brain"}
PUT_BACK = "put back"
# Stores whose one save is journaled into every room it touches, sharing one causation_id.
SITE = ("site", "dashboards")


def _ms(ts) -> int:
    try:
        at = datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return 0
    if at.tzinfo is None:
        at = at.replace(tzinfo=UTC)
    return int(at.timestamp() * 1000)


def _kind(event) -> str:
    """The change kind of a journal event."""
    kind, data = event["kind"], event.get("data") or {}
    if kind == "target.changed":
        detail = (event.get("source") or {}).get("detail") or ""
        if detail.startswith(("preset ", "copy from ")) or "recipe" in detail:
            return "recipe"
        return "setpoint"
    if kind == "config.changed":
        if data.get("section") == "alert_rules":
            return "alerts"
        if data.get("store") == "calibration":
            return "calibration"
        return "setup"
    if kind in PLAN_KINDS:
        return "plan"
    return "calibration"


def _ledger_key(event):
    ledger_id = (event.get("correlation") or {}).get("ledger_id")
    return None if ledger_id is None else (event.get("room_id"), str(ledger_id))


def _outcomes(events) -> dict:
    """{(room_id, ledger_id): [(ts ms, ai.outcome data)]}. An outcome names the controller's ledger row in
    correlation.ledger_id, and so does the AI's own write of the change it judges (setpoint_log, from its claim).
    """
    out: dict = {}
    for event in events:
        key = _ledger_key(event) if event.get("kind") == "ai.outcome" else None
        if key is not None:
            out.setdefault(key, []).append(
                (_ms(event.get("ts")), event.get("data") or {})
            )
    for found in out.values():
        found.sort(key=lambda o: o[0])
    return out


def _outcome(event, outcomes):
    if (event.get("source") or {}).get("actor") not in WRITERS:
        return None
    # A ledger that was damaged starts its ids again: only an outcome at or after the change judges it.
    at = _ms(event.get("ts"))
    found = next(
        (data for ts, data in outcomes.get(_ledger_key(event), ()) if ts >= at), None
    )
    if found is None or not isinstance(found.get("good"), bool):
        return TOO_SOON
    return GOOD if found["good"] else NOT_YET


def _limits(event, key, limits):
    writer = WRITERS.get((event.get("source") or {}).get("actor"))
    if writer is None or event["kind"] != "target.changed":
        return None
    low, high = ENGINE_BOUNDS.get(key, (None, None))
    scope = (limits.get(event.get("room_id")) or {}).get("step_scope")
    return {
        "writer": writer,
        "min": low,
        "max": high,
        "step_scope": (
            scope if scope in SETPOINT_STEP_SCOPES else SETPOINT_STEP_SCOPES[0]
        ),
    }


def _superseded(events) -> set:
    """Ids of the committed calibrations that a later commit or revert of the same probe replaced
    (`events` in time order)."""
    out, later = set(), set()
    for event in reversed(events):
        if event["kind"] not in ("calibration.committed", "calibration.reverted"):
            continue
        probe = (event.get("data") or {}).get("probe")
        if event["kind"] == "calibration.committed" and probe in later:
            out.add(event["id"])
        later.add(probe)
    return out


def _revertible(event, superseded) -> bool:
    kind, data = event["kind"], event.get("data") or {}
    if event.get("outcome") not in (None, "ok"):
        return False
    if kind == "target.changed":
        return (
            data.get("layer", "base") == "base"
            and data.get("old") is not None
            and data.get("new") is not None
            and isinstance(data.get("entity_id"), str)
        )
    if kind == "config.changed":
        return (data.get("store"), data.get("section")) in REVERTIBLE_SECTIONS and (
            data.get("old") is not None
        )
    if kind == "calibration.committed":
        return bool(data.get("applied")) and event["id"] not in superseded
    return False


def _row(event, outcomes, limits, superseded) -> dict:
    kind, data = event["kind"], event.get("data") or {}
    source = event.get("source") or {}
    key = section = reason = None
    scope = "zone:%s" % event["zone"] if event.get("zone") is not None else "room"
    old = new = None
    if kind == "target.changed":
        key, scope = data.get("key"), data.get("scope") or scope
        old, new, reason = data.get("old"), data.get("new"), data.get("reason")
    elif kind == "config.changed":
        section = data.get("section")
        if data.get("store") in SITE:
            scope = "site"
        old, new = data.get("old"), data.get("new")
    elif kind in PLAN_KINDS:
        section, new = "plan", data.get("status")
        reason = data.get("reason") or kind.split(".", 1)[1]
    elif kind == "pump.calibrated":
        section, key = "pump", data.get("pump")
        old, new = data.get("previous_ml_min"), data.get("ml_min")
    else:  # calibration.committed / reverted
        section, key = "calibration", data.get("probe")
        if kind == "calibration.reverted":
            old, new = data.get("reverted_record_id"), data.get("record_id")
            reason = "reverted"
        else:
            old, new = data.get("superseded_record_id"), data.get("record_id")
            reason = data.get("verdict")
    return {
        "id": event["id"],
        "event_id": event["id"],
        "room_id": event.get("room_id"),
        "ts": event["ts"],
        "actor": source.get("actor"),
        "detail": source.get("detail"),
        "user_id": source.get("user_id"),
        "kind": _kind(event),
        "key": key,
        "section": section,
        "scope": scope,
        "old": old,
        "new": new,
        "reason": reason,
        "outcome": _outcome(event, outcomes),
        "limits": _limits(event, key, limits),
        "revertible": _revertible(event, superseded),
        "causation_id": (event.get("correlation") or {}).get("causation_id"),
    }


def fold_changes(events: list[dict], limits: dict[str, dict]) -> list[dict]:
    """The change rows of `events` (journal events, of one room or several), newest first.

    `limits`: {room_id: {step_scope}}, the room's "Max setpoint move applies to" choice; a room
    missing reads as the default. A site change journaled into several rooms (one save, one
    causation_id) is one row. Ordered by `ts`, never `seq`: backfilled rows get later seqs.
    """
    events = sorted(
        (e for e in events if isinstance(e, dict) and e.get("kind") in KINDS),
        key=lambda e: _ms(e.get("ts")),
    )
    outcomes, superseded = _outcomes(events), _superseded(events)
    rows, seen = [], set()
    for event in events:
        if event["kind"] == "ai.outcome":
            continue
        data = event.get("data") or {}
        cause = (event.get("correlation") or {}).get("causation_id")
        if event["kind"] == "config.changed" and cause and data.get("store") in SITE:
            once = (cause, data.get("store"), data.get("section"))
            if once in seen:
                continue
            seen.add(once)
        rows.append(_row(event, outcomes, limits, superseded))
    rows.reverse()
    return rows
