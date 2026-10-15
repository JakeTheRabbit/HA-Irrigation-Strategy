"""The controller's own pass of plan adherence (Controller._watch_plan), under rules: the plan sensor and the
integration's strategy services as a room with a running plan publishes them, a zone held on yesterday's day.

One CS-713 card per episode, the plan line on the brain panel, and not one write: the plan's targets in force are the
integration's, and a number changed by hand is advised, never overwritten.
"""
from datetime import timedelta, timezone

import pytest

import controller
from test_blind_grace import _Clock, clock  # noqa: F401 - the pinned wall clock (lights 10:00-22:00)
from test_room_status import _room

pytestmark = pytest.mark.usefixtures("settings_built_in")

PLAN = "sensor.crop_steering_strategy_plan"
SHOT = "number.crop_steering_zone_1_p2_shot_size"
DAY16 = {"dryback_target": 18.0, "ec_target_p0": 3.0, "ec_target_p1": 3.5, "ec_target_p2": 4.0, "p1_target_vwc": 60.0,
         "p2_vwc_threshold": 34.0, "p2_shot_size": 5.0, "p1_initial_shot_size": 4.0,
         "p3_emergency_vwc_threshold": 25.0, "p3_emergency_shot_size": 3.0}
DAY17 = {**DAY16, "dryback_target": 22.0, "p2_vwc_threshold": 32.0}


def _publish_plan(fake, held=True):
    today = _Clock.now().date()
    row = {"zone_id": 1, "status": "active", "profile_id": "bulk" if held else "finish", "bias": 70,
           "day": 16 if held else 17, "parameters": DAY16 if held else DAY17,
           "applied_day": (today - timedelta(days=1) if held else today).isoformat()}
    if held:
        row["held"] = "Zone 1 VWC is unavailable or stale"
    now = _Clock.now(timezone.utc)
    fake.set_state(PLAN, "active", {
        "room_id": "room:", "snapshot_version": 1, "revision": 7, "enabled": True, "release_legacy": False,
        "updated_at": now.isoformat(), "valid_until": (now + timedelta(seconds=180)).isoformat(),
        "grow_day": today.isoformat(), "zones": [row], "managed_zone_ids": [1], "error": None,
        "degraded_reason": "Zone 1 VWC is unavailable or stale: zone 1 stays on the targets of yesterday" if held
        else None, "degraded_kind": "probe_stale" if held else None, "status": "active"})


def _services(calls):
    today = _Clock.now().date()

    def answer(domain, service, data, timeout=12):
        calls.append((domain, service, dict(data)))
        if service == "strategy_get":
            return 200, {"room_id": "room:", "revision": 7, "status": "active",
                         "plan": {"schema_version": 1, "name": "Autumn run",
                                  "profiles": [{"id": "bulk", "name": "Bulk"}, {"id": "finish", "name": "Finish"}],
                                  "zones": [{"zone_id": 1, "start_date": "2026-09-09",
                                             "schedule": [{"start_day": 1, "end_day": 16, "profile_id": "bulk",
                                                           "bias": 70},
                                                          {"start_day": 17, "end_day": 84, "profile_id": "finish",
                                                           "bias": 70}]}]},
                         "catalog": {"1": {"p2_shot_size": {"entity_ids": [SHOT], "value": 5.0, "step": 0.5}}},
                         "armed_after": None, "disarm_after": None}
        if service == "strategy_preview":
            day = data["date"]
            params, number = (DAY17, 17) if day == today.isoformat() else (DAY16, 16)
            return 200, {"preview": {"date": day, "zones": [{"zone_id": 1, "status": "active", "day": number,
                                                             "parameters": params, "errors": []}]}}
        return 200, None
    return answer


@pytest.fixture
def room(monkeypatch):
    return make_room(monkeypatch)


def make_room(monkeypatch):
    c, fake = _room("on")
    c._start = _Clock.now() - timedelta(hours=2)
    st = c.rooms[0].state[1]
    st.update(phase="P2", last_daily_reset=_Clock.now().date(), last_shot=_Clock.now(),
              last_phase_change=_Clock.now() - timedelta(hours=1))
    calls = []
    monkeypatch.setattr(controller, "ha_service_response", _services(calls))
    fake.set_state(SHOT, "5")
    fake.set_state("number.crop_steering_lights_on_hour", "10")  # the integration's hours, as the rig's option
    fake.set_state("number.crop_steering_lights_off_hour", "22")
    _publish_plan(fake)
    return c, fake, calls


def _plan_cards(fake):
    return [d for dom, svc, d in fake.calls if (dom, svc) == ("persistent_notification", "create")
            and str(d.get("notification_id", "")).startswith("f2_plan_")]


def _writes(fake):
    return [(dom, svc, d) for dom, svc, d in fake.calls if dom in ("number", "input_number", "select")]


