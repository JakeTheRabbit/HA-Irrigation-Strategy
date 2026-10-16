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
        "detail": "Every alert with critical severity, for example a missing kill "
        "switch (CS-601). A new code that the integration does not know comes here "
        "when the controller marks it critical.",
        # Every code whose severity is critical in docs/error-codes.json.
        "codes": _codes(
            "CS-201 CS-202 CS-203 CS-204 CS-207 CS-211 CS-301 CS-308 CS-310 CS-311 "
            "CS-315 CS-402 CS-601 CS-606 CS-801 CS-809 CS-811 CS-901 CS-902"
        ),
        "events": (),
    },
    {
        "id": "hardware",
        "name": "Hardware lockouts",
        "detail": "Alerts about a pump or a valve that did not obey, a hardware "
        "hold, or a shot that the controller cut. Also a zone at its longest shot, "
        "and water that does not reach a zone or goes past its substrate. Also a "
        "table that does not drain. Also a sump pump that stopped, and a pump or "
        "valve that the controller cannot switch. Also rescue shots that do not raise "
        "the moisture, a waste valve that is not closed, and a pump that runs with "
        "every valve shut. Also a sump water balance that does not close.",
        "codes": _codes(
            "CS-301 CS-302 CS-303 CS-304 CS-305 CS-306 CS-307 CS-308 CS-309 CS-310 CS-311 "
            "CS-312 CS-313 CS-314 CS-315 CS-316 CS-317 CS-701 CS-710"
        ),
        "events": (),
    },
    {
        "id": "sensors",
        "name": "Sensors and drift",
        "detail": "Alerts about a VWC or EC reading that the controller cannot use, "
        "a probe set aside for its unit, and a zone without a probe. Also a zone "
        "whose probes disagree or whose primary probe is offline, and a zone that "
        "steers on bulk EC. Also a probe that the AI assistant doubts or sets aside.",
        "codes": _codes(
            "CS-101 CS-102 CS-103 CS-104 CS-502 CS-503 CS-504 CS-505 CS-603 CS-604 CS-703 "
            "CS-704"
        ),
        "events": (),
    },
    {
        "id": "watering",
        "name": "Shots stopped",
        "detail": "Alerts when something stops the shots in a room or a zone. Also a "
        "controller that does not run, a second controller on the room, and a room "
        "with no shots for some time, and shots held for too long. Also a tank at "
        "its minimum, due for a refill or above its full mark, and a batch tank to "
        "refill. Also a waste valve that holds the shots, and a low estimated tank "
        "level.",
        "codes": _codes(
            "CS-202 CS-203 CS-204 CS-205 CS-206 CS-207 CS-208 CS-209 CS-210 CS-211 CS-316 "
            "CS-602 CS-609 CS-901 CS-902 CS-903 CS-904 CS-905 CS-906"
        ),
        "events": (),
    },
    {
        "id": "phases",
        "name": "Phase changes",
        "detail": "A message each time that a zone moves from one phase to the next: "
        "P0, P1, P2, P3.",
        "codes": (),
        "events": ("phase",),
    },
    {
        "id": "vitals",
        "name": "Vitals",
        "detail": "The regular report of the controller on every zone: VWC, EC and "
        "water today. While the predictions switch of the room is on, the report "
        "also tells what each zone does next.",
        "codes": (),
        "events": ("vitals",),
    },
    {
        "id": "stock",
        "name": "Stock tanks",
        "detail": "Alerts for stock tanks that are low, and for a dose that was not "
        "taken off its stock tank.",
        "codes": _codes("CS-608 CS-807"),
        "events": (),
    },
    {
        "id": "dosing",
        "name": "Dosing",
        "detail": "Alerts for a dose or a batch that did not end correctly, and for "
        "a batch with its EC or pH outside its band. Also pH auto-correct, and the "
        "light dimmed on dry substrate.",
        "codes": _codes(
            "CS-801 CS-802 CS-803 CS-804 CS-805 CS-806 CS-808 CS-809 CS-810 CS-811"
        ),
        "events": (),
    },
    {
        "id": "jev",
        "name": "AI assistant",
        "detail": "Messages from the AI assistant: its advice about a zone, a "
        "setting that it moves, and a pause of its automatic targets. Also low "
        "calls, a zone on its stricter gate, a spent AI budget, a refused key and "
        "the removed first AI route. Also its feed proposals, and the grow plan "
        "state of the room.",
        "codes": _codes(
            "CS-404 CS-501 CS-702 CS-705 CS-706 CS-707 CS-708 CS-709 CS-711 CS-712 CS-713"
        ),
        "events": ("jev_setpoint",),
    },
    {
        "id": "setup",
        "name": "Setup and settings",
        "detail": "Alerts about a setup change that waits, and a setting that is "
        "missing, out of range or read from a new place. Also the grow plan, and an "
        "Engine Enabled switch that does not stop water. A push with no code or an "
        "unknown code that is not critical also comes here.",
        "codes": _codes(
            "CS-201 CS-401 CS-402 CS-403 CS-405 CS-601 CS-605 CS-606 CS-607 CS-610 CS-611 "
            "CS-713"
        ),
        "events": (),
    },
)
KIND_IDS = tuple(kind["id"] for kind in KINDS)
EVENTS = {event: kind["id"] for kind in KINDS for event in kind["events"]}
EMERGENCY = KINDS[0]["codes"]
# Every code whose severity is info in docs/error-codes.json: a digest lists them apart from the warnings.
INFO = _codes("CS-205 CS-305 CS-403 CS-501 CS-702 CS-705 CS-711 CS-712 CS-906")

# The integration's own Repairs cards (health.py, stock_api.py, bounds.py) by translation key, with the code each one
# carries in its title (strings.json). tests/test_notify_catalog.py keeps the two in step.
REPAIRS = {
    "kill_switch_missing": "CS-601",
    "engine_offline": "CS-602",
    "zone_no_sensor": "CS-603",
    "fused_sensor_unavailable": "CS-604",
    "entities_moved": "CS-605",
    "max_run_latch": "CS-312",
    "strategy_hold": "CS-606",
    "strategy_degraded": "CS-607",
    "stock_low": "CS-608",
    "engine_switch_not_gate": "CS-610",
    "outside_zone_bounds": "CS-611",
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
