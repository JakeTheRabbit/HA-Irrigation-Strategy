"""Plan adherence (plan_adherence.py): is the room running the grow plan its grower chose?

Code compares what the plan expects since lights-on with what the room is doing and says so: one CS-713 card per
episode and a plan line on the brain panel. It reports, it never corrects: no number is written, and a plan is armed,
edited or disarmed only by a person. These drive each detector both ways on a hand-built View, then the controller's
own pass on a fake Home Assistant whose strategy services answer as the integration does.
"""
from datetime import date, datetime, timedelta

import pytest

import plan_adherence as A

NOW = datetime(2026, 10, 1, 9, 0)  # lights 06:00-18:00
TODAY = date(2026, 10, 1)
YESTERDAY = TODAY - timedelta(days=1)
DAY16 = {"p2_shot_size": 5.0, "dryback_target": 18.0, "p2_vwc_threshold": 34.0, "p1_target_vwc": 60.0}
DAY17 = {**DAY16, "dryback_target": 22.0, "p2_vwc_threshold": 32.0}


def _plan(**over):
    plan = {
        "plan": {"schema_version": 1, "name": "Autumn run",
                 "profiles": [{"id": "bulk", "name": "Bulk", "vegetative": {}, "generative": {}},
                              {"id": "finish", "name": "Finish", "vegetative": {}, "generative": {}}],
                 "zones": [{"zone_id": z, "start_date": "2026-09-15",
                            "schedule": [{"start_day": 1, "end_day": 16, "profile_id": "bulk", "bias": 70},
                                         {"start_day": 17, "end_day": 84, "profile_id": "finish", "bias": 70}]}
                           for z in (1, 2)]},
        "catalog": {str(z): {"p2_shot_size": {"entity_ids": [f"number.crop_steering_zone_{z}_p2_shot_size"],
                                              "value": 5.0, "step": 0.5}} for z in (1, 2)},
        "armed_after": None,
    }
    plan.update(over)
    return plan


def _row(z, day=17, params=None, applied=None, status="active", profile="finish", **extra):
    return {"zone_id": z, "day": day, "status": status, "profile_id": profile, "bias": 70,
            "parameters": dict(params or DAY17), "applied_day": (applied or TODAY).isoformat(), **extra}


def view(**over):
    base = dict(
        now=NOW, expected_day=TODAY, uptime_min=600.0, lights_on=True, on_hour=6.0, off_hour=18.0,
        status="active", attrs={"revision": 7, "grow_day": TODAY.isoformat(), "zones": [_row(1), _row(2)]},
        plan=_plan(), plan_age_h=0.5,
        preview={"today": {1: _row(1), 2: _row(2)}, "yesterday": {1: _row(1, 16, DAY16, YESTERDAY, profile="bulk"),
                                                                  2: _row(2, 16, DAY16, YESTERDAY, profile="bulk")}},
        natives={"number.crop_steering_zone_1_p2_shot_size": 5.0, "number.crop_steering_zone_2_p2_shot_size": 5.0},
        steering={1: "generative", 2: "generative"},
        zones={z: {"phase": "P1", "last_phase_change": NOW - timedelta(minutes=20), "last_daily_reset": TODAY,
                   "shots": 2, "p0_wait": 90.0, "p1_shots": 8, "p1_gap": 15.0} for z in (1, 2)},
        titles={1: "zone 1", 2: "zone 2"},
    )
    base.update(over)
    return A.View(**base)


def later(days, **over):
    """The same room `days` grow-days on: every date moves with it."""
    day, now = TODAY + timedelta(days=days), NOW + timedelta(days=days)
    base = view()
    attrs = {**base.attrs, "grow_day": day.isoformat(),
             "zones": [{**r, "applied_day": day.isoformat()} for r in base.attrs["zones"]]}
    zones = {z: {**zs, "last_daily_reset": day, "last_phase_change": now - timedelta(minutes=20)}
             for z, zs in base.zones.items()}
    return view(**{"now": now, "expected_day": day, "attrs": attrs, "zones": zones,
                   "preview": {"today": {r["zone_id"]: r for r in attrs["zones"]}}, **over})


def classes(v, adh=None):
    return [d.cls for d in A.detect(v, A.fresh() if adh is None else adh)]


# ---------------------------------------------------------------- on track
def test_an_active_plan_on_its_day_is_on_track_with_its_name_day_and_week():
    v = view()
    assert classes(v) == []
    assert A.headline(v, []) == "Plan: Autumn run · day 17 of 84 (week 3) · on track"
    zone = A.zone_plan(v, 1)
    assert (zone["day"], zone["week"], zone["of_days"], zone["profile"]) == (17, 3, 84, "Finish")
    assert zone["next_change"] is None


