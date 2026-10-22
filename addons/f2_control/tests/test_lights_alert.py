""""Lights now read from the integration" is for the operator it can help, not every new install.

First real install: the wizard was told the lights hours, and the first notification was "The
add-on option still says 10:00-22:00": a setting the operator had never made or seen (it is the
shipped default, the hours of the facility this was first written for).
"""
from datetime import datetime

import pytest

import controller
from test_controller import _build
from test_zone_count import KILL, _room

NOW = datetime(2026, 9, 21, 14, 0, 0)
LEGACY = "input_boolean.f2_control_enabled"
SHIPPED = {"num_zones": 3, "enable_flag": LEGACY, "lights_on_hour": 10, "lights_off_hour": 22}


def _lights_alerts(states, options):
    states = dict(states)
    states["number.crop_steering_lights_on_hour"] = ("7", {})
    states["number.crop_steering_lights_off_hour"] = ("20", {})
    c, fake = _build(dict(options), states=states)
    c.loop_once(NOW)
    assert (c.rooms[0].lights_on_hour, c.rooms[0].lights_off_hour) == (7.0, 20.0)  # never in question
    return [d for dom, svc, d in fake.calls
            if (dom, svc) == ("persistent_notification", "create") and d["notification_id"] == "f2_lights_source"]


def _legacy_room():
    """An install from before the wizard had its own kill switch: the helper, revision zero."""
    states = _room(3, revision=0)
    states[controller_descriptor()][1]["enable_flag"] = LEGACY
    states[LEGACY] = ("off", {})
    return states


def controller_descriptor():
    return "sensor.crop_steering_engine_config"


def test_the_shipped_options_match_what_this_test_calls_shipped():
    import yaml  # the add-on's own config.yaml is the authority
    from pathlib import Path

    options = yaml.safe_load((Path(controller.__file__).parents[1] / "config.yaml").read_text())["options"]
    assert (float(options["lights_on_hour"]), float(options["lights_off_hour"])) == controller.SHIPPED_LIGHTS


def test_a_wizard_made_room_on_untouched_options_hears_nothing():
    assert _room(1)["sensor.crop_steering_engine_config"][1]["enable_flag"] == KILL
    assert _lights_alerts(_room(1), SHIPPED) == []  # fired on every fresh install


def test_options_written_before_the_lights_option_existed_count_as_untouched():
    assert _lights_alerts(_room(1), {"num_zones": 3, "enable_flag": LEGACY}) == []


@pytest.mark.parametrize("hours", [(8, 20), (10, 20), (6, 22)])
def test_a_wizard_made_room_whose_operator_set_the_option_is_still_told(hours):
    """Somebody typed those hours. The engine is about to use different ones: say so."""
    options = {**SHIPPED, "lights_on_hour": hours[0], "lights_off_hour": hours[1]}
    (alert,) = _lights_alerts(_room(1), options)
    assert "lights-on at 7:00 and lights-off at 20:00" in alert["message"]
    assert f"still says {hours[0]}:00-{hours[1]}:00" in alert["message"]


def test_a_legacy_room_is_still_told_even_on_the_shipped_hours():
    """UPGRADE IN PLACE. A legacy box may be growing on exactly 10-22 from the option."""
    (alert,) = _lights_alerts(_legacy_room(), SHIPPED)
    assert "10:00-22:00" in alert["message"]


def test_one_unreadable_loop_keeps_the_integration_hours():
    """Home Assistant restarting, an integration reload or a timed-out read made one loop fall back
    to the app's option: at 08:30, with the integration on 7-20 and the option on 10-22, the room
    read lights-off and was forced to P3, and the next loop's lights-on edge restarted its day."""
    states = dict(_room(1))
    states["number.crop_steering_lights_on_hour"] = ("7", {})
    states["number.crop_steering_lights_off_hour"] = ("20", {})
    c, fake = _build(dict(SHIPPED), states=states)
    c.loop_once(datetime(2026, 9, 21, 8, 29))
    fake.set_state("number.crop_steering_lights_on_hour", "unavailable")
    c.loop_once(datetime(2026, 9, 21, 8, 30))
    assert (c.rooms[0].lights_on_hour, c.rooms[0].lights_off_hour) == (7.0, 20.0)


def _equal_hours_alerts(fake):
    return [d for dom, svc, d in fake.calls
            if (dom, svc) == ("persistent_notification", "create") and "CS-401" in d["message"]
            and "same hour" in d["message"]]


def test_lights_on_and_off_at_the_same_hour_keep_the_last_hours_read():
    """CTL-030. Both hour entities take any hour from 0 to 23, so lights-on can equal lights-off (a 24 h
    schedule typed as 0 and 0, or one step of swapping the two hours). Equal hours read as lights never
    on: every zone was held in its overnight phase all day, and a blind zone got no water at all. Setup
    refuses equal hours; the controller does not use them, keeps the hours it last read, and says so."""
    states = dict(_room(1))
    states["number.crop_steering_lights_on_hour"] = ("7", {})
    states["number.crop_steering_lights_off_hour"] = ("20", {})
    c, fake = _build(dict(SHIPPED), states=states)
    c.loop_once(datetime(2026, 9, 21, 13, 59))
    fake.set_state("number.crop_steering_lights_on_hour", "20")
    c.loop_once(NOW)
    room = c.rooms[0]
    assert (room.lights_on_hour, room.lights_off_hour) == (7.0, 20.0)
    assert c._lights_on(room, NOW)
    (alert,) = _equal_hours_alerts(fake)
    assert "20:00" in alert["message"] and "7:00-20:00" in alert["message"]


def test_the_same_hour_with_no_hours_read_since_start_uses_the_option_hours():
    """A restart with the two entities already equal: nothing usable read yet, so the option's hours, as
    for entities that cannot be read, and the alert."""
    states = dict(_room(1))
    states["number.crop_steering_lights_on_hour"] = ("0", {})
    states["number.crop_steering_lights_off_hour"] = ("0", {})
    c, fake = _build(dict(SHIPPED), states=states)
    c.loop_once(NOW)
    room = c.rooms[0]
    assert (room.lights_on_hour, room.lights_off_hour) == (10.0, 22.0)
    assert c._lights_on(room, NOW)
    (alert,) = _equal_hours_alerts(fake)
    assert "0:00" in alert["message"] and "10:00-22:00" in alert["message"]


@pytest.mark.parametrize("on, off, lit", [
    (10, 22, set(range(10, 22))),
    (22, 10, set(range(22, 24)) | set(range(0, 10))),
])
def test_the_lights_hours_that_differ_read_as_before(on, off, lit):
    states = dict(_room(1))
    states["number.crop_steering_lights_on_hour"] = (str(on), {})
    states["number.crop_steering_lights_off_hour"] = (str(off), {})
    c, fake = _build(dict(SHIPPED), states=states)
    c.loop_once(NOW)
    room = c.rooms[0]
    assert (room.lights_on_hour, room.lights_off_hour) == (float(on), float(off))
    assert {h for h in range(24) if c._lights_on(room, datetime(2026, 9, 21, h, 30))} == lit
    assert _equal_hours_alerts(fake) == []
