"""The exact first-install scenario: a tent whose one zone is named GT1, in a real Home Assistant,
looked up in the real device registry (which is what the "Name and assign" dialog shows)."""

from homeassistant.helpers import device_registry as dr, entity_registry as er
from test_configure import _save_map
from test_real_flow import ZONES
from test_setup_entry import _install
from test_upgrade_in_place import _upgrade

DOMAIN = "crop_steering"


def _zone_devices(hass, entry):
    registry = dr.async_get(hass)
    return {
        next(iter(device.identifiers))[1].rsplit("_zone_", 1)[1]: device
        for device in dr.async_entries_for_config_entry(registry, entry.entry_id)
        if "_zone_" in next(iter(device.identifiers))[1]
    }


async def test_a_zone_named_gt1_is_offered_as_a_device_called_gt1(hass, monkeypatch):
    monkeypatch.setitem(ZONES, "zone_1_name", "GT1")
    entry = await _install(hass)
    devices = _zone_devices(hass, entry)
    assert set(devices) == {"1"}  # one zone was set up: one zone device, no phantom zones
    assert devices["1"].name == "GT1"  # it said "Zone 1"
    assert devices["1"].model == "Zone Controller"


async def test_the_entity_ids_do_not_follow_the_name(hass, monkeypatch):
    """The controller and every dashboard find a zone by id. A friendly name must never move one."""
    monkeypatch.setitem(ZONES, "zone_1_name", "GT1")
    await _install(hass)
    registry = er.async_get(hass)
    for entity_id in (
        "sensor.crop_steering_vwc_zone_1",
        "switch.crop_steering_zone_1_enabled",
        "number.crop_steering_zone_1_plant_count",
    ):
        assert registry.async_get(entity_id) is not None, entity_id
    assert not [e for e in registry.entities if "gt1" in e]


async def test_renaming_the_zone_in_configure_renames_the_device(hass, monkeypatch):
    monkeypatch.setitem(ZONES, "zone_1_name", "GT1")
    entry = await _install(hass)
    await _save_map(hass, entry, zone_1_name="Grow tent one")
    await hass.async_block_till_done()
    assert _zone_devices(hass, entry)["1"].name == "Grow tent one"


async def test_an_old_install_gets_the_names_it_configured_and_keeps_every_id(hass):
    entry, seed = await _upgrade(hass, "entry_2_17_wizard.json")
    devices = _zone_devices(hass, entry)
    for number, zone in seed["data"]["zones"].items():
        assert devices[number].name == (zone.get("name") or f"Zone {number}")
    assert er.async_get(hass).async_get("sensor.crop_steering_vwc_zone_1") is not None