def test_without_a_plan_name_the_profile_names_the_line_and_mixed_profiles_none():
    unnamed = _plan()
    unnamed["plan"].pop("name")
    v = view(plan=unnamed)
    assert A.headline(v, []).startswith("Plan: Finish · day 17")
    v = view(plan=unnamed, attrs={"revision": 7, "grow_day": TODAY.isoformat(),
                                  "zones": [_row(1), _row(2, 16, DAY16, profile="bulk")]})
    assert A.headline(v, []).startswith("Plan · days 16-17 (week 3)")


def test_no_plan_says_nothing_and_the_seed_draft_says_nothing():
    assert A.headline(view(status="none", attrs={}), []) is None
    assert A.headline(view(status="draft", attrs={"revision": 0}), []) is None
    assert classes(view(status="draft", attrs={"revision": 0})) == []


# ---------------------------------------------------------------- D1/D2: today's day not applied
def test_a_zone_held_on_yesterday_whose_day_changes_targets_is_a_missed_transition():
    attrs = {"revision": 7, "grow_day": TODAY.isoformat(), "degraded_kind": "probe_stale",
             "degraded_reason": "Zone 2 VWC is unavailable or stale",
             "zones": [_row(1), _row(2, 16, DAY16, YESTERDAY, profile="bulk", held="Zone 2 VWC is unavailable")]}
    [d] = A.detect(view(attrs=attrs), A.fresh())
    assert d.cls == "transition_missed" and d.alert and d.ask and d.sev == 1
    assert "zone 2" in d.line and "the dryback target from 18 % of the peak to 22 % of the peak" in d.line
    assert d.extra["zones"] == {2: DAY17}
    assert d.suggestions[0].startswith("Fix or unmap the probe the plan waits for")


def test_a_day_that_changes_no_target_is_only_behind_and_raises_nothing():
    attrs = {"revision": 7, "grow_day": YESTERDAY.isoformat(),
             "zones": [_row(1, 16, DAY17, YESTERDAY), _row(2, 16, DAY17, YESTERDAY)]}
    [d] = A.detect(view(attrs=attrs), A.fresh())
    assert d.cls == "day_behind" and not d.alert and not d.ask


def test_a_missed_day_waits_for_lights_on_to_settle_and_for_a_preview():
    attrs = {"revision": 7, "grow_day": YESTERDAY.isoformat(),
             "zones": [_row(1, 16, DAY16, YESTERDAY), _row(2, 16, DAY16, YESTERDAY)]}
    assert classes(view(attrs=attrs, now=datetime(2026, 10, 1, 6, 5))) == []
    assert classes(view(attrs=attrs, preview={})) == ["day_behind"]  # no preview: never guessed
    assert classes(view(attrs=attrs, plan_age_h=7.0)) == ["day_behind"]  # stale plan: not judged


# ---------------------------------------------------------------- D3/D4/D5
def test_an_armed_plan_that_did_not_start_at_its_lights_on():
    plan = _plan(armed_after="2026-10-01T06:00:00")
    attrs = {"revision": 7, "grow_day": None, "zones": [], "degraded_reason": "Zone 1 VWC is unavailable or stale"}
    v = view(status="armed", attrs=attrs, plan=plan, now=datetime(2026, 10, 1, 6, 40))
    assert classes(v) == ["armed_not_started"]
    assert classes(view(status="armed", attrs=attrs, plan=plan, now=datetime(2026, 10, 1, 6, 20))) == []
    later = _plan(armed_after="2026-10-02T06:00:00")
    assert classes(view(status="armed", attrs=attrs, plan=later)) == []
    assert A.headline(view(status="armed", attrs=attrs, plan=later), []).startswith("Plan armed: it starts at")


def test_a_saved_plan_not_armed_for_a_whole_day_is_said_once_per_revision():
    adh = A.fresh()
    attrs = {"revision": 3, "release_legacy": False}
    assert classes(view(status="draft", attrs=attrs), adh) == []  # first seen today
    nxt = later(1, status="draft", attrs=attrs)
    [d] = A.detect(nxt, adh)
    assert d.cls == "saved_not_armed" and d.once and A.due(adh, d, nxt.expected_day)
    A.raised(adh, d, nxt.expected_day)
    fifth = later(5, status="draft", attrs=attrs)
    [again] = A.detect(fifth, adh)
    assert not A.due(adh, again, fifth.expected_day)
    assert classes(view(status="draft", attrs={"revision": 3, "release_legacy": True}), A.fresh()) == []


