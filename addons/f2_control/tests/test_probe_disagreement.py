"""CS-502: a zone set to steer on its Lowest or Highest probe, with too few probes that agree.

The integration combines a zone's probes (calculations.fuse_probes) and publishes the method the
zone chose (`method`) and the one it steered by (`steered_by`). Lowest and Highest let one probe
steer the zone, so with fewer than three probes that agree it steers on their median instead; the
controller says so, once per zone and reading, and waters on as normal.
"""
from datetime import datetime

from test_clamp_alert import _alerts
from test_controller import _build
from test_zone_count import _room

NOW = datetime(2026, 9, 21, 14, 0, 0)
VWC = "sensor.crop_steering_vwc_zone_1"


def _loop(**fusion):
    states = _room(2)
    states[VWC] = ("51", {"unit_of_measurement": "%", **fusion})
    c, fake = _build({"num_zones": 2, "enable_flag": "input_boolean.f2_control_enabled"}, states=states)
    c.loop_once(NOW)
    return [a for a in _alerts(fake) if a["notification_id"].startswith("f2_probe_method_")]


def test_lowest_with_too_few_probes_that_agree_is_told_once_and_names_the_probe_left_out():
    (alert,) = _loop(
        method="Lowest",
        steered_by="Median",
        used=["sensor.a", "sensor.b"],
        excluded={"sensor.c": "far from the others"},
    )
    assert alert["title"].endswith("too few moisture probes agree for Lowest (CS-502)")
    assert alert["notification_id"] == "f2_probe_method_default_z1_vwc"
    assert "steers on their median" in alert["message"] and "sensor.c" in alert["message"]


def test_a_zone_steering_as_chosen_hears_nothing():
    assert _loop(method="Lowest", steered_by="Lowest") == []
    assert _loop(method="Median", steered_by="Median") == []


def test_an_older_integration_or_a_probe_mapped_straight_to_the_controller_hears_nothing():
    """No `method` attribute: an integration from before the selects, or a raw probe."""
    assert _loop() == []


# CS-504: a zone with pore and bulk EC probes steering on bulk, as no pore EC probe reports.
EC = "sensor.crop_steering_ec_zone_1"


def _ec_loop(**fusion):
    states = _room(2)
    states[EC] = ("1.2", {"unit_of_measurement": "mS/cm", **fusion})
    c, fake = _build({"num_zones": 2, "enable_flag": "input_boolean.f2_control_enabled"}, states=states)
    c.loop_once(NOW)
    return [a for a in _alerts(fake) if a["notification_id"].startswith("f2_ec_type_")]


def test_a_zone_steering_on_bulk_ec_is_told_and_names_the_pore_probe_left_out():
    (alert,) = _ec_loop(ec_type="bulk", used=["sensor.bulk"], excluded={"sensor.pore": "no reading"})
    assert alert["title"].endswith("zone EC from bulk EC: no pore EC probe reports (CS-504)")
    assert alert["notification_id"] == "f2_ec_type_default_z1"
    assert "sensor.pore" in alert["message"] and EC in alert["message"]


def test_a_zone_steering_on_pore_ec_or_an_older_integration_hears_nothing():
    assert _ec_loop(ec_type="pore", excluded={"sensor.bulk": "bulk EC, kept apart from pore EC"}) == []
    assert _ec_loop() == []
