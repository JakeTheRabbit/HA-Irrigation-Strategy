"""A notification calls a zone what the operator called it.

First real install: zones named GT1 and GT4, and the phone said "default Z2 probe dead". The
operator's answer: "I don't have a zone_2". The room's descriptor has carried `zone_names` all
along; the controller never read it.
"""
from datetime import datetime

from test_controller import _build
from test_zone_count import DESCRIPTOR, _room

NOW = datetime(2026, 9, 21, 14, 0, 0)
OPTIONS = {"num_zones": 3, "enable_flag": "input_boolean.f2_control_enabled"}


def _dead_probe_alerts(states):
    for zone in (1, 2):  # no live moisture reading in either zone
        states[f"sensor.crop_steering_vwc_zone_{zone}"] = ("unavailable", {})
    c, fake = _build(dict(OPTIONS), states=states)
    c.loop_once(NOW)
    alerts = {d["notification_id"]: d for dom, svc, d in fake.calls
              if (dom, svc) == ("persistent_notification", "create")}
    return c, alerts, fake


def test_a_named_zone_is_named_and_its_number_is_still_there():
    states = _room(2)
    states[DESCRIPTOR][1]["zone_names"] = {"1": "GT1", "2": "GT4"}
    _c, alerts, _fake = _dead_probe_alerts(states)
    title = alerts["f2_blind_default_z2"]["title"]
    assert title == "GT4 (Z2): moisture sensor not reporting (CS-102)"
    assert alerts["f2_blind_default_z1"]["title"].startswith("GT1 (Z1): ")


def test_ids_entities_and_log_lines_keep_the_number():
    """Nothing that is looked up by id may follow a friendly name."""
    states = _room(2)
    states[DESCRIPTOR][1]["zone_names"] = {"1": "GT1", "2": "GT4"}
    _c, alerts, fake = _dead_probe_alerts(states)
    assert set(alerts) >= {"f2_blind_default_z1", "f2_blind_default_z2"}
    assert "sensor.crop_steering_vwc_zone_2" in alerts["f2_blind_default_z2"]["message"]
    assert not [entity_id for entity_id in fake.sets if "gt4" in entity_id.lower()]


def test_a_rename_in_configure_reaches_the_next_notification_without_a_new_setup_revision():
    states = _room(2)
    c, _alerts, fake = _dead_probe_alerts(states)
    assert c.rooms[0].zone_names == {}
    descriptor = dict(_room(2)[DESCRIPTOR][1], zone_names={"1": "Bench A", "2": "Bench B"})
    fake.set_state(DESCRIPTOR, "default", descriptor)
    c._rediscover(NOW)
    assert c.rooms[0].zone_names == {1: "Bench A", 2: "Bench B"}


def test_an_install_without_names_gets_the_zone_number():
    """UPGRADE IN PLACE: an older integration publishes no zone_names, a newer one publishes
    "Zone N" for a zone nobody named, and either may hold rubbish."""
    for names in (None, {"1": "Zone 1", "2": "Zone 2"}, "rubbish", {"x": "A", "2": 7, "1": "  "}):
        states = _room(2)
        if names is None:
            states[DESCRIPTOR][1].pop("zone_names", None)
        else:
            states[DESCRIPTOR][1]["zone_names"] = names
        _c, alerts, _fake = _dead_probe_alerts(states)
        assert alerts["f2_blind_default_z2"]["title"] == "Zone 2: moisture sensor not reporting (CS-102)", names
