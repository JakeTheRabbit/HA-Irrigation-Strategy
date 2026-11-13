"""A room steered on its average: the room's "Steer on room average" switch.

Off, or absent on an older integration, every zone decides on its own probe, as before. On, every zone of the room
decides on one reading, the mean moisture and the mean pore EC of the zones that are switched on and give a
reading. The zones then move together, and each still gets its own shot through its own valve. What watches a
zone itself (a table that does not drain) keeps the zone's own probe.
"""

from datetime import timedelta

import pytest

from test_plan_hold_never_stops_rescues import Clock, opened, probe, rig  # noqa: F401 (rig: a pytest fixture)

pytestmark = pytest.mark.usefixtures("no_blind_grace", "settings_built_in")

SWITCH = "switch.crop_steering_steer_on_room_average"


def _p2(room, now, ago=timedelta(hours=1)):
    for zone in (1, 2):
        room.state[zone].update(phase="P2", last_shot=now - ago)


def test_without_the_switch_each_zone_decides_on_its_own_probe(rig):  # noqa: F811
    c, fake, room = rig
    now = Clock.now()
    probe(fake, 1, 30)  # under the 45 re-water threshold
    probe(fake, 2, 50)
    _p2(room, now)
    pub = c._loop_room(room, now)
    assert pub[1]["fire"] and not pub[2]["fire"]
    assert (pub[1]["vwc"], pub[2]["vwc"]) == (30, 50)
    assert room.state[1]["room_avg"] is False
    fake.set_state(SWITCH, "off")
    assert c._room_average(room) is None


def test_on_the_average_a_dry_room_waters_every_zone_through_its_own_valve(rig):  # noqa: F811
    c, fake, room = rig
    now = Clock.now()
    fake.set_state(SWITCH, "on")
    probe(fake, 1, 30, ec=4.0)
    probe(fake, 2, 50, ec=6.0)  # the room reads 40: under the threshold, though this zone alone is over it
    _p2(room, now)
    pub = c._loop_room(room, now)
    assert pub[1]["fire"] and pub[2]["fire"]
    assert (pub[1]["vwc"], pub[2]["vwc"]) == (40, 40) and (pub[1]["ec"], pub[2]["ec"]) == (5.0, 5.0)
    assert opened(fake).count("switch.v1") == 1 and opened(fake).count("switch.v2") == 1


def test_on_the_average_one_dry_probe_does_not_water_its_zone_alone(rig):  # noqa: F811
    c, fake, room = rig
    now = Clock.now()
    fake.set_state(SWITCH, "on")
    probe(fake, 1, 30)
    probe(fake, 2, 70)  # the room reads 50
    _p2(room, now)
    pub = c._loop_room(room, now)
    assert not pub[1]["fire"] and not pub[2]["fire"]
    assert opened(fake) == []


def test_a_zone_with_a_dead_probe_follows_the_room(rig):  # noqa: F811
    c, fake, room = rig
    now = Clock.now()
    fake.set_state(SWITCH, "on")
    probe(fake, 2, 40)  # zone 1 has no reading of its own
    _p2(room, now)
    pub = c._loop_room(room, now)
    assert pub[1]["fire"] and pub[2]["fire"] and pub[1]["blind"] is False
    assert pub[1]["vwc"] == 40


def test_a_zone_switched_off_is_left_out_of_the_average(rig):  # noqa: F811
    c, fake, room = rig
    fake.set_state(SWITCH, "on")
    probe(fake, 1, 30, ec=4.0)
    probe(fake, 2, 50, ec=6.0)
    fake.set_state("switch.crop_steering_zone_2_enabled", "off")
    assert c._room_average(room) == (30, 4.0)


def test_no_reading_in_the_room_leaves_every_zone_blind_as_before(rig):  # noqa: F811
    c, fake, room = rig
    fake.set_state(SWITCH, "on")
    assert c._room_average(room) == (None, None)
    snap, _p = c._snapshot(room, 1, Clock.now(), True, False)
    assert snap is None


def test_the_peak_starts_again_when_the_steering_reading_changes(rig):  # noqa: F811
    c, fake, room = rig
    now = Clock.now()
    probe(fake, 1, 70)
    probe(fake, 2, 30)
    room.state[1].update(peak=79.0, p1_peak_before=78.0, win=[(now - timedelta(minutes=5), 78.0)])
    fake.set_state(SWITCH, "on")
    room._room_reading = c._room_average(room)
    snap, _p = c._snapshot(room, 1, now, True, False)
    st = room.state[1]
    assert (snap.vwc, snap.peak_vwc, st["peak"], st["room_avg"]) == (50, 50, 50, True)
    assert st["win"] == [(now, 50)] and st["p1_peak_before"] is None
    st["peak"] = 60.0  # the room's own peak, later in the day: kept while the switch stays on
    assert c._snapshot(room, 1, now, True, False)[0].peak_vwc == 60.0
    fake.set_state(SWITCH, "off")
    room._room_reading = c._room_average(room)
    snap, _p = c._snapshot(room, 1, now, True, False)
    assert (snap.vwc, snap.peak_vwc, st["room_avg"]) == (70, 70, False)


def test_on_the_average_the_gap_between_shots_counts_from_the_rooms_last_shot(rig):  # noqa: F811
    c, fake, room = rig
    now = Clock.now()
    probe(fake, 1, 40)
    probe(fake, 2, 40)
    room.state[1]["last_shot"] = now - timedelta(hours=2)
    room.state[2]["last_shot"] = now - timedelta(minutes=5)
    assert c._snapshot(room, 1, now, True, False)[0].minutes_since_shot == pytest.approx(120)
    fake.set_state(SWITCH, "on")
    room._room_reading = c._room_average(room)
    assert c._snapshot(room, 1, now, True, False)[0].minutes_since_shot == pytest.approx(5)
    assert c._snapshot(room, 2, now, True, False)[0].minutes_since_shot == pytest.approx(5)


def test_the_drain_watch_keeps_the_zones_own_probe(rig):  # noqa: F811
    c, fake, room = rig
    now = Clock.now()
    fake.set_state(SWITCH, "on")
    probe(fake, 1, 30)
    probe(fake, 2, 70)
    _p2(room, now)
    seen = {}
    c._watch_backup = lambda room, zone, snap, now: seen.update({zone: snap.vwc}) or False
    c._loop_room(room, now)
    assert seen == {1: 30, 2: 70}


def test_a_saved_state_from_before_the_switch_loads_and_steers_on_its_own_probe(rig):  # noqa: F811
    c, fake, room = rig
    now = Clock.now()
    for zone in (1, 2):
        room.state[zone].pop("room_avg")
        probe(fake, zone, 50)
    room.state[1]["peak"] = 62.0
    snap, _p = c._snapshot(room, 1, now, True, False)
    assert snap.peak_vwc == 62.0 and "room_avg" not in room.state[1]
