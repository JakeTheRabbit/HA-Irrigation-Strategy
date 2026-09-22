"""zone_N_status has one writer: the integration. The controller publishes its label on
zone_N_status_app, which the integration's sensor mirrors. Both used to write zone_N_status, and it
flipped between "Dry - Needs Water" (the integration's fixed 40 % threshold) and the controller's
phase-aware label about twice a minute."""
from datetime import datetime

import controller
from test_controller import _build

KILL = "input_boolean.kill"
HARDWARE = {"pump": "switch.p", "mainline": "switch.m", "valves": {"1": "switch.v1", "2": "switch.v2"}}


def _room(room_active="on"):
    c, fake = _build({"num_zones": 2, "hardware": HARDWARE, "enable_flag": KILL})
    for eid in ("switch.p", "switch.m", "switch.v1", "switch.v2"):
        fake.set_state(eid, "off")
    fake.set_state("switch.crop_steering_room_active", room_active)
    fake.set_state("sensor.crop_steering_vwc_zone_1", "55")
    fake.set_state("sensor.crop_steering_ec_zone_1", "5")  # zone 2 has no probe: the blind label
    return c, fake


def test_the_controller_publishes_each_zone_label_on_its_own_entity_and_never_on_the_integrations():
    c, fake = _room()
    c.loop_once(datetime(2026, 9, 23, 12, 0))
    assert fake.sets["sensor.crop_steering_zone_1_status_app"][0] == "Optimal"
    assert fake.sets["sensor.crop_steering_zone_2_status_app"][0] == "Probe dead — copying"
    label, attrs = fake.sets["sensor.crop_steering_zone_1_status_app"]
    assert "reason" in attrs
    assert not {"sensor.crop_steering_zone_1_status", "sensor.crop_steering_zone_2_status"} & set(fake.sets)


def test_an_off_room_says_so_on_the_same_entity():
    c, fake = _room("off")
    c.loop_once(datetime(2026, 9, 23, 12, 0))
    assert fake.sets["sensor.crop_steering_zone_1_status_app"] == (
        "Room off", {"reason": "Room off (nothing growing)", "friendly_name": "Zone 1 status (controller)",
                     "engine": "f2-control"})
    assert "sensor.crop_steering_zone_1_status" not in fake.sets


def test_the_publisher_names_the_rooms_prefix():
    room = controller.Room("f1", "f1_", {1: {}}, {"pump": None, "mainline": None, "valves": {1: "switch.f1_v1"}},
                           "switch.crop_steering_f1_engine_enabled", "", "", 10, 22)
    published = {}
    original = controller.ha_set
    controller.ha_set = lambda entity, state, attributes=None: published.update({entity: state})
    try:
        controller.Controller._publish_zone_status(room, 1, "Optimal", "in band")
    finally:
        controller.ha_set = original
    assert published == {"sensor.crop_steering_f1_zone_1_status_app": "Optimal"}
