"""A room's no-touch window (Pause AI Changes): while it runs the brain asks nothing and changes nothing in the
room, on either route, and the rules carry on; the panel says when it ends, and once it is over the controller sets
the select back to Off and the brain asks again."""
from datetime import timedelta

import jev_kit as K
from test_brain_wiring import _zone, claude  # noqa: F401 (claude, jev_with: fixtures the tests take by name)
from test_jev_controller import NOW, _p1_zone, jev_with  # noqa: F401

NO_TOUCH = "select.crop_steering_ai_no_touch"


def _choose(fake, option, at):
    fake.set_state(NO_TOUCH, option, {"since": at.astimezone().isoformat()})


def _resets(fake):
    return [d for dom, svc, d in fake.calls if (dom, svc) == ("select", "select_option") and d["entity_id"] == NO_TOUCH]


def test_inside_the_window_the_brain_asks_nothing_and_the_panel_says_when_it_ends(claude):  # noqa: F811
    c, fake = claude()
    _choose(fake, "1 h", NOW - timedelta(minutes=10))
    _zone(c)
    c.loop_once(NOW)
    assert c._client.requests == []
    assert c.rooms[0].state[1]["phase"] == "P1"  # nothing the brain would move was moved
    panel = fake.sets["sensor.crop_steering_jev"][1]
    assert panel["no_touch_until"] == (NOW + timedelta(minutes=50)).isoformat(timespec="minutes")
    assert _resets(fake) == []


def test_once_the_window_is_over_the_select_goes_back_to_off_and_the_brain_asks_again(claude):  # noqa: F811
    c, fake = claude()
    _choose(fake, "1 h", NOW - timedelta(minutes=61))
    _zone(c)
    c.loop_once(NOW)
    assert c._client.requests, "it asked"
    assert _resets(fake)[0]["option"] == "Off"
    assert fake.sets["sensor.crop_steering_jev"][1]["no_touch_until"] is None


def test_off_or_no_select_is_no_window(claude):  # noqa: F811
    c, fake = claude()
    room = c.rooms[0]
    assert c._no_touch_until(room, NOW) is None  # a Home Assistant without the select (an old integration)
    _choose(fake, "Off", NOW)
    assert c._no_touch_until(room, NOW) is None and _resets(fake) == []


def test_until_lights_on_runs_to_the_next_lights_on_and_a_day_runs_a_day(claude):  # noqa: F811
    c, fake = claude()
    room = c.rooms[0]  # lights on at 10:00; chosen at 13:00
    _choose(fake, "Until lights-on", NOW)
    assert c._no_touch_until(room, NOW + timedelta(hours=20)) == NOW + timedelta(hours=21)
    assert c._no_touch_until(room, NOW + timedelta(hours=21)) is None and _resets(fake)
    _choose(fake, "24 h", NOW)
    assert c._no_touch_until(room, NOW + timedelta(hours=23)) == NOW + timedelta(hours=24)


def test_the_legacy_route_asks_nothing_inside_the_window(jev_with):  # noqa: F811
    c, fake = jev_with(K.both("ramp_state", K.choice_answer("ec_is_feed_front", {"ec_is_feed_front": 0.8})))
    _choose(fake, "24 h", NOW - timedelta(hours=1))
    _p1_zone(c)
    c.loop_once(NOW)
    assert c._jev_transport.calls == []
    assert c.rooms[0].state[1]["phase"] == "P1"
