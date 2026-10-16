"""What only the dashboard shows, mapped on its Setup page, in a real Home Assistant: the room camera,
CO2 and PPFD sensors and each zone's root-zone temperature probe are saved through setup_save and
published in the room's descriptor only when mapped; an old room keeps its descriptor as it was. The
Hardware panel switch is off on a new room, and only an administrator may set it to on."""

import pytest
from homeassistant.auth.const import GROUP_ID_USER
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockUser
from test_setup_entry import _install
from test_upgrade_in_place import DESCRIPTOR as OLD_DESCRIPTOR, _upgrade

DOMAIN = "crop_steering"
DESCRIPTOR = "sensor.crop_steering_tent_engine_config"
PANEL = "switch.crop_steering_tent_manual_hardware_enabled"
NEW_KEYS = {
    "camera_entity",
    "co2_sensor",
    "ppfd_sensor",
    "substrate_temperature_sensors",
}


async def _call(hass, user, service, data):
    return await hass.services.async_call(
        DOMAIN,
        service,
        data,
        blocking=True,
        return_response=True,
        context=Context(user_id=user.id if user else None),
    )


async def test_a_room_maps_camera_co2_ppfd_and_a_root_zone_probe(hass, hass_admin_user):
    await _install(hass)
    hass.states.async_set("camera.tent", "idle")
    hass.states.async_set("sensor.tent_co2", "800", {"unit_of_measurement": "ppm"})
    hass.states.async_set("sensor.tent_ppfd", "900", {"unit_of_measurement": "µmol/m²/s"})
    hass.states.async_set("sensor.slab_1_temp", "21.5", {"unit_of_measurement": "°C"})
    assert not NEW_KEYS & set(hass.states.get(DESCRIPTOR).attributes)
    read = await _call(hass, hass_admin_user, "setup_read", {})
    assert "camera.tent" in {c["entity_id"] for c in read["candidates"]}
    room = read["rooms"][0]
    assert room["zones"][0]["substrate_temperature_sensor"] == ""
    zones = [
        {**z, "substrate_temperature_sensor": "sensor.slab_1_temp"} if z["id"] == 1 else z
        for z in room["zones"]
    ]
    hardware = {
        **room["hardware"],
        "camera_entity": "camera.tent",
        "co2_sensor": "sensor.tent_co2",
        "ppfd_sensor": "sensor.tent_ppfd",
    }
    await _call(
        hass,
        hass_admin_user,
        "setup_save",
        {
            "entry_id": room["entry_id"],
            "expected_revision": room["revision"],
            "room_name": room["room_name"],
            "active": room["active"],
            "zones": zones,
            "hardware": hardware,
        },
    )
    await hass.async_block_till_done()
    descriptor = hass.states.get(DESCRIPTOR).attributes
    assert descriptor["camera_entity"] == "camera.tent"
    assert descriptor["co2_sensor"] == "sensor.tent_co2"
    assert descriptor["ppfd_sensor"] == "sensor.tent_ppfd"
    assert descriptor["substrate_temperature_sensors"] == {"1": "sensor.slab_1_temp"}
    again = (await _call(hass, hass_admin_user, "setup_read", {}))["rooms"][0]
    assert again["zones"][0]["substrate_temperature_sensor"] == "sensor.slab_1_temp"


async def test_a_root_zone_probe_must_report_a_temperature(hass, hass_admin_user):
    await _install(hass)
    hass.states.async_set("sensor.slab_vwc", "55", {"unit_of_measurement": "%"})
    room = (await _call(hass, hass_admin_user, "setup_read", {}))["rooms"][0]
    zones = [{**z, "substrate_temperature_sensor": "sensor.slab_vwc"} for z in room["zones"]]
    with pytest.raises(HomeAssistantError, match="unit"):
        await _call(
            hass,
            hass_admin_user,
            "setup_save",
            {
                "entry_id": room["entry_id"],
                "expected_revision": room["revision"],
                "room_name": room["room_name"],
                "active": room["active"],
                "zones": zones,
                "hardware": room["hardware"],
            },
        )


async def test_an_old_room_publishes_none_of_the_new_keys(hass):
    await _upgrade(hass, "entry_3_11_1_pumped_room.json")
    assert not NEW_KEYS & set(hass.states.get(OLD_DESCRIPTOR).attributes)


async def test_the_hardware_panel_is_off_and_only_an_administrator_turns_it_on(
    hass, hass_admin_user
):
    await _install(hass)
    assert hass.states.get(PANEL).state == "off"
    users = await hass.auth.async_get_group(GROUP_ID_USER)
    staff = MockUser(name="Staff phone", groups=[users]).add_to_hass(hass)
    with pytest.raises(HomeAssistantError, match="administrator"):
        await hass.services.async_call(
            "switch",
            "turn_on",
            {"entity_id": PANEL},
            blocking=True,
            context=Context(user_id=staff.id),
        )
    assert hass.states.get(PANEL).state == "off"
    await hass.services.async_call(
        "switch",
        "turn_on",
        {"entity_id": PANEL},
        blocking=True,
        context=Context(user_id=hass_admin_user.id),
    )
    assert hass.states.get(PANEL).state == "on"
    await hass.services.async_call(
        "switch",
        "turn_off",
        {"entity_id": PANEL},
        blocking=True,
        context=Context(user_id=staff.id),
    )
    assert hass.states.get(PANEL).state == "off"
