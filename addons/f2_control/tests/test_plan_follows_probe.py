"""The plan follows the probe (plan_follow.py, controller._plan_follow).

F1, 9 Nov 2026: a reseated probe read about 15 points lower (peaks 76 -> about 53). The armed plan kept a P1
target of 61 and a P2 threshold of 54 the zone could never reach, and it was overwatered for 10 days. Now, once a
grow-day after the ramp, a zone whose peaks have not agreed with its plan for 3 clean grow-days gets a VWC offset on
the plan (crop_steering.strategy_zone_offset), the whole way in one write, read back and told (CS-714). A zone more
than 8 points off is moved after one clean grow-day.
"""
from datetime import datetime, timedelta

import pytest
import test_p3_time_between_shots as p3

import controller
import plan_follow as F
from test_controller import _build, _desc

pytestmark = pytest.mark.usefixtures("settings_built_in")

NOW = datetime(2026, 11, 9, 15, 0, 0)
PLAN = "sensor.crop_steering_strategy_plan"


def _days(*peaks):
    return [{"day": f"2026-11-0{i + 1}", "peak": p, "rose": 8.0} for i, p in enumerate(peaks)]


def _watered_day(rec, day, peak, before=None):
    """A clean grow-day: the first shot found the zone at `before`, the ramp ended (a reading in P2), peak `peak`."""
    F.watered(rec, peak - 8 if before is None else before)
    rec["ramped"] = True
    F.close_day(rec, day, peak)


# ------------------------------------------------------------------ the rule (pure)
def test_an_unreachable_p1_target_moves_the_offset_the_whole_way_in_one_write():
    got = F.decide(_days(53, 52.5, 53.4), p1=61, fc=64, base_fc=64, offset=0)
    assert got == {"offset": -10.0, "why": "unreachable", "median": 53, "goal": -10.0, "peaks": [53, 52.5, 53.4],
                   "gap": 8.0}
    # the next grow-day, on the moved plan (P1 51, FC 54), nothing more to do
    assert F.decide(_days(53, 52.5, 53.4), p1=51, fc=54, base_fc=64, offset=-10) is None


def test_peaks_over_field_capacity_move_the_offset_up():
    got = F.decide(_days(70, 71, 69.5), p1=61, fc=64, base_fc=64, offset=0)
    assert (got["why"], got["offset"], got["goal"]) == ("overshoot", 7.0, 7.0)
    assert F.decide(_days(68, 68, 68), p1=61, fc=64, base_fc=64, offset=3)["offset"] == 5.0


def test_three_days_must_all_agree_for_a_small_gap():
    assert F.decide(_days(53, 53), p1=61, fc=64, base_fc=64, offset=0) is None  # 8 points off: not over 8
    assert F.decide(_days(53, 58, 53), p1=61, fc=64, base_fc=64, offset=0) is None  # one day within 4 points
    assert F.decide(_days(70, 66, 70), p1=61, fc=64, base_fc=64, offset=0) is None  # one day within 3 over FC


def test_a_zone_way_off_is_moved_after_one_clean_grow_day():
    """The F1 incident: P1 61, the reseated probe peaking at 46 the first clean day after it."""
    got = F.decide(_days(46), p1=61, fc=64, base_fc=64, offset=0)
    assert (got["offset"], got["why"], got["peaks"], got["gap"]) == (-17.0, "unreachable", [46], 15.0)
    # the one day judged is the last: an older far-off day does not count once a closer one follows
    assert F.decide(_days(46, 55), p1=61, fc=64, base_fc=64, offset=0) is None
    got = F.decide(_days(75), p1=61, fc=64, base_fc=64, offset=0)
    assert (got["offset"], got["why"]) == (12.0, "overshoot")


def test_there_is_no_bound_on_the_offset_but_the_settings_own():
    got = F.decide(_days(30), p1=61, fc=64, base_fc=64, offset=-19)
    assert got["offset"] == -33.0  # the integration clamps each setting and keeps their order


