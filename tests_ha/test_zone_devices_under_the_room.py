"""Each zone's device sits under its room's, without the parameter Home Assistant deprecated.

Home Assistant 2026.9 warns in its log that a device's `via_device` stops working in 2027.8.0. The
zones are put under their room in the device registry instead (`via_device_id`), which every Home
Assistant this supports has: on a fresh install, and on an old one updated in place, where the
devices the old version registered are kept (same device ids) and no entity id moves.
"""

import logging

import pytest
from homeassistant.helpers import device_registry as dr, entity_registry as er
from test_setup_entry import _install
from test_upgrade_in_place import _upgrade

DOMAIN = "crop_steering"


def _room_and_zones(hass, entry):
    devices = dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)
    (room,) = [d for d in devices if (DOMAIN, entry.entry_id) in d.identifiers]
    zones = [
        d
        for d in devices
        if any(
            str(key).startswith(f"{entry.entry_id}_zone_")
            for _domain, key in d.identifiers
        )
    ]
    return room, zones


def _entity_ids(hass, entry):
    return {
        e.entity_id
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    }


async def test_a_fresh_install_puts_its_zones_under_the_room_with_no_warning(
    hass, caplog
):
    caplog.set_level(logging.WARNING)
    entry = await _install(hass)
    room, zones = _room_and_zones(hass, entry)
    assert zones and all(zone.via_device_id == room.id for zone in zones)
    assert "via_device" not in caplog.text


@pytest.mark.parametrize(
    "seed_name",
    [
        "entry_2_17_wizard.json",
        "entry_2_25_1_pumped_room.json",
        "entry_3_11_1_pumped_room.json",
    ],
)
async def test_an_old_install_keeps_its_devices_and_entities(
    hass, caplog, monkeypatch, seed_name
):
    """The devices an old version registered (zones linked with `via_device`) are the ones in use."""
    registry = dr.async_get(hass)
    old = {}
    setup = hass.config_entries.async_setup

    async def _setup_on_the_old_registry(entry_id, *args, **kwargs):
        entry = hass.config_entries.async_get_entry(entry_id)
        room = registry.async_get_or_create(
            config_entry_id=entry_id,
            identifiers={(DOMAIN, entry_id)},
            name="Crop Steering",
        )
        old[room.id] = room
        for number in entry.data["zones"]:
            zone = registry.async_get_or_create(
                config_entry_id=entry_id,
                identifiers={(DOMAIN, f"{entry_id}_zone_{number}")},
                name=f"Zone {number}",
            )
            # What the old version's `via_device` left in the registry.
            old[zone.id] = registry.async_update_device(zone.id, via_device_id=room.id)
        caplog.clear()
        return await setup(entry_id, *args, **kwargs)

    monkeypatch.setattr(hass.config_entries, "async_setup", _setup_on_the_old_registry)
    caplog.set_level(logging.WARNING)
    entry, seed = await _upgrade(hass, seed_name)

    room, zones = _room_and_zones(hass, entry)
    assert len(zones) == len(seed["data"]["zones"])
    assert all(zone.via_device_id == room.id for zone in zones)
    devices = dr.async_entries_for_config_entry(registry, entry.entry_id)
    assert {d.id for d in devices} == set(old)  # no device made anew, none dropped
    assert "via_device" not in caplog.text

    # Loading it again changes nothing: same devices, same zones under the room, same entity ids.
    entity_ids = _entity_ids(hass, entry)
    assert "sensor.crop_steering_vwc_zone_1" in entity_ids
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    again_room, again_zones = _room_and_zones(hass, entry)
    assert again_room.id == room.id
    assert {z.id: z.via_device_id for z in again_zones} == {
        z.id: z.via_device_id for z in zones
    }
    assert _entity_ids(hass, entry) == entity_ids
