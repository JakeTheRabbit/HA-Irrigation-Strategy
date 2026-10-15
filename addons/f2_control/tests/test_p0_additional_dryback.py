"""P0 additional dryback reaches decide() from the zone's own setting,
number.crop_steering_<prefix>zone_N_p0_additional_dryback. An integration older than the setting has no
such number: the controller then uses 0 (off), so P0 waits for the dryback target as it always has,
and raises no missing-setting alert.
"""
from test_controller import _build

ZONE = "number.crop_steering_zone_1_p0_additional_dryback"
ROOM = "number.crop_steering_p0_additional_dryback"
HARDWARE = {"pump": "switch.p", "mainline": "switch.m", "valves": {"1": "switch.v1"}}


def _params(states):
    c, _fake = _build({"num_zones": 1, "hardware": HARDWARE}, states=states)
    room = c.rooms[0]
    return c, room, c._params(room, 1)


def test_the_zones_own_value_reaches_the_engine():
    _c, _room, p = _params({ZONE: ("3", {})})
    assert p.p0_additional_dryback == 3.0


def test_an_integration_without_it_leaves_p0_off_and_alerts_nothing():
    c, _room, p = _params({})
    assert p.p0_additional_dryback == 0.0
    assert ROOM not in c._defaulted_this_loop and ZONE not in c._defaulted_this_loop


def test_the_old_p0_setting_is_still_not_read():
    """The older P0 drop percent stays unread: reading it would make every upgraded room's P0 wait."""
    _c, _room, p = _params({"number.crop_steering_zone_1_p0_dryback_drop_percent": ("24", {})})
    assert p.p0_additional_dryback == 0.0
