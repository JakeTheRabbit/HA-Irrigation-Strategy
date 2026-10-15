"""The zone safety status the controller publishes does not flap on a reading that sits on a threshold.

The label still sets at its threshold; it clears only once the reading is a small band back past it and
the label has been shown a few minutes. What the controller shows is what the engine works out from the
label it showed before and how long it has shown it.
"""

from datetime import datetime, timedelta

from test_controller import _build

ZONE = "sensor.crop_steering_zone_1_safety_status"


def _room():
    c, fake = _build(
        {"num_zones": 1, "hardware": {"pump": "switch.p", "mainline": "switch.m",
                                      "valves": {"1": "switch.v1"}}},
        states={"sensor.crop_steering_vwc_zone_1": ("50", {})},
    )
    return c, fake, c.rooms[0]


def _publish(c, fake, room, vwc, ec, now):
    p = c._params(room, 1)
    pub = {1: {"phase": "P2", "vwc": vwc, "ec": ec, "fire": False, "block": None,
               "reason": "hold", "blind": False, "p": p, "vmax": None, "next_h": None}}
    c._publish_status(room, pub, now)
    return fake.sets[ZONE][0], p


def test_a_vwc_jittering_on_field_capacity_gives_one_change_not_many():
    c, fake, room = _room()
    fc = c._params(room, 1).field_capacity
    start = datetime(2026, 1, 1, 12, 0)
    shown = [_publish(c, fake, room, fc - 10, 3.0, start)[0]]
    for minute in range(1, 31):
        vwc = fc + 0.1 if minute % 2 else fc - 0.1
        shown.append(_publish(c, fake, room, vwc, 3.0, start + timedelta(minutes=minute))[0])
    assert shown[0] == "safe" and set(shown[1:]) == {"over_saturated"}
    assert fake.sets["sensor.crop_steering_system_safety_status"][0] == "unsafe"


def test_the_label_clears_past_the_band_after_the_hold():
    c, fake, room = _room()
    fc = c._params(room, 1).field_capacity
    start = datetime(2026, 1, 1, 12, 0)
    assert _publish(c, fake, room, fc, 3.0, start)[0] == "over_saturated"  # at its threshold
    assert _publish(c, fake, room, fc - 10, 3.0, start + timedelta(minutes=1))[0] == "over_saturated"
    assert _publish(c, fake, room, fc - 10, 3.0, start + timedelta(minutes=5))[0] == "safe"
