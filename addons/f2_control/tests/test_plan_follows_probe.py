"""The plan follows the probe (plan_follow.py, controller._plan_follow).

F1, 9 Nov 2026: a reseated probe read about 15 points lower (peaks 76 -> about 53). The armed plan kept a P1
target of 61 and a P2 threshold of 54 the zone could never reach, and it was overwatered for 10 days. Now, once a
grow-day after the ramp, a zone whose peaks have not agreed with its plan for 3 clean grow-days gets a VWC offset on
the plan (crop_steering.strategy_zone_offset), at most 3 points a grow-day, read back and told (CS-714).
"""
from datetime import datetime

import pytest

import controller
import plan_follow as F
from test_controller import _build, _desc

pytestmark = pytest.mark.usefixtures("settings_built_in")

NOW = datetime(2026, 11, 9, 15, 0, 0)
PLAN = "sensor.crop_steering_strategy_plan"


def _days(*peaks):
    return [{"day": f"2026-11-0{i + 1}", "peak": p} for i, p in enumerate(peaks)]


# ------------------------------------------------------------------ the rule (pure)
def test_an_unreachable_p1_target_moves_the_offset_down_by_at_most_three_points():
    got = F.decide(_days(53, 52.5, 53.4), p1=61, fc=64, base_fc=64, offset=0)
    assert got == {"offset": -3.0, "why": "unreachable", "median": 53, "goal": -10.0, "peaks": [53, 52.5, 53.4]}
    # the next grow-day, judged on the plan as it is then, moves on towards the goal
    assert F.decide(_days(53, 52.5, 53.4), p1=58, fc=61, base_fc=64, offset=-3)["offset"] == -6.0
    # within reach (55 - 53.4 is under 4): left alone
    assert F.decide(_days(53, 52.5, 53.4), p1=55, fc=58, base_fc=64, offset=-6) is None


def test_peaks_over_field_capacity_move_the_offset_up():
    got = F.decide(_days(70, 71, 69.5), p1=61, fc=64, base_fc=64, offset=0)
    assert (got["why"], got["offset"], got["goal"]) == ("overshoot", 3.0, 7.0)
    # a small goal is reached in one step
    assert F.decide(_days(68, 68, 68), p1=61, fc=64, base_fc=64, offset=3)["offset"] == 5.0


def test_three_days_must_all_agree():
    assert F.decide(_days(53, 53), p1=61, fc=64, base_fc=64, offset=0) is None
    assert F.decide(_days(53, 58, 53), p1=61, fc=64, base_fc=64, offset=0) is None  # one day within 4 points
    assert F.decide(_days(70, 66, 70), p1=61, fc=64, base_fc=64, offset=0) is None  # one day within 3 over FC


def test_the_offset_never_leaves_twenty_points():
    got = F.decide(_days(30, 30, 30), p1=61, fc=64, base_fc=64, offset=-19)
    assert got["offset"] == -20.0
    assert F.decide(_days(30, 30, 30), p1=44, fc=47, base_fc=64, offset=-20) is None


def test_a_step_change_or_a_day_without_a_peak_starts_the_count_again():
    rec = F.fresh()
    for day, peak in (("a", 76), ("b", 75)):
        F.close_day(rec, day, peak)
    F.reading(rec, 75.0, 0)
    F.reading(rec, 0.0, 60)  # the probe pulled out
    F.close_day(rec, "c", 74)
    assert rec["days"] == []
    F.reading(rec, 70.0, 120)
    F.blind(rec)
    F.reading(rec, 55.0, 4000)  # back after a gap, 15 points lower
    F.close_day(rec, "d", 55)
    assert rec["days"] == []
    for day in "efg":
        F.reading(rec, 53.0, 5000)
        F.close_day(rec, day, 53)
    assert [d["day"] for d in rec["days"]] == ["e", "f", "g"]
    F.close_day(rec, "h", None)  # blind all day
    assert rec["days"] == []


def test_a_slow_rise_is_not_a_step_change():
    rec = F.fresh()
    F.reading(rec, 50.0, 0)
    F.reading(rec, 61.0, 3600)  # 11 points over an hour of ramp shots, no gap
    assert rec["step"] is False


def test_a_saved_record_is_restored_or_made_fresh():
    assert F.restore(None) == F.fresh()
    assert F.restore({"days": "x", "step": "yes"}) == F.fresh()
    saved = {"days": _days(53, 52, 54, 55), "step": True, "last": [53.0, 1.0], "gap": False, "checked": "2026-11-08"}
    out = F.restore(saved)
    assert [d["peak"] for d in out["days"]] == [52, 54, 55] and out["step"] and out["checked"] == "2026-11-08"


