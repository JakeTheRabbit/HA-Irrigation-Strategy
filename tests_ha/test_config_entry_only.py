"""Crop Steering is set up from the UI only, and Home Assistant says so to anyone who tries YAML.

hassfest asks an integration that has `async_setup` to declare its CONFIG_SCHEMA. It had none: a
`crop_steering:` block in configuration.yaml was ignored without a word. Declared config-entry-only,
Home Assistant raises its own Repairs card for the block, and everything else is unchanged.
"""

from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component

DOMAIN = "crop_steering"
ISSUE = ("homeassistant", f"config_entry_only_{DOMAIN}")


async def test_a_yaml_block_is_reported_and_setup_still_runs(hass):
    assert await async_setup_component(hass, DOMAIN, {DOMAIN: {"rooms": 1}})
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(*ISSUE) is not None
    assert hass.services.has_service(DOMAIN, "setup_read")  # async_setup ran as before


async def test_without_yaml_nothing_is_reported(hass):
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(*ISSUE) is None
    assert hass.services.has_service(DOMAIN, "setup_read")