def test_a_step_change_or_a_day_without_a_peak_starts_the_count_again():
    rec = F.fresh()
    for day, peak in (("a", 76), ("b", 75)):
        _watered_day(rec, day, peak)
    assert [d["day"] for d in rec["days"]] == ["a", "b"]
    F.reading(rec, 75.0, 0)
    F.reading(rec, 0.0, 60)  # the probe pulled out
    _watered_day(rec, "c", 74)
    assert rec["days"] == []
    F.reading(rec, 70.0, 120)
    F.blind(rec)
    F.reading(rec, 55.0, 4000)  # back after a gap, 15 points lower
    _watered_day(rec, "d", 55)
    assert rec["days"] == []
    for day in "efg":
        F.reading(rec, 53.0, 5000)
        _watered_day(rec, day, 53)
    assert [d["day"] for d in rec["days"]] == ["e", "f", "g"]
    F.watered(rec, 45.0)
    rec["ramped"] = True
    F.close_day(rec, "h", None)  # blind all day
    assert rec["days"] == []


# ------------------------------------------------------------------ a day without water is not a clean day
def test_a_grow_day_with_no_water_starts_the_count_again():
    """The kill switch off, a hold or an empty tank all day: the peak is the lights-on reading, low because no water
    came. Before, that day counted, and one such day 8 points under the P1 target moved the whole ladder down."""
    rec = F.fresh()
    _watered_day(rec, "a", 61)
    F.reading(rec, 47.0, 0, "P1")  # in P1 all day behind a hold; lights-off takes it to P3
    F.close_day(rec, "b", 47)
    assert rec["days"] == []
    assert F.decide(rec["days"], p1=61, fc=64, base_fc=64, offset=0) is None


def test_a_grow_day_whose_shots_did_not_raise_the_reading_starts_the_count_again():
    """A blocked line: the shots are counted and the ramp ends (P1 stalled -> P2), but the highest reading of the day
    is still the one from before the first shot."""
    rec = F.fresh()
    F.reading(rec, 47.0, 0, "P1")
    F.watered(rec, 47.0)  # the first shot: the day's highest so far is 47
    F.watered(rec, 47.0)  # later shots do not move what was kept
    F.reading(rec, 46.5, 3600, "P2")
    F.close_day(rec, "a", 47.4)  # 0.4 over: under RISE_PTS
    assert rec["days"] == []


def test_a_grow_day_whose_ramp_did_not_end_starts_the_count_again():
    """Two ramp shots, then a hold until lights-off: the reading rose, but the zone never left P1."""
    rec = F.fresh()
    F.reading(rec, 44.0, 0, "P1")
    F.watered(rec, 44.0)
    F.reading(rec, 50.0, 1800, "P1")
    F.close_day(rec, "a", 50)
    assert rec["days"] == []


def test_a_watered_grow_day_is_kept_with_its_rise_and_the_next_day_starts_empty():
    rec = F.fresh()
    F.reading(rec, 45.0, 0, "P0")
    F.watered(rec, 45.0)
    F.reading(rec, 53.0, 3600, "P2")
    F.close_day(rec, "a", 53)
    assert rec["days"] == [{"day": "a", "peak": 53, "rose": 8.0}]
    assert (rec["watered"], rec["before"], rec["ramped"]) == (False, None, False)
    # no trusted reading before the first shot (blind until then): the rise cannot be judged
    F.watered(rec, 0.0)
    F.reading(rec, 53.0, 90000, "P2")
    F.close_day(rec, "b", 53)
    assert rec["days"] == []


def test_the_reseated_probe_still_moves_after_one_watered_grow_day():
    """The F1 incident keeps working: the probe reads 15 points lower, the ramp still raises it, the ramp ends."""
    rec = F.fresh()
    F.reading(rec, 38.0, 0, "P0")
    F.watered(rec, 38.0)
    F.reading(rec, 46.0, 7200, "P2")
    F.close_day(rec, "2026-11-08", 46)
    got = F.decide(rec["days"], p1=61, fc=64, base_fc=64, offset=0)
    assert (got["offset"], got["why"], got["peaks"]) == (-17.0, "unreachable", [46])


