"""The zone's setpoints follow its own highest readings, and P1 ends when a shot no longer raises them.

The owner, 6 Oct 2026: "the P1 target should be the VWC MAX the previous days actual field capacity, the highest
value that the VWC got to during the day is the next days p1 target", "the FC needs to increase as the sensor
does", "the p2 dryback and shit needs to move as well to be in line with the new FC", "the rescue floor should
increase too", "get rid of this rule ... which may only rise 2 points a day", and "the transition from p1 to p2 is
determined by reaching the p1 target, giving an extra shot, if it doesnt rise more, transition to p2, if it rises
more, do another shot until it stops rising". So:
  - at lights-on the grow-day's peak (the highest VWC since the last lights-on) is kept as the day before's;
  - field capacity = the higher of today's peak and the day before's; the P1 target = the day before's, with no
    limit on how far it moves; the re-water threshold and the rescue floor move with field capacity, within each
    number's own min and max, the ladder written so it holds after every write; nothing is written until a
    lights-on has kept a day before;
  - the learner writes neither; the P1 rule (core.decide) is fed the latch, the peak before each P1 shot and the
    count of shots after the target.
Numbers: F2 zone 2 and zone 3 on 6 Oct 2026 (their 5 Oct peaks 71.48 and 73.4).
"""
import json
from datetime import date, timedelta
from types import SimpleNamespace

import controller
from test_plan_hold_never_stops_rescues import Clock, probe, rig  # noqa: F401 (rig: a pytest fixture)

LADDER = ("field_capacity", "p1_target_vwc", "p2_vwc_threshold", "p3_emergency_vwc_threshold")


def _ladder(fake, zone, fc, target, thr, rescue):
    for key, value in zip(LADDER, (fc, target, thr, rescue)):
        fake.set_state(f"number.crop_steering_zone_{zone}_{key}", str(value))


def _writes(fake, zone=1):
    out = {s: [] for s in LADDER}
    for dom, svc, d in fake.calls:
        for s in LADDER:
            if (dom, svc) == ("number", "set_value") and d.get("entity_id") == f"number.crop_steering_zone_{zone}_{s}":
                out[s].append(d["value"])
    return out


def _room(fake, room, now, vwc=45.0):
    fake.set_state("switch.crop_steering_auto_setpoints", "on")
    for zone in (1, 2):
        _ladder(fake, zone, 68, 65.5, 41.5, 34)  # zone 2 after 3.10.0
        room.state[zone].update(phase="P2", last_shot=now - timedelta(minutes=30), last_daily_reset=date(2026, 9, 23))
        probe(fake, zone, vwc)


def test_until_a_lights_on_keeps_a_day_before_nothing_is_written(rig):  # noqa: F811
    c, fake, room = rig
    now = Clock.instant = Clock(2026, 9, 23, 14, 0)
    _room(fake, room, now)
    for phase in ("P0", "P1", "P2", "P3"):  # updated mid-grow-day: today's peak is no stand-in for the day before
        room.state[1].update(phase=phase, peak=51.39, peak_prev=None)
        assert c._vwc_maxima(room.state[1]) == (None, None)
    room.state[1].update(phase="P2", peak=51.39)  # 6 Oct: zone 2's ramp stopped at its shot limit
    c._loop_room(room, now)
    assert _writes(fake, 1) == {s: [] for s in LADDER}  # field capacity stays 68, never follows a short ramp down


def test_a_floor_under_the_numbers_own_minimum_stops_there_and_a_falling_ladder_moves_from_the_bottom(rig):  # noqa: F811
    c, fake, room = rig
    now = Clock.instant = Clock(2026, 9, 23, 14, 0)
    _room(fake, room, now)
    _ladder(fake, 1, 71.5, 71.5, 45.5, 38.0)  # zone 2 on 6 Oct, its day before 71.48
    fake.set_state("number.crop_steering_zone_1_p3_emergency_vwc_threshold", "38.0", {"min": 20.0, "max": 65.0})
    room.state[1].update(peak=35.0, peak_prev=51.39)  # the next lights-on: that day's ramp stopped at 51.4
    c._loop_room(room, now)
    # 71.5 -> 51.4 is 20.1 down: the floor would be 17.9, under the number's own minimum, so it stops at 20
    assert _writes(fake, 1) == {"field_capacity": [51.4], "p1_target_vwc": [51.4], "p2_vwc_threshold": [25.4],
                                "p3_emergency_vwc_threshold": [20.0]}
    order = [d["entity_id"].rsplit("zone_1_", 1)[1] for dom, svc, d in fake.calls
             if (dom, svc) == ("number", "set_value") and d["entity_id"].rsplit("zone_1_", 1)[-1] in LADDER]
    assert order == ["p3_emergency_vwc_threshold", "p2_vwc_threshold", "p1_target_vwc", "field_capacity"]


