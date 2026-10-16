"""The envelope's catch_up branch (envelope._admit_catch_up): the only thing the plan task can ever cause.

Today's plan day, the plan's own previewed values, applied by the controller while a stale probe holds the plan's
day. Each rule refuses on its own, and only the clean case is admitted.
"""
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from brain.envelope import Directive, admit
from brain.plan_task import PlanContext

NOW = datetime(2026, 10, 1, 9, 0)  # lights 06:00-18:00
DAY16 = {"dryback_target": 18.0, "ec_target_p0": 3.0, "ec_target_p1": 3.5, "ec_target_p2": 4.0, "p1_target_vwc": 60.0,
         "p2_vwc_threshold": 34.0, "p2_shot_size": 5.0, "p1_initial_shot_size": 4.0,
         "p3_emergency_vwc_threshold": 25.0, "p3_emergency_shot_size": 3.0}
DAY17 = {**DAY16, "dryback_target": 22.0, "p2_vwc_threshold": 32.0}


def clean():
    return PlanContext(
        now=NOW, status="active", required=True, error=None, managed=(1, 2), room_zones=(1, 2), revision=7,
        expected_day="2026-10-01", in_force_days={1: "2026-10-01", 2: "2026-09-30"},
        parameters={1: DAY17, 2: DAY16},
        preview={1: {"status": "active", "errors": [], "parameters": DAY17},
                 2: {"status": "active", "errors": [], "parameters": DAY17}},
        degraded_kind="probe_stale", degraded_since=datetime(2026, 10, 1, 6, 0, 30), lights_on=True,
        lights_on_at=datetime(2026, 10, 1, 6, 0), lights_off_at=datetime(2026, 10, 1, 18, 0))


def directive(**over):
    value = {"day": "2026-10-01", "revision": 7, "zones": {2: dict(DAY17)}}
    value.update(over)
    return Directive("plan", "catch_up", value, "keep_yesterday: no", NOW + timedelta(minutes=45))


def test_the_clean_case_is_admitted():
    ok, why = admit(directive(), clean())
    assert ok, why


@pytest.mark.parametrize("change, d, words", [
    ({}, Directive("plan", "catch_up", {"day": "2026-10-01", "revision": 7, "zones": {2: DAY17}}, "w",
                   NOW - timedelta(minutes=1)), "expired"),
    ({"status": "armed"}, None, "not active"),
    ({"error": "Strategy snapshot is stale"}, None, "not active"),
    ({"managed": (1,)}, None, "zones are not the room's"),
    ({"revision": 8}, None, "plan changed"),
    ({"expected_day": "2026-10-02"}, None, "not today's"),
    ({"in_force_days": {1: "2026-10-01", 2: "2026-10-01"}}, None, "already on today's"),
    ({"degraded_kind": "heartbeat"}, None, "not held by a stale probe"),
    ({"degraded_kind": None}, None, "not held by a stale probe"),
    ({"degraded_since": datetime(2026, 10, 1, 8, 45)}, None, "less than 30 min"),
    ({"preview": {1: {"status": "active", "errors": [], "parameters": DAY17},
                  2: {"status": "complete", "errors": [], "parameters": {}}}}, None, "not active and clean"),
    ({}, directive(zones={2: {**DAY17, "p2_shot_size": 9.0}}), "not the plan's own preview"),
    ({"parameters": {1: DAY17, 2: DAY17}}, None, "changes nothing"),
    ({"lights_on": False}, None, "never at night"),
    ({"now": datetime(2026, 10, 1, 6, 5), "degraded_since": datetime(2026, 10, 1, 5, 0)}, None, "less than 30"),
    ({"now": datetime(2026, 10, 1, 15, 30)}, None, "of lights-off"),
    ({"busy": True}, None, "shot is in flight"),
    ({"room_hold": "the kill switch is off"}, None, "room is held"),
    ({"health": "impaired"}, None, "too old"),
    ({"no_touch": True}, None, "no-touch"),
    ({"cooldown_until": NOW + timedelta(days=6)}, None, "resting"),
    ({"bridge_day": "2026-10-01"}, None, "once this photoperiod"),
])
def test_each_rule_refuses_on_its_own(change, d, words):
    ctx = replace(clean(), **change)
    d = d or directive()
    if "now" in change:
        d = Directive(d.judge, d.kind, d.value, d.why, change["now"] + timedelta(minutes=45))
    ok, why = admit(d, ctx)
    assert not ok and words in why, why


def test_bad_bands_in_the_preview_are_refused():
    bad = {**DAY17, "p2_vwc_threshold": 26.0}  # within 3 points of the rescue floor
    ctx = clean()
    ctx.preview[2] = {"status": "active", "errors": [], "parameters": bad}
    ok, why = admit(directive(zones={2: bad}), ctx)
    assert not ok and "zone 2" in why


def test_a_zone_judges_context_never_reaches_it():
    ok, why = admit(directive(), type("Ctx", (), {"now": NOW, "snap": None, "params": None})())
    assert not ok