def test_a_slow_rise_is_not_a_step_change():
    rec = F.fresh()
    F.reading(rec, 50.0, 0)
    F.reading(rec, 61.0, 3600)  # 11 points over an hour of ramp shots, no gap
    assert rec["step"] is False


def test_a_saved_record_is_restored_or_made_fresh():
    assert F.restore(None) == F.fresh()
    assert F.restore({"days": "x", "step": "yes"}) == F.fresh()
    saved = {"days": _days(53, 52, 54, 55), "step": True, "last": [53.0, 1.0], "gap": False, "checked": "2026-11-08",
             "watered": True, "before": 44.5, "ramped": True}
    out = F.restore(saved)
    assert [d["peak"] for d in out["days"]] == [52, 54, 55] and out["step"] and out["checked"] == "2026-11-08"
    assert [d["rose"] for d in out["days"]] == [8.0, 8.0, 8.0]
    assert (out["watered"], out["before"], out["ramped"]) == (True, 44.5, True)


@pytest.mark.parametrize("junk", ["45", True, 150, -3, float("nan"), [45.0]])
def test_a_saved_reading_that_is_not_one_loads_as_none_and_lights_on_still_closes_the_day(junk):
    """`before` comes back from the state file at lights-on, in a call nothing guards: junk in it must never raise
    there. The day is simply not kept."""
    out = F.restore({"watered": True, "before": junk, "ramped": True})
    assert out["before"] is None
    F.close_day(out, "a", 53)
    assert out["days"] == []


def test_a_record_saved_by_3_19_0_keeps_no_day_it_did_not_judge():
    """3.19.0 kept a day's peak without asking whether water raised it. Those days are dropped at load, so a day
    without water kept before the update cannot move a plan after it, and the grow-day in progress is not kept."""
    saved = {"days": [{"day": "2026-11-08", "peak": 47.0}], "step": False, "last": [47.0, 1.0], "gap": False,
             "checked": "2026-11-08"}
    out = F.restore(saved)
    assert out["days"] == [] and (out["watered"], out["before"], out["ramped"]) == (False, None, False)
    F.reading(out, 53.0, 100, "P2")
    F.close_day(out, "2026-11-09", 53)  # the day the update landed in: its first shot was not seen
    assert out["days"] == []


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
    assert _offset_calls(fake) == [{
        "room_id": "room:", "zone_id": 1, "offset": -10.0,
        "reason": "P1 target out of reach: peaks 53, 52.5, 53.4% on the last 3 clean grow-days"}]
    card = _cards(fake)[-1]
    assert "(CS-714)" in card["title"]
    assert "from +0 to -10 points, a move of -10 points in one step" in card["message"]
    assert "53, 52.5, 53.4% (median 53%)" in card["message"] and "all 3 days agreed" in card["message"]
    assert "its P1 target was 8 points over that" in card["message"]
    assert "The P1 target is now 51%." in card["message"]
    # once a grow-day
    assert c._plan_follow(room, 1, st, NOW.replace(hour=18)) is False
    assert len(_offset_calls(fake)) == 1


def test_a_zone_way_off_is_moved_the_whole_way_after_one_clean_grow_day():
    c, fake, room, st = _rig(days=(46,))  # the F1 probe: 15 points under its P1 target the first clean day
    assert c._plan_follow(room, 1, st, NOW) is True
    (call,) = _offset_calls(fake)
    assert call["offset"] == -17.0
    assert call["reason"] == "P1 target out of reach: peak 46% on the last clean grow-day"
    card = _cards(fake)[-1]["message"]
    assert "from +0 to -17 points, a move of -17 points in one step" in card
    assert "one clean grow-day is enough when a zone is more than 8 points off" in card


