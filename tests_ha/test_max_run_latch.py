"""The max-run latch (CS-312), in a real Home Assistant: the per-room switch, the Repairs card and its fix.

A room set up from this release gets the switch ON; a room set up before it keeps watering exactly
as it did, with the switch OFF, and is only told when a zone keeps hitting its longest allowed shot.
"""

import pytest
from homeassistant.components.repairs import repairs_flow_manager
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component

from custom_components.crop_steering import health
from test_setup_entry import _install
from test_upgrade_in_place import JEV_3_11_1, UPSTREAM_2_25_1, _upgrade
from conftest import fixture

DOMAIN = "crop_steering"
LATCH = "switch.crop_steering_max_run_latch"
HEARTBEAT = "sensor.crop_steering_ai_heartbeat"


def _card(hass):
    return ir.async_get(hass).async_get_issue(DOMAIN, "max_run_latch")


def _beat(hass, max_run):
    hass.states.async_set(HEARTBEAT, "healthy", {"max_run": max_run})


async def test_a_room_set_up_now_gets_the_latch_on(hass):
    entry = await _install(hass)
    assert entry.data["max_run_latch"] is True
    latch = hass.states.get(LATCH)
    assert latch.state == "on" and latch.attributes["resets"] == 0


@pytest.mark.parametrize("name", [UPSTREAM_2_25_1, JEV_3_11_1])
async def test_a_room_set_up_before_it_gets_the_latch_off(hass, name):
    entry, seed = await _upgrade(hass, name, registry_ids=fixture(name)["registry"])
    assert entry.data == seed["data"]  # loading marks nothing
    assert hass.states.get(LATCH).state == "off"


async def test_the_card_only_reports_while_nothing_is_latched(hass):
    entry = await _install(hass)
    _beat(hass, {"1": {"capped": 3, "latched": False}})
    health.run_health_check(hass, entry)
    card = _card(hass)
    assert card.severity is ir.IssueSeverity.WARNING and not card.is_fixable
    assert card.translation_placeholders["zones"] == "1"
    assert "Nothing has been stopped" in card.translation_placeholders["what"]
    _beat(hass, {})  # the zone's next shot was not cut
    health.run_health_check(hass, entry)
    assert _card(hass) is None


async def test_the_repairs_fix_releases_a_latched_zone(hass):
    assert await async_setup_component(hass, "repairs", {})
    entry = await _install(hass)
    _beat(hass, {"1": {"capped": 3, "latched": True, "resets": 0}})
    health.run_health_check(hass, entry)
    card = _card(hass)
    assert card.severity is ir.IssueSeverity.ERROR and card.is_fixable
    assert "stopped watering zone(s) 1" in card.translation_placeholders["what"]

    flows = repairs_flow_manager(hass)
    result = await flows.async_init(DOMAIN, data={"issue_id": "max_run_latch"})
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "confirm"
    assert result["description_placeholders"]["zones"] == "1"
    result = await flows.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert hass.states.get(LATCH).attributes["resets"] == 1  # what the controller watches
    assert _card(hass) is None
    # The controller has not seen the reset yet: its beat still says latched, with the old count.
    health.run_health_check(hass, entry)
    assert _card(hass) is None
