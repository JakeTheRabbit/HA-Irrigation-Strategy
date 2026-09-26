"""System Enabled and Auto Irrigation Enabled, retired: the engine switch is the one switch.

They stay, hidden, for controllers from 2.24.0 or before, which still stop every shot while one of
them reads off and treat a missing one as off. A newer controller switches the engine switch off
while one of them is off (CS-208), so a room someone stopped with one of them stays stopped.
"""

from homeassistant.helpers import entity_registry as er
from test_setup_entry import _install
from test_upgrade_in_place import _upgrade

RETIRED = {
    "switch.crop_steering_system_enabled": "system_enabled",
    "switch.crop_steering_auto_irrigation_enabled": "auto_irrigation_enabled",
}


def _hidden_and_on(hass):
    registry = er.async_get(hass)
    for entity_id in RETIRED:
        item = registry.async_get(entity_id)
        assert item is not None, entity_id  # the same id an older controller reads
        assert item.hidden_by is er.RegistryEntryHider.INTEGRATION, entity_id
        state = hass.states.get(entity_id)
        assert state.state == "on", entity_id
        assert state.attributes["friendly_name"].endswith("(retired)"), entity_id


async def test_a_new_room_has_them_hidden_and_on(hass):
    await _install(hass)
    _hidden_and_on(hass)


async def test_an_upgraded_room_keeps_their_ids_and_hides_them(hass):
    """In-place upgrade: an older install registered both, visible."""
    await _upgrade(hass, "entry_2_17_wizard.json", registry_ids=RETIRED)
    _hidden_and_on(hass)