def test_a_moved_offset_moves_again_from_where_it_is():
    c, fake, room, st = _rig(offset=-4.0, days=(46,))  # P1 57 in force, base FC 64
    assert c._plan_follow(room, 1, st, NOW) is True
    assert _offset_calls(fake)[0]["offset"] == -17.0
    assert "from -4 to -17 points, a move of -13 points" in _cards(fake)[-1]["message"]


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
    {"days": (55, 55)},  # only two clean grow-days, 6 points off (not over 8)
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


def test_counted_water_keeps_what_the_zone_read_before_the_first_shot_of_the_grow_day():
    c, fake, room, st = _rig(days=())
    st["fc_follow"]["peak"] = 44.5  # the highest trusted reading since lights-on
    c._advance_shot_counters(room, 1, 2.0)
    assert (st["plan_follow"]["watered"], st["plan_follow"]["before"]) == (True, 44.5)
    st["fc_follow"]["peak"] = 52.0
    c._advance_shot_counters(room, 1, 2.0)
    assert st["plan_follow"]["before"] == 44.5  # only the first shot of the grow-day sets it


def test_one_grow_day_without_water_no_longer_moves_the_plan():
    """The whole path on the controller. Day 1: the kill switch off, so no shot; the zone reads 47 at lights-on and
    dries. Day 2 at lights-on the day is closed; after day 2's ramp the rule looks. Before this fix it wrote an
    offset of -16 (peak 47 against a P1 target of 61), rescue floor included."""
    c, fake, room, st = _rig(days=())
    st["phase"], st["fc_follow"]["peak"] = "P3", 47.0
    st["last_daily_reset"] = c._grow_day_start(room, NOW.replace(day=8))
    c._change_phase(room, 1, st, "P0", "lights-on -> P0", NOW.replace(hour=6))
    assert st["plan_follow"]["days"] == []
    st["phase"] = "P2"
    assert c._plan_follow(room, 1, st, NOW) is False
    assert _offset_calls(fake) == []


# ------------------------------------------------------------------ a whole grow-day, through the controller's loop
night_room = p3.rig  # two zones in P3 at 23:00 on 23 Sep, lights 10 to 22, last watered at 21:00


def _passes(c, fake, room, start, readings):
    """One pass a minute from `start`, zone 1 reading each of `readings` in turn (zone 2 a steady 55)."""
    for minute, vwc in enumerate(readings):
        p3.Clock.instant = now = start + timedelta(minutes=minute)
        p3.probe(fake, 1, vwc)
        p3.probe(fake, 2, 55)
        c._loop_room(room, now)


def _grow_day(c, fake, room, day, readings_after_lights_on, set_phase="P2"):
    """Lights-on at 10:00 on `day`, the readings a minute apart, the operator's Set Phase after them (the ramp
    handed over), a reading in that phase, then lights-off at 22:00 and a reading at night."""
    on = p3.Clock(2026, 9, day, 10, 0)
    _passes(c, fake, room, on, readings_after_lights_on)
    fake.set_state("select.crop_steering_zone_1_set_phase", set_phase)
    _passes(c, fake, room, on + timedelta(minutes=30), [readings_after_lights_on[-1] + 4])
    fake.set_state("select.crop_steering_zone_1_set_phase", "Keep")  # as Home Assistant does on the controller's call
    _passes(c, fake, room, p3.Clock(2026, 9, day, 22, 1), [readings_after_lights_on[-1] + 2])


def _valve_opened(fake):
    return ("switch", "turn_on", {"entity_id": "switch.v1"}) in fake.calls