def test_the_seed_plan_never_counts_as_a_saved_plan():
    seed = _plan()
    seed["plan"]["profiles"] = [{"id": "zone-1-current", "name": "x", "vegetative": {"a": 1}, "generative": {"a": 1}}]
    adh = {**A.fresh(), "draft_seen": {"revision": 1, "first_day": "2026-09-01"}}
    assert classes(view(status="draft", attrs={"revision": 1}, plan=seed), adh) == []


def test_a_plan_ending_is_said_at_three_days_and_again_at_one():
    def at(day):
        attrs = {"revision": 7, "grow_day": TODAY.isoformat(), "zones": [_row(1, day), _row(2, 40)]}
        return A.detect(view(attrs=attrs), A.fresh())
    assert [d.cls for d in at(80)] == []
    [three] = at(81)
    [two] = at(82)
    [one] = at(83)
    assert three.cls == "plan_ending" and three.zone == 1 and three.key == two.key != one.key
    assert "ends after day 84 (in 3 days)" in three.line


# ---------------------------------------------------------------- D7: a hand edit is advised, never overwritten
def test_a_number_changed_by_hand_while_the_plan_runs_is_advised_once_a_photoperiod():
    adh = A.fresh()
    assert classes(view(), adh) == []  # the baseline
    edited = {"number.crop_steering_zone_1_p2_shot_size": 6.0, "number.crop_steering_zone_2_p2_shot_size": 5.0}
    [d] = A.detect(view(natives=edited), adh)
    assert d.cls == "shadowed_edit" and d.zone == 1 and d.ask
    assert "changed to 6 %" in d.line and "keeps it at 5 %" in d.line
    assert d.suggestions[0].startswith("Your change to the maintenance shot size on zone 1 has no effect")
    A.raised(adh, d, TODAY)
    [again] = A.detect(view(natives=edited), adh)
    assert not A.due(adh, again, TODAY)
    tomorrow = later(1, natives=edited)
    [next_day] = A.detect(tomorrow, adh)
    assert A.due(adh, next_day, tomorrow.expected_day)
    assert classes(view(natives=dict(view().natives)), adh) == []  # set back: nothing to say


def test_a_new_revision_starts_a_new_baseline():
    adh = A.fresh()
    A.detect(view(), adh)
    edited = {"number.crop_steering_zone_1_p2_shot_size": 6.0}
    attrs = {**view().attrs, "revision": 8}
    assert classes(view(attrs=attrs, natives=edited), adh) == []
    assert adh["baseline"]["revision"] == 8


# ---------------------------------------------------------------- D8/D9/D10/D11
def test_what_comes_back_at_a_disarm_is_listed_when_it_differs_by_more_than_a_step():
    plan = _plan()
    plan["catalog"]["1"]["p2_shot_size"]["value"] = 7.0
    [d] = A.detect(view(status="disarming", plan=plan), A.fresh())
    assert d.cls == "disarm_return" and "the maintenance shot size on zone 1 5 % -> 7 %" in d.line and d.once
    plan["catalog"]["1"]["p2_shot_size"]["value"] = 5.5
    assert classes(view(status="disarming", plan=plan)) == []


@pytest.mark.parametrize("bias, mode, found", [(70, "vegetative", True), (70, "generative", False),
                                               (30, "generative", True), (50, "vegetative", False)])
def test_a_steering_select_that_disagrees_with_the_plans_bias(bias, mode, found):
    attrs = {"revision": 7, "grow_day": TODAY.isoformat(), "zones": [{**_row(1), "bias": bias}]}
    assert ("steering_disagrees" in classes(view(attrs=attrs, steering={1: mode}))) is found


def test_lights_hours_from_elsewhere_for_half_an_hour():
    since = NOW - timedelta(minutes=31)
    assert classes(view(lights_source="add-on option", lights_bad_since=since)) == ["day_boundary"]
    assert classes(view(lights_source="add-on option", lights_bad_since=NOW - timedelta(minutes=5))) == []
    assert classes(view(status="draft", attrs={"revision": 0}, lights_bad_since=since)) == []


def test_a_light_that_disagrees_with_the_hours_away_from_an_edge():
    v = view(light_state="off", light_since=NOW - timedelta(minutes=16))
    assert classes(v) == ["lights_entity"]
    assert classes(view(light_state="off", light_since=NOW - timedelta(minutes=5))) == []
    near = datetime(2026, 10, 1, 17, 55)
    zones = {z: {**zs, "phase": "P2"} for z, zs in view().zones.items()}
    assert classes(view(now=near, zones=zones, light_state="off", light_since=near - timedelta(minutes=20))) == []


