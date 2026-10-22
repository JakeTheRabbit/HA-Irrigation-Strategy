"""Dashboards from templates (G11): render() names only entities the room has, refuses an unknown
template, and a new dashboard takes the lowest free number."""

import pytest

from . import ha_stubs

ha_stubs.install()

from custom_components.crop_steering import dashboards  # noqa: E402

F2 = {
    "room_id": "room:f2_",
    "name": "F2",
    "zones": [{"zone": 1, "name": "Bench 1"}, {"zone": 2, "name": "Bench 2"}],
    # Zone 2 has no EC probe, and the room maps no feed pH probe and no tank.
    "entities": [
        "sensor.crop_steering_f2_current_phase",
        "sensor.crop_steering_f2_configured_avg_vwc",
        "switch.crop_steering_f2_room_active",
        "sensor.crop_steering_f2_vwc_zone_1",
        "sensor.crop_steering_f2_ec_zone_1",
        "sensor.crop_steering_f2_zone_1_status",
        "sensor.crop_steering_f2_vwc_zone_2",
        "sensor.crop_steering_f2_zone_2_status",
        "sensor.crop_steering_f2_dosing_config",
        "sensor.feed_ec",
    ],
    "hardware": {"feed_ec_sensor": "sensor.feed_ec"},
}
VEG = {
    "room_id": "room:veg_",
    "name": "Veg",
    "zones": [{"zone": 1, "name": "Zone 1"}],
    "entities": ["sensor.crop_steering_veg_current_phase"],
    "hardware": {},
}


def _named(node):
    """Every entity id a Lovelace config names."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "entity":
                yield value
            elif key == "entities":
                yield from (e if isinstance(e, str) else e["entity"] for e in value)
            else:
                yield from _named(value)
    elif isinstance(node, list):
        for item in node:
            yield from _named(item)


ALLOWED_CARDS = {"entities", "gauge", "tile", "history-graph"}


def _cards(config):
    return [card for view in config["views"] for card in view["cards"]]


@pytest.mark.parametrize(
    "template, rooms",
    [
        ("facility_wall", [F2, VEG]),
        ("room_tablet", [F2]),
        ("dosing_station", [F2, VEG]),
    ],
)
def test_each_template_renders_only_entities_the_room_has(template, rooms):
    config = dashboards.render(template, rooms)
    assert config["views"] and _cards(config)
    assert {card["type"] for card in _cards(config)} <= ALLOWED_CARDS
    named = set(_named(config))
    assert named and named <= {e for room in rooms for e in room["entities"]}


def test_the_room_tablet_shows_each_zone_and_the_dosing_station_the_feed():
    tablet = set(_named(dashboards.render("room_tablet", [F2])))
    assert {
        "sensor.crop_steering_f2_zone_1_status",
        "sensor.crop_steering_f2_zone_2_status",
    } <= tablet
    assert "sensor.crop_steering_f2_ec_zone_2" not in tablet
    station = set(_named(dashboards.render("dosing_station", [F2])))
    assert {"sensor.feed_ec", "sensor.crop_steering_f2_dosing_config"} <= station


def test_unknown_template_is_refused():
    with pytest.raises(ValueError, match="Unknown dashboard template"):
        dashboards.render("kiosk", [F2])


def test_a_room_tablet_takes_exactly_one_room():
    with pytest.raises(ValueError, match="exactly one"):
        dashboards.render("room_tablet", [F2, VEG])


def test_the_number_is_the_lowest_free_one():
    used = {
        "crop-steering-room_tablet-1",
        "crop-steering-room_tablet-3",
        "crop-steering-facility_wall-2",
    }
    assert dashboards.url_path_for("room_tablet", used) == "crop-steering-room_tablet-2"
    assert (
        dashboards.url_path_for("facility_wall", used)
        == "crop-steering-facility_wall-1"
    )
    assert dashboards.TEMPLATES == ("facility_wall", "room_tablet", "dosing_station")


def test_a_dashboard_that_would_name_no_entity_is_refused():
    with pytest.raises(ValueError, match="would show nothing"):
        dashboards.render("dosing_station", [VEG])
