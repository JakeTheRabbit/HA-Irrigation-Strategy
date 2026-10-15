"""What a saved room setup change is recorded as: the words setup_api.setup_changes gives the
logbook and the log, from the room the setup page showed and the room saved."""

from copy import deepcopy

from custom_components.crop_steering.setup_api import (
    HARDWARE_DOMAINS,
    HARDWARE_WORDS,
    setup_changes,
)


def room():
    """A room as setup_room gives it: what Rooms & hardware shows and sends back."""
    return {
        "room_name": "Crop Steering System",
        "active": True,
        "plumbing": "pump_valves",
        "hardware": {"pump_switch": "switch.irrigation_pump", "light_entity": ""},
        "zones": [
            {
                "id": 1,
                "name": "Bench 1",
                "active": True,
                "valve": "switch.bench_1_valve",
                "vwc_sensors": ["sensor.probe_a_vwc", "sensor.probe_b_vwc"],
                "ec_sensors": ["sensor.probe_a_ec", "sensor.probe_b_ec"],
                "plant_count": 40,
                "substrate_volume": 3.2,
                "drippers_per_plant": 1,
                "dripper_flow_rate": 4,
            }
        ],
    }


def test_every_mapping_the_setup_page_saves_has_its_words():
    assert set(HARDWARE_WORDS) == set(HARDWARE_DOMAINS)


def test_a_rename_is_said_as_a_rename_and_nothing_else():
    new = room()
    new["room_name"] = "Back room"
    assert setup_changes(room(), new) == ["renamed from “Crop Steering System”"]


def test_a_save_that_changes_nothing_says_nothing():
    same = room()
    # The page may send a whole number back as a float.
    same["zones"][0]["plant_count"] = 40.0
    assert setup_changes(room(), same) == []


def test_mappings_probes_and_sizing_say_what_they_were_and_are():
    new = room()
    new["hardware"] = {
        "pump_switch": "",
        "light_entity": "light.room",
        "feed_ec_sensor": "sensor.feed_ec",
    }
    new["plumbing"] = "valves_only"
    zone = new["zones"][0]
    zone.update(
        valve="switch.bench_1_valve_b",
        vwc_sensors=["sensor.probe_a_vwc"],
        substrate_volume=3.3,
    )
    assert setup_changes(room(), new) == [
        "plumbing: zone valves only",
        "pump switch.irrigation_pump → none",
        "lights none → light.room",
        "feed EC sensor none → sensor.feed_ec",
        "zone 1 valve switch.bench_1_valve → switch.bench_1_valve_b",
        "zone 1 moisture probes sensor.probe_a_vwc, sensor.probe_b_vwc → sensor.probe_a_vwc",
        "zone 1 pot volume (L) 3.2 → 3.3",
    ]


def test_zones_added_renamed_archived_and_the_room_archived_and_restored():
    new = room()
    new["zones"][0].update(name="Bench 1 door end", active=False)
    new["zones"].append({**deepcopy(room()["zones"][0]), "id": 2, "name": "Zone 2"})
    assert setup_changes(room(), new) == [
        "zone 1 archived",
        "zone 1 renamed from “Bench 1” to “Bench 1 door end”",
        "zone 2 added",
    ]
    archived = {**room(), "active": False}
    assert setup_changes(room(), archived) == ["archived"]
    assert setup_changes(archived, room()) == ["restored"]
