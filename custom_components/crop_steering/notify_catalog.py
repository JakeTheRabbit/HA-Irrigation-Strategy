"""The kinds of alert a phone can tick, and which kinds a push belongs to (docs/NOTIFICATIONS.md). PURE.

The mapping lives here and nowhere else: notify_get hands it to the page, so each checkbox shows exactly what
it covers, and notify routes every push by it. tests/test_notify_catalog.py fails when a code in
docs/error-codes.json is in no kind, or when the emergencies are not exactly its critical codes.
"""

from __future__ import annotations


def _codes(text: str) -> tuple[str, ...]:
    return tuple(text.split())


KINDS = (
    {
        "id": "emergency",
        "name": "Emergencies",
        "detail": "Every alert whose severity is critical",
        # Every code whose severity is critical in docs/error-codes.json.
        "codes": _codes(
            "CS-201 CS-202 CS-203 CS-204 CS-207 CS-301 CS-308 CS-310 CS-311 CS-402 "
            "CS-601 CS-606 CS-801"
        ),
        "events": (),
    },
    {
        "id": "hardware",
        "name": "Hardware lockouts",
        "detail": "A pump or valve that did not do what it was told, a hardware hold, a shot "
        "cut, water that isn't reaching a zone, a table that isn't draining and a sump pump that stopped",
        "codes": _codes(
            "CS-301 CS-302 CS-303 CS-304 CS-305 CS-306 CS-307 CS-308 CS-309 CS-310 CS-311 "
            "CS-701"
        ),
        "events": (),
    },
    {
        "id": "sensors",
        "name": "Sensors and drift",
        "detail": "A moisture or EC reading the controller can't use, a zone without a "
        "sensor, and a probe Jev doubts or set aside",
        "codes": _codes("CS-101 CS-102 CS-103 CS-104 CS-603 CS-604 CS-703 CS-704"),
        "events": (),
    },
    {
        "id": "watering",
        "name": "Watering stopped",
        "detail": "Something stopping shots in a room or a zone, the engine not running, and "
        "a room that has watered nothing for a while",
        "codes": _codes(
            "CS-202 CS-203 CS-204 CS-205 CS-206 CS-207 CS-208 CS-209 CS-602"
        ),
        "events": (),
    },
    {
        "id": "phases",
        "name": "Phase changes",
        "detail": "A zone moving P0 → P1 → P2 → P3",
        "codes": (),
        "events": ("phase",),
    },
    {
        "id": "stock",
        "name": "Stock tanks",
        "detail": "Stock tanks running low, and a dose that was not taken off its stock tank",
        "codes": _codes("CS-608 CS-807"),
        "events": (),
    },
    {
        "id": "dosing",
        "name": "Dosing",
        "detail": "A dose or a batch that did not end as it should",
        "codes": _codes("CS-801 CS-802 CS-803 CS-804 CS-805 CS-806"),
        "events": (),
    },
    {
        "id": "jev",
        "name": "Jev",
        "detail": "Jev's advice about a zone, its automatic targets paused, Jev moving a "
        "setting, its calls running low, and a zone on its stricter gate",
        "codes": _codes("CS-404 CS-501 CS-702 CS-705 CS-706 CS-707"),
        "events": ("jev_setpoint",),
    },
    {
        "id": "setup",
        "name": "Setup and settings",
        "detail": "A setup change waiting, a setting missing, out of range or read from "
        "somewhere new, and the grow strategy plan",
        "codes": _codes(
            "CS-201 CS-401 CS-402 CS-403 CS-405 CS-601 CS-605 CS-606 CS-607"
        ),
        "events": (),
    },
)
KIND_IDS = tuple(kind["id"] for kind in KINDS)
EVENTS = {event: kind["id"] for kind in KINDS for event in kind["events"]}
EMERGENCY = KINDS[0]["codes"]

# The integration's own Repairs cards (health.py, stock_api.py) by translation key, with the code each one
# carries in its title (strings.json). tests/test_notify_catalog.py keeps the two in step.
REPAIRS = {
    "kill_switch_missing": "CS-601",
    "engine_offline": "CS-602",
    "zone_no_sensor": "CS-603",
    "fused_sensor_unavailable": "CS-604",
    "entities_moved": "CS-605",
    "strategy_hold": "CS-606",
    "strategy_degraded": "CS-607",
    "stock_low": "CS-608",
}


def kinds_for(code=None, event=None, urgent=False) -> set[str]:
    """The kinds a push belongs to, from its code, its event, or both.

    A code the catalog does not know (a controller newer than this integration) goes to `emergency` when
    the controller marks it urgent (its severity is critical), else to `setup`; so does a push that names
    neither. An event the catalog does not know belongs to no kind.
    """
    unknown = {"emergency" if urgent else "setup"}
    kinds = set()
    if code:
        kinds = {kind["id"] for kind in KINDS if code in kind["codes"]} or unknown
    if event in EVENTS:
        kinds.add(EVENTS[event])
    return kinds if code or event else unknown


def serial() -> list[dict]:
    """The kinds as notify_get answers them: id, name, detail, codes and events, in the page's order."""
    return [
        {
            "id": kind["id"],
            "name": kind["name"],
            "detail": kind["detail"],
            "codes": list(kind["codes"]),
            "events": list(kind["events"]),
        }
        for kind in KINDS
    ]
