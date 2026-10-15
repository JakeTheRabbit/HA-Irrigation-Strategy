"""CS-505: the probe a zone's setup names primary goes offline.

The integration publishes the zone's primary probe (`primary`) and why it left any probe out of the
zone's reading (`excluded`). The reading carries on from the other probes; the controller says so
once while the primary stays offline, and takes the card down when it reports again.
"""
from datetime import datetime, timedelta

from test_clamp_alert import _alerts
from test_controller import _build
from test_zone_count import _room

NOW = datetime(2026, 9, 21, 14, 0, 0)
VWC = "sensor.crop_steering_vwc_zone_1"
KEY = "f2_probe_primary_default_z1_vwc"


def _controller(**fusion):
    states = _room(2)
    states[VWC] = ("51", {"unit_of_measurement": "%", **fusion})
    return _build({"num_zones": 2, "enable_flag": "input_boolean.f2_control_enabled"}, states=states)


def _primary_alerts(fake):
    return [a for a in _alerts(fake) if a["notification_id"] == KEY]


def test_the_primary_going_offline_is_told_once_per_episode():
    c, fake = _controller(primary="sensor.b", used=["sensor.a"], excluded={"sensor.b": "no reading"})
    c.loop_once(NOW)
    (alert,) = _primary_alerts(fake)
    assert alert["title"].endswith("the primary moisture probe is offline (CS-505)")
    assert "sensor.b" in alert["message"] and "carries on from its other probes" in alert["message"]
    for minutes in (40, 80):  # past any repeat window: still once
        c.loop_once(NOW + timedelta(minutes=minutes))
    assert len(_primary_alerts(fake)) == 1

    # It reports again: the card goes, and a later outage is told again.
    fake.set_state(VWC, "51", {"primary": "sensor.b", "used": ["sensor.a", "sensor.b"], "excluded": {}})
    c.loop_once(NOW + timedelta(minutes=90))
    assert any(
        (domain, service, data.get("notification_id")) == ("persistent_notification", "dismiss", KEY)
        for domain, service, data in fake.calls
    )
    fake.set_state(VWC, "51", {"primary": "sensor.b", "used": ["sensor.a"], "excluded": {"sensor.b": "not reporting"}})
    c.loop_once(NOW + timedelta(minutes=100))
    assert len(_primary_alerts(fake)) == 2


def test_no_primary_or_a_primary_that_reads_hears_nothing():
    for fusion in (
        {"used": ["sensor.a"], "excluded": {"sensor.b": "no reading"}},  # none chosen: as before
        {"primary": "sensor.a", "used": ["sensor.a"], "excluded": {"sensor.b": "no reading"}},
        {"primary": "sensor.b", "used": ["sensor.a"], "excluded": {"sensor.b": "far from the others"}},
        {},  # an older integration
    ):
        c, fake = _controller(**fusion)
        c.loop_once(NOW)
        assert _primary_alerts(fake) == [], fusion
