"""The config entry itself: does it load, and do the wizard's answers reach the entities?

Both failures here were invisible to every existing test. The stub suite gives the code a
`frontend.async_panel_exists` that the real frontend only has from Home Assistant 2026.5.0, and
this tier used to replace the whole panel registration with a no-op.
"""

import pytest
from homeassistant.components import frontend
from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import FlowResultType

from test_real_flow import ZONES, _seed, _to_zones_step

PANEL = "crop-steering"


async def _install(hass, hardware=None):
    _seed(hass)
    flow_id = await _to_zones_step(hass)
    result = await hass.config_entries.flow.async_configure(flow_id, dict(ZONES))
    assert result["step_id"] == "hardware", result.get("errors")
    result = await hass.config_entries.flow.async_configure(flow_id, hardware or {})
    assert result["type"] is FlowResultType.CREATE_ENTRY, result
    await hass.async_block_till_done()
    return result["result"]


# ------------------------------------------------------------------ the sidebar panel
async def test_the_entry_sets_up_on_a_home_assistant_that_has_no_async_panel_exists(
    hass, monkeypatch
):
    """Every Home Assistant from the advertised 2024.3 up to 2026.4. Removing the attribute keeps
    this meaningful on the day this tier runs on a Home Assistant that does have it."""
    monkeypatch.delattr(frontend, "async_panel_exists", raising=False)
    entry = await _install(hass)
    assert entry.state is ConfigEntryState.LOADED  # was SETUP_ERROR: AttributeError
    assert PANEL in hass.data[frontend.DATA_PANELS]
    assert hass.http.async_register_static_paths.await_count == 1


async def test_a_home_assistant_that_has_the_helper_is_asked_through_it(
    hass, monkeypatch
):
    asked = []

    def exists(hass_, path):
        asked.append(path)
        return path in hass_.data.get(frontend.DATA_PANELS, {})

    monkeypatch.setattr(frontend, "async_panel_exists", exists, raising=False)
    entry = await _install(hass)
    assert entry.state is ConfigEntryState.LOADED
    assert asked and set(asked) == {PANEL}


@pytest.mark.parametrize("has_helper", [False, True])
async def test_a_sidebar_path_somebody_else_owns_is_left_alone_on_either_path(
    hass, monkeypatch, has_helper
):
    if has_helper:
        monkeypatch.setattr(
            frontend,
            "async_panel_exists",
            lambda hass_, path: path in hass_.data.get(frontend.DATA_PANELS, {}),
            raising=False,
        )
    else:
        monkeypatch.delattr(frontend, "async_panel_exists", raising=False)
    theirs = object()
    hass.data.setdefault(frontend.DATA_PANELS, {})[PANEL] = theirs
    entry = await _install(hass)
    assert entry.state is ConfigEntryState.LOADED
    assert hass.data[frontend.DATA_PANELS][PANEL] is theirs  # neither replaced...
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert hass.data[frontend.DATA_PANELS][PANEL] is theirs  # ...nor removed on unload


# ------------------------------------------------------------------ what the wizard was told
async def test_the_lights_hours_the_wizard_asked_for_are_the_ones_that_run(hass):
    """They were stored on the entry and never reached the entities, which seeded to 12 and 0:
    the grow-day, the P3->P0 reset and the overnight dry-back all ran on the wrong clock."""
    entry = await _install(hass, {"lights_on_hour": 6, "lights_off_hour": 22})
    assert entry.data["parameters"]["lights_on_hour"] == 6
    assert float(hass.states.get("number.crop_steering_lights_on_hour").state) == 6
    assert float(hass.states.get("number.crop_steering_lights_off_hour").state) == 22


async def test_the_sizing_the_wizard_accepted_is_a_value_the_entity_can_hold(hass):
    """Setup accepts 0.1-200 L and 1-20 drippers; the room-wide entities allowed 1.0-200 and
    1-6, so a 0.65 L rockwool cube could be set up and then never adjusted."""
    await _install(hass)
    for entity_id, value in (
        ("number.crop_steering_substrate_volume", 0.65),
        ("number.crop_steering_drippers_per_plant", 12),
    ):
        await hass.services.async_call(
            "number", "set_value", {"entity_id": entity_id, "value": value}, blocking=True
        )
        assert float(hass.states.get(entity_id).state) == value
