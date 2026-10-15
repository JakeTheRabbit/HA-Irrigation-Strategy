"""Which of a zone's probes count, and which one is its primary (the Probes page picker).

Both are stored with the zone's setup (`<kind>_unused`, `<kind>_primary`) and change nothing until
someone chooses: every mapped probe counts and none is primary, as before. They map no hardware, so
a save that changes only them is allowed while the room waters.
"""

import asyncio
from types import SimpleNamespace

import pytest

from .test_sensor_weekly_and_fusion import _reported, _zone
from .test_setup import api, payload, rig


def _rig():
    hass, entry, states = rig()
    states["sensor.vwc2"] = SimpleNamespace(
        entity_id="sensor.vwc2", state="52", attributes={"unit_of_measurement": "%"}
    )
    first = payload()
    first["zones"][1]["vwc_sensors"] = ["sensor.vwc", "sensor.vwc2"]
    asyncio.run(api.save_setup(hass, first))
    return hass, entry, states


def _choose(hass, **zone2):
    """What the Probes page sends: each zone's id, whether it is active, and its probe choice."""
    (room,) = api.read_setup(hass)["rooms"]
    zones = [
        {
            k: v
            for k, v in z.items()
            if k == "id" or k == "active" or k in api.PROBE_CHOICE
        }
        for z in room["zones"]
    ]
    zones[1].update(zone2)
    return {
        "entry_id": room["entry_id"],
        "expected_revision": room["revision"],
        "zones": zones,
    }


def test_no_choice_is_stored_or_shown_until_someone_chooses():
    hass, entry, _ = _rig()
    assert not set(entry.data["zones"]["2"]) & api.PROBE_CHOICE
    (room,) = api.read_setup(hass)["rooms"]
    zone = room["zones"][1]
    assert (zone["vwc_unused"], zone["vwc_primary"]) == ([], "")
    assert (zone["ec_unused"], zone["ec_primary"]) == ([], "")


def test_a_probe_choice_alone_is_saved_while_the_room_waters():
    hass, entry, states = _rig()
    states["switch.crop_steering_veg_engine_enabled"].state = "on"
    states["switch.v2"].state = "on"
    revision = entry.data["setup_revision"]
    asyncio.run(
        api.save_setup(
            hass, _choose(hass, vwc_primary="sensor.vwc2", vwc_unused=["sensor.vwc"])
        )
    )
    zone = entry.data["zones"]["2"]
    assert (zone["vwc_primary"], zone["vwc_unused"]) == ("sensor.vwc2", ["sensor.vwc"])
    # No new setup revision: the controller has nothing to take on, so the room keeps watering.
    assert entry.data["setup_revision"] == revision
    # Anything else in the same save still needs the room off.
    with pytest.raises(ValueError, match="OFF"):
        asyncio.run(api.save_setup(hass, _choose(hass, name="Back")))
    # Clearing the choice leaves the zone as it was before anyone chose.
    asyncio.run(api.save_setup(hass, _choose(hass, vwc_primary="", vwc_unused=[])))
    assert not set(entry.data["zones"]["2"]) & api.PROBE_CHOICE


@pytest.mark.parametrize(
    "choice,refused",
    [
        ({"vwc_unused": ["sensor.vwc", "sensor.vwc2"]}, "must count"),
        (
            {"vwc_unused": ["sensor.vwc"], "vwc_primary": "sensor.vwc"},
            "one that counts",
        ),
        ({"vwc_unused": "sensor.vwc"}, "a list"),
    ],
)
def test_a_zone_keeps_a_probe_that_counts_and_its_primary_counts(choice, refused):
    hass, entry, _ = _rig()
    with pytest.raises(ValueError, match=refused):
        asyncio.run(api.save_setup(hass, _choose(hass, **choice)))
    assert not set(entry.data["zones"]["2"]) & api.PROBE_CHOICE


def test_a_zone_given_other_probes_has_its_choice_made_again():
    hass, entry, _ = _rig()
    asyncio.run(
        api.save_setup(
            hass, _choose(hass, vwc_primary="sensor.vwc2", vwc_unused=["sensor.vwc"])
        )
    )
    # The setup page sends the old choice back with a probe unmapped: every probe counts again.
    asyncio.run(api.save_setup(hass, _choose(hass, vwc_sensors=["sensor.vwc"])))
    assert not set(entry.data["zones"]["2"]) & api.PROBE_CHOICE


def test_a_probe_that_does_not_count_is_named_and_the_primary_published():
    states = {
        "sensor.a": _reported(40, "%", 1),
        "sensor.b": _reported(42, "%", 1),
        "sensor.c": _reported(60, "%", 1),
    }
    entity = _zone(
        states,
        vwc_sensors=["sensor.a", "sensor.b", "sensor.c"],
        vwc_unused=["sensor.c"],
        vwc_primary="sensor.b",
    )
    assert entity._get_zone_vwc(1) == 41.0  # the mean of a and b; c does not count
    attributes = entity.extra_state_attributes
    assert attributes["used"] == ["sensor.a", "sensor.b"]
    assert attributes["excluded"] == {"sensor.c": "not counted"}
    assert attributes["primary"] == "sensor.b"


def test_a_primary_that_goes_offline_is_left_out_and_the_others_carry_on():
    states = {"sensor.a": _reported(40, "%", 1), "sensor.b": _reported(46, "%", 1)}
    entity = _zone(states, vwc_sensors=["sensor.a", "sensor.b"], vwc_primary="sensor.b")
    assert entity._get_zone_vwc(1) == 43.0
    states["sensor.b"] = SimpleNamespace(state="unavailable", attributes={})
    assert entity._get_zone_vwc(1) == 43.0  # a, with its learned offset
    attributes = entity.extra_state_attributes
    assert attributes["excluded"] == {"sensor.b": "no reading"}
    assert attributes["primary"] == "sensor.b"


def test_a_zone_with_no_choice_publishes_no_primary():
    states = {"sensor.a": _reported(40, "%", 1)}
    entity = _zone(states, vwc_sensors=["sensor.a"])
    assert entity._get_zone_vwc(1) == 40.0
    assert entity.extra_state_attributes["primary"] is None