# ------------------------------------------------------------------ the controller
def _rig(offset=0.0, auto="on", power=None, no_touch="Off", status="active", held=None, phase="P2", days=(53, 52.5, 53.4)):
    states = {
        "sensor.crop_steering_engine_config": ("ok", _desc()),
        "sensor.crop_steering_vwc_zone_1": ("53", {}),
        "switch.crop_steering_auto_setpoints": (auto, {}),
        "select.crop_steering_ai_no_touch": (no_touch, {"since": NOW.astimezone().isoformat()}),
    }
    if power is not None:
        states["switch.crop_steering_ai_power_set_targets_from_achievable"] = (power, {})
    c, fake = _build({"num_zones": 1}, states=states)
    room = c.rooms[0]
    day = c._grow_day_start(room, NOW).isoformat()
    row = {"zone_id": 1, "status": "active", "applied_day": day, "vwc_offset": offset,
           "parameters": {"p1_target_vwc": 61 + offset, "field_capacity": 64 + offset,
                          "p2_vwc_threshold": 54 + offset, "p3_emergency_vwc_threshold": 40 + offset},
           "vwc_base": {"p1_target_vwc": 61, "field_capacity": 64, "p2_vwc_threshold": 54,
                        "p3_emergency_vwc_threshold": 40}}
    if held:
        row["held"] = held
    attrs = {"grow_day": day, "zones": [row]}
    fake.set_state(PLAN, status, attrs)
    room._strategy_raw = (status, attrs)
    room.strategy_snapshot = {"required": True, "error": None}
    st = room.state[1]
    st["phase"] = phase
    st["plan_follow"]["days"] = _days(*days)

    def offset_service(data, timeout):  # the integration's answer: the plan sensor shows the new offset
        new = dict(row, vwc_offset=data["offset"],
                   parameters={k: v - offset + data["offset"] for k, v in row["parameters"].items()})
        fake.set_state(PLAN, status, dict(attrs, zones=[new]))
        return 200, {"offsets": {"1": data["offset"]}}

    fake.responses[("crop_steering", "strategy_zone_offset")] = offset_service
    return c, fake, room, st


def _offset_calls(fake):
    return [d for dom, svc, d in fake.calls if (dom, svc) == ("crop_steering", "strategy_zone_offset")]


def _cards(fake):
    return [d for dom, svc, d in fake.calls if (dom, svc) == ("persistent_notification", "create")]


def test_the_controller_moves_the_offset_reads_it_back_and_says_so():
    c, fake, room, st = _rig()
    assert c._plan_follow(room, 1, st, NOW) is True
    assert _offset_calls(fake) == [{"room_id": "room:", "zone_id": 1, "offset": -3.0,
                                    "reason": "P1 target out of reach: peaks 53, 52.5, 53.4% on the last 3 grow-days"}]
    card = _cards(fake)[-1]
    assert "(CS-714)" in card["title"]
    assert "from +0 to -3 points" in card["message"] and "53, 52.5, 53.4%" in card["message"]
    assert "The P1 target is now 58%." in card["message"]
    # once a grow-day
    assert c._plan_follow(room, 1, st, NOW.replace(hour=18)) is False
    assert len(_offset_calls(fake)) == 1


def test_an_offset_that_did_not_land_raises_no_card():
    c, fake, room, st = _rig()
    fake.responses[("crop_steering", "strategy_zone_offset")] = lambda data, timeout: (400, None)
    assert c._plan_follow(room, 1, st, NOW) is False
    assert len(_offset_calls(fake)) == 1 and not [x for x in _cards(fake) if "CS-714" in x["title"]]


def test_the_ai_power_alone_is_enough_and_neither_switch_means_nothing():
    c, fake, room, st = _rig(auto="off", power="on")
    assert c._plan_follow(room, 1, st, NOW) is True
    c, fake, room, st = _rig(auto="off", power="off")
    assert c._plan_follow(room, 1, st, NOW) is False
    assert _offset_calls(fake) == []


def test_pause_ai_changes_stops_it():
    assert "1 h" in controller.NO_TOUCH_HOURS
    c, fake, room, st = _rig(no_touch="1 h")
    assert c._plan_follow(room, 1, st, NOW) is False
    assert _offset_calls(fake) == []


@pytest.mark.parametrize("kwargs", [
    {"held": "Zone 1 VWC is unavailable or stale"},  # the probe is stale: the plan holds the zone
    {"status": "armed"},  # not running yet
    {"phase": "P1"},  # the ramp has not ended
    {"days": (53, 52.5)},  # only two clean grow-days
    {"days": (53, 59, 53)},  # one day within reach
])
def test_it_waits(kwargs):
    c, fake, room, st = _rig(**kwargs)
    assert c._plan_follow(room, 1, st, NOW) is False
    assert _offset_calls(fake) == []


def test_a_blind_zone_is_never_followed():
    """A zone with no trusted reading this pass takes the blind path and never reaches the rule: its next reading
    is compared across the gap, so a probe that comes back 15 points lower starts the count again."""
    c, fake, room, st = _rig()
    rec = st["plan_follow"]
    F.reading(rec, 76.0, 0)
    F.blind(rec)
    F.reading(rec, 55.0, 9000)
    assert rec["step"] is True


def test_an_old_state_file_without_the_record_loads_fresh(tmp_path):
    c, _fake = _build({"num_zones": 1}, states={"sensor.crop_steering_engine_config": ("ok", _desc())})
    fresh = c._fresh_zone()
    saved = c._serialize_zone(fresh)
    saved.pop("plan_follow")
    assert c._apply_saved_zone(c._fresh_zone(), saved)["plan_follow"] == F.fresh()
    st = c._fresh_zone()
    st["plan_follow"]["days"] = _days(53, 54)
    again = c._apply_saved_zone(c._fresh_zone(), c._serialize_zone(st))
    assert [d["peak"] for d in again["plan_follow"]["days"]] == [53, 54]
