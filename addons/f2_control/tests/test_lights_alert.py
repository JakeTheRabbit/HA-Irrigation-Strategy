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
    assert "lights on at 7:00 and off at 20:00" in alert["message"]
    assert f"still says {hours[0]}:00-{hours[1]}:00" in alert["message"]


def test_a_legacy_room_is_still_told_even_on_the_shipped_hours():
    """UPGRADE IN PLACE. A legacy box may be growing on exactly 10-22 from the option."""
    (alert,) = _lights_alerts(_legacy_room(), SHIPPED)
    assert "10:00-22:00" in alert["message"]