def test_a_zone_held_on_yesterday_raises_one_card_and_shows_the_plan_line(room):
    c, fake, calls = room
    c.loop_once(_Clock.now())
    [card] = _plan_cards(fake)
    assert card["notification_id"] == "f2_plan_transition_missed_default_2026-09-25"
    assert "(CS-713)" in card["title"] and "the dryback target from 18 % of the peak to 22 % of the peak" in (
        card["message"])
    assert "Zone 1 VWC is unavailable or stale" in card["message"]
    plan = fake.sets["sensor.crop_steering_jev"][1]["plan"]
    assert plan["status"] == "active" and plan["drifts"][0]["class"] == "transition_missed"
    assert plan["headline"].startswith("Plan: Autumn run · day 16 of 84 (week 3) · today's targets not applied")
    assert [s for _d, s, _x in calls].count("strategy_get") == 1
    # The next passes: the same episode raises no second card, and the plan is not fetched again.
    for minutes in (1, 31, 61):
        _Clock.current += timedelta(minutes=minutes)
        _publish_plan(fake)
        c.loop_once(_Clock.now())
    assert len(_plan_cards(fake)) == 1
    assert [s for _d, s, _x in calls].count("strategy_get") == 1
    assert c.rooms[0]._adherence["alerted"] == {"plan_transition_missed_default_2026-09-25": "2026-09-25"}
    assert _writes(fake) == []  # nothing written, ever


def test_once_the_zone_has_its_day_the_plan_is_on_track(room):
    c, fake, calls = room
    _publish_plan(fake, held=False)
    c.loop_once(_Clock.now())
    assert _plan_cards(fake) == []
    plan = fake.sets["sensor.crop_steering_jev"][1]["plan"]
    assert plan["headline"] == "Plan: Autumn run · day 17 of 84 (week 3) · on track"


def test_a_number_changed_by_hand_is_advised_and_never_written_back(room):
    c, fake, _calls = room
    _publish_plan(fake, held=False)
    c.loop_once(_Clock.now())  # the baseline
    fake.set_state(SHOT, "6")
    _Clock.current += timedelta(minutes=16)
    _publish_plan(fake, held=False)
    c.loop_once(_Clock.now())
    [card] = _plan_cards(fake)
    assert "has no effect" in card["message"] and "(CS-713)" in card["title"]
    assert fake.states[SHOT][0] == "6"  # the operator's value stays
    assert _writes(fake) == []


def test_a_room_with_no_plan_asks_nothing_and_shows_no_line(monkeypatch):
    c, fake = _room("on")
    c._start = _Clock.now() - timedelta(hours=2)
    calls = []
    monkeypatch.setattr(controller, "ha_service_response", _services(calls))
    c.loop_once(_Clock.now())
    assert [s for _d, s, _x in calls if s.startswith("strategy")] == []
    assert fake.sets["sensor.crop_steering_jev"][1]["plan"]["headline"] is None
    assert "_adherence" not in (c._saved_room_blocks.get("default") or {})


def test_a_failed_plan_fetch_is_not_guessed_at(room, monkeypatch):
    c, fake, _calls = room
    monkeypatch.setattr(controller, "ha_service_response", lambda *a, **k: (None, None))
    c.loop_once(_Clock.now())
    assert _plan_cards(fake) == []  # without the plan's own preview, a missed day is not claimed
    assert fake.sets["sensor.crop_steering_jev"][1]["plan"]["drifts"][0]["class"] == "day_behind"


def test_a_grow_light_that_reads_on_at_night_is_said_once(room):
    c, fake, _calls = room
    _publish_plan(fake, held=False)
    state, attrs, _ = fake.ha_get("sensor.crop_steering_engine_config")
    fake.set_state("sensor.crop_steering_engine_config", state, {**attrs, "light_entity": "light.grow"})
    _Clock.current = _Clock.current.replace(hour=23)  # the rig's lights are 10:00-22:00
    fake.set_state("light.grow", "on")
    for minutes in (0, 10, 6, 30):
        _Clock.current += timedelta(minutes=minutes)
        _publish_plan(fake, held=False)
        c.loop_once(_Clock.now())
    cards = [d for d in _plan_cards(fake) if "lights_entity" in d["notification_id"]]
    assert len(cards) == 1 and "reads on but the lights hours say off" in cards[0]["message"]
    assert _writes(fake) == [] and [d for d, s, x in fake.calls if d == "light"] == []  # never switched


def test_a_room_with_no_grow_light_mapped_reads_none(room):
    c, fake, _calls = room
    _publish_plan(fake, held=False)
    c.loop_once(_Clock.now())
    assert not [d for d in _plan_cards(fake) if "lights_entity" in d["notification_id"]]