def test_a_refused_write_stops_the_rest_so_the_ladder_is_never_left_inverted(rig, monkeypatch):  # noqa: F811
    c, fake, room = rig
    now = Clock.instant = Clock(2026, 9, 23, 14, 0)
    _room(fake, room, now)
    _ladder(fake, 1, 71.5, 71.5, 45.5, 38.0)
    room.state[1].update(peak=35.0, peak_prev=51.39)
    refused = "number.crop_steering_zone_1_p2_vwc_threshold"
    monkeypatch.setattr(controller, "ha_call",
                        lambda domain, service, **data: data.get("entity_id") != refused and fake.ha_call(
                            domain, service, **data))
    c._loop_room(room, now)
    # the floor moved first; the threshold was refused, so the P1 target and field capacity wait for the next loop
    assert _writes(fake, 1) == {"field_capacity": [], "p1_target_vwc": [], "p2_vwc_threshold": [],
                                "p3_emergency_vwc_threshold": [17.9]}


def test_the_p1_target_is_the_day_befores_peak_and_field_capacity_the_higher_of_both(rig):  # noqa: F811
    c, fake, room = rig
    now = Clock.instant = Clock(2026, 9, 23, 14, 0)
    _room(fake, room, now)
    _ladder(fake, 1, 60.9, 58.9, 47.8, 35.3)  # zone 3 after 3.10.0
    room.state[1].update(peak=50.0, peak_prev=73.4)  # this morning so far, and all of yesterday
    c._loop_room(room, now)
    # no 2-point limit: the target goes straight to yesterday's highest reading
    assert _writes(fake, 1) == {"field_capacity": [73.4], "p1_target_vwc": [73.4], "p2_vwc_threshold": [60.3],
                                "p3_emergency_vwc_threshold": [47.8]}


def test_field_capacity_rises_the_same_day_the_sensor_reads_higher(rig):  # noqa: F811
    c, fake, room = rig
    now = Clock.instant = Clock(2026, 9, 23, 14, 0)
    _room(fake, room, now)
    _ladder(fake, 1, 71.5, 71.5, 45.0, 37.5)
    room.state[1].update(peak=72.8, peak_prev=71.48)
    c._loop_room(room, now)
    # 1.3 points: field capacity, threshold and floor move; the target stays yesterday's
    assert _writes(fake, 1) == {"field_capacity": [72.8], "p1_target_vwc": [], "p2_vwc_threshold": [46.3],
                                "p3_emergency_vwc_threshold": [38.8]}


def test_a_small_move_is_field_capacity_alone(rig):  # noqa: F811
    c, fake, room = rig
    now = Clock.instant = Clock(2026, 9, 23, 14, 0)
    _room(fake, room, now)
    _ladder(fake, 1, 71.5, 71.5, 45.0, 37.5)
    room.state[1].update(peak=72.0, peak_prev=71.48)
    c._loop_room(room, now)
    assert _writes(fake, 1) == {"field_capacity": [72.0], "p1_target_vwc": [], "p2_vwc_threshold": [],
                                "p3_emergency_vwc_threshold": []}


def test_a_zone_watering_without_its_probe_follows_too(rig):  # noqa: F811
    c, fake, room = rig
    now = Clock.instant = Clock(2026, 9, 23, 14, 0)
    _room(fake, room, now)
    room.state[1].update(peak=40.0, peak_prev=71.48)
    fake.set_state("sensor.crop_steering_vwc_zone_1", "unavailable")  # no reading: the blind path
    c._loop_room(room, now)
    assert _writes(fake, 1)["p1_target_vwc"] == [71.5] and _writes(fake, 1)["field_capacity"] == [71.5]


def test_nothing_is_written_with_auto_setpoints_off_or_a_ladder_it_would_invert(rig):  # noqa: F811
    c, fake, room = rig
    now = Clock.instant = Clock(2026, 9, 23, 14, 0)
    _room(fake, room, now)
    fake.set_state("switch.crop_steering_auto_setpoints", "off")
    room.state[1].update(peak=40.0, peak_prev=71.48)
    c._loop_room(room, now)
    assert _writes(fake, 1) == {s: [] for s in LADDER}
    fake.set_state("switch.crop_steering_auto_setpoints", "on")
    _ladder(fake, 2, 68, 65.5, 41.5, 34)
    room.state[2].update(peak=68.0, peak_prev=30.0)  # yesterday's peak under today's re-water threshold
    Clock.instant = now = now + timedelta(minutes=1)
    c._loop_room(room, now)
    assert _writes(fake, 2) == {s: [] for s in LADDER}  # a target of 30 would sit under 41.5: nothing moves


def test_lights_on_keeps_the_grow_days_peak_as_the_day_befores(rig):  # noqa: F811
    c, fake, room = rig
    now = Clock.instant = Clock(2026, 9, 23, 14, 0)
    _room(fake, room, now, vwc=40.0)
    for zone in (1, 2):  # still in last night's P3 on a new grow-day: the engine starts P0
        room.state[zone].update(phase="P3", peak=71.48, last_daily_reset=date(2026, 9, 22))
    c._loop_room(room, now)
    st = room.state[1]
    assert st["phase"] == "P0" and st["peak_prev"] == 71.48 and st["peak"] == 40.0