def test_a_watered_grow_day_is_kept_at_the_next_lights_on_through_the_whole_loop(night_room):
    """Lights-on, a reading under the rescue level (P0 hands over to P1 at once and the ramp's first shot fires),
    the reading rising, P2, night, lights-on again: the day is kept with its peak and its rise."""
    c, fake, room = night_room
    _grow_day(c, fake, room, 24, [45, 39, 48])
    assert _valve_opened(fake)
    rec = room.state[1]["plan_follow"]
    # 39: the follower's counted peak when the first shot fired. It counts from the pass after lights-on, so the
    # 45 of the lights-on pass itself is in neither this nor the day's peak: the two are measured alike.
    assert (rec["watered"], rec["before"], rec["ramped"]) == (True, 39.0, True)
    _passes(c, fake, room, p3.Clock(2026, 9, 25, 10, 0), [47])  # lights-on closes the 24th
    assert rec["days"] == [{"day": "2026-09-24", "peak": 52.0, "rose": 13.0}]
    assert (rec["watered"], rec["before"], rec["ramped"]) == (False, None, False)


def test_a_grow_day_behind_the_kill_switch_is_not_kept_through_the_whole_loop(night_room):
    """The same day with the room's kill switch off: no shot, and the reading only falls. Not kept."""
    c, fake, room = night_room
    fake.set_state("input_boolean.kill", "off")
    _grow_day(c, fake, room, 24, [45, 39, 38])
    assert not _valve_opened(fake)
    _passes(c, fake, room, p3.Clock(2026, 9, 25, 10, 0), [37])
    assert room.state[1]["plan_follow"]["days"] == []


def test_a_grow_day_that_never_reached_p2_is_not_kept_through_the_whole_loop(night_room):
    """Watered, and the reading rose, but the zone went from its ramp straight to the night."""
    c, fake, room = night_room
    _grow_day(c, fake, room, 24, [45, 39, 48], set_phase="Keep")
    assert _valve_opened(fake) and room.state[1]["plan_follow"]["ramped"] is False
    _passes(c, fake, room, p3.Clock(2026, 9, 25, 10, 0), [47])
    assert room.state[1]["plan_follow"]["days"] == []


def test_a_reading_at_night_is_not_the_end_of_a_ramp():
    rec = F.fresh()
    for phase in ("P0", "P1", "P3", None):
        F.reading(rec, 50.0, 0, phase)
    assert rec["ramped"] is False
    F.reading(rec, 50.0, 60, "P2")
    assert rec["ramped"] is True


def test_a_shot_in_the_pass_that_starts_the_grow_day_keeps_that_passes_reading():
    """Lights-on zeroes the follower's peak after this pass's reading was counted, and a shot can fire in the same
    pass (a P0 EC flush). The reading of the pass is then what the zone read before its first shot."""
    rec = F.fresh()
    F.reading(rec, 46.0, 0, "P3")
    F.watered(rec, 0.0)  # no peak counted yet this grow-day
    assert (rec["watered"], rec["before"]) == (True, 46.0)
    F.reading(rec, 53.0, 3600, "P2")
    F.close_day(rec, "a", 53)
    assert rec["days"] == [{"day": "a", "peak": 53, "rose": 7.0}]
    # ...but not across a blind gap: that reading is from before the gap
    rec = F.fresh()
    F.reading(rec, 46.0, 0, "P3")
    F.blind(rec)
    F.watered(rec, None)
    assert (rec["watered"], rec["before"]) == (True, None)


def test_a_rise_of_exactly_three_points_counts_and_less_does_not():
    assert F.RISE_PTS == 3.0
    for peak, kept in ((48.0, True), (47.99, False)):
        rec = F.fresh()
        F.watered(rec, 45.0)
        F.reading(rec, peak, 60, "P2")
        F.close_day(rec, "a", peak)
        assert bool(rec["days"]) is kept, peak


@pytest.mark.parametrize("rose", [True, "8", None, float("nan"), 2.9, -3])
def test_a_saved_day_whose_rise_is_not_a_rise_is_dropped_with_the_days_before_it(rose):
    good = {"day": "2026-11-0%d", "peak": 53.0, "rose": 8.0}
    days = [dict(good, day="2026-11-01"), dict(good, day="2026-11-02", rose=rose), dict(good, day="2026-11-03")]
    out = F.restore({"days": days})
    assert [d["day"] for d in out["days"]] == ["2026-11-03"]  # days in a row: only the run after it


