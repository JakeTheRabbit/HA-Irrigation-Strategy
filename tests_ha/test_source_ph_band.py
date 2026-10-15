"""The source-water pH band: 5.5-6.5 on a new room, and an updated room keeps the band it ran on.

The pH half of the source-water gate holds watering while the feed water's pH reads outside the
band, and only when a feed pH probe is mapped; with none mapped there is no pH check. A new room
used to start on 5.8-6.2, narrower than most feed water is kept, so it now starts on 5.5-6.5. A
room that already has the two numbers restores its own: an update never moves the band a room is
running on, and a dead mapped probe still holds the water.
"""

import pytest
from conftest import fixture
from test_setup_entry import _install
from test_upgrade_in_place import JEV_3_11_1, UPSTREAM_2_25_1, _upgrade

PH_MIN = "number.crop_steering_irrigation_ph_min"
PH_MAX = "number.crop_steering_irrigation_ph_max"
TANK_PH = "sensor.tank_ph"
KILL = "switch.crop_steering_engine_enabled"
ARMED = (
    KILL,
    "switch.crop_steering_system_enabled",
    "switch.crop_steering_auto_irrigation_enabled",
    "switch.crop_steering_zone_1_enabled",
)
# What both older lineages created the two numbers with, and so what Home Assistant restores on a
# room where nobody changed them (number.py DEFAULT_VALUES in 2.25.1 and in 3.11.1).
OLD_BAND = {PH_MIN: "5.8", PH_MAX: "6.2"}


def _band(hass):
    return float(hass.states.get(PH_MIN).state), float(hass.states.get(PH_MAX).state)


def _arm(fake):
    for switch in ARMED:
        fake.set_state(switch, "on")


async def test_a_new_room_starts_on_a_5_5_to_6_5_band(hass):
    await _install(hass)
    assert _band(hass) == (5.5, 6.5)


@pytest.mark.parametrize("name", [UPSTREAM_2_25_1, JEV_3_11_1])
async def test_an_updated_room_keeps_the_band_it_ran_on(hass, name):
    seed = fixture(name)
    await _upgrade(hass, name, registry_ids=seed["registry"], restored=OLD_BAND)
    assert _band(hass) == (5.8, 6.2)


async def test_a_new_room_with_a_ph_probe_waters_inside_5_5_to_6_5_and_holds_outside_it(
    hass, controller_for
):
    hass.states.async_set(TANK_PH, "6.4", {"unit_of_measurement": "pH"})
    await _install(hass, {"feed_ph_sensor": TANK_PH})
    c, fake, _clock = controller_for({"enable_flag": KILL})
    room = c.rooms[0]
    assert room.feed_ph_sensor == TANK_PH  # from the room's setup, no app option
    _arm(fake)

    fake.set_state(TANK_PH, "unavailable")  # no good reading yet: fail closed
    assert "pH probe dead" in (c._blocked(room, 1) or "")
    fake.set_state(TANK_PH, "6.4", {"unit_of_measurement": "pH"})
    assert c._blocked(room, 1) is None  # was held under 5.8-6.2
    fake.set_state(TANK_PH, "6.6", {"unit_of_measurement": "pH"})
    assert c._blocked(room, 1) == "source-water pH 6.60 out of [5.5,6.5]"


async def test_a_new_room_with_no_ph_probe_has_no_ph_check(hass, controller_for):
    await _install(hass)
    c, fake, _clock = controller_for({"enable_flag": KILL})
    room = c.rooms[0]
    assert room.feed_ph_sensor == ""
    _arm(fake)
    assert c._blocked(room, 1) is None


async def test_an_updated_room_still_holds_on_its_own_band_and_on_a_dead_probe(
    hass, controller_for
):
    """A 2.25.1 room with its feed pH probe mapped, updated in place: 6.4 is inside a new room's
    band but outside the 5.8-6.2 this room runs on, so it still holds, as does a dead probe."""
    seed = fixture(UPSTREAM_2_25_1)
    await _upgrade(hass, UPSTREAM_2_25_1, registry_ids=seed["registry"], restored=OLD_BAND)
    c, fake, _clock = controller_for(seed["addon_options"], saved_state=seed["controller_saved"])
    room = c.rooms[0]
    assert room.feed_ph_sensor == "sensor.feed_ph"
    _arm(fake)

    fake.set_state("sensor.feed_ph", "unavailable")
    assert "pH probe dead" in (c._blocked(room, 1) or "")
    fake.set_state("sensor.feed_ph", "5.9")
    assert c._blocked(room, 1) is None
    fake.set_state("sensor.feed_ph", "6.4")
    assert c._blocked(room, 1) == "source-water pH 6.40 out of [5.8,6.2]"
