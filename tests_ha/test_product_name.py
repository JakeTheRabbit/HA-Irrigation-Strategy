"""The product's name in what a user reads, on old installs, with every machine id kept.

An upgraded 2.25.1 room (tests_ha/fixtures/entry_2_25_1_pumped_room.json) and an upgraded 3.11.1 room
with Jev on (entry_3_11_1_pumped_room.json): the controller's first pass publishes the same entities
with every attribute name the old code published (recorded below from the 3.11.1 controller on these
fixtures), `sensor.f2_control_vitals` and the `f2_vitals` notification among them, and no value says
"f2-control": the `engine` attribute names the Crop Steering Controller.
"""

import json
from datetime import datetime

import pytest
from conftest import fixture
from test_upgrade_in_place import JEV_3_11_1, KILL, UPSTREAM_2_25_1, _jev_3_11_1_app, _upgrade

PRODUCT = "Crop Steering Controller"
WATER = ["device_class", "engine", "friendly_name", "state_class", "unit_of_measurement"]
WEEK = [
    "complete_grow_days",
    "coverage",
    "device_class",
    "engine",
    "friendly_name",
    "history_complete",
    "legacy_volume_excluded_l",
    "measurement",
    "observed_grow_days",
    "state_class",
    "unit_of_measurement",
    "window_end_grow_day",
    "window_start_grow_day",
]
SAFETY = [
    "ec",
    "ec_degraded",
    "ec_fallback",
    "ec_settled",
    "ec_valid",
    "field_capacity",
    "max_ec_limit",
    "vwc",
]
SETPOINTS = [
    "day_rate",
    "engine",
    "friendly_name",
    "frozen_reason",
    "gain",
    "hold_days",
    "jev",
    "jev_changed_today",
    "jev_last",
    "last_change",
    "learned_peak",
    "managed",
    "managed_by",
    "night_rate",
    "p1_outcome",
    "updated",
    "working_peak_adjust",
]
# What the 3.11.1 controller published on its first pass over these rooms: entity -> attribute names.
BOTH = {
    "sensor.crop_steering_activity_log": ["event_count", "feed"],
    "sensor.crop_steering_ai_heartbeat": [
        "controller_version",
        "enable_flag",
        "engine",
        "hardware_fault",
        "last_beat",
        "room_active",
        "setup_active",
        "setup_lifecycle_version",
        "setup_pending",
        "setup_revision",
        "strategy_error",
        "strategy_required",
        "strategy_snapshot_version",
    ],
    "sensor.crop_steering_app_current_phase": ["friendly_name"],
    "sensor.crop_steering_app_status": ["engine", "updated"],
    "sensor.crop_steering_current_decision": ["blocked", "fired"],
    "sensor.crop_steering_system_safety_status": ["safe_zones", "unsafe_zones", "warning_zones"],
    "sensor.f2_control_vitals": ["live", "vitals"],
}
for _z in (1, 2):
    BOTH |= {
        f"sensor.crop_steering_zone_{_z}_daily_water_app": WATER,
        f"sensor.crop_steering_zone_{_z}_irrigation_count_app": [
            "engine",
            "friendly_name",
            "state_class",
        ],
        f"sensor.crop_steering_zone_{_z}_last_irrigation_app": ["device_class"],
        f"sensor.crop_steering_zone_{_z}_phase": ["engine", "reason"],
        f"sensor.crop_steering_zone_{_z}_safety_status": SAFETY,
        f"sensor.crop_steering_zone_{_z}_status_app": ["engine", "friendly_name", "reason"],
        f"sensor.crop_steering_zone_{_z}_waiting_for_app": [
            "at",
            "conditions",
            "engine",
            "friendly_name",
        ],
        f"sensor.crop_steering_zone_{_z}_weekly_water_app": WEEK,
    }
ONLY_2_25_1 = {
    "sensor.crop_steering_prediction_zone_2_next_irrigation_hours": [
        "engine",
        "friendly_name",
        "unit_of_measurement",
    ],
    "sensor.crop_steering_zone_1_auto_setpoints": SETPOINTS,
    "sensor.crop_steering_zone_2_auto_setpoints": SETPOINTS,
}
ONLY_3_11_1 = {
    "sensor.crop_steering_jev": [
        "calls_today",
        "daily_budget",
        "engine",
        "errors_today",
        "failovers_today",
        "friendly_name",
        "input_tokens_today",
        "judge_errors",
        "judges",
        "last_error",
        "last_route",
        "reasks_today",
        "retries_today",
        "routes",
        "stage",
    ],
    "sensor.crop_steering_jev_log": ["engine", "entries", "friendly_name"],
    "sensor.crop_steering_zone_1_jev": ["engine", "friendly_name", "judges", "strict"],
    "sensor.crop_steering_zone_2_jev": ["engine", "friendly_name", "judges", "strict"],
}


async def _first_pass(hass, controller_for, monkeypatch, name):
    seed = fixture(name)
    await _upgrade(hass, name, registry_ids=seed["registry"])
    hass.states.async_set(KILL, "on")  # armed and growing: nobody is going to disarm it
    if name == UPSTREAM_2_25_1:
        c, fake, _clock = controller_for(
            seed["addon_options"], saved_state=seed["controller_saved"]
        )
        c.loop_once(datetime(2026, 9, 23, 12, 0))
        return fake, BOTH | ONLY_2_25_1
    c, fake, _built, usage, _state = _jev_3_11_1_app(
        controller_for, monkeypatch, "options_3_11_1_jev_cf.json"
    )
    c.loop_once(datetime.fromisoformat(usage["day"]).replace(hour=12))
    return fake, BOTH | ONLY_3_11_1


@pytest.mark.parametrize("name", [UPSTREAM_2_25_1, JEV_3_11_1])
async def test_an_old_room_keeps_every_id_and_attribute_name_and_reads_the_product_name(
    hass, controller_for, monkeypatch, name
):
    fake, published = await _first_pass(hass, controller_for, monkeypatch, name)

    for entity_id, names in published.items():
        assert entity_id in fake.sets, entity_id
        assert set(names) <= set(fake.sets[entity_id][1]), entity_id
    assert any(
        (dom, svc, d.get("notification_id")) == ("persistent_notification", "create", "f2_vitals")
        for dom, svc, d in fake.calls
    )
    assert fake.sets["sensor.f2_control_vitals"][1]["friendly_name"] == "Crop Steering vitals"

    engines = {a["engine"] for _state, a in fake.sets.values() if "engine" in a}
    assert engines == {PRODUCT}
    shown = json.dumps([fake.sets, fake.calls], default=str).lower()
    assert "f2-control" not in shown