def test_a_saved_day_that_rose_exactly_the_least_is_kept():
    day = {"day": "2026-11-03", "peak": 53.0, "rose": F.RISE_PTS}
    assert F.restore({"days": [day]})["days"] == [day]


@pytest.mark.parametrize("key", ["watered", "ramped"])
@pytest.mark.parametrize("junk", [1, "yes", "False", [0], {"a": 1}])
def test_a_saved_mark_that_is_not_true_itself_loads_as_false(key, junk):
    """Only `true` in the file says the grow-day in progress got water, or reached P2. Anything else is "no"."""
    assert F.restore({key: junk})[key] is False
    assert F.restore({key: True})[key] is True


# ------------------------------------------------------------------ counted water is not delivered water
@pytest.mark.parametrize("before, readings, why", [
    (39.0, (40.2, 33.0, 27.0), "day 2 of no supply: a cold first shot, a point of warm-up drift, then drying on"),
    (33.0, (35.3, 34.0, 33.5), "day 3: the reading hardly falls any more, and drifts up 2.3 points"),
    (47.0, (49.9, 44.0, 38.0), "the supply failed after two ramp shots that raised the reading 2.9 points"),
])
def test_a_day_whose_counted_shots_brought_little_or_no_water_is_not_kept(before, readings, why):
    """A blocked line, an empty tank or a dead pump: the shots are counted, the ramp runs out its shots and P2
    follows, but the reading rises by drift alone, or by the little that arrived. Not a clean day."""
    rec = F.fresh()
    F.reading(rec, before, 60, "P0")
    F.watered(rec, before)
    for n, vwc in enumerate(readings):
        F.reading(rec, vwc, 1800 * (n + 1), "P2")
    F.close_day(rec, "2026-11-09", max(readings))
    assert rec["days"] == [], why
    assert F.decide(rec["days"], p1=61, fc=64, base_fc=64, offset=0) is None


def test_a_supply_that_fails_after_the_ramp_raised_the_reading_still_counts():
    """The stated limit: one probe cannot tell this day from a probe that reads lower."""
    rec = F.fresh()
    F.reading(rec, 44.0, 60, "P0")
    F.watered(rec, 44.0)
    F.reading(rec, 50.0, 3600, "P2")  # 6 points up, then the tank ran out
    F.reading(rec, 41.0, 30000, "P2")
    F.close_day(rec, "2026-11-09", 50.0)
    assert F.decide(rec["days"], p1=61, fc=64, base_fc=64, offset=0)["why"] == "unreachable"


def test_a_peak_under_what_the_zone_read_before_its_first_shot_is_not_a_rise():
    rec = F.fresh()
    F.watered(rec, 50.0)
    rec["ramped"] = True
    F.close_day(rec, "a", 47.0)  # 3 points UNDER: never the size of the difference
    assert rec["days"] == []


def test_a_test_shot_and_a_timer_shot_count_as_water_and_a_failing_record_never_loses_the_shots_count(monkeypatch):
    c, fake, room, st = _rig(days=())
    st["fc_follow"]["peak"] = 44.5
    c._advance_shot_counters(room, 1, 2.0, steering=False)  # a test shot
    assert (st["plan_follow"]["watered"], st["plan_follow"]["before"]) == (True, 44.5)
    st["plan_follow"] = F.fresh()
    c._advance_shot_counters(room, 1, 2.0, learn=False)  # a timer shot
    assert st["plan_follow"]["watered"] is True
    before = st["daily_vol"]

    def broken(rec, peak):
        raise RuntimeError("the record is damaged")

    monkeypatch.setattr(F, "watered", broken)
    c._advance_shot_counters(room, 1, 2.0)
    assert st["daily_vol"] > before and st["last_shot"] is not None  # the water is counted all the same


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