def test_a_zone_on_the_blind_path_keeps_its_grow_days_peak_at_lights_on_too(rig):  # noqa: F811
    c, fake, room = rig
    now = Clock.instant = Clock(2026, 9, 23, 14, 0)
    _room(fake, room, now, vwc=40.0)
    for zone in (1, 2):
        room.state[zone].update(phase="P3", peak=71.48, last_daily_reset=date(2026, 9, 22))
    fake.set_state("sensor.crop_steering_vwc_zone_1", "unavailable")  # no reading: the blind path
    c._loop_room(room, now)
    st = room.state[1]
    assert st["phase"] == "P0" and st["peak_prev"] == 71.48 and st["peak"] == 0.0


def test_the_learner_never_writes_the_p1_target_or_field_capacity(rig):  # noqa: F811
    c, fake, room = rig
    now = Clock.instant = Clock(2026, 9, 23, 14, 0)
    _room(fake, room, now)
    room.state[1]["learn"].update(peak=80.0, outcome="reached", gain=1.0)  # it would want 81 / 83
    c._auto_tick(room, 1, SimpleNamespace(vwc=45.0, ec=5.0, dryback_rate=0.0),
                 c._params(room, 1), True, now)
    sent = [d["entity_id"] for dom, svc, d in fake.calls if (dom, svc) == ("number", "set_value")]
    assert not any(e.endswith(("p1_target_vwc", "field_capacity")) for e in sent)


def test_the_p1_rule_is_fed_the_latch_the_peak_before_each_shot_and_the_extra_shots(rig):  # noqa: F811
    c, fake, room = rig
    room.state[1].update(phase="P1", peak=60.0, p1_reached=False, p1_peak_before=None, p1_extra=0)
    c._advance_shot_counters(room, 1, 3.0, delivered_l=10.0)  # a ramp shot
    assert room.state[1]["p1_peak_before"] == 60.0 and room.state[1]["p1_extra"] == 0
    room.state[1].update(peak=72.0, p1_reached=True)
    c._advance_shot_counters(room, 1, 3.4, delivered_l=11.0)  # the extra shot at the target
    assert room.state[1]["p1_peak_before"] == 72.0 and room.state[1]["p1_extra"] == 1
    c._record_phase(room, 1, room.state[1], "P0", "P1", Clock.instant, "test")  # a fresh P1 starts again
    assert (room.state[1]["p1_reached"], room.state[1]["p1_peak_before"], room.state[1]["p1_extra"]) == (False, None, 0)


def test_entering_p1_already_at_the_target_counts_that_ticks_shot_as_the_extra_one(rig):  # noqa: F811
    c, fake, room = rig
    now = Clock.instant = Clock(2026, 9, 23, 14, 0)
    _room(fake, room, now, vwc=70.0)  # P1 target 65.5: already over it
    for zone in (1, 2):
        room.state[zone].update(phase="P0", peak=70.0, last_phase_change=now - timedelta(hours=2),
                                last_shot=now - timedelta(hours=3))
    pub = c._loop_room(room, now)  # P0 times out into P1 and fires at once (the rig delivers it in the loop)
    st = room.state[1]
    assert st["phase"] == "P1" and pub[1]["fire"] and pub[1]["reason"].kind == "p1_extra"
    assert st["p1_reached"] is True and st["p1_extra"] == 1 and st["p1_peak_before"] == 70.0


def test_the_new_keys_survive_a_restart_and_an_old_file_loads_without_them(tmp_path, rig):  # noqa: F811
    c, fake, room = rig
    room.state[1].update(peak_prev=71.48, p1_reached=True, p1_peak_before=72.0, p1_extra=2)
    saved = c._serialize_zone(room.state[1])
    assert (saved["peak_prev"], saved["p1_reached"], saved["p1_peak_before"], saved["p1_extra"]) == (71.48, True, 72.0, 2)
    back = c._apply_saved_zone(c._fresh_zone(), json.loads(json.dumps(saved)))
    assert (back["peak_prev"], back["p1_reached"], back["p1_peak_before"], back["p1_extra"]) == (71.48, True, 72.0, 2)
    old = {k: v for k, v in saved.items() if k not in ("peak_prev", "p1_reached", "p1_peak_before", "p1_extra")}
    back = c._apply_saved_zone(c._fresh_zone(), old)
    assert (back["peak_prev"], back["p1_reached"], back["p1_peak_before"], back["p1_extra"]) == (None, False, None, 0)
    junk = dict(old, peak_prev="x", p1_reached="yes", p1_peak_before=-3, p1_extra=True)
    back = c._apply_saved_zone(c._fresh_zone(), junk)
    assert (back["peak_prev"], back["p1_reached"], back["p1_peak_before"], back["p1_extra"]) == (None, False, None, 0)
    assert controller.FC_SHIFT_MIN == 1.0