# ---------------------------------------------------------------- tripwires and the long ramp
def test_a_zone_that_did_not_start_its_day_or_stop_for_the_night_is_a_tripwire():
    zones = view().zones
    stuck = {**zones, 1: {**zones[1], "phase": "P3", "last_daily_reset": YESTERDAY}}
    [d] = A.detect(view(zones=stuck), A.fresh())
    assert d.cls == "missed_day_start" and d.alert and not d.ask and "report it" in d.suggestions[0]
    night = datetime(2026, 10, 1, 18, 30)
    late = {**zones, 2: {**zones[2], "phase": "P2"}, 1: {**zones[1], "phase": "P3"}}
    assert classes(view(now=night, lights_on=False, zones=late)) == ["missed_lights_off"]
    fresh_zone = {**zones, 1: {**zones[1], "phase": "P3", "last_daily_reset": None}}
    assert classes(view(zones=fresh_zone)) == []  # a zone with no dated reset yet is never judged


def test_a_zone_in_p0_past_its_maximum_wait_is_a_tripwire_and_a_long_ramp_is_advice():
    zones = view().zones
    p0 = {**zones, 1: {**zones[1], "phase": "P0", "last_phase_change": NOW - timedelta(minutes=106)}}
    assert classes(view(zones=p0)) == ["p0_overrun"]
    p0 = {**zones, 1: {**zones[1], "phase": "P0", "last_phase_change": NOW - timedelta(minutes=100)}}
    assert classes(view(zones=p0)) == []
    long = {**zones, 1: {**zones[1], "last_phase_change": NOW - timedelta(minutes=8 * 15 + 61)}}
    [d] = A.detect(view(zones=long), A.fresh())
    assert d.cls == "p1_long" and not d.alert and d.ask
    longer = {**zones, 1: {**zones[1], "last_phase_change": NOW - timedelta(minutes=2 * (8 * 15 + 60) + 1)}}
    assert A.detect(view(zones=longer), A.fresh())[0].alert


def test_lights_on_equal_to_lights_off_has_no_lights_on_edge():
    v = view(on_hour=6.0, off_hour=6.0)
    assert v.lights_on_at is None
    zones = view().zones
    stuck = {**zones, 1: {**zones[1], "phase": "P3", "last_daily_reset": YESTERDAY}}
    assert "missed_day_start" not in classes(view(on_hour=6.0, off_hour=6.0, zones=stuck))


def test_nothing_is_judged_in_the_first_ten_minutes():
    zones = view().zones
    stuck = {**zones, 1: {**zones[1], "phase": "P3", "last_daily_reset": YESTERDAY}}
    assert classes(view(uptime_min=5.0, zones=stuck)) == []


# ---------------------------------------------------------------- observe, the panel, the record
def test_observe_logs_each_change_with_why_bounded_and_from_this_grow_day():
    adh = A.fresh()
    start = datetime(2026, 10, 1, 6, 0)
    assert A.observe(adh, 1, "P0", start, "lights-on -> P0", start)
    assert not A.observe(adh, 1, "P0", start + timedelta(minutes=1), None, start)
    assert A.observe(adh, 1, "P1", start + timedelta(minutes=90), None, start)
    log = adh["phase_log"]["1"]
    assert log[-1] == {"at": "2026-10-01T07:30", "from": "P0", "to": "P1", "how": "observed"}
    for i in range(30):
        A.observe(adh, 1, "P2" if i % 2 else "P1", start + timedelta(minutes=100 + i), None, start)
    assert len(adh["phase_log"]["1"]) == A.LOG_MAX
    nxt = start + timedelta(days=1)
    A.observe(adh, 1, "P0", nxt, None, nxt)
    assert len(adh["phase_log"]["1"]) == 1


def test_the_panel_names_the_drift_and_its_suggestion():
    edited = {"number.crop_steering_zone_1_p2_shot_size": 6.0, "number.crop_steering_zone_2_p2_shot_size": 5.0}
    adh = A.fresh()
    A.detect(view(), adh)
    v = view(natives=edited)
    drifts = A.detect(v, adh)
    out = A.panel(v, drifts)
    assert out["status"] == "active" and out["in_force_day"] == TODAY.isoformat() and not out["bridged"]
    assert out["headline"].startswith("Plan: Autumn run · day 17 of 84 (week 3) · the maintenance shot size")
    assert out["drifts"][0]["action"] == "advise" and out["drifts"][0]["suggestion"] == drifts[0].suggestions[0]
    assert [z["zone"] for z in out["zones"]] == [1, 2]


def test_the_record_round_trips_and_an_empty_one_is_not_written():
    assert A.dump(A.fresh(), TODAY) is None
    adh = A.load({"alerted": {"old": "2026-01-01", "new": TODAY.isoformat()}, "later": 1})
    out = A.dump(adh, TODAY)
    assert out["alerted"] == {"new": TODAY.isoformat()} and out["later"] == 1
