"""The "setting outside the engine's range" alert is for anybody's room, and says what to do.

First real install: a tent set its field capacity to 95 %, which the number entity accepts and the
engine limits to 90. The notification was titled "F2 config clamp": F2 is one facility's room
name, and nothing in the text said the value had been limited, or how to clear it.
"""
from datetime import datetime

from test_controller import _build
from test_zone_count import _room

NOW = datetime(2026, 9, 21, 14, 0, 0)


def _alerts(fake):
    return [d for dom, svc, d in fake.calls if (dom, svc) == ("persistent_notification", "create")]


def _loop(states):
    c, fake = _build({"num_zones": 3, "enable_flag": "input_boolean.f2_control_enabled"}, states=states)
    c.loop_once(NOW)
    return [a for a in _alerts(fake) if a["notification_id"].startswith("f2_cfg_")]


def test_a_value_the_engine_limits_is_reported_in_words_anyone_can_act_on():
    states = _room(1)
    states["number.crop_steering_zone_1_field_capacity"] = ("95", {})
    (alert,) = _loop(states)
    assert "F2" not in alert["title"] and "range" in alert["title"]
    assert "field_capacity=95" in alert["message"] and "90" in alert["message"]
    assert "nearest allowed value" in alert["message"] and alert["title"].endswith("(CS-401)")
    assert alert["notification_id"] == "f2_cfg_default_z1_field_capacity"  # same id: it replaces the old card


def test_a_room_inside_the_range_hears_nothing():
    """Every working install: no new notification after the update."""
    assert _loop(_room(1)) == []


def test_the_alert_names_the_zone_the_way_every_other_notification_does():
    from test_zone_count import DESCRIPTOR

    states = _room(1)
    states[DESCRIPTOR][1]["zone_names"] = {"1": "GT1"}
    states["number.crop_steering_zone_1_field_capacity"] = ("95", {})
    (alert,) = _loop(states)
    assert alert["title"].startswith("GT1 (Z1): ") and "default" not in alert["title"]
    assert alert["notification_id"] == "f2_cfg_default_z1_field_capacity"
