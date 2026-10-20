"""Each zone's "what would move it next" (crop_steering_engine.waiting_for), published by the controller
on sensor.crop_steering_<prefix>zone_N_waiting_for_app for the dashboard's zone card and grow-day line."""
from datetime import datetime

from test_zone_status_one_owner import _room


def test_a_zone_with_a_probe_says_what_it_waits_for_and_one_without_says_nothing():
    c, fake = _room()
    c.loop_once(datetime(2026, 9, 23, 12, 0))
    phase, attrs = fake.sets["sensor.crop_steering_zone_1_waiting_for_app"]
    assert phase == c.rooms[0].state[1]["phase"]
    assert attrs["conditions"] and all("rule" in item for item in attrs["conditions"])
    assert datetime.fromisoformat(attrs["at"]).tzinfo is not None  # a wait's clock time is at + in_min
    assert fake.sets["sensor.crop_steering_zone_2_waiting_for_app"][1]["conditions"] == []  # no probe


def test_an_off_room_clears_them():
    c, fake = _room("off")
    c.loop_once(datetime(2026, 9, 23, 12, 0))
    for zone in (1, 2):
        state, attrs = fake.sets[f"sensor.crop_steering_zone_{zone}_waiting_for_app"]
        assert (state, attrs["conditions"]) == ("none", [])


def test_a_zone_moved_to_another_phase_this_minute_says_what_the_new_one_waits_for():
    c, fake = _room()
    c.loop_once(datetime(2026, 9, 23, 12, 0))
    assert fake.sets["sensor.crop_steering_zone_1_waiting_for_app"][0] != "P3"
    c.loop_once(datetime(2026, 9, 23, 23, 0))  # lights-off moves the zone to P3 on this pass
    phase, attrs = fake.sets["sensor.crop_steering_zone_1_waiting_for_app"]
    assert phase == c.rooms[0].state[1]["phase"] == "P3"
    assert [item["rule"] for item in attrs["conditions"]] == ["p3_emergency", "lights_on"]
