"""The recipe system is deprecated, not removed: it still works, says so once in Repairs, and an
install that stored a recipe before the deprecation loads it unchanged. Applying a stage through
the service applies it once."""

import copy

import pytest
from conftest import fixture
from custom_components.crop_steering.recipe import RecipeManager, get_manager
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

DOMAIN = "crop_steering"
VWC = "number.crop_steering_zone_1_p1_target_vwc"  # an upgraded room keeps un-prefixed ids
STAGE = "select.crop_steering_recipe_stage"
PHASE = "select.crop_steering_irrigation_phase"
OLD_RECIPE = {
    "version": 1,
    "active_stage": "Bulk",
    "stages": {"Bulk": {"p1_target_vwc": 61.0}, "Ripen": {"p1_target_vwc": 66.0}},
}


async def _old_install(hass, hass_storage):
    seed = fixture("entry_2_25_1_pumped_room.json")
    for entity_id, (state, attributes) in seed["states"].items():
        hass.states.async_set(entity_id, state, attributes)
    store = f"{DOMAIN}_recipes_{seed['entry_id']}"
    hass_storage[store] = {
        "version": 1,
        "minor_version": 1,
        "key": store,
        "data": copy.deepcopy(OLD_RECIPE),
    }
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=seed.get("version", 1),
        minor_version=seed.get("minor_version", 1),
        entry_id=seed["entry_id"],
        unique_id=seed["unique_id"],
        title=seed["title"],
        data=seed["data"],
        options=seed["options"],
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    return entry


def _issues(hass):
    registry = ir.async_get(hass)
    return sorted(i for (d, i) in registry.issues if d == DOMAIN and i.startswith("deprecated_"))


async def test_an_install_with_a_stored_recipe_loads_it_unchanged(hass, hass_storage):
    entry = await _old_install(hass, hass_storage)
    mgr = get_manager(hass, entry)
    assert mgr.recipe == OLD_RECIPE
    assert hass.states.get(STAGE).state == "Bulk"
    assert _issues(hass) == []  # loading raises nothing


async def test_apply_recipe_applies_once_and_shows_the_stage(hass, hass_storage, monkeypatch):
    await _old_install(hass, hass_storage)
    calls = []
    real = RecipeManager.async_apply

    async def counting(self, stage=None):
        calls.append(stage)
        return await real(self, stage)

    monkeypatch.setattr(RecipeManager, "async_apply", counting)
    await hass.services.async_call(DOMAIN, "apply_recipe", {"stage": "Ripen"}, blocking=True)
    await hass.async_block_till_done()
    assert calls == ["Ripen"]  # was twice: the service, then the select it set
    assert float(hass.states.get(VWC).state) == 66.0
    assert hass.states.get(STAGE).state == "Ripen"


@pytest.mark.parametrize(
    "service,data,issue",
    [
        ("apply_recipe", {"stage": "Ripen"}, "deprecated_apply_recipe"),
        ("save_recipe", {"recipe": OLD_RECIPE}, "deprecated_save_recipe"),
    ],
)
async def test_a_deprecated_service_works_and_raises_its_repair_once(
    hass, hass_storage, service, data, issue
):
    entry = await _old_install(hass, hass_storage)
    await hass.services.async_call(DOMAIN, service, data, blocking=True)
    assert _issues(hass) == [issue]
    registry = ir.async_get(hass)
    raised = registry.async_get_issue(DOMAIN, issue)
    assert raised.severity is ir.IssueSeverity.WARNING
    assert raised.translation_key == "deprecated_feature"
    assert not raised.is_fixable
    # a second use works and leaves the one issue as it is
    await hass.services.async_call(DOMAIN, service, data, blocking=True)
    assert _issues(hass) == [issue]
    if service == "save_recipe":
        assert get_manager(hass, entry).recipe == OLD_RECIPE


async def test_choosing_in_a_deprecated_select_works_and_raises_its_repair(hass, hass_storage):
    await _old_install(hass, hass_storage)
    await hass.services.async_call(
        "select", "select_option", {"entity_id": STAGE, "option": "Ripen"}, blocking=True
    )
    await hass.async_block_till_done()
    assert float(hass.states.get(VWC).state) == 66.0
    assert _issues(hass) == ["deprecated_recipe_stage"]
    await hass.services.async_call(
        "select", "select_option", {"entity_id": PHASE, "option": "P2"}, blocking=True
    )
    assert hass.states.get(PHASE).state == "P2"
    assert _issues(hass) == ["deprecated_irrigation_phase", "deprecated_recipe_stage"]
